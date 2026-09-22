#!/usr/bin/env bash
set -euo pipefail

BASE_DIR="$(cd "$(dirname "$0")/.." && pwd)"
RUNTIME_ENV="$BASE_DIR/runtime.env"
STATE_FILE="$BASE_DIR/install/install-state.env"

usage() {
  echo "Usage: $0 on|off|status" >&2
  exit 2
}

[[ -f "$RUNTIME_ENV" ]] || { echo "runtime.env not found: $RUNTIME_ENV" >&2; exit 1; }

set_mode() {
  local value="$1"
  if grep -q '^RAG_MAINTENANCE_MODE=' "$RUNTIME_ENV"; then
    sed -i "s/^RAG_MAINTENANCE_MODE=.*/RAG_MAINTENANCE_MODE=$value/" "$RUNTIME_ENV"
  else
    printf '\nRAG_MAINTENANCE_MODE=%s\n' "$value" >> "$RUNTIME_ENV"
  fi
  chmod 600 "$RUNTIME_ENV"
}

current_mode() {
  local value
  value="$(sed -n 's/^RAG_MAINTENANCE_MODE=//p' "$RUNTIME_ENV" | tail -1)"
  value="$(printf '%s' "$value" | tr '[:upper:]' '[:lower:]')"
  case "$value" in
    1|true|yes|on) echo on ;;
    *) echo off ;;
  esac
}

deployment_mode="native"
if [[ -f "$STATE_FILE" ]]; then
  value="$(sed -n 's/^DEPLOYMENT_MODE=//p' "$STATE_FILE" | tail -1)"
  [[ "$value" == "dockerized" || "$value" == "native" ]] && deployment_mode="$value"
elif [[ -f "$BASE_DIR/.aki-rag-installation" ]]; then
  value="$(sed -n 's/^DEPLOYMENT_MODE=//p' "$BASE_DIR/.aki-rag-installation" | tail -1)"
  [[ "$value" == "dockerized" || "$value" == "native" ]] && deployment_mode="$value"
fi

compose() {
  (
    cd "$BASE_DIR/install/super-light"
    if docker compose version >/dev/null 2>&1; then
      docker compose "$@"
    elif command -v docker-compose >/dev/null 2>&1; then
      docker-compose "$@"
    else
      echo "Docker Compose not found." >&2
      exit 1
    fi
  )
}

native_systemd_available() {
  command -v systemctl >/dev/null 2>&1 && [[ -f /etc/systemd/system/rag-provider.service ]]
}

native_require_root() {
  if native_systemd_available && [[ ${EUID:-$(id -u)} -ne 0 ]]; then
    echo "Systemd-managed maintenance switching requires root; rerun with sudo." >&2
    exit 1
  fi
}

enable_native() {
  native_require_root
  if native_systemd_available; then
    systemctl stop rag-api rag-graph-worker rag-sync-worker rag-mail-worker 2>/dev/null || true
    systemctl restart rag-provider
  else
    "$BASE_DIR/stop-all.sh" || true
    "$BASE_DIR/start-all.sh"
  fi
}

disable_native() {
  native_require_root
  if native_systemd_available; then
    systemctl start rag-api
    systemctl restart rag-provider
    systemctl start rag-sync-worker rag-mail-worker 2>/dev/null || true
    if systemctl is-enabled rag-graph-worker >/dev/null 2>&1; then
      systemctl start rag-graph-worker
    fi
  else
    "$BASE_DIR/stop-all.sh" || true
    "$BASE_DIR/start-all.sh"
  fi
}

enable_dockerized() {
  compose stop api mail-worker >/dev/null 2>&1 || true
  compose up -d --no-deps --force-recreate provider
}

disable_dockerized() {
  compose up -d neo4j playwright-renderer api mail-worker

  local schema_ready=0
  local attempt
  for attempt in $(seq 1 90); do
    if compose exec -T api python -m rag.graph --config /app/config.yaml init >/dev/null 2>&1; then
      schema_ready=1
      break
    fi
    if [[ $attempt -eq 1 || $((attempt % 10)) -eq 0 ]]; then
      printf 'Neo4j/schema: waiting (attempt %d/90)\n' "$attempt"
    fi
    sleep 2
  done
  if [[ $schema_ready -ne 1 ]]; then
    echo "Neo4j did not become ready or the AKI schema upgrade failed; returning to maintenance mode." >&2
    compose exec -T api python -m rag.graph --config /app/config.yaml init >&2 || true
    return 1
  fi
  printf 'Neo4j/schema: ready\n'
  compose up -d --no-deps --force-recreate provider
}

case "${1:-}" in
  status)
    echo "maintenance=$(current_mode) deployment=$deployment_mode"
    ;;
  on)
    set_mode true
    if [[ "$deployment_mode" == "dockerized" ]]; then enable_dockerized; else enable_native; fi
    echo "AKI maintenance mode enabled."
    ;;
  off)
    set_mode false
    if { [[ "$deployment_mode" == "dockerized" ]] && disable_dockerized; } || { [[ "$deployment_mode" != "dockerized" ]] && disable_native; }; then
      echo "AKI maintenance mode disabled; normal services started."
    else
      rc=$?
      echo "Normal startup failed; restoring maintenance mode." >&2
      set_mode true
      if [[ "$deployment_mode" == "dockerized" ]]; then
        enable_dockerized || true
      else
        enable_native || true
      fi
      exit "$rc"
    fi
    ;;
  *)
    usage
    ;;
esac
