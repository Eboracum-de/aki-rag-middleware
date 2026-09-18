"""Helpers for persistent positive research findings.

RC10 deliberately does *not* run another graph-extraction model.  It preserves
semantic work that already happened in the retrieval planner and candidate
verifier.  Only positive, document-grounded matches are eligible.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from rag.retrieval_planner import normalize_query_frame

PROVENANCE_CODE = "aki_research"
PROVENANCE_LABEL = "AKI Recherche"


def _clean(value: Any, limit: int = 500) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:limit]


def canonical_query_frame(value: Any) -> dict[str, Any]:
    """Return a stable semantic frame independent of planner-local entity IDs.

    Planner entity IDs (e.g. e1/e2) are local implementation details.  Findings
    should coalesce when the same semantic frame is produced with a different
    local numbering or entity order, so entities are sorted by their textual
    role and remapped to stable q1/q2/... identifiers before hashing.
    """
    frame = normalize_query_frame(value)
    entities = list(frame.get("entities") or [])
    entities.sort(key=lambda item: (
        str(item.get("text") or "").casefold(),
        str(item.get("role") or "").casefold(),
        str(item.get("id") or "").casefold(),
    ))

    id_map: dict[str, str] = {}
    canonical_entities: list[dict[str, str]] = []
    for index, item in enumerate(entities, start=1):
        old_id = str(item.get("id") or "")
        new_id = f"q{index}"
        id_map[old_id] = new_id
        canonical_entities.append({
            "id": new_id,
            "text": _clean(item.get("text"), 300),
            "role": _clean(item.get("role"), 160),
        })

    relations: list[dict[str, str]] = []
    for item in frame.get("relations") or []:
        source = id_map.get(str(item.get("source") or ""))
        target = id_map.get(str(item.get("target") or ""))
        predicate = _clean(item.get("predicate"), 300)
        if source and target and predicate:
            relations.append({"source": source, "predicate": predicate, "target": target})
    relations.sort(key=lambda item: (item["source"], item["predicate"].casefold(), item["target"]))

    constraints = [
        {"kind": _clean(item.get("kind"), 120), "value": _clean(item.get("value"), 300)}
        for item in (frame.get("constraints") or [])
        if isinstance(item, dict) and _clean(item.get("kind"), 120) and _clean(item.get("value"), 300)
    ]
    constraints.sort(key=lambda item: (item["kind"].casefold(), item["value"].casefold()))

    concepts = sorted(
        {_clean(item, 240) for item in (frame.get("concepts") or []) if _clean(item, 240)},
        key=str.casefold,
    )

    return {
        "intent": _clean(frame.get("intent"), 240),
        "entities": canonical_entities,
        "relations": relations,
        "constraints": constraints,
        "concepts": concepts,
    }


def query_frame_has_structure(value: Any) -> bool:
    """Return true when a frame contains reusable semantics beyond a generic intent."""
    frame = canonical_query_frame(value)
    return bool(frame["entities"] or frame["relations"] or frame["constraints"] or frame["concepts"])


def query_frame_hash(value: Any) -> str:
    frame = canonical_query_frame(value)
    payload = json.dumps(frame, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def finding_id(document_id: str, query_frame: Any, *, provenance_code: str = PROVENANCE_CODE) -> str:
    basis = "\0".join((str(provenance_code or PROVENANCE_CODE), str(document_id or ""), query_frame_hash(query_frame)))
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()


def frame_relation_texts(value: Any) -> list[str]:
    """Render stable human-readable relation descriptors without creating fact edges."""
    frame = canonical_query_frame(value)
    by_id = {item["id"]: item["text"] for item in frame["entities"]}
    out: list[str] = []
    for relation in frame["relations"]:
        source = by_id.get(relation["source"], relation["source"])
        target = by_id.get(relation["target"], relation["target"])
        out.append(f"{source} | {relation['predicate']} | {target}"[:1000])
    return out
