import argparse
from pathlib import Path

import httpx
import yaml

from rag.embeddings import build_embedding_backend_from_config
from rag.elasticsearch_client import httpx_options as elastic_httpx_options
from rag.vector import VectorStore


# ------------------------------------------------------------
# Konfiguration
# ------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent.parent

with (BASE_DIR / "config.yaml").open("r") as f:
    config = yaml.safe_load(f)


ES_URL = config["elasticsearch"]["url"].rstrip("/")
ES_INDEX = config["elasticsearch"]["index"]
ES_TIMEOUT = config["elasticsearch"].get("timeout", 60)
ES_HTTPX_OPTIONS = elastic_httpx_options(config)

embeddings = build_embedding_backend_from_config(config)

store = VectorStore(
    config["qdrant"]["url"],
    config["qdrant"]["collection"],
)


# ------------------------------------------------------------
# Kommandozeile
# ------------------------------------------------------------

parser = argparse.ArgumentParser(
    description="Hybridsuche in Elasticsearch und Qdrant"
)

parser.add_argument(
    "semantic",
    nargs="?",
    default=None,
    help="Semantische Suchanfrage für Qdrant",
)

parser.add_argument(
    "--must",
    action="append",
    default=[],
    help="Begriff muss vorkommen; mehrfach verwendbar",
)

parser.add_argument(
    "--should",
    action="append",
    default=[],
    help="Begriff sollte vorkommen; mehrfach verwendbar",
)

parser.add_argument(
    "--not",
    dest="must_not",
    action="append",
    default=[],
    help="Begriff darf nicht vorkommen; mehrfach verwendbar",
)

parser.add_argument(
    "--phrase",
    action="append",
    default=[],
    help="Exakte Wortgruppe; mehrfach verwendbar",
)

parser.add_argument(
    "--from-date",
    default=None,
    help="Frühestes attachment.date, z.B. 2022-01-01",
)

parser.add_argument(
    "--to-date",
    default=None,
    help="Spätestes attachment.date, z.B. 2023-12-31",
)

parser.add_argument(
    "--limit",
    type=int,
    default=10,
    help="Anzahl ausgegebener Treffer",
)

parser.add_argument(
    "--es-limit",
    type=int,
    default=50,
    help="Anzahl Kandidaten aus Elasticsearch",
)

parser.add_argument(
    "--vector-limit",
    type=int,
    default=50,
    help="Anzahl Kandidaten aus Qdrant",
)

parser.add_argument(
    "--threshold",
    type=float,
    default=0.55,
    help="Minimaler Qdrant-Score",
)

args = parser.parse_args()


# ------------------------------------------------------------
# Elasticsearch Query
# ------------------------------------------------------------

def normal_clause(term):
    """
    Normale Begriffe.

    Bei mehreren Wörtern müssen innerhalb dieses Arguments
    alle Wörter vorkommen, aber nicht zwingend direkt
    nebeneinander.
    """
    return {
        "multi_match": {
            "query": term,
            "fields": [
                "title^3",
                "content",
            ],
            "operator": "and",
        }
    }


def phrase_clause(term):
    """
    Exakte bzw. nahezu exakte Phrase.
    """
    return {
        "multi_match": {
            "query": term,
            "fields": [
                "title^3",
                "content",
            ],
            "type": "phrase",
            "slop": 1,
        }
    }


def elastic_search():
    has_elastic_query = (
        args.must
        or args.should
        or args.must_not
        or args.phrase
        or args.from_date
        or args.to_date
    )

    if not has_elastic_query:
        return []


    bool_query = {
        "must": [],
        "should": [],
        "must_not": [],
        "filter": [],
    }


    # Muss-Begriffe
    for term in args.must:
        bool_query["must"].append(
            normal_clause(term)
        )


    # Exakte Phrasen
    for term in args.phrase:
        bool_query["must"].append(
            phrase_clause(term)
        )


    # Sollte-Begriffe
    for term in args.should:
        bool_query["should"].append(
            normal_clause(term)
        )


    # Ausschlüsse
    for term in args.must_not:
        bool_query["must_not"].append(
            normal_clause(term)
        )


    # Falls ausschließlich SHOULD benutzt wird,
    # muss wenigstens einer davon treffen.
    if (
        args.should
        and not args.must
        and not args.phrase
    ):
        bool_query["minimum_should_match"] = 1


    # Zeitfilter
    if args.from_date or args.to_date:
        date_range = {}

        if args.from_date:
            date_range["gte"] = args.from_date

        if args.to_date:
            date_range["lte"] = args.to_date

        bool_query["filter"].append(
            {
                "range": {
                    "attachment.date": date_range
                }
            }
        )


    body = {
        "size": args.es_limit,
        "track_total_hits": True,
        "_source": [
            "title",
            "source",
            "share_names",
            "attachment.date",
            "attachment.content_type",
        ],
        "query": {
            "bool": bool_query
        },
        "highlight": {
            "pre_tags": [""],
            "post_tags": [""],
            "fields": {
                "content": {
                    "fragment_size": 1200,
                    "number_of_fragments": 1,
                }
            },
        },
    }


    response = httpx.post(
        f"{ES_URL}/{ES_INDEX}/_search",
        json=body,
        timeout=ES_TIMEOUT,
        **ES_HTTPX_OPTIONS,
    )

    response.raise_for_status()

    data = response.json()

    hits = []

    for rank, hit in enumerate(
        data["hits"]["hits"],
        start=1,
    ):
        source = hit.get("_source", {})

        highlight = hit.get(
            "highlight",
            {},
        ).get(
            "content",
            [],
        )

        snippet = ""

        if highlight:
            snippet = highlight[0]

        hits.append(
            {
                "document_id": hit["_id"],
                "rank": rank,
                "score": hit.get("_score"),
                "title": source.get(
                    "title",
                    "",
                ),
                "snippet": snippet,
                "source": source,
            }
        )

    return hits


# ------------------------------------------------------------
# Qdrant Vector Search
# ------------------------------------------------------------

def vector_search():
    if not args.semantic:
        return []


    query_vector = embeddings.embed_query(args.semantic)


    raw_results = store.search(
        query_vector,
        limit=args.vector_limit,
    )


    # Ein langes Dokument kann viele Chunks liefern.
    # Für die Fusion interessiert uns zunächst der
    # beste Chunk jedes Dokuments.
    documents = []
    seen = set()

    for result in raw_results:
        if result.score < args.threshold:
            continue

        document_id = result.payload.get(
            "document_id"
        )

        if not document_id:
            continue

        if document_id in seen:
            continue

        seen.add(document_id)

        documents.append(
            {
                "document_id": document_id,
                "score": result.score,
                "title": result.payload.get(
                    "title",
                    "",
                ),
                "chunk_no": result.payload.get(
                    "chunk_no",
                ),
                "snippet": result.payload.get(
                    "text",
                    "",
                ),
            }
        )


    # Rang erst NACH der Deduplizierung vergeben.
    for rank, document in enumerate(
        documents,
        start=1,
    ):
        document["rank"] = rank

    return documents


# ------------------------------------------------------------
# Reciprocal Rank Fusion
# ------------------------------------------------------------

def fuse_results(
    elastic_results,
    vector_results,
    k=60,
):
    combined = {}


    # Elasticsearch
    for item in elastic_results:
        document_id = item["document_id"]

        record = combined.setdefault(
            document_id,
            {
                "document_id": document_id,
                "title": item["title"],
                "rrf": 0.0,
                "es_rank": None,
                "es_score": None,
                "vector_rank": None,
                "vector_score": None,
                "snippet": "",
                "chunk_no": None,
            },
        )

        record["es_rank"] = item["rank"]
        record["es_score"] = item["score"]

        record["rrf"] += (
            1.0 / (k + item["rank"])
        )

        if item["snippet"]:
            record["snippet"] = item["snippet"]


    # Qdrant
    for item in vector_results:
        document_id = item["document_id"]

        record = combined.setdefault(
            document_id,
            {
                "document_id": document_id,
                "title": item["title"],
                "rrf": 0.0,
                "es_rank": None,
                "es_score": None,
                "vector_rank": None,
                "vector_score": None,
                "snippet": "",
                "chunk_no": None,
            },
        )

        # Qdrant-Titel bevorzugen, falls ES keinen hat
        if not record["title"]:
            record["title"] = item["title"]

        record["vector_rank"] = item["rank"]
        record["vector_score"] = item["score"]
        record["chunk_no"] = item.get("chunk_no")

        record["rrf"] += (
            1.0 / (k + item["rank"])
        )

        # Der semantisch gefundene Chunk ist für die
        # Ausgabe normalerweise informativer.
        if item["snippet"]:
            record["snippet"] = item["snippet"]


    results = sorted(
        combined.values(),
        key=lambda x: x["rrf"],
        reverse=True,
    )

    return results


# ------------------------------------------------------------
# Ausgabe
# ------------------------------------------------------------

def display_results(results):
    if not results:
        print()
        print("Keine Treffer.")
        return


    print()
    print("=" * 80)
    print("HYBRIDSUCHE")
    print("=" * 80)

    if args.semantic:
        print(
            f"Semantik: {args.semantic}"
        )

    if args.must:
        print(
            "MUSS:     "
            + ", ".join(args.must)
        )

    if args.phrase:
        print(
            "PHRASE:   "
            + ", ".join(args.phrase)
        )

    if args.should:
        print(
            "SOLLTE:   "
            + ", ".join(args.should)
        )

    if args.must_not:
        print(
            "NICHT:    "
            + ", ".join(args.must_not)
        )

    if args.from_date or args.to_date:
        print(
            "ZEIT:     "
            f"{args.from_date or '*'}"
            " bis "
            f"{args.to_date or '*'}"
        )

    print()


    for hybrid_rank, item in enumerate(
        results[:args.limit],
        start=1,
    ):
        print("=" * 80)
        print(f"Hybrid-Rang: {hybrid_rank}")
        print(f"RRF:         {item['rrf']:.6f}")

        es_rank = (
            item["es_rank"]
            if item["es_rank"] is not None
            else "-"
        )

        vector_rank = (
            item["vector_rank"]
            if item["vector_rank"] is not None
            else "-"
        )

        print(f"ES-Rang:     {es_rank}")
        print(f"Vector-Rang: {vector_rank}")

        if item["vector_score"] is not None:
            print(
                "Vector-Score: "
                f"{item['vector_score']:.4f}"
            )

        print(
            f"Datei:       {item['title']}"
        )

        print(
            f"Dokument-ID: {item['document_id']}"
        )

        if item["chunk_no"] is not None:
            print(
                f"Chunk:       {item['chunk_no']}"
            )

        print()

        snippet = item.get(
            "snippet",
            "",
        ).strip()

        if snippet:
            print(snippet[:1500])

        print()


# ------------------------------------------------------------
# Hauptprogramm
# ------------------------------------------------------------

try:
    es_results = elastic_search()

    vector_results = vector_search()

    results = fuse_results(
        es_results,
        vector_results,
    )

    display_results(results)

except httpx.HTTPError as exc:
    print()
    print("HTTP-Fehler:")
    print(exc)

except Exception as exc:
    print()
    print("Fehler:")
    print(exc)
