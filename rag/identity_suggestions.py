#!/usr/bin/env python3
"""Read-only duplicate/identity suggestions for the Neo4j seed graph.

The module NEVER merges entities and NEVER changes CardDAV.  It merely ranks
pairs that may describe the same real-world person/organization and explains
why.  The score is a heuristic triage score, not a calibrated probability.
"""

from __future__ import annotations

import argparse
import itertools
import json
from dataclasses import asdict, dataclass, field
from typing import Any

from rapidfuzz import fuzz

from rag.graph import BASE_DIR, GraphStore, load_config, normalize_name


@dataclass
class IdentitySuggestion:
    entity_a: dict[str, Any]
    entity_b: dict[str, Any]
    score: float
    positive_evidence: list[dict[str, Any]] = field(default_factory=list)
    contradictory_evidence: list[dict[str, Any]] = field(default_factory=list)
    status: str = "open"


def _type(profile: dict[str, Any]) -> str:
    labels = profile.get("labels") or []
    if "Person" in labels:
        return "PERSON"
    if "Organization" in labels:
        return "ORGANIZATION"
    return "ENTITY"


def _names(profile: dict[str, Any]) -> list[str]:
    values = [normalize_name(n.get("value", "")) for n in profile.get("names") or []]
    display = normalize_name(profile.get("display_name", ""))
    if display:
        values.append(display)
    return sorted({x for x in values if x})


def _middle_name_compatible(a: str, b: str) -> bool:
    """Treat extra middle/additional given names as compatible, not conflict.

    Examples:\n      max mustermann <-> max alexander mustermann\n      anna maria meier <-> anna meier\n    """
    ta = a.split()
    tb = b.split()
    if len(ta) < 2 or len(tb) < 2:
        return False
    if ta[-1] != tb[-1]:
        return False
    if ta[0] != tb[0]:
        return False
    short, long = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    # First given name and family name must align; intervening middle names may differ.
    return short[0] == long[0] and short[-1] == long[-1]


def _best_name_evidence(a: dict[str, Any], b: dict[str, Any]) -> tuple[float, dict[str, Any] | None]:
    names_a = _names(a)
    names_b = _names(b)
    best_score = 0.0
    best: dict[str, Any] | None = None
    for na in names_a:
        for nb in names_b:
            if na == nb:
                score = 0.55
                ev = {"kind": "exact_name", "a": na, "b": nb, "weight": score}
            elif _middle_name_compatible(na, nb):
                score = 0.52
                ev = {"kind": "middle_name_compatible", "a": na, "b": nb, "weight": score}
            else:
                sim = float(fuzz.ratio(na, nb))
                if sim >= 96:
                    score = 0.45
                elif sim >= 92:
                    score = 0.36
                elif sim >= 88:
                    score = 0.27
                else:
                    continue
                ev = {
                    "kind": "fuzzy_name",
                    "a": na,
                    "b": nb,
                    "similarity": round(sim, 2),
                    "weight": score,
                }
            if score > best_score:
                best_score = score
                best = ev
    return best_score, best


def _set(profile: dict[str, Any], key: str) -> set[str]:
    return {str(x) for x in profile.get(key) or [] if str(x)}


def _org_ids(profile: dict[str, Any]) -> set[str]:
    return {
        str(o.get("entity_id"))
        for o in profile.get("organizations") or []
        if o.get("entity_id")
    }


def compare_profiles(a: dict[str, Any], b: dict[str, Any]) -> IdentitySuggestion | None:
    if _type(a) != _type(b):
        return None

    score = 0.0
    evidence: list[dict[str, Any]] = []

    name_score, name_ev = _best_name_evidence(a, b)
    if name_ev:
        score += name_score
        evidence.append(name_ev)
    else:
        # Without any reasonably compatible name, do not create a suggestion.
        return None

    shared_emails = sorted(_set(a, "emails") & _set(b, "emails"))
    if shared_emails:
        score += 0.35
        evidence.append({"kind": "shared_email", "values": shared_emails, "weight": 0.35})

    shared_phones = sorted(_set(a, "phones") & _set(b, "phones"))
    if shared_phones:
        score += 0.35
        evidence.append({"kind": "shared_phone", "values": shared_phones, "weight": 0.35})

    shared_addresses = sorted(_set(a, "addresses") & _set(b, "addresses"))
    if shared_addresses:
        score += 0.20
        evidence.append({"kind": "shared_address", "values": shared_addresses, "weight": 0.20})

    shared_orgs = sorted(_org_ids(a) & _org_ids(b))
    if shared_orgs:
        score += 0.15
        evidence.append({"kind": "shared_organization", "entity_ids": shared_orgs, "weight": 0.15})

    score = round(min(score, 0.99), 3)
    return IdentitySuggestion(
        entity_a={
            "entity_id": a.get("entity_id"),
            "entity_type": _type(a),
            "display_name": a.get("display_name"),
            "contact_records": a.get("contact_records") or [],
        },
        entity_b={
            "entity_id": b.get("entity_id"),
            "entity_type": _type(b),
            "display_name": b.get("display_name"),
            "contact_records": b.get("contact_records") or [],
        },
        score=score,
        positive_evidence=evidence,
        contradictory_evidence=[],
    )


def build_suggestions(
    profiles: list[dict[str, Any]],
    *,
    min_score: float = 0.50,
    limit: int = 100,
) -> list[IdentitySuggestion]:
    suggestions: list[IdentitySuggestion] = []
    for a, b in itertools.combinations(profiles, 2):
        suggestion = compare_profiles(a, b)
        if suggestion and suggestion.score >= min_score:
            suggestions.append(suggestion)
    suggestions.sort(key=lambda s: s.score, reverse=True)
    return suggestions[:limit]


def main() -> int:
    parser = argparse.ArgumentParser(description="Suggest possible duplicate graph entities (read-only)")
    parser.add_argument("--config", default=str(BASE_DIR / "config.yaml"))
    parser.add_argument("--type", choices=["Person", "Organization"], default=None)
    parser.add_argument("--min-score", type=float, default=0.50)
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args()

    cfg = load_config(args.config)
    with GraphStore.from_config(cfg) as graph:
        graph.verify_connectivity()
        profiles = graph.identity_profiles(args.type)
        suggestions = build_suggestions(profiles, min_score=args.min_score, limit=args.limit)
        payload = {
            "note": "Scores are triage heuristics, not identity probabilities. No data was changed.",
            "profiles_seen": len(profiles),
            "suggestions": [asdict(s) for s in suggestions],
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
