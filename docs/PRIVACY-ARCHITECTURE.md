# Privacy architecture and trust boundary

**Reference:** 0.8.5-rc3

The middleware deliberately separates access to the complete private corpus from
processing of already selected evidence. Privacy is therefore not defined as
"every model must run locally". The primary invariant is that the complete
Nextcloud/Elasticsearch corpus, vector index and ACL state remain inside the
operator-controlled retrieval plane.

## Private retrieval plane

The following operations are intended to remain local/private:

1. Nextcloud FullTextSearch / Elasticsearch access;
2. document chunking and embedding;
3. Qdrant vector storage and search;
4. optional Neo4j retrieval over an existing graph;
5. Cross-Encoder/TEI reranking when a local reranker is configured;
6. live Nextcloud ACL authorization.

Only candidates that survived the configured local retrieval and authorization
pipeline are eligible for transmission to a remote LLM role.

```text
Nextcloud / Elasticsearch
          |
          v
 local embedding -> Qdrant
          |
          v
 hybrid / graph retrieval
          |
          v
    local reranker
          |
          v
 Nextcloud Live ACL
          |
---------- trust boundary ----------
          |
          v
 candidate verifier / evidence control / answer LLM
```

## Role-specific LLM routing

The current 0.8.4 reference can route four LLM roles independently:

- `planner`: Query Rewrite/SearchSpec generation and optional bounded round control;
- `verifier`: semantic verification of ACL-authorized document candidates;
- `evidence`: evidence decisions and citation-integrity control;
- `answer`: final answer generation and streaming.

Unset role settings inherit the canonical `LLM_*` backend for compatibility. Each role can override backend, URL, model, API key, TLS verification
and trust scope through `<ROLE>_LLM_*` variables.

A practical `private-retrieval` deployment keeps embedding, Qdrant, reranking
and ACL local while using a capable remote model for verifier/evidence/answer.
A `strict-local` deployment points all roles at a local provider instead.

## Remote evidence budgets

When a role endpoint is classified as remote, the provider applies hard evidence caps in
addition to the feature-specific limits:

- maximum characters per answer document: `REMOTE_LLM_MAX_CHARS_PER_DOCUMENT`;
- maximum total answer/evidence characters per call: `REMOTE_LLM_MAX_TOTAL_CHARS`;
- maximum verifier candidates: `REMOTE_VERIFIER_MAX_CANDIDATES`;
- maximum verifier characters per candidate: `REMOTE_VERIFIER_MAX_CHARS_PER_DOCUMENT`;
- maximum answer documents: `REMOTE_ANSWER_MAX_DOCUMENTS`.

Loopback and private/link-local IP endpoints are classified as local by default;
public IPs and ordinary public DNS names are remote. `*_LLM_SCOPE=local|remote`
can override this classification when the administrator knows the actual trust
boundary.

These limits constrain transmitted evidence, not the user question itself. A
remote planner may receive the user's query and bounded conversation context.

## Graph extraction is different

Graph extraction can inspect much larger portions of a document than normal
answer evidence. The graph entity/relation extractors therefore remain a
separate administrative trust decision. Their backend is configured under
`graph_entity_discovery` / `graph_relation_discovery` (or the corresponding
`GRAPH_*` environment variables).

Automatic graph processing is **off by default** in the current reference configuration even when Neo4j and the
Graph Queue are available:

```yaml
graph_queue:
  enabled: true
  auto_enqueue_cited_documents: false
  worker:
    enabled: false
```

This prevents answer-cited documents from being silently sent to a remote graph
extractor. Administrators may still enqueue/process graph jobs deliberately.

## Public Web Research

Public Web Research is separate from the private corpus. Search results are
fetched first; only actually fetched content can become evidence. Selected
sources can be archived to the current user's Nextcloud via WebDAV. Archive TLS
verification has its own `web.yaml: archive.verify_tls` setting because the
archive write is a separate HTTP client path.

## Operational principle

A deployment should make the trust decision explicit rather than infer it from
where a model happens to run. Provider health reports the effective backend,
model and local/remote scope for Query-Rewriter (`planner`), verifier, evidence and answer roles.

## RC10: Research-Finding-Provenienz

`research_findings` persistiert ausschließlich positive, bereits verifizierte Dokumenttreffer. Negative (`reject`) und unsichere (`uncertain`) Dokument-/Query-Paare werden nicht gespeichert. Der Finding-Knoten enthält den aus dem SearchSpec abgeleiteten strukturierten Query-Frame und den Verifier-Evidence-Frame, aber **keine Kopie des freien Benutzer-Fragetextes** und keine Benutzer-ID. Ein technischer `query_id`-Verweis darf zur Laufprovenienz gespeichert werden.

Die Daten werden lokal in Neo4j abgelegt. Query-Frame-Relationen sind als Recherchebeobachtung gekennzeichnet und werden nicht automatisch als globale Fakten zwischen Entities materialisiert. Dadurch bleibt die epistemische Herkunft `AKI Recherche` nachvollziehbar und getrennt von CardDAV-Seeds, manueller Kuration oder expliziter Dokumentextraktion.
