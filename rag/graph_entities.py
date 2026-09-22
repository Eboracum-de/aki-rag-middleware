#!/usr/bin/env python3
"""Query-side entity detection/resolution against the Neo4j identity seed.

Phase 1.5 adds *fuzzy candidate generation* for OCR/typing deviations while
keeping identity resolution conservative:

- exact/recorded forms may resolve an entity;
- graph context may disambiguate exact candidates;
- fuzzy forms only create ranked candidates for retrieval/inspection;
- fuzzy matching never merges entities and never writes aliases to Neo4j.

Example: ``Mäx Mustermann`` may produce ``Max Mustermann`` as a fuzzy candidate,
but it remains explicitly marked as fuzzy unless stronger graph context exists.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable

from rapidfuzz import fuzz

from rag.graph import BASE_DIR, GraphStore, load_config, normalize_name


DEFAULT_FUZZY_THRESHOLD = 86.0
DEFAULT_FUZZY_STRONG_THRESHOLD = 92.0
DEFAULT_FUZZY_MAX_CANDIDATES = 5
DEFAULT_FUZZY_MAX_TOKENS = 6


@dataclass
class EntityCandidate:
    entity_id: str
    entity_type: str
    display_name: str
    form_value: str
    form_type: str
    weight: float
    similarity: float = 100.0
    candidate_score: float = 1.0
    reasons: list[str] = field(default_factory=list)


@dataclass
class QueryEntity:
    mention: str
    normalized_mention: str
    start: int
    end: int
    status: str
    entity_id: str | None = None
    entity_type: str | None = None
    display_name: str | None = None
    matched_form: str | None = None
    matched_form_type: str | None = None
    resolution_weight: float = 0.0
    resolution_method: str | None = None
    candidates: list[EntityCandidate] = field(default_factory=list)
    search_forms: list[dict[str, Any]] = field(default_factory=list)
    context_links: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class EntityAwareQuery:
    original_query: str
    entities: list[QueryEntity]

    @property
    def resolved_entities(self) -> list[QueryEntity]:
        return [e for e in self.entities if e.status == "resolved"]

    @property
    def fuzzy_entities(self) -> list[QueryEntity]:
        return [e for e in self.entities if e.status == "fuzzy_candidate"]

    def to_dict(self) -> dict[str, Any]:
        return {
            "original_query": self.original_query,
            "entities": [asdict(e) for e in self.entities],
        }


def _entity_type(labels: list[str]) -> str:
    if "Person" in labels:
        return "PERSON"
    if "OrganizationalUnit" in labels:
        return "ORGANIZATIONAL_UNIT"
    if "Organization" in labels:
        return "ORGANIZATION"
    return "ENTITY"


def _normalized_with_map(text: str) -> tuple[str, list[int]]:
    """Normalize a query and retain a best-effort char map to original text."""
    pieces: list[str] = []
    mapping: list[int] = []
    in_space = True
    for idx, char in enumerate(text):
        norm = normalize_name(char)
        if norm:
            for c in norm:
                pieces.append(c)
                mapping.append(idx)
            in_space = False
        else:
            if not in_space and pieces:
                pieces.append(" ")
                mapping.append(idx)
                in_space = True
    while pieces and pieces[-1] == " ":
        pieces.pop()
        mapping.pop()
    return "".join(pieces), mapping


def _token_spans(normalized_query: str) -> list[tuple[int, int, str]]:
    return [(m.start(), m.end(), m.group(0)) for m in re.finditer(r"\S+", normalized_query)]


def _overlaps(start: int, end: int, spans: Iterable[tuple[int, int]]) -> bool:
    return any(not (end <= s or start >= e) for s, e in spans)


def _candidate_from_form(
    item: dict[str, Any],
    *,
    fallback_form: str,
    similarity: float = 100.0,
    reason: str,
) -> EntityCandidate:
    form_weight = float(item.get("weight", 0.0))
    similarity01 = max(0.0, min(1.0, similarity / 100.0))
    # Source weight and string similarity both matter.  This score is only a
    # retrieval/candidate ranking signal, never an identity-merge probability.
    candidate_score = round(form_weight * similarity01, 4)
    return EntityCandidate(
        entity_id=str(item["entity_id"]),
        entity_type=_entity_type(item.get("labels") or []),
        display_name=str(item.get("display_name") or ""),
        form_value=str(item.get("value") or fallback_form),
        form_type=str(item.get("form_type") or "name"),
        weight=form_weight,
        similarity=round(float(similarity), 2),
        candidate_score=candidate_score,
        reasons=[reason],
    )


def _dedup_candidates(candidates: Iterable[EntityCandidate]) -> list[EntityCandidate]:
    dedup: dict[str, EntityCandidate] = {}
    for candidate in candidates:
        old = dedup.get(candidate.entity_id)
        if old is None or candidate.candidate_score > old.candidate_score:
            dedup[candidate.entity_id] = candidate
        elif old is not None:
            old.reasons = sorted(set(old.reasons + candidate.reasons))
    return sorted(
        dedup.values(),
        key=lambda c: (c.candidate_score, c.similarity, c.weight),
        reverse=True,
    )


def _exact_matches(
    normalized_query: str,
    forms: list[dict[str, Any]],
) -> list[tuple[int, int, str, list[dict[str, Any]]]]:
    by_form: dict[str, list[dict[str, Any]]] = {}
    for form in forms:
        normalized = str(form.get("normalized") or "").strip()
        if len(normalized) < 3:
            continue
        by_form.setdefault(normalized, []).append(form)

    matches: list[tuple[int, int, str, list[dict[str, Any]]]] = []
    for form, candidates in by_form.items():
        pattern = re.compile(rf"(?<!\w){re.escape(form)}(?!\w)")
        for m in pattern.finditer(normalized_query):
            matches.append((m.start(), m.end(), form, candidates))

    def match_strength(item):
        start, end, _, candidates = item
        max_weight = max(float(c.get("weight", 0.0)) for c in candidates)
        return (end - start, max_weight)

    matches.sort(key=match_strength, reverse=True)
    accepted: list[tuple[int, int, str, list[dict[str, Any]]]] = []
    for candidate in matches:
        s, e, _, _ = candidate
        if any(not (e <= as_ or s >= ae) for as_, ae, _, _ in accepted):
            continue
        accepted.append(candidate)
    accepted.sort(key=lambda x: x[0])
    return accepted


def _fuzzy_matches(
    normalized_query: str,
    forms: list[dict[str, Any]],
    *,
    occupied: list[tuple[int, int]],
    threshold: float,
    max_candidates: int,
    max_tokens: int,
) -> list[tuple[int, int, str, list[EntityCandidate]]]:
    """Find typo/OCR-tolerant query spans.

    Only multi-token spans are considered by default because fuzzy single-word
    matching against person surnames or organization fragments creates too many
    false positives.  Exact single-word entities are still handled above.
    """
    token_spans = _token_spans(normalized_query)
    if len(token_spans) < 2:
        return []

    # Collapse graph forms by normalized spelling first.  A spelling can still
    # point to several entities, which is preserved in the candidate list.
    by_form: dict[str, list[dict[str, Any]]] = {}
    for form in forms:
        normalized = str(form.get("normalized") or "").strip()
        n_tokens = len(normalized.split())
        if len(normalized) < 4 or n_tokens < 2 or n_tokens > max_tokens:
            continue
        by_form.setdefault(normalized, []).append(form)

    found: list[tuple[int, int, str, list[EntityCandidate], float]] = []
    for i in range(len(token_spans)):
        for length in range(2, max_tokens + 1):
            j = i + length
            if j > len(token_spans):
                break
            start = token_spans[i][0]
            end = token_spans[j - 1][1]
            if _overlaps(start, end, occupied):
                continue
            span_text = normalized_query[start:end]

            local_candidates: list[EntityCandidate] = []
            best_similarity = 0.0
            for known_form, raw_candidates in by_form.items():
                # Compare spans to forms of approximately equal token length.
                form_len = len(known_form.split())
                if abs(form_len - length) > 1:
                    continue
                similarity = float(fuzz.ratio(span_text, known_form))
                if similarity < threshold:
                    continue
                best_similarity = max(best_similarity, similarity)
                for item in raw_candidates:
                    local_candidates.append(_candidate_from_form(
                        item,
                        fallback_form=known_form,
                        similarity=similarity,
                        reason=f"fuzzy_name_similarity:{similarity:.1f}",
                    ))

            local_candidates = _dedup_candidates(local_candidates)[:max_candidates]
            if local_candidates:
                found.append((start, end, span_text, local_candidates, best_similarity))

    # Prefer longest/highest-confidence non-overlapping spans.
    found.sort(key=lambda x: ((x[1] - x[0]), x[4], x[3][0].candidate_score), reverse=True)
    accepted: list[tuple[int, int, str, list[EntityCandidate]]] = []
    used = list(occupied)
    for start, end, span_text, candidates, _ in found:
        if _overlaps(start, end, used):
            continue
        accepted.append((start, end, span_text, candidates))
        used.append((start, end))
    accepted.sort(key=lambda x: x[0])
    return accepted


def _to_original_span(
    query: str,
    charmap: list[int],
    start: int,
    end: int,
    fallback: str,
) -> tuple[int, int, str]:
    if not charmap:
        return 0, 0, fallback
    orig_start = charmap[min(start, len(charmap) - 1)]
    orig_end = charmap[min(end - 1, len(charmap) - 1)] + 1
    mention = query[orig_start:orig_end].strip(" \t\r\n,;:()[]{}") or fallback
    return orig_start, orig_end, mention


def detect_known_entities(
    query: str,
    graph: GraphStore,
    *,
    fuzzy: bool = True,
    fuzzy_threshold: float = DEFAULT_FUZZY_THRESHOLD,
    fuzzy_max_candidates: int = DEFAULT_FUZZY_MAX_CANDIDATES,
    fuzzy_max_tokens: int = DEFAULT_FUZZY_MAX_TOKENS,
) -> EntityAwareQuery:
    normalized_query, charmap = _normalized_with_map(query)
    forms = graph.name_forms(include_inactive_names=True)

    exact = _exact_matches(normalized_query, forms)
    entities: list[QueryEntity] = []
    occupied: list[tuple[int, int]] = []

    for s, e, form, raw_candidates in exact:
        orig_start, orig_end, mention = _to_original_span(query, charmap, s, e, form)
        candidates = _dedup_candidates(
            _candidate_from_form(item, fallback_form=form, reason="exact_name_form")
            for item in raw_candidates
        )
        occupied.append((s, e))

        same_as_resolved = False
        if len(candidates) > 1:
            component_lookup = getattr(graph, "same_as_component_ids", None)
            if callable(component_lookup):
                component = set(component_lookup(candidates[0].entity_id))
                same_as_resolved = bool(component) and all(c.entity_id in component for c in candidates)

        if len(candidates) == 1 or same_as_resolved:
            c = candidates[0]
            entities.append(QueryEntity(
                mention=mention,
                normalized_mention=form,
                start=orig_start,
                end=orig_end,
                status="resolved",
                entity_id=c.entity_id,
                entity_type=c.entity_type,
                display_name=c.display_name,
                matched_form=c.form_value,
                matched_form_type=c.form_type,
                resolution_weight=c.weight,
                resolution_method="same_as_equivalent_form" if same_as_resolved else "unique_name_form",
                candidates=candidates,
                search_forms=graph.entity_search_forms(c.entity_id),
            ))
        else:
            entities.append(QueryEntity(
                mention=mention,
                normalized_mention=form,
                start=orig_start,
                end=orig_end,
                status="ambiguous",
                matched_form=candidates[0].form_value if candidates else form,
                matched_form_type=candidates[0].form_type if candidates else None,
                resolution_weight=candidates[0].weight if candidates else 0.0,
                resolution_method="ambiguous_name_form",
                candidates=candidates,
            ))

    if fuzzy:
        for s, e, span_text, candidates in _fuzzy_matches(
            normalized_query,
            forms,
            occupied=occupied,
            threshold=fuzzy_threshold,
            max_candidates=fuzzy_max_candidates,
            max_tokens=fuzzy_max_tokens,
        ):
            orig_start, orig_end, mention = _to_original_span(query, charmap, s, e, span_text)
            best = candidates[0]
            # Fuzzy matching is deliberately a candidate, not a resolution.
            entities.append(QueryEntity(
                mention=mention,
                normalized_mention=span_text,
                start=orig_start,
                end=orig_end,
                status="fuzzy_candidate",
                entity_id=None,
                entity_type=None,
                display_name=None,
                matched_form=best.form_value,
                matched_form_type=best.form_type,
                resolution_weight=best.candidate_score,
                resolution_method="fuzzy_name_form",
                candidates=candidates,
                search_forms=[],
            ))

    entities.sort(key=lambda e: e.start)

    # Conservative graph-context disambiguation for exact ambiguous forms.
    changed = True
    while changed:
        changed = False
        resolved_ids = [e.entity_id for e in entities if e.status == "resolved" and e.entity_id]
        if not resolved_ids:
            break
        for entity in entities:
            if entity.status != "ambiguous" or not entity.candidates:
                continue
            candidate_ids = [c.entity_id for c in entity.candidates]
            links = graph.candidate_context_links(candidate_ids, resolved_ids)
            if not links:
                continue

            scores: dict[str, int] = {}
            for candidate_id, candidate_links in links.items():
                scores[candidate_id] = sum(
                    max(1, len(link.get("relations") or []))
                    for link in candidate_links
                )
            if not scores:
                continue
            best_score = max(scores.values())
            best_ids = [candidate_id for candidate_id, score in scores.items() if score == best_score]
            if best_score <= 0 or len(best_ids) != 1:
                continue

            best_id = best_ids[0]
            best = next((c for c in entity.candidates if c.entity_id == best_id), None)
            if best is None:
                continue
            entity.status = "resolved"
            entity.entity_id = best.entity_id
            entity.entity_type = best.entity_type
            entity.display_name = best.display_name
            entity.matched_form = best.form_value
            entity.matched_form_type = best.form_type
            entity.resolution_weight = best.weight
            entity.resolution_method = "graph_context"
            entity.search_forms = graph.entity_search_forms(best.entity_id)
            entity.context_links = links.get(best.entity_id, [])
            changed = True

    # Fuzzy candidates may use already-resolved context for *ranking*, but are
    # intentionally not promoted to resolved status in this prototype.
    resolved_ids = [e.entity_id for e in entities if e.status == "resolved" and e.entity_id]
    if resolved_ids:
        for entity in entities:
            if entity.status != "fuzzy_candidate" or not entity.candidates:
                continue
            links = graph.candidate_context_links(
                [c.entity_id for c in entity.candidates],
                resolved_ids,
            )
            if not links:
                continue
            for candidate in entity.candidates:
                candidate_links = links.get(candidate.entity_id, [])
                if candidate_links:
                    candidate.candidate_score = round(min(1.0, candidate.candidate_score + 0.06), 4)
                    candidate.reasons.append("graph_context_support")
            entity.candidates.sort(key=lambda c: c.candidate_score, reverse=True)
            entity.context_links = [
                {"candidate_entity_id": cid, "links": candidate_links}
                for cid, candidate_links in links.items()
            ]
            if entity.candidates:
                entity.resolution_weight = entity.candidates[0].candidate_score
                entity.matched_form = entity.candidates[0].form_value
                entity.matched_form_type = entity.candidates[0].form_type

    return EntityAwareQuery(original_query=query, entities=entities)


def elastic_entity_phrases(entity_query: EntityAwareQuery) -> list[dict[str, Any]]:
    """Return weighted phrase expansions suitable for later ES integration.

    Resolved entities export all known search forms.  Fuzzy candidates export
    only the best candidate's canonical/search forms with an additional fuzzy
    penalty and retain the original typo in the user's query untouched.
    """
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    for entity in entity_query.resolved_entities:
        for form in entity.search_forms:
            value = str(form.get("value") or "").strip()
            if not value:
                continue
            key = (entity.entity_id or "", normalize_name(value))
            if key in seen:
                continue
            seen.add(key)
            out.append({
                "entity_id": entity.entity_id,
                "entity_type": entity.entity_type,
                "value": value,
                "weight": float(form.get("weight", 0.5)),
                "kind": form.get("kind"),
                "active": bool(form.get("active", True)),
                "source": form.get("source"),
                "resolution": entity.resolution_method,
            })

    for entity in entity_query.fuzzy_entities:
        if not entity.candidates:
            continue
        best = entity.candidates[0]
        # Require a clearly useful fuzzy candidate for query expansion.
        if best.similarity < DEFAULT_FUZZY_STRONG_THRESHOLD:
            continue
        forms = entity.search_forms or []
        # Fetch lazily is not possible here without graph; therefore include the
        # matched known form itself.  search.py integration can later expand the
        # candidate via GraphStore.entity_search_forms().
        value = best.form_value.strip()
        if not value:
            continue
        key = (best.entity_id, normalize_name(value))
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "entity_id": best.entity_id,
            "entity_type": best.entity_type,
            "value": value,
            "weight": round(min(0.78, best.candidate_score * 0.82), 4),
            "kind": "fuzzy_candidate",
            "active": True,
            "source": "fuzzy",
            "similarity": best.similarity,
            "original_mention": entity.mention,
            "resolution": "fuzzy_candidate",
        })
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Detect/resolve query entities against Neo4j")
    parser.add_argument("query", help="Natural-language query")
    parser.add_argument("--config", default=str(BASE_DIR / "config.yaml"))
    parser.add_argument("--no-fuzzy", action="store_true", help="Disable typo/OCR-tolerant candidate generation")
    parser.add_argument("--fuzzy-threshold", type=float, default=DEFAULT_FUZZY_THRESHOLD)
    parser.add_argument("--fuzzy-max-candidates", type=int, default=DEFAULT_FUZZY_MAX_CANDIDATES)
    args = parser.parse_args()

    cfg = load_config(args.config)
    with GraphStore.from_config(cfg) as graph:
        graph.verify_connectivity()
        result = detect_known_entities(
            args.query,
            graph,
            fuzzy=not args.no_fuzzy,
            fuzzy_threshold=args.fuzzy_threshold,
            fuzzy_max_candidates=args.fuzzy_max_candidates,
        )
        payload = result.to_dict()
        payload["elastic_phrase_expansion"] = elastic_entity_phrases(result)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
