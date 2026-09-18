"""Deterministische Analyse der Retrieval-Trefferlisten.

Die Rohscores von Elasticsearch und Qdrant werden NICHT miteinander verglichen.
Jeder Arm wird relativ zu seiner eigenen Scorekurve beurteilt. Harte Grenzwerte
bleiben lediglich ein Fangnetz für offensichtlich flache Trefferfelder.
"""

from __future__ import annotations

import math
import statistics
from typing import Any, Iterable


_EPSILON = 1e-12


def _finite_scores(values: Iterable[Any]) -> list[float]:
    scores: list[float] = []
    for value in values:
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(number):
            scores.append(number)
    return sorted(scores, reverse=True)


def analyze_score_curve(
    scores: Iterable[Any],
    *,
    total_hits: int | None = None,
    total_relation: str | None = None,
    explicit_anchor: bool = False,
    head_size: int = 3,
    tail_fraction: float = 0.33,
    min_curve_candidates: int = 8,
    small_field_signal: float = 0.35,
    explicit_anchor_signal: float = 0.45,
) -> dict[str, Any]:
    """Beschreibt die Form einer absteigenden Trefferliste.

    ``signal_strength`` misst die Trennung von Kopf und Hintergrund der Liste.
    Kleine Trefferfelder werden nicht als unspezifisch verworfen, weil eine
    Kurvenanalyse dort statistisch wenig aussagekräftig ist. Ein expliziter
    Benutzeranker (+term oder "phrase") zählt ebenfalls als starkes
    lexikalisches Signal, ohne die Rohscores zu verändern.
    """

    ordered = _finite_scores(scores)
    count = len(ordered)

    profile: dict[str, Any] = {
        "available": bool(ordered),
        "count": count,
        "total_hits": total_hits,
        "total_relation": total_relation,
        "explicit_anchor": bool(explicit_anchor),
        "curve_reliable": count >= max(2, min_curve_candidates),
        "top_score": ordered[0] if ordered else None,
        "tail_median": None,
        "head_mean": None,
        "relative_spread": 0.0,
        "head_contrast": 0.0,
        "elbow_strength": 0.0,
        "elbow_rank": None,
        "raw_signal_strength": 0.0,
        "signal_strength": 0.0,
    }

    if not ordered:
        return profile

    head_size = max(1, int(head_size))
    tail_fraction = min(1.0, max(0.05, float(tail_fraction)))
    head_count = min(head_size, count)
    tail_count = min(count, max(1, math.ceil(count * tail_fraction)))

    head_mean = statistics.fmean(ordered[:head_count])
    tail_median = statistics.median(ordered[-tail_count:])
    top_score = ordered[0]
    denominator = max(abs(top_score), _EPSILON)

    relative_spread = max(0.0, (top_score - tail_median) / denominator)
    head_contrast = max(0.0, (head_mean - tail_median) / denominator)

    elbow_strength = 0.0
    elbow_rank: int | None = None
    if count >= 2:
        drops = [
            max(0.0, (ordered[index] - ordered[index + 1]) / denominator)
            for index in range(count - 1)
        ]
        elbow_strength = max(drops)
        elbow_rank = drops.index(elbow_strength) + 1

    # Interpretierbare Mischung: dominierend ist die Trennung zwischen dem
    # Kopf der Liste und ihrem Hintergrund; Gesamtspreizung und stärkster
    # einzelner Sprung ergänzen das Bild.
    raw_signal = (
        0.55 * head_contrast
        + 0.25 * relative_spread
        + 0.20 * elbow_strength
    )
    raw_signal = min(1.0, max(0.0, raw_signal))

    effective_signal = raw_signal
    if count < min_curve_candidates:
        effective_signal = max(effective_signal, float(small_field_signal))
    if explicit_anchor:
        effective_signal = max(effective_signal, float(explicit_anchor_signal))
    effective_signal = min(1.0, max(0.0, effective_signal))

    profile.update(
        {
            "tail_median": tail_median,
            "head_mean": head_mean,
            "relative_spread": relative_spread,
            "head_contrast": head_contrast,
            "elbow_strength": elbow_strength,
            "elbow_rank": elbow_rank,
            "raw_signal_strength": raw_signal,
            "signal_strength": effective_signal,
        }
    )
    return profile


def overlap_at_k(
    left_document_ids: Iterable[str],
    right_document_ids: Iterable[str],
    k: int = 10,
) -> dict[str, Any]:
    k = max(1, int(k))
    left = [value for value in left_document_ids if value][:k]
    right = [value for value in right_document_ids if value][:k]
    common = set(left).intersection(right)
    denominator = min(len(left), len(right))
    return {
        "k": k,
        "common": len(common),
        "ratio": (len(common) / denominator) if denominator else 0.0,
    }


def choose_retrieval_strategy(
    es_profile: dict[str, Any],
    vector_profile: dict[str, Any],
    *,
    unspecific_signal_floor: float = 0.08,
    dominance_ratio: float = 1.50,
    dominance_margin: float = 0.10,
    secondary_weight_floor: float = 0.20,
) -> dict[str, Any]:
    """Wählt ES, Vector oder Fusion aus der Form der beiden Listen.

    Ein Trefferfeld darf nur wegen eines niedrigen Signals als unspezifisch
    gelten, wenn genügend Kandidaten für eine belastbare Kurvenmessung
    vorliegen und kein expliziter Benutzeranker es schützt.
    """

    floor = max(0.0, float(unspecific_signal_floor))
    ratio = max(1.0, float(dominance_ratio))
    margin = max(0.0, float(dominance_margin))
    secondary_floor = min(1.0, max(0.0, float(secondary_weight_floor)))

    def state(profile: dict[str, Any]) -> tuple[bool, float, bool]:
        available = bool(profile.get("available"))
        signal = float(profile.get("signal_strength") or 0.0)
        rejectable = bool(profile.get("curve_reliable")) and not bool(
            profile.get("explicit_anchor")
        )
        weak = available and rejectable and signal < floor
        return available, signal, weak

    es_available, es_signal, es_weak = state(es_profile)
    vector_available, vector_signal, vector_weak = state(vector_profile)

    if not es_available and not vector_available:
        return {
            "strategy": "no_results",
            "es_weight": 0.0,
            "vector_weight": 0.0,
            "reason": "Beide Retrieval-Arme lieferten keine verwendbaren Treffer.",
        }

    if es_available and not vector_available:
        if es_weak:
            return {
                "strategy": "unspecific",
                "es_weight": 0.0,
                "vector_weight": 0.0,
                "reason": "Die Elasticsearch-Trefferliste ist breit und nahezu flach.",
            }
        return {
            "strategy": "es_preferred",
            "es_weight": 1.0,
            "vector_weight": 0.0,
            "reason": "Nur Elasticsearch liefert ein belastbares Trefferbild.",
        }

    if vector_available and not es_available:
        if vector_weak:
            return {
                "strategy": "unspecific",
                "es_weight": 0.0,
                "vector_weight": 0.0,
                "reason": "Die Vektor-Trefferliste ist breit und nahezu flach.",
            }
        return {
            "strategy": "vector_preferred",
            "es_weight": 0.0,
            "vector_weight": 1.0,
            "reason": "Nur die Vektorsuche liefert ein belastbares Trefferbild.",
        }

    if es_weak and vector_weak:
        return {
            "strategy": "unspecific",
            "es_weight": 0.0,
            "vector_weight": 0.0,
            "reason": "Beide Retrieval-Arme liefern breite, nahezu flache Trefferfelder.",
        }

    if es_weak and not vector_weak:
        return {
            "strategy": "vector_preferred",
            "es_weight": secondary_floor,
            "vector_weight": 1.0,
            "reason": "Die Vektorsuche trennt deutlich besser als Elasticsearch.",
        }

    if vector_weak and not es_weak:
        return {
            "strategy": "es_preferred",
            "es_weight": 1.0,
            "vector_weight": secondary_floor,
            "reason": "Elasticsearch trennt deutlich besser als die Vektorsuche.",
        }

    es_dominates = (
        es_signal >= vector_signal * ratio
        and es_signal - vector_signal >= margin
    )
    vector_dominates = (
        vector_signal >= es_signal * ratio
        and vector_signal - es_signal >= margin
    )

    if es_dominates:
        secondary = max(
            secondary_floor,
            min(1.0, vector_signal / max(es_signal, _EPSILON)),
        )
        return {
            "strategy": "es_preferred",
            "es_weight": 1.0,
            "vector_weight": secondary,
            "reason": "Die Elasticsearch-Trefferliste trägt das klarere Signal.",
        }

    if vector_dominates:
        secondary = max(
            secondary_floor,
            min(1.0, es_signal / max(vector_signal, _EPSILON)),
        )
        return {
            "strategy": "vector_preferred",
            "es_weight": secondary,
            "vector_weight": 1.0,
            "reason": "Die Vektor-Trefferliste trägt das klarere Signal.",
        }

    return {
        "strategy": "fusion",
        "es_weight": 1.0,
        "vector_weight": 1.0,
        "reason": "Beide Retrieval-Arme liefern ein ähnlich klares Signal.",
    }
