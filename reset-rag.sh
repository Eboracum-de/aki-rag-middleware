#!/usr/bin/env bash
set -euo pipefail

BASE_DIR="$(cd "$(dirname "$0")" && pwd)"
CONFIG_FILE="$BASE_DIR/config.yaml"

if [[ ! -f "$CONFIG_FILE" ]]; then
  echo "Fehler: $CONFIG_FILE nicht gefunden."
  echo "Dieses Skript bitte in das Root-Verzeichnis von rag-middleware legen."
  exit 1
fi

if [[ "${1:-}" != "--yes" ]]; then
  echo "ACHTUNG: Dies loescht den lokalen SQLite-Sync-State und ALLE Punkte"
  echo "aus der in config.yaml eingetragenen Qdrant-Collection."
  echo "Elasticsearch/Nextcloud werden NICHT veraendert."
  echo
  echo "Ausfuehren mit: $0 --yes"
  exit 0
fi

readarray -t CFG < <(python - "$CONFIG_FILE" "$BASE_DIR" <<'PY'
from pathlib import Path
import sys
import yaml

config_path = Path(sys.argv[1])
base_dir = Path(sys.argv[2])
with config_path.open('r', encoding='utf-8') as f:
    cfg = yaml.safe_load(f)

state = Path(cfg.get('sync', {}).get('state_db') or cfg.get('state', {}).get('database', 'state.sqlite'))
if not state.is_absolute():
    state = base_dir / state

print(state)
print(cfg['qdrant']['url'].rstrip('/'))
print(cfg['qdrant']['collection'])
PY
)

STATE_FILE="${CFG[0]}"
QDRANT_URL="${CFG[1]}"
QDRANT_COLLECTION="${CFG[2]}"

echo "SQLite-State: $STATE_FILE"
echo "Qdrant:       $QDRANT_URL"
echo "Collection:   $QDRANT_COLLECTION"
echo

rm -f "$STATE_FILE"
echo "SQLite-State geloescht."

HTTP_CODE="$(curl -sS -o /tmp/rag-qdrant-reset.$$ -w '%{http_code}' -X DELETE \
  "$QDRANT_URL/collections/$QDRANT_COLLECTION")"
if [[ "$HTTP_CODE" != "200" && "$HTTP_CODE" != "404" ]]; then
  echo "Fehler beim Loeschen der Qdrant-Collection (HTTP $HTTP_CODE):" >&2
  cat /tmp/rag-qdrant-reset.$$ >&2 || true
  rm -f /tmp/rag-qdrant-reset.$$
  exit 1
fi
rm -f /tmp/rag-qdrant-reset.$$

echo "Qdrant-Collection geloescht (oder bereits nicht vorhanden)."
echo "Sie wird beim naechsten Sync mit der aktuellen Embedding-Dimension neu angelegt."

echo
echo "Reset fertig. Elasticsearch/Nextcloud wurden nicht angefasst."
