"""Small, versioned relation ontology used by graph extraction.

The ontology is intentionally not part of config.yaml.  It defines graph
semantics (allowed predicates and type signatures), whereas config.yaml is
runtime tuning.  The default file lives at ``ontology/relations-v1.yaml`` and
may be overridden with ``RAG_RELATION_ONTOLOGY_FILE`` for experiments.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any

import yaml

BASE_DIR = Path(__file__).resolve().parent.parent


DEFAULT_ONTOLOGY_PATH = BASE_DIR / "ontology" / "relations-v1.yaml"


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(x).strip() for x in value if str(x).strip()]
    value = str(value).strip()
    return [value] if value else []


def load_relation_ontology(path: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    override = str(path or os.getenv("RAG_RELATION_ONTOLOGY_FILE") or "").strip()
    ontology_path = Path(override) if override else DEFAULT_ONTOLOGY_PATH
    if not ontology_path.is_absolute():
        ontology_path = BASE_DIR / ontology_path
    with ontology_path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}
    predicates_raw = raw.get("predicates") or {}
    if not isinstance(predicates_raw, dict) or not predicates_raw:
        raise RuntimeError(f"Relation ontology has no predicates: {ontology_path}")

    predicates: dict[str, dict[str, Any]] = {}
    for raw_name, raw_spec in predicates_raw.items():
        name = str(raw_name or "").strip().upper()
        if not name:
            continue
        spec = dict(raw_spec or {})
        subject_types = _as_list(spec.get("subject_types"))
        object_types = _as_list(spec.get("object_types"))
        if not subject_types or not object_types:
            raise RuntimeError(f"Ontology predicate {name} needs subject_types/object_types")
        predicates[name] = {
            "description": str(spec.get("description") or "").strip(),
            "subject_types": subject_types,
            "object_types": object_types,
            # Predicates are document-extractable by default. Seed-only relations
            # (for example CardDAV organizational-unit links) remain part of the
            # ontology without becoming legal LLM extraction outputs.
            "sources": _as_list(spec.get("sources")) or ["document"],
            "roles": _as_list(spec.get("roles")),
            "subject_kinds": _as_list(spec.get("subject_kinds")),
            "object_kinds": _as_list(spec.get("object_kinds")),
            "relation_cues_any": [x.casefold() for x in _as_list(spec.get("relation_cues_any"))],
        }

    serialized = yaml.safe_dump(
        {"version": raw.get("version"), "name": raw.get("name"), "predicates": predicates},
        allow_unicode=True,
        sort_keys=True,
    )
    return {
        "path": str(ontology_path),
        "version": raw.get("version", 1),
        "name": str(raw.get("name") or ontology_path.stem),
        "predicates": predicates,
        "hash": hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:16],
    }


def relation_names_with_role(
    ontology: dict[str, Any],
    role: str,
    *,
    source: str | None = None,
) -> list[str]:
    """Return ontology predicates carrying ``role`` in declaration order.

    ``source`` may restrict the set to relations admitted from a particular
    origin (e.g. ``document`` or ``seed``).  Runtime retrieval code uses this
    instead of keeping a second hard-coded relation vocabulary in config.yaml.
    """
    wanted_role = str(role or "").strip()
    wanted_source = str(source or "").strip()
    out: list[str] = []
    for name, spec in (ontology.get("predicates") or {}).items():
        if wanted_role not in set(spec.get("roles") or []):
            continue
        if wanted_source and wanted_source not in set(spec.get("sources") or []):
            continue
        out.append(str(name))
    return out


def document_predicates(ontology: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Return only predicates allowed to be extracted from document text."""
    return {
        name: spec
        for name, spec in (ontology.get("predicates") or {}).items()
        if "document" in set(spec.get("sources") or ["document"])
    }


def relation_schema(ontology: dict[str, Any]) -> dict[str, Any]:
    predicate_names = sorted(document_predicates(ontology).keys())
    return {
        "type": "object",
        "properties": {
            "relations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "subject_entity_id": {"type": "string"},
                        "predicate": {"type": "string", "enum": predicate_names},
                        "predicate_text": {"type": "string"},
                        "relation_text": {"type": "string"},
                        "object_entity_id": {"type": "string"},
                        "evidence_text": {"type": "string"},
                        "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                        "stance": {
                            "type": "string",
                            "enum": ["asserted", "negated", "alleged", "questioned", "conditional", "unknown"],
                        },
                        "valid_from": {"type": "string"},
                        "valid_to": {"type": "string"},
                    },
                    "required": [
                        "subject_entity_id", "predicate", "predicate_text", "relation_text",
                        "object_entity_id", "evidence_text", "confidence", "stance",
                        "valid_from", "valid_to",
                    ],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["relations"],
        "additionalProperties": False,
    }


def ontology_prompt(ontology: dict[str, Any]) -> str:
    lines = [
        "ERLAUBTE RELATIONEN (abschliessend; KEINE anderen Predicates erfinden):",
    ]
    for name, spec in document_predicates(ontology).items():
        subject = "|".join(spec.get("subject_types") or [])
        obj = "|".join(spec.get("object_types") or [])
        sk = ",".join(spec.get("subject_kinds") or [])
        ok = ",".join(spec.get("object_kinds") or [])
        suffix = []
        if sk:
            suffix.append(f"subject_kind={sk}")
        if ok:
            suffix.append(f"object_kind={ok}")
        tail = f" [{' ; '.join(suffix)}]" if suffix else ""
        description = str(spec.get("description") or "").strip()
        lines.append(f"- {name}: {subject} -> {obj}{tail}. {description}")
    lines.extend([
        "Wenn keine erlaubte Relation durch eine explizite Textpassage belegt ist: keine Relation ausgeben.",
        "Eine freie, nur plausibel klingende Relationsbezeichnung ist verboten.",
    ])
    return "\n".join(lines)



def validate_relation_semantics(
    ontology: dict[str, Any],
    *,
    predicate: str,
    subject_type: str,
    subject_kind: str,
    object_type: str,
    object_kind: str,
    relation_text: str,
    evidence_text: str,
) -> str | None:
    """Return a deterministic rejection reason or ``None``.

    This deliberately checks only ontology semantics (predicate, domain/range,
    kind constraints and lexical relation cues). Source grounding is checked by
    graph_indexer because it has the exact document chunk and entity forms.
    """
    spec = (ontology.get("predicates") or {}).get(str(predicate or "").strip().upper())
    if not spec:
        return "predicate_not_in_ontology"
    if "document" not in set(spec.get("sources") or ["document"]):
        return "predicate_not_document_extractable"
    if subject_type not in set(spec.get("subject_types") or []):
        return f"subject_type_not_allowed:{subject_type}"
    if object_type not in set(spec.get("object_types") or []):
        return f"object_type_not_allowed:{object_type}"
    subject_kinds = set(spec.get("subject_kinds") or [])
    object_kinds = set(spec.get("object_kinds") or [])
    if subject_kinds and subject_kind not in subject_kinds:
        return f"subject_kind_not_allowed:{subject_kind}"
    if object_kinds and object_kind not in object_kinds:
        return f"object_kind_not_allowed:{object_kind}"
    cues = [str(x).casefold() for x in (spec.get("relation_cues_any") or []) if str(x).strip()]
    haystack = f"{relation_text}\n{evidence_text}".casefold()
    if cues and not any(cue in haystack for cue in cues):
        return "missing_explicit_relation_cue"
    return None
