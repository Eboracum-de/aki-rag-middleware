#!/usr/bin/env bash
set -euo pipefail
# Compatibility helper. The supported operator interface is contacts.sh and is
# keyed by the human Nextcloud login, not by an internal canonical UUID.
cd "$(dirname "$0")"
if [[ $# -eq 0 ]]; then
  echo "Usage: $0 --user NEXTCLOUD_LOGIN [--server URL] [--dry-run] [--limit N]" >&2
  echo "       or use: ./contacts.sh sync --user NEXTCLOUD_LOGIN" >&2
  exit 2
fi
exec ./contacts.sh sync "$@"
