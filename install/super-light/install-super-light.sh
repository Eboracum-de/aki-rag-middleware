#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
echo "NOTE: use install/install.sh --profile super-light; forwarding for compatibility." >&2
exec "$SCRIPT_DIR/../install.sh" --profile super-light "$@"
