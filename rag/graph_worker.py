#!/usr/bin/env python3
"""Idle-time worker for the asynchronous Graph v3 evidence queue."""

from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import socket
import threading
import time
import uuid
from datetime import datetime
from typing import Any

from rag.graph import BASE_DIR, cfg_get, load_config
from rag.logging_utils import get_logger
from rag.graph_indexer import GraphEvidenceIndexer
from rag.graph_queue import GraphQueue

log = get_logger("worker")
_STOP = False


def _signal_handler(signum: int, frame: Any) -> None:
    global _STOP
    _STOP = True


def _within_window(start: str, end: str) -> bool:
    """Return true when local clock is inside HH:MM..HH:MM; supports overnight."""
    try:
        sh, sm = [int(x) for x in start.split(":", 1)]
        eh, em = [int(x) for x in end.split(":", 1)]
    except Exception:
        return True
    now_local = datetime.now()
    now = now_local.hour * 60 + now_local.minute
    a = sh * 60 + sm
    b = eh * 60 + em
    if a == b:
        return True
    if a < b:
        return a <= now < b
    return now >= a or now < b



class _Heartbeat:
    """Keep queue worker liveness fresh even while one LLM job is blocking."""

    def __init__(self, queue: GraphQueue, interval: float):
        self.queue = queue
        self.interval = max(2.0, float(interval))
        self.pid = os.getpid()
        self.host = socket.gethostname()
        self.instance_id = uuid.uuid4().hex[:12]
        self.started_at = datetime.now().astimezone().isoformat(timespec="seconds")
        self._state = "starting"
        self._job_id: int | None = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="graph-worker-heartbeat", daemon=True)

    def _write(self) -> None:
        with self._lock:
            state = self._state
            job_id = self._job_id
        try:
            self.queue.worker_heartbeat(
                state=state,
                pid=self.pid,
                host=self.host,
                instance_id=self.instance_id,
                job_id=job_id,
                started_at=self.started_at,
            )
        except Exception:
            log.exception("Could not write graph worker heartbeat")

    def _run(self) -> None:
        self._write()
        while not self._stop.wait(self.interval):
            self._write()

    def start(self) -> None:
        self._thread.start()

    def set(self, state: str, job_id: int | None = None) -> None:
        with self._lock:
            self._state = str(state)
            self._job_id = job_id
        self._write()

    def stop(self) -> None:
        with self._lock:
            self._state = "stopped"
            self._job_id = None
        self._write()
        self._stop.set()
        self._thread.join(timeout=max(1.0, self.interval + 1.0))


def main() -> int:
    parser = argparse.ArgumentParser(description="Process queued graph evidence during RAG idle time")
    parser.add_argument("--config", default=str(BASE_DIR / "config.yaml"))
    parser.add_argument("--once", action="store_true", help="process at most one job and exit")
    parser.add_argument("--ignore-idle", action="store_true", help="process even while RAG is active")
    parser.add_argument("--log-level", default=None)
    args = parser.parse_args()

    if args.log_level:
        log.setLevel(getattr(logging, str(args.log_level).upper(), log.level))
    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)

    cfg = load_config(args.config)
    queue = GraphQueue(cfg)
    if not queue.enabled:
        log.warning("graph_queue.enabled=false; worker exits")
        return 0
    if not bool(cfg_get(cfg, "graph_queue.worker.enabled", default=False)):
        log.warning("graph_queue.worker.enabled=false; worker exits")
        return 0

    idle_required = float(cfg_get(cfg, "graph_queue.worker.idle_seconds", default=120) or 120)
    poll_seconds = float(cfg_get(cfg, "graph_queue.worker.poll_seconds", default=10) or 10)
    retry_seconds = float(cfg_get(cfg, "graph_queue.worker.retry_seconds", default=60) or 60)
    max_attempts = int(cfg_get(cfg, "graph_queue.worker.max_attempts", default=3) or 3)
    stale_seconds = int(cfg_get(cfg, "graph_queue.worker.stale_running_seconds", default=3600) or 3600)
    quiet_enabled = bool(cfg_get(cfg, "graph_queue.worker.quiet_hours.enabled", default=False))
    quiet_start = str(cfg_get(cfg, "graph_queue.worker.quiet_hours.start", default="22:00"))
    quiet_end = str(cfg_get(cfg, "graph_queue.worker.quiet_hours.end", default="07:00"))
    heartbeat_interval = float(cfg_get(cfg, "graph_queue.worker.heartbeat_seconds", default=15) or 15)

    heartbeat = _Heartbeat(queue, heartbeat_interval)
    heartbeat.start()

    try:
        recovered = queue.recover_stale_running(stale_seconds)
        if recovered:
            log.warning("Recovered %d stale running graph job(s)", recovered)

        indexer = GraphEvidenceIndexer(cfg)
        heartbeat.set("idle")
        log.info(
            "Graph worker started: db=%s idle=%ss poll=%ss quiet_hours=%s heartbeat=%ss",
            queue.path,
            idle_required,
            poll_seconds,
            quiet_enabled,
            heartbeat_interval,
        )

        while not _STOP:
            if quiet_enabled and not _within_window(quiet_start, quiet_end):
                heartbeat.set("quiet_hours")
                if args.once:
                    return 0
                time.sleep(poll_seconds)
                continue

            idle = queue.idle_seconds()
            if not args.ignore_idle and idle < idle_required:
                heartbeat.set("waiting_for_idle")
                if args.once:
                    log.info("RAG only idle %.1fs (< %.1fs); no job processed", idle, idle_required)
                    return 0
                time.sleep(min(poll_seconds, max(1.0, idle_required - idle)))
                continue

            job = queue.claim_next()
            if job is None:
                heartbeat.set("idle")
                if args.once:
                    return 0
                time.sleep(poll_seconds)
                continue

            job_id = int(job["id"])
            payload = dict(job["payload"])
            heartbeat.set("processing", job_id)
            log.info(
                "Processing graph job=%s document=%s attempt=%s",
                job_id,
                job.get("document_id"),
                job.get("attempts"),
            )
            try:
                result = indexer.index_evidence(
                    list(payload.get("documents") or []),
                    query_id=str(payload.get("query_id") or ""),
                    user_query=str(payload.get("user_query") or ""),
                    retrieval_query=str(payload.get("retrieval_query") or ""),
                    evidence_action=str(payload.get("evidence_action") or "answer"),
                    force_reindex=bool(payload.get("force_reindex", False)),
                    entity_discovery=(
                        None if payload.get("entity_discovery") is None
                        else bool(payload.get("entity_discovery"))
                    ),
                    relation_discovery=(
                        None if payload.get("relation_discovery") is None
                        else bool(payload.get("relation_discovery"))
                    ),
                    count_evidence=bool(payload.get("count_evidence", True)),
                    force_oversize=bool(payload.get("force_oversize", False)),
                )
                if result.get("errors"):
                    raise RuntimeError(
                        "Graph indexer reported errors: "
                        + json.dumps(result.get("errors"), ensure_ascii=False)
                    )
                queue.finish(job_id, result)
                docs = list(result.get("documents") or [])
                resolutions = [
                    item
                    for doc in docs
                    for item in (doc.get("entity_resolutions") or [])
                ]
                skipped_oversize = sum(1 for d in docs if d.get("status") == "skipped_oversize")
                log.info(
                    "Finished graph job=%s documents=%s observed=%s relations=%s created=%s existing=%s ambiguous=%s unresolved=%s rejected=%s skipped_oversize=%s errors=%s",
                    job_id,
                    [d.get("document_id") for d in docs],
                    sum(len(d.get("discovered_entities") or []) for d in docs),
                    sum(len(d.get("relations") or []) for d in docs),
                    sum(1 for item in resolutions if item.get("status") == "created_provisional"),
                    sum(1 for item in resolutions if item.get("status") == "resolved_existing"),
                    sum(1 for item in resolutions if item.get("status") == "ambiguous"),
                    sum(1 for item in resolutions if item.get("status") == "unresolved"),
                    sum(1 for item in resolutions if item.get("status") == "rejected"),
                    skipped_oversize,
                    result.get("errors") or [],
                )
                heartbeat.set("idle")
            except Exception as exc:
                attempts = int(job.get("attempts") or 1)
                retry = attempts < max_attempts
                queue.fail(job_id, f"{type(exc).__name__}: {exc}", retry=retry)
                heartbeat.set("retry_wait" if retry else "idle")
                log.exception("Graph job=%s failed; retry=%s", job_id, retry)
                if retry:
                    time.sleep(retry_seconds)

            if args.once:
                return 0

        return 0
    finally:
        heartbeat.stop()
        log.info("Graph worker stopped")


if __name__ == "__main__":
    raise SystemExit(main())
