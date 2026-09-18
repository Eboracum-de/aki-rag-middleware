#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

set -a
[[ -f provider.env ]] && source provider.env
[[ -f runtime.env ]] && source runtime.env
set +a

exec ./.venv/bin/python -m rag.graph_worker "$@"
