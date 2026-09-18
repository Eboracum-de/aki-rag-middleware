#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
URL='https://raw.githubusercontent.com/microsoft/playwright/v1.62.0/utils/docker/seccomp_profile.json'
TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT
curl -fsSL "$URL" -o "$TMP"
jq -e '.defaultAction == "SCMP_ACT_ERRNO"' "$TMP" >/dev/null
jq -e 'any(.syscalls[]?; (.action == "SCMP_ACT_ALLOW") and ((.names // []) | index("clone")) and ((.names // []) | index("setns")) and ((.names // []) | index("unshare")))' "$TMP" >/dev/null
mv "$TMP" seccomp_profile.json
trap - EXIT
printf '%s\n' 'Official Playwright seccomp profile verified and written.'
