#!/usr/bin/env bash
set -u
PREFIX="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
PY="$PREFIX/.venv/bin/python"
FAIL=0

OWNER="$(stat -c '%U' "$PREFIX" 2>/dev/null || id -un)"
OWNER_HOME="$(getent passwd "$OWNER" 2>/dev/null | cut -d: -f6 || true)"

run_as_owner() {
  if [[ ${EUID:-$(id -u)} -eq 0 && -n "$OWNER" && "$OWNER" != "root" ]]; then
    if command -v runuser >/dev/null 2>&1; then
      runuser -u "$OWNER" -m -- env HOME="${OWNER_HOME:-/tmp}" "$@"
      return
    elif command -v sudo >/dev/null 2>&1; then
      sudo -u "$OWNER" -H -- "$@"
      return
    fi
  fi
  "$@"
}

LOCAL_QDRANT=0
LOCAL_NEO4J=0
LOCAL_OPENWEBUI=0
LOCAL_PROXY=0
MULTI_USER=0
if [[ -f "$PREFIX/install/install-state.env" ]]; then
  source "$PREFIX/install/install-state.env"
fi

set -a
[[ -f "$PREFIX/provider.env" ]] && source "$PREFIX/provider.env"
[[ -f "$PREFIX/runtime.env" ]] && source "$PREFIX/runtime.env"
set +a

ok() { echo "[ OK ] $*"; }
bad() { echo "[FAIL] $*"; FAIL=1; }

[[ -x "$PY" ]] && ok "Python venv" || bad "Python venv missing"
if [[ -x "$PY" ]]; then
  echo "[INFO] Checking lightweight Python imports ..."
  run_as_owner "$PY" - <<'PY' >/dev/null 2>&1 && ok "Python core imports" || bad "Python core imports"
import fastapi, httpx, requests, yaml, neo4j, qdrant_client, rapidfuzz, vobject
PY

  echo "[INFO] Checking ML imports (torch/transformers can take a while on a cold filesystem) ..."
  ml_tmp="$(mktemp)"
  ( run_as_owner "$PY" - <<'PY' >"$ml_tmp" 2>&1
import transformers, torch
assert torch.__version__ == "2.13.0+cpu", torch.__version__
assert transformers.__version__ == "4.57.6", transformers.__version__
import torch.export
from transformers import AutoModelForSequenceClassification
PY
  ) &
  ml_pid=$!
  ml_elapsed=0
  while kill -0 "$ml_pid" 2>/dev/null; do
    sleep 10
    ml_elapsed=$((ml_elapsed + 10))
    if kill -0 "$ml_pid" 2>/dev/null; then
      echo "[INFO] ML imports still running (${ml_elapsed}s) ..."
    fi
  done
  if wait "$ml_pid"; then
    ok "Python ML imports"
  else
    cat "$ml_tmp" >&2
    bad "Python ML imports"
  fi
  rm -f "$ml_tmp"

  (cd "$PREFIX" && run_as_owner "$PY" -m compileall -q rag) && ok "rag compileall" || bad "rag compileall"
  (cd "$PREFIX" && run_as_owner "$PY" - <<'PY' >/dev/null 2>&1) && ok "RAG application imports" || bad "RAG application imports"
import rag.api
import rag.openai_provider
PY

  if [[ -f "$PREFIX/runtime/users.sqlite" ]]; then
    if (cd "$PREFIX" && run_as_owner "$PY" -c 'from rag.credential_store import CredentialStore; assert CredentialStore("runtime/users.sqlite").client_count() >= 1' >/dev/null 2>&1); then
      ok "Trusted provider client registry"
    else
      bad "Trusted provider client registry missing/empty"
    fi
  fi

  for db in graph_queue.sqlite research.sqlite runtime/users.sqlite; do
    if [[ -e "$PREFIX/$db" ]]; then
      if run_as_owner test -w "$PREFIX/$db"; then
        ok "Runtime DB writable ($db)"
      else
        bad "Runtime DB not writable by $OWNER ($db)"
      fi
    fi
  done
fi

QDRANT_URL="http://127.0.0.1:6333"
QDRANT_COLLECTION="nextcloud_rag"
if [[ -x "$PY" && -f "$PREFIX/config.yaml" ]]; then
  mapfile -t QDRANT_CFG < <(cd "$PREFIX" && run_as_owner "$PY" - <<'PY'
import yaml
with open('config.yaml', encoding='utf-8') as f:
    cfg = yaml.safe_load(f) or {}
q = cfg.get('qdrant') or {}
print(str(q.get('url') or 'http://127.0.0.1:6333').rstrip('/'))
print(str(q.get('collection') or 'nextcloud_rag'))
PY
)
  [[ ${#QDRANT_CFG[@]} -ge 1 ]] && QDRANT_URL="${QDRANT_CFG[0]}"
  [[ ${#QDRANT_CFG[@]} -ge 2 ]] && QDRANT_COLLECTION="${QDRANT_CFG[1]}"
fi

if curl -fsS "$QDRANT_URL/collections" >/dev/null 2>&1; then
  ok "Qdrant HTTP ($QDRANT_URL)"
  if [[ -x "$PY" ]]; then
    echo "[INFO] Testing configured embedding backend and Qdrant write/read ..."
    if (cd "$PREFIX" && run_as_owner "$PY" -m rag.qdrant_smoke --config config.yaml); then
      ok "Embedding + Qdrant smoke point ($QDRANT_COLLECTION)"
    else
      bad "Embedding/Qdrant smoke probe"
    fi
  fi
else
  [[ $LOCAL_QDRANT -eq 1 ]] && bad "Qdrant HTTP ($QDRANT_URL)" || echo "[INFO] Qdrant not reachable at configured URL: $QDRANT_URL"
fi

if curl -fsS http://127.0.0.1:7474 >/dev/null 2>&1; then
  ok "Neo4j HTTP"
else
  [[ $LOCAL_NEO4J -eq 1 ]] && bad "Neo4j HTTP" || echo "[INFO] Local Neo4j not selected; configure a remote endpoint if graph retrieval is required."
fi

if [[ $LOCAL_OPENWEBUI -eq 1 ]]; then
  if curl -fsS "http://127.0.0.1:${OPENWEBUI_PORT:-3000}/health" >/dev/null 2>&1; then
    ok "OpenWebUI HTTP (127.0.0.1:${OPENWEBUI_PORT:-3000})"
  else
    bad "OpenWebUI HTTP (127.0.0.1:${OPENWEBUI_PORT:-3000})"
  fi
fi


if [[ $LOCAL_PROXY -eq 1 ]]; then
  if curl -kfsS https://127.0.0.1/proxy-health >/dev/null 2>&1; then
    ok "nginx reverse proxy HTTPS"
  else
    bad "nginx reverse proxy HTTPS"
  fi
  if curl -sSI http://127.0.0.1/ 2>/dev/null | head -1 | grep -Eq ' 30[1278] '; then
    ok "nginx HTTP -> HTTPS redirect"
  else
    bad "nginx HTTP -> HTTPS redirect"
  fi
fi

api_probe_host="${RAG_API_HOST:-127.0.0.1}"
[[ "$api_probe_host" == "0.0.0.0" || "$api_probe_host" == "::" ]] && api_probe_host="127.0.0.1"
provider_probe_host="${PROVIDER_HOST:-0.0.0.0}"
[[ "$provider_probe_host" == "0.0.0.0" || "$provider_probe_host" == "::" ]] && provider_probe_host="127.0.0.1"

if curl -fsS "http://${api_probe_host}:${RAG_API_PORT:-8765}/health" >/dev/null 2>&1; then
  ok "RAG API health"
else
  echo "[INFO] RAG API not running yet."
fi
if curl -fsS "http://${provider_probe_host}:${PROVIDER_PORT:-8766}/health" >/dev/null 2>&1; then
  ok "Provider health"
else
  echo "[INFO] Provider not running yet."
fi

exit "$FAIL"
