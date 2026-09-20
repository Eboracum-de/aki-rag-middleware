#!/usr/bin/env python3
"""Shared graph curation facade for CLI and the browser admin UI.

This module intentionally contains no Cypher of its own.  It exposes the
curation operations implemented by :class:`rag.graph.GraphStore` through one
small Python API so the CLI and the future /rag-admin/ UI cannot drift apart.
"""

from __future__ import annotations

from typing import Any

from rag.graph import GraphStore, blocked_generic_names


class GraphCurator:
    """Thin, schema-aware facade around GraphStore curation operations."""

    def __init__(self, graph: GraphStore):
        self.graph = graph

    @classmethod
    def from_config(cls, cfg: dict[str, Any]) -> "GraphCurator":
        return cls(GraphStore.from_config(cfg))

    def close(self) -> None:
        self.graph.close()

    def __enter__(self) -> "GraphCurator":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    # Read operations -------------------------------------------------

    def find_entities(self, query: str, *, limit: int = 50) -> list[dict[str, Any]]:
        return self.graph.find_entities(query, limit=limit)

    def get_entity(self, entity_id: str) -> dict[str, Any]:
        return self.graph.entity_detail(entity_id)

    def list_forms(self, entity_id: str) -> list[dict[str, Any]]:
        return self.graph.entity_forms(entity_id)

    def list_observations(self, entity_id: str) -> list[dict[str, Any]]:
        return self.graph.entity_observations(entity_id)

    def list_relations(self, query: str = "", *, limit: int = 200) -> list[dict[str, Any]]:
        return self.graph.list_relation_observations(query=query, limit=limit)

    def search_observations(
        self, *, query: str = "", status: str = "needs_review", limit: int = 200
    ) -> list[dict[str, Any]]:
        return self.graph.list_observations(query=query, status=status, limit=limit)

    def get_observation(self, observation_id: str) -> dict[str, Any] | None:
        return self.graph.observation_detail(observation_id)

    def list_research_runs(
        self, *, canonical_user_id: str = "", query: str = "", state: str = "open", limit: int = 200
    ) -> list[dict[str, Any]]:
        return self.graph.list_research_runs(
            canonical_user_id=canonical_user_id, query=query, state=state, limit=limit
        )

    def research_finding_observed_by_user(self, canonical_user_id: str, finding_id: str) -> bool:
        return self.graph.research_finding_observed_by_user(canonical_user_id, finding_id)

    def get_research_run(self, run_id: str) -> dict[str, Any] | None:
        return self.graph.research_run_detail(run_id)

    def dismiss_research_run(self, run_id: str, *, actor: str = "admin", reason: str = "") -> dict[str, Any]:
        return self.graph.dismiss_research_run(run_id, actor=actor, reason=reason)

    def set_research_run_finding_disposition(
        self, run_id: str, finding_ids: list[str], *, disposition: str, actor: str = "admin"
    ) -> dict[str, Any]:
        return self.graph.set_research_run_finding_disposition(
            run_id, finding_ids, disposition=disposition, actor=actor
        )

    def list_research_findings(self, query: str = "", *, limit: int = 200) -> list[dict[str, Any]]:
        return self.graph.list_research_findings(query=query, limit=limit)

    def get_research_finding(self, finding_id: str) -> dict[str, Any] | None:
        return self.graph.research_finding_detail(finding_id)

    def curate_research_finding(
        self, finding_id: str, *, status: str, reason: str = "", apply: bool = False,
        curator_actor: str = "manual_admin",
    ) -> dict[str, Any]:
        detail = self.graph.research_finding_detail(finding_id)
        if detail is None:
            raise ValueError(f"Finding nicht gefunden: {finding_id}")
        if apply:
            return self.graph.curate_research_finding(
                finding_id, status=status, reason=reason, curator_actor=curator_actor
            )
        return {
            "action": "curate_research_finding",
            "finding_id": finding_id,
            "new_status": status,
            "reason": reason,
            "current": detail,
            "note": "Preview; keine Änderung.",
        }

    def research_finding_entity_options(self, finding_id: str, *, limit: int = 6) -> list[dict[str, Any]]:
        return self.graph.research_finding_entity_options(finding_id, limit=limit)

    def research_finding_claim_options(self, finding_id: str) -> list[dict[str, Any]]:
        return self.graph.research_finding_claim_options(finding_id)

    def curate_research_finding_entity(
        self, finding_id: str, *, entity_text: str, action: str, target_entity_id: str = "",
        new_name: str = "", entity_type: str = "", reason: str = "", apply: bool = False,
        curator_actor: str = "manual_admin",
    ) -> dict[str, Any]:
        if apply:
            return self.graph.curate_research_finding_entity(
                finding_id, entity_text=entity_text, action=action, target_entity_id=target_entity_id,
                new_name=new_name, entity_type=entity_type, reason=reason,
                curator_actor=curator_actor,
            )
        return self.graph.curate_research_finding_entity_preview(
            finding_id, entity_text=entity_text, action=action, target_entity_id=target_entity_id,
            new_name=new_name, entity_type=entity_type, reason=reason,
            curator_actor=curator_actor,
        )

    def accept_research_finding_entity_defaults(
        self,
        finding_id: str,
        *,
        curator_actor: str = "manual_admin",
    ) -> dict[str, Any]:
        return self.graph.accept_research_finding_entity_defaults(
            finding_id, curator_actor=curator_actor
        )

    def bulk_curate_research_finding_entities(
        self, finding_ids: list[str], *, entity_text: str, action: str,
        target_entity_id: str = "", reason: str = "", apply: bool = False,
        curator_actor: str = "manual_admin",
    ) -> dict[str, Any]:
        clean_ids = list(dict.fromkeys(str(x or "").strip() for x in finding_ids if str(x or "").strip()))
        if not clean_ids:
            raise ValueError("Keine Findings ausgewählt")
        if not apply:
            return {"action": "bulk_curate_research_finding_entities", "count": len(clean_ids), "finding_ids": clean_ids,
                    "entity_text": entity_text, "entity_action": action, "target_entity_id": target_entity_id,
                    "note": "Preview; keine Änderung."}
        updated = 0
        failures: list[dict[str, str]] = []
        graph_action = "resolve" if str(action or "").casefold() == "resolve" else "suppress"
        for finding_id in clean_ids:
            try:
                self.graph.curate_research_finding_entity(
                    finding_id, entity_text=entity_text, action=graph_action,
                    target_entity_id=target_entity_id, reason=reason,
                    curator_actor=curator_actor,
                )
                updated += 1
            except Exception as exc:
                failures.append({"finding_id": finding_id, "error": str(exc)})
        return {"action": "bulk_curate_research_finding_entities", "updated": updated, "requested": len(clean_ids), "failures": failures}

    def suppress_research_findings_without_entities(self, *, apply: bool = False) -> dict[str, Any]:
        if not apply:
            return {"action": "suppress_research_findings_without_entities", "note": "Preview; keine Änderung."}
        return self.graph.suppress_research_findings_without_entities()

    def curate_research_finding_claim(
        self, finding_id: str, *, subject_entity_id: str, predicate_id: str, object_entity_id: str,
        predicate_label: str = "", claim_text: str = "", apply: bool = False,
        curator_actor: str = "manual_admin",
    ) -> dict[str, Any]:
        if apply:
            return self.graph.create_research_finding_claim(
                finding_id, subject_entity_id=subject_entity_id, predicate_id=predicate_id,
                object_entity_id=object_entity_id, predicate_label=predicate_label, claim_text=claim_text,
                curator_actor=curator_actor,
            )
        return self.graph.research_finding_claim_preview(
            finding_id, subject_entity_id=subject_entity_id, predicate_id=predicate_id,
            object_entity_id=object_entity_id, predicate_label=predicate_label, claim_text=claim_text,
        )

    def review_research_finding_claim(
        self,
        finding_id: str,
        *,
        relation_id: str,
        action: str,
        reason: str = "",
        curator_actor: str = "manual_admin",
    ) -> dict[str, Any]:
        return self.graph.review_research_finding_claim(
            finding_id,
            relation_id=relation_id,
            action=action,
            reason=reason,
            curator_actor=curator_actor,
        )

    def list_candidates(self) -> list[dict[str, Any]]:
        return self.graph.list_merge_candidates()

    def list_merges(self, query: str = "", *, limit: int = 100) -> list[dict[str, Any]]:
        return self.graph.list_merges(query, limit=limit)

    def list_contact_sources(self) -> list[dict[str, Any]]:
        return self.graph.list_contact_sources()

    def list_contact_import_runs(self, *, limit: int = 100) -> list[dict[str, Any]]:
        return self.graph.list_contact_import_runs(limit=limit)

    def list_contacts(self, *, cloud_id: str = "", source_user_id: str = "", addressbook: str = "", import_run_id: str = "", limit: int = 500) -> list[dict[str, Any]]:
        return self.graph.contact_records(
            cloud_id=cloud_id, source_user_id=source_user_id, addressbook=addressbook,
            import_run_id=import_run_id, limit=limit,
        )

    def get_contact(self, contact_id: str) -> dict[str, Any] | None:
        return self.graph.contact_record(contact_id)

    def blocked_entities(self, cfg: dict[str, Any]) -> dict[str, Any]:
        blocked = sorted(blocked_generic_names(cfg))
        blocked_set = set(blocked)
        rows = self.graph._run(
            """
            MATCH (e:Entity)
            WHERE (e:Person OR e:Organization)
              AND coalesce(properties(e)['identity_status'],'') <> 'merged'
              AND coalesce(properties(e)['identity_status'],'') <> 'orphaned'
            RETURN e.entity_id AS entity_id, e.display_name AS display_name,
                   labels(e) AS labels
            ORDER BY e.display_name
            """
        )
        from rag.graph import normalize_name

        return {
            "blocked_names": blocked,
            "entities": [
                dict(row)
                for row in rows
                if normalize_name(str(row.get("display_name") or "")) in blocked_set
            ],
        }

    # Preview-first mutation operations -------------------------------

    def merge(self, keep_entity_id: str, merge_entity_id: str, *, alias_policy: str = "contextual", apply: bool = False) -> dict[str, Any]:
        if apply:
            return self.graph.merge_entities(keep_entity_id, merge_entity_id, alias_policy=alias_policy)
        return self.graph.merge_entities_preview(keep_entity_id, merge_entity_id, alias_policy=alias_policy)

    def reject_merge(self, left_entity_id: str, right_entity_id: str, *, reason: str = "manual_rejection", apply: bool = False) -> dict[str, Any]:
        left = self.graph._entity_curation_summary(left_entity_id)
        right = self.graph._entity_curation_summary(right_entity_id)
        if left is None or right is None:
            raise ValueError("Mindestens eine Entity wurde nicht gefunden")
        if apply:
            return self.graph.reject_merge_candidate(left_entity_id, right_entity_id, reason=reason)
        return {
            "action": "reject_merge",
            "left": left,
            "right": right,
            "reason": reason,
            "note": "Preview; keine Änderung.",
        }

    def correct_name(self, entity_id: str, new_name: str, *, reason: str = "manual_name_correction", apply: bool = False) -> dict[str, Any]:
        if apply:
            return self.graph.correct_name(entity_id, new_name, reason=reason)
        return self.graph.correct_name_preview(entity_id, new_name, reason=reason)

    def correct_observation(self, observation_id: str, target_entity_id: str, *, reason: str = "ocr", apply: bool = False) -> dict[str, Any]:
        if apply:
            return self.graph.correct_observation(observation_id, target_entity_id, reason=reason)
        return self.graph.correct_observation_preview(observation_id, target_entity_id, reason=reason)

    def delete_entity(self, entity_id: str, *, reason: str = "manual_not_an_entity", apply: bool = False) -> dict[str, Any]:
        if apply:
            return self.graph.delete_entity(entity_id, reason=reason)
        return self.graph.delete_entity_preview(entity_id, reason=reason)

    def set_form_policy(self, entity_id: str, form: str, policy: str, *, apply: bool = False) -> dict[str, Any]:
        if apply:
            return self.graph.set_form_policy(entity_id, form, policy)
        return self.graph.set_form_policy_preview(entity_id, form, policy)

    def add_alias(self, entity_id: str, alias: str, *, policy: str = "contextual", weight: float = 0.95, apply: bool = False) -> dict[str, Any]:
        if apply:
            return self.graph.add_alias(entity_id, alias, policy=policy, weight=weight)
        return self.graph.add_alias_preview(entity_id, alias, policy=policy, weight=weight)

    def remove_alias(self, entity_id: str, alias: str, *, apply: bool = False) -> dict[str, Any]:
        if apply:
            return self.graph.remove_alias(entity_id, alias)
        return self.graph.remove_alias_preview(entity_id, alias)
    def rollback_contacts(self, *, cloud_id: str = "", source_user_id: str = "", addressbook: str = "", import_run_id: str = "", apply: bool = False) -> dict[str, Any]:
        if apply:
            return self.graph.rollback_contacts(
                cloud_id=cloud_id, source_user_id=source_user_id, addressbook=addressbook, import_run_id=import_run_id
            )
        return self.graph.rollback_contacts_preview(
            cloud_id=cloud_id, source_user_id=source_user_id, addressbook=addressbook, import_run_id=import_run_id
        )

    def reassign_contact(self, contact_id: str, target_entity_id: str, *, apply: bool = False) -> dict[str, Any]:
        if apply:
            return self.graph.reassign_contact(contact_id, target_entity_id)
        return self.graph.reassign_contact_preview(contact_id, target_entity_id)

