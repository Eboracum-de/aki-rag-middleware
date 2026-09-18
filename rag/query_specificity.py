"""Deterministic query-specificity helpers.

Kept dependency-light so broad-query behaviour can be regression-tested without
loading Qdrant, Neo4j or reranker runtimes.
"""
from __future__ import annotations

import re

_BROAD_ENTITY_GENERIC_WORDS = {
    "alle", "alles", "dokument", "dokumente", "dokumenten", "finde", "find",
    "gibt", "informationen", "information", "info", "infos", "mir", "nach",
    "suche", "such", "uber", "über", "unterlagen", "was", "weisst", "weißt",
    "wissen", "zu", "zeige", "zeig", "wer", "ist", "es", "den", "die", "der",
    "eine", "einen", "zum", "zur", "von", "intern", "interne", "internen",
    "netz", "web", "internet", "online", "und", "im",
}

def is_broad_entity_query(question: str, entity_context: dict) -> bool:
    """Detect single-entity navigation queries without a narrowing anchor."""
    resolved = [
        item for item in (entity_context.get("entities") or [])
        if str(item.get("status") or "") == "resolved" and str(item.get("entity_id") or "").strip()
    ]
    if len(resolved) != 1:
        return False
    text = str(question or "")
    mention = str(resolved[0].get("mention") or resolved[0].get("display_name") or "").strip()
    if mention:
        text = re.sub(re.escape(mention), " ", text, count=1, flags=re.IGNORECASE)
    if re.search(r"\b(?:19|20)\d{2}\b|\b\d{1,2}[./-]\d{1,2}(?:[./-]\d{2,4})?\b", text):
        return False
    words = [w.casefold() for w in re.findall(r"[\wÄÖÜäöüß-]+", text, flags=re.UNICODE)]
    substantive = [w for w in words if w not in _BROAD_ENTITY_GENERIC_WORDS and len(w) > 1]
    return not substantive
