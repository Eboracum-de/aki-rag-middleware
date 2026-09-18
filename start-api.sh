#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

set -a
[[ -f provider.env ]] && source provider.env
[[ -f runtime.env ]] && source runtime.env
set +a

exec ./.venv/bin/python -m uvicorn rag.api:app \
  --host "${RAG_API_HOST:-127.0.0.1}" \
  --port "${RAG_API_PORT:-8765}"
