#!/usr/bin/env bash
set -euo pipefail
BASE_DIR="$(cd "$(dirname "$0")" && pwd)"
RUN_DIR="$BASE_DIR/run"

stop_one() {
  local name="$1" pidfile="$RUN_DIR/$1.pid"
  if [[ ! -f "$pidfile" ]]; then
    printf '%-14s not running (no pidfile)\n' "$name"
    return 0
  fi
  local pid
  pid="$(cat "$pidfile" 2>/dev/null || true)"
  if [[ -z "$pid" ]] || ! kill -0 "$pid" 2>/dev/null; then
    printf '%-14s not running\n' "$name"
    rm -f "$pidfile"
    return 0
  fi
  kill "$pid"
  for _ in $(seq 1 30); do
    if ! kill -0 "$pid" 2>/dev/null; then break; fi
    sleep 0.2
  done
  if kill -0 "$pid" 2>/dev/null; then
    echo "$name did not stop after 6s; sending KILL" >&2
    kill -KILL "$pid" 2>/dev/null || true
  fi
  rm -f "$pidfile"
  printf '%-14s stopped\n' "$name"
}

stop_one mail-worker
stop_one sync-worker
stop_one graph-worker
stop_one provider
stop_one api
