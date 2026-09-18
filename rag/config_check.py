"""Static configuration consistency checks for RAG Middleware.

This checker deliberately avoids network calls and secret-store writes.  It is
intended for installers and administrators before services are started.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class ConfigIssue:
    level: str  # "error" or "warning"
    message: str


def _get(cfg: dict[str, Any], path: str, default: Any = None) -> Any:
    cur: Any = cfg
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur


def _truthy(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _reranker_backend(cfg: dict[str, Any]) -> str:
    return str(_get(cfg, "reranker.backend", "local") or "local").strip().lower()


def check_config(cfg: dict[str, Any]) -> list[ConfigIssue]:
    """Return static configuration errors and warnings without external probes."""
    issues: list[ConfigIssue] = []

    es_enabled = _truthy(_get(cfg, "elasticsearch.enabled", True), True)
    qdrant_enabled = _truthy(_get(cfg, "qdrant.enabled", True), True)
    sync_enabled = _truthy(_get(cfg, "sync_worker.enabled", False), False)
    reranker = _reranker_backend(cfg)
    profile = str(_get(cfg, "deployment.profile", "default") or "default").strip().lower()
    neo4j_enabled = _truthy(_get(cfg, "neo4j.enabled", False), False)
    research_findings_enabled = _truthy(_get(cfg, "research_findings.enabled", False), False)
    graph_doc_enabled = neo4j_enabled and _truthy(_get(cfg, "graph_retrieval.enabled", True), True)
    deployment_mode = str(_get(cfg, "deployment.mode", "native") or "native").strip().lower()

    policy_modes = {
        arm: str(_get(cfg, f"retrieval_policy.internal.{arm}", default) or default).strip().lower()
        for arm, default in (("files", "optional"), ("vector", "optional"), ("graph", "optional"))
    }
    optional_default = str(_get(cfg, "retrieval_policy.optional_default", "include") or "include").strip().lower()
    web_policy = str(_get(cfg, "retrieval_policy.web", "planner") or "planner").strip().lower()

    if not es_enabled and not qdrant_enabled:
        issues.append(ConfigIssue("error", "no document retrieval arm is enabled (Elasticsearch and Qdrant are both disabled)"))

    if reranker not in {"none", "local", "tei"}:
        issues.append(ConfigIssue("error", f"unknown reranker.backend={reranker!r}; allowed: none, local, tei"))

    if deployment_mode not in {"native", "dockerized"}:
        issues.append(ConfigIssue("error", f"unknown deployment.mode={deployment_mode!r}; allowed: native, dockerized"))

    for arm, mode in policy_modes.items():
        if mode not in {"required", "optional", "disabled"}:
            issues.append(ConfigIssue("error", f"retrieval_policy.internal.{arm} must be required, optional or disabled"))
    if optional_default not in {"include", "exclude"}:
        issues.append(ConfigIssue("error", "retrieval_policy.optional_default must be include or exclude"))
    if web_policy not in {"disabled", "explicit", "planner"}:
        issues.append(ConfigIssue("error", "retrieval_policy.web must be disabled, explicit or planner"))

    capability_enabled = {"files": es_enabled, "vector": qdrant_enabled, "graph": graph_doc_enabled}
    for arm, mode in policy_modes.items():
        if mode == "required" and not capability_enabled[arm]:
            issues.append(ConfigIssue("error", f"retrieval_policy requires {arm}, but its backend/capability is disabled"))
    if all(mode == "disabled" or not capability_enabled[arm] for arm, mode in policy_modes.items()):
        issues.append(ConfigIssue("error", "retrieval_policy leaves no default internal document retrieval arm"))

    if qdrant_enabled:
        embedding_backend = str(_get(cfg, "embedding.backend", "") or "").strip()
        embedding_model = str(_get(cfg, "embedding.model", "") or "").strip()
        if not embedding_backend or not embedding_model:
            issues.append(ConfigIssue("error", "Qdrant retrieval requires embedding.backend and embedding.model"))
        if reranker == "none" and es_enabled:
            issues.append(ConfigIssue(
                "warning",
                "Elasticsearch + Qdrant without a reranker is supported via RRF, but final ranking quality may be lower",
            ))

    if sync_enabled and not qdrant_enabled:
        issues.append(ConfigIssue(
            "warning",
            "sync_worker.enabled=true while Qdrant is disabled; the document embedding sync is normally unnecessary in this profile",
        ))

    if research_findings_enabled and not neo4j_enabled:
        issues.append(ConfigIssue(
            "warning",
            "research_findings.enabled=true while neo4j.enabled=false; AKI research findings will not be persisted",
        ))

    if reranker == "tei" and not str(_get(cfg, "reranker.tei_url", "") or "").strip():
        issues.append(ConfigIssue("error", "reranker.backend=tei requires reranker.tei_url"))

    if profile == "super-light":
        if deployment_mode != "dockerized":
            issues.append(ConfigIssue("error", "deployment.profile=super-light requires deployment.mode=dockerized"))
        required_false = {
            "qdrant.enabled": qdrant_enabled,
            "sync_worker.enabled": sync_enabled,
            "graph_retrieval.enabled": _truthy(_get(cfg, "graph_retrieval.enabled", False), False),
            "graph_indexer.enabled": _truthy(_get(cfg, "graph_indexer.enabled", False), False),
            "graph_entity_discovery.enabled": _truthy(_get(cfg, "graph_entity_discovery.enabled", False), False),
            "graph_relation_discovery.enabled": _truthy(_get(cfg, "graph_relation_discovery.enabled", False), False),
        }
        if not es_enabled:
            issues.append(ConfigIssue("error", "deployment.profile=super-light requires elasticsearch.enabled=true"))
        if reranker != "none":
            issues.append(ConfigIssue("error", "deployment.profile=super-light requires reranker.backend=none"))
        for path, enabled in required_false.items():
            if enabled:
                issues.append(ConfigIssue("error", f"deployment.profile=super-light requires {path}=false"))

    return issues


def load_config_file(path: str | Path) -> dict[str, Any]:
    cfg_path = Path(path)
    with cfg_path.open("r", encoding="utf-8") as handle:
        cfg = yaml.safe_load(handle) or {}
    if not isinstance(cfg, dict):
        raise ValueError("config root must be a mapping")
    return cfg


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check RAG Middleware configuration consistency without network access")
    parser.add_argument("--config", default="config.yaml", help="configuration file (default: config.yaml)")
    args = parser.parse_args(argv)

    try:
        cfg = load_config_file(args.config)
    except Exception as exc:
        print(f"ERROR: cannot load {args.config}: {exc}")
        return 2

    issues = check_config(cfg)
    profile = str(_get(cfg, "deployment.profile", "default") or "default")
    print(f"Config: {args.config}")
    print(f"Profile: {profile}")

    if not issues:
        print("OK: no static configuration issues found")
        return 0

    for issue in issues:
        print(f"{issue.level.upper()}: {issue.message}")

    return 2 if any(issue.level == "error" for issue in issues) else 0


if __name__ == "__main__":
    raise SystemExit(main())
