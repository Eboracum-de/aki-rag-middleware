#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if docker compose version >/dev/null 2>&1; then
  C=(docker compose -f docker-compose.yml)
elif command -v docker-compose >/dev/null 2>&1; then
  C=(docker-compose -f docker-compose.yml)
else
  echo "Docker Compose not found." >&2
  exit 1
fi
exec "${C[@]}" exec -T api python -m rag.contacts "$@"
