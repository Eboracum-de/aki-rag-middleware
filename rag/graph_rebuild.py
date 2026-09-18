#!/usr/bin/env python3
"""Replay historic graph evidence documents through Graph v3.

The queue itself is not modified.  This command reads DISTINCT document_ids from
``graph_queue.sqlite`` and reprocesses them with the current extractor.

Recommended fresh-build sequence:
  1. clear Neo4j explicitly;
  2. re-import CardDAV seeds;
  3. run ``python -m rag.graph_rebuild --phase both``.

Phase ``discover`` lets the LLM grow the entity catalogue. Phase ``relink``
performs a second mention pass against the completed catalogue and extracts
relations. Phase ``relations`` upgrades an existing graph to Claim/RelationObservation
without running entity discovery again.
"""

from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import time
from typing import Any

from rag.graph import BASE_DIR, GraphStore, load_config
from rag.graph_indexer import EXTRACTOR_VERSION, GraphEvidenceIndexer
from rag.graph_queue import GraphQueue

log = logging.getLogger("rag-graph-rebuild")


def _document_ids(queue: GraphQueue, *, limit: int = 0, offset: int = 0) -> list[str]:
    with sqlite3.connect(queue.path) as con:
        con.row_factory = sqlite3.Row
        rows = con.execute(
            """
            SELECT document_id, MIN(id) AS first_job_id
            FROM graph_jobs
            WHERE document_id IS NOT NULL AND TRIM(document_id) <> ''
            GROUP BY document_id
            ORDER BY first_job_id
            """
        ).fetchall()
    ids = [str(row["document_id"]) for row in rows]
    if offset > 0:
        ids = ids[offset:]
    if limit > 0:
        ids = ids[:limit]
    return ids


def _run_phase(
    indexer: GraphEvidenceIndexer,
    ids: list[str],
    *,
    phase: str,
    sleep_seconds: float,
    force_oversize: bool = False,
) -> dict[str, Any]:
    discovery = phase == "discover"
    relation_discovery = phase in {"relink", "relations"}
    ok = 0
    failed = 0
    created = 0
    resolved = 0
    ambiguous = 0
    unresolved = 0
    rejected = 0
    discovered = 0
    relations = 0
    errors: list[dict[str, Any]] = []

    total = len(ids)
    for pos, document_id in enumerate(ids, start=1):
        log.info("[%d/%d] %s phase=%s", pos, total, document_id, phase)
        result = indexer.index_evidence(
            [{"document_id": document_id}],
            query_id="graph-rebuild",
            user_query="Graph rebuild",
            retrieval_query="Graph rebuild",
            evidence_action="rebuild",
            force_reindex=True,
            entity_discovery=discovery,
            relation_discovery=relation_discovery,
            _state_signature_override=(indexer.extractor_signature if phase in {"relink", "relations"} else None),
            # Replay is maintenance, not a new user evidence event.  For a
            # fresh graph we count the discovery pass once per distinct doc;
            # relink never increments it a second time.
            count_evidence=discovery,
            force_oversize=force_oversize,
        )
        docs = list(result.get("documents") or [])
        errs = list(result.get("errors") or [])
        if errs or not docs:
            failed += 1
            errors.extend([{"document_id": document_id, **dict(err)} for err in errs] or [{
                "document_id": document_id,
                "error": "no_document_result",
            }])
        else:
            ok += 1
            doc = docs[0]
            observations = list(doc.get("discovered_entities") or [])
            resolutions = list(doc.get("entity_resolutions") or [])
            discovered += len(observations)
            relations += len(doc.get("relations") or [])
            created += sum(1 for item in resolutions if item.get("status") == "created_provisional")
            resolved += sum(1 for item in resolutions if item.get("status") == "resolved_existing")
            ambiguous += sum(1 for item in resolutions if item.get("status") == "ambiguous")
            unresolved += sum(1 for item in resolutions if item.get("status") == "unresolved")
            rejected += sum(1 for item in resolutions if item.get("status") == "rejected")
        if sleep_seconds > 0:
            time.sleep(sleep_seconds)

    return {
        "phase": phase,
        "documents_total": total,
        "documents_ok": ok,
        "documents_failed": failed,
        "entity_observations": discovered,
        "relation_observations": relations,
        "entities_created_provisional": created,
        "entities_resolved_existing": resolved,
        "entities_ambiguous": ambiguous,
        "observations_unresolved": unresolved,
        "observations_rejected": rejected,
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Replay graph_queue evidence through Graph v3")
    parser.add_argument("--config", default=str(BASE_DIR / "config.yaml"))
    parser.add_argument("--phase", choices=["discover", "relink", "relations", "both"], default="both")
    parser.add_argument("--limit", type=int, default=0, help="process at most N distinct documents; 0=all")
    parser.add_argument("--offset", type=int, default=0, help="skip first N distinct documents")
    parser.add_argument("--document", action="append", default=[], help="process only these document_id values; repeatable")
    parser.add_argument("--sleep", type=float, default=0.0, help="optional pause between documents")
    parser.add_argument("--log-level", default="INFO")
    parser.add_argument("--force", action="store_true", help="force reindex and bypass automatic oversize limits")
    parser.add_argument("--force-oversize", action="store_true", help="bypass automatic graph oversize limits")
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, str(args.log_level).upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    cfg = load_config(args.config)
    queue = GraphQueue(cfg)
    ids = [str(x).strip() for x in args.document if str(x).strip()]
    if not ids:
        ids = _document_ids(queue, limit=max(0, args.limit), offset=max(0, args.offset))
    if not ids:
        print(json.dumps({"documents": 0, "message": "Keine document_id in der Graph-Queue gefunden."}, ensure_ascii=False, indent=2))
        return 0

    # Fail early before spending model time.
    with GraphStore.from_config(cfg) as graph:
        graph.verify_connectivity()
        graph.ensure_schema()
        before = graph.stats()

    indexer = GraphEvidenceIndexer(cfg)
    summaries: list[dict[str, Any]] = []
    if args.phase in {"discover", "both"}:
        summaries.append(_run_phase(indexer, ids, phase="discover", sleep_seconds=max(0.0, args.sleep), force_oversize=(args.force or args.force_oversize)))
    if args.phase in {"relink", "both"}:
        summaries.append(_run_phase(indexer, ids, phase="relink", sleep_seconds=max(0.0, args.sleep), force_oversize=(args.force or args.force_oversize)))
    if args.phase == "relations":
        summaries.append(_run_phase(indexer, ids, phase="relations", sleep_seconds=max(0.0, args.sleep), force_oversize=(args.force or args.force_oversize)))

    with GraphStore.from_config(cfg) as graph:
        after = graph.stats()

    output = {
        "queue_database": str(queue.path),
        "documents": len(ids),
        "extractor": EXTRACTOR_VERSION,
        "before": before,
        "phases": summaries,
        "after": after,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2, default=str))
    return 1 if any(int(item.get("documents_failed") or 0) for item in summaries) else 0


if __name__ == "__main__":
    raise SystemExit(main())
