#!/usr/bin/env bash
set -u
BASE_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$BASE_DIR"
set -a
[[ -f provider.env ]] && source provider.env
[[ -f runtime.env ]] && source runtime.env
set +a
RUN_DIR="$BASE_DIR/run"
LOCAL_PROXY=0
LOCAL_OPENWEBUI=0
LOCAL_PLAYWRIGHT=0
[[ -f install/install-state.env ]] && source install/install-state.env

proc_status() {
  local name="$1" pidfile="$RUN_DIR/$1.pid"
  if [[ -f "$pidfile" ]]; then
    local pid
    pid="$(cat "$pidfile" 2>/dev/null || true)"
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
      printf '%-14s RUNNING pid=%s\n' "$name" "$pid"
      return
    fi
  fi
  printf '%-14s STOPPED\n' "$name"
}

proc_status api
proc_status provider
proc_status graph-worker
proc_status sync-worker
proc_status mail-worker

maintenance_value="${RAG_MAINTENANCE_MODE:-false}"
maintenance_value="$(printf '%s' "$maintenance_value" | tr '[:upper:]' '[:lower:]')"
case "$maintenance_value" in
  1|true|yes|on) printf '%-14s ENABLED\n' maintenance ;;
  *) printf '%-14s disabled\n' maintenance ;;
esac

printf '\nEndpoints:\n'
api_probe_host="${RAG_API_HOST:-127.0.0.1}"
[[ "$api_probe_host" == "0.0.0.0" || "$api_probe_host" == "::" ]] && api_probe_host="127.0.0.1"
provider_probe_host="${PROVIDER_HOST:-127.0.0.1}"
[[ "$provider_probe_host" == "0.0.0.0" || "$provider_probe_host" == "::" ]] && provider_probe_host="127.0.0.1"

api_auth_args=()
[[ -n "${RAG_INTERNAL_API_KEY:-}" ]] && api_auth_args=(-H "X-AKI-Internal-Key: ${RAG_INTERNAL_API_KEY}")
if curl -fsS --max-time 3 "${api_auth_args[@]}" "http://${api_probe_host}:${RAG_API_PORT:-8765}/health" >/dev/null 2>&1; then
  printf '%-14s OK http://%s:%s/health\n' api "$api_probe_host" "${RAG_API_PORT:-8765}"
else
  printf '%-14s DOWN http://%s:%s/health\n' api "$api_probe_host" "${RAG_API_PORT:-8765}"
fi
if curl -fsS --max-time 3 "http://${provider_probe_host}:${PROVIDER_PORT:-8766}/live" >/dev/null 2>&1; then
  printf '%-14s OK http://%s:%s/live\n' provider "$provider_probe_host" "${PROVIDER_PORT:-8766}"
else
  printf '%-14s DOWN http://%s:%s/live\n' provider "$provider_probe_host" "${PROVIDER_PORT:-8766}"
fi


if [[ ${LOCAL_PLAYWRIGHT:-0} -eq 1 ]]; then
  if curl -fsS --max-time 3 "http://127.0.0.1:${PLAYWRIGHT_PORT:-8090}/live" >/dev/null 2>&1; then
    printf '%-14s OK http://127.0.0.1:%s/live\n' playwright "${PLAYWRIGHT_PORT:-8090}"
  else
    printf '%-14s DOWN http://127.0.0.1:%s/live\n' playwright "${PLAYWRIGHT_PORT:-8090}"
  fi
fi

if [[ ${LOCAL_OPENWEBUI:-0} -eq 1 ]]; then
  if curl -fsS --max-time 3 "http://127.0.0.1:${OPENWEBUI_PORT:-3000}/health" >/dev/null 2>&1; then
    printf '%-14s OK http://127.0.0.1:%s/health
' openwebui "${OPENWEBUI_PORT:-3000}"
  else
    printf '%-14s DOWN http://127.0.0.1:%s/health
' openwebui "${OPENWEBUI_PORT:-3000}"
  fi
fi

if [[ ${LOCAL_PROXY:-0} -eq 1 ]]; then
  if curl -kfsS --max-time 3 https://127.0.0.1/proxy-health >/dev/null 2>&1; then
    printf '%-14s OK https://127.0.0.1/proxy-health\n' proxy
  else
    printf '%-14s DOWN https://127.0.0.1/proxy-health\n' proxy
  fi
fi
