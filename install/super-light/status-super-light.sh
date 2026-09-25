#!/usr/bin/env bash
set -u
cd "$(dirname "$0")"
if docker compose version >/dev/null 2>&1; then
  C=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
  C=(docker-compose)
else
  echo "Docker Compose not found." >&2
  exit 1
fi
"${C[@]}" ps

probe() {
  local name="$1" url="$2" opt
  if [[ $url == https:* ]]; then opt=-kfsS; else opt=-fsS; fi
  if curl $opt --max-time 3 "$url" >/dev/null 2>&1; then
    printf '  %-12s OK\n' "$name"
  else
    printf '  %-12s DOWN/STARTING\n' "$name"
  fi
}

printf '\nLocal probes:\n'
probe 'RAG API' 'http://127.0.0.1:8765/live'
probe 'Provider' 'http://127.0.0.1:8766/live'

playwright_cid="$("${C[@]}" ps -q playwright-renderer 2>/dev/null || true)"
if [[ -n "$playwright_cid" ]]; then
  probe 'Playwright' 'http://127.0.0.1:8090/live'
fi

for optional in openwebui proxy; do
  cid="$("${C[@]}" ps -q "$optional" 2>/dev/null || true)"
  [[ -n "$cid" ]] || continue
  if [[ "$optional" == openwebui ]]; then
    probe 'OpenWebUI' 'http://127.0.0.1:3000/health'
  else
    probe 'Proxy' 'https://127.0.0.1/proxy-health'
  fi
done
