"""Small structured query contract shared by provider and retrieval API.

A SearchSpec is deliberately small.  The query rewriter writes one
Nextcloud-compatible full-text expression for the Elasticsearch/files arm and
one natural semantic query for the vector arm.  Entity/concept/constraint fields
are analytical side-products for Graph-Lite, verification and provenance; they
do not silently rewrite the files query.
"""
from __future__ import annotations

import re
from typing import Any


def _clean_text(value: Any, *, max_len: int = 300) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:max_len]


def _clean_list(value: Any, *, max_items: int = 24) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = _clean_text(item)
        folded = text.casefold()
        if not text or folded in seen:
            continue
        seen.add(folded)
        out.append(text)
        if len(out) >= max_items:
            break
    return out


def _clean_constraints(value: Any, *, max_items: int = 12) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    out: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for item in value:
        if not isinstance(item, dict):
            continue
        kind = _clean_text(item.get("kind"), max_len=120)
        val = _clean_text(item.get("value"), max_len=300)
        key = (kind.casefold(), val.casefold())
        if not kind or not val or key in seen:
            continue
        seen.add(key)
        out.append({"kind": kind, "value": val})
        if len(out) >= max_items:
            break
    return out


def normalize_search_spec(value: Any, *, original_query: str = "") -> dict[str, Any]:
    raw = value if isinstance(value, dict) else {}
    semantic_query = _clean_text(raw.get("semantic_query"), max_len=1200)
    if not semantic_query:
        semantic_query = _clean_text(original_query, max_len=1200)

    return {
        "elastic_query": _clean_text(raw.get("elastic_query"), max_len=1200),
        "semantic_query": semantic_query,
        # Analytical side-products.  These may guide verification/provenance
        # and Graph-Lite but do not silently alter elastic_query.
        "entities": _clean_list(raw.get("entities"), max_items=16),
        "concepts": _clean_list(raw.get("concepts"), max_items=16),
        "constraints": _clean_constraints(raw.get("constraints")),
        "verification_requirements": _clean_list(raw.get("verification_requirements"), max_items=16),
        # Legacy structured lexical fields remain accepted for old callers and
        # diagnostics, but rc3's query rewriter no longer emits them.
        "must": _clean_list(raw.get("must")),
        "should": _clean_list(raw.get("should")),
        "must_not": _clean_list(raw.get("must_not")),
        "phrases": _clean_list(raw.get("phrases")),
        "must_not_phrases": _clean_list(raw.get("must_not_phrases")),
    }


def has_lexical_terms(spec: dict[str, Any] | None) -> bool:
    value = spec or {}
    return bool(str(value.get("elastic_query") or "").strip()) or any(
        value.get(field) for field in ("must", "should", "phrases", "must_not", "must_not_phrases")
    )


def positive_lexical_terms(spec: dict[str, Any] | None) -> bool:
    value = spec or {}
    if str(value.get("elastic_query") or "").strip():
        return True
    return any(value.get(field) for field in ("must", "should", "phrases"))


def query_frame_from_search_spec(spec: dict[str, Any] | None, *, intent: str = "") -> dict[str, Any]:
    value = spec or {}
    entities = [
        {"id": f"q{index}", "text": text, "role": ""}
        for index, text in enumerate(value.get("entities") or [], start=1)
        if str(text or "").strip()
    ]
    return {
        "intent": _clean_text(intent, max_len=500),
        "entities": entities,
        "relations": [],
        "constraints": list(value.get("constraints") or []),
        "concepts": list(value.get("concepts") or []),
    }


def fingerprint(spec: dict[str, Any] | None) -> tuple:
    value = spec or {}
    return (
        str(value.get("elastic_query") or ""),
        str(value.get("semantic_query") or ""),
        tuple(value.get("entities") or []),
        tuple(value.get("concepts") or []),
        tuple((str(item.get("kind") or ""), str(item.get("value") or "")) for item in (value.get("constraints") or []) if isinstance(item, dict)),
        tuple(value.get("verification_requirements") or []),
    )
