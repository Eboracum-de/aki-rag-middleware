#!/usr/bin/env bash
set -euo pipefail

SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PREFIX="/opt/nextcloud-rag"
NEXTCLOUD_URL=""
ELASTICSEARCH_URL=""
ELASTICSEARCH_INDEX="my_index"
INSTALL_SYSTEM_PACKAGES=1
ASSUME_YES=0
PLAN_ONLY=0
START_STACK=1
WITH_OPENWEBUI=0
WITH_PROXY=0
CA_CERTIFICATES=()
X509_STRICT=0

usage() {
  cat <<'USAGE'
Usage: sudo ./install/install.sh --profile super-light [options]

Installs the 0.8.5 super-light installation profile as a Docker-hosted deployment.  Host Python
is not used by the middleware and may be older than Python 3.10 (e.g. Leap 15.3).

Required for a started installation:
  --nextcloud-url URL       Nextcloud base URL, preferably HTTPS
  --elasticsearch-url URL   Existing Nextcloud FullTextSearch Elasticsearch URL

Options:
  --elasticsearch-index ID  Elasticsearch index (default: my_index)
  --prefix PATH             Install prefix (default: /opt/nextcloud-rag)
  --skip-system-packages    Do not install Docker/curl/jq/openssl
  --no-start                Prepare files/images but do not start the stack
  --with-openwebui          Also start bundled OpenWebUI (default: off)
  --with-proxy              Also start bundled nginx on host 80/443 (default: off)
  --ca-certificate FILE     Trust one private CA certificate inside API/provider containers; repeatable
  --x509-strict             Enable Python/OpenSSL VERIFY_X509_STRICT (default: off)
  --no-x509-strict          Compatibility alias; keep strict mode disabled
  --plan                    Show the intended deployment and exit
  -y, --yes                 Non-interactive confirmation
  -h, --help                Show help

Example:
  sudo ./install/install.sh --profile super-light \
    --nextcloud-url https://cloud.example.org \
    --elasticsearch-url http://10.0.0.20:9200 \
    --elasticsearch-index my_index
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --prefix) PREFIX="$2"; shift 2 ;;
    --nextcloud-url) NEXTCLOUD_URL="$2"; shift 2 ;;
    --elasticsearch-url) ELASTICSEARCH_URL="$2"; shift 2 ;;
    --elasticsearch-index) ELASTICSEARCH_INDEX="$2"; shift 2 ;;
    --skip-system-packages) INSTALL_SYSTEM_PACKAGES=0; shift ;;
    --no-start) START_STACK=0; shift ;;
    --with-openwebui) WITH_OPENWEBUI=1; shift ;;
    --with-proxy) WITH_PROXY=1; shift ;;
    --ca-certificate) [[ $# -ge 2 ]] || { echo "--ca-certificate requires a file" >&2; exit 2; }; CA_CERTIFICATES+=("$2"); shift 2 ;;
    --x509-strict) X509_STRICT=1; shift ;;
    --no-x509-strict) X509_STRICT=0; shift ;;
    --plan) PLAN_ONLY=1; shift ;;
    -y|--yes) ASSUME_YES=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage; exit 2 ;;
  esac
done

log() { printf '\n==> %s\n' "$*"; }

print_plan() {
  # Conservative image/layer estimate only. Neo4j data, web archive and other
  # site/user data are additional. OpenWebUI is deliberately expensive and is
  # counted only when explicitly requested.
  local disk_low=2
  local disk_high=4
  if [[ $WITH_OPENWEBUI -eq 1 ]]; then
    disk_low=$((disk_low + 6))
    disk_high=$((disk_high + 8))
  fi

  cat <<PLAN
AKI RAG Middleware 0.8.5-rc3 - super-light installation profile
----------------------------------------------
Install prefix:          $PREFIX
Deployment mode:         dockerized
Host Python required:    no
Document retrieval:      Elasticsearch only
Neo4j:                   local, seeds/entity aliases/query expansion only
Graph document arm:      disabled
Graph extraction worker: disabled
Qdrant/embeddings:       disabled / not installed
Reranker/TEI:            disabled / not installed
Playwright archive:      local renderer enabled
OpenWebUI:               $([[ $WITH_OPENWEBUI -eq 1 ]] && echo pull/start || echo not pulled/not started)
Reverse proxy:           $([[ $WITH_PROXY -eq 1 ]] && echo bundled/start || echo disabled)
Nextcloud URL:           ${NEXTCLOUD_URL:-<required before start>}
Elasticsearch URL:       ${ELASTICSEARCH_URL:-<required before start>}
Elasticsearch index:     $ELASTICSEARCH_INDEX
RAM target:              4 GiB practical minimum, 4-8 GiB recommended; Neo4j 256m pagecache / 512m max heap
Private CA trust:        ${#CA_CERTIFICATES[@]} certificate(s) supplied on this run
Python X.509 strict:      $([[ $X509_STRICT -eq 1 ]] && echo enabled || echo disabled-compatibility-mode)
Estimated disk use:      roughly ${disk_low}-${disk_high} GiB before site/user data
PLAN
}

if [[ $PLAN_ONLY -eq 1 ]]; then
  print_plan
  exit 0
fi
if [[ ${EUID:-$(id -u)} -ne 0 ]]; then
  echo "Run this installer as root (sudo)." >&2
  exit 1
fi
if [[ $START_STACK -eq 1 && ( -z "$NEXTCLOUD_URL" || -z "$ELASTICSEARCH_URL" ) ]]; then
  echo "--nextcloud-url and --elasticsearch-url are required unless --no-start is used." >&2
  exit 2
fi

print_plan
if [[ $ASSUME_YES -ne 1 ]]; then
  if [[ ! -t 0 ]]; then
    echo "Non-interactive stdin: rerun with -y after reviewing --plan." >&2
    exit 1
  fi
  printf '\nProceed? [y/N] '
  read -r answer
  case "$answer" in y|Y|yes|YES|Yes) ;; *) echo "Cancelled."; exit 0 ;; esac
fi

install_packages() {
  [[ $INSTALL_SYSTEM_PACKAGES -eq 1 ]] || return 0
  log "Installing host prerequisites (no middleware Python packages)"
  if command -v zypper >/dev/null 2>&1; then
    zypper --non-interactive refresh
    zypper --non-interactive install ca-certificates curl jq openssl docker docker-compose
    systemctl enable --now docker
  elif command -v apt-get >/dev/null 2>&1; then
    apt-get update
    DEBIAN_FRONTEND=noninteractive apt-get install -y ca-certificates curl jq openssl docker.io
    apt-get install -y docker-compose-v2 2>/dev/null || apt-get install -y docker-compose-plugin 2>/dev/null || apt-get install -y docker-compose
    systemctl enable --now docker
  else
    echo "Unsupported package manager. Install Docker, Docker Compose, curl, jq and openssl manually." >&2
    exit 1
  fi
}

compose() {
  if docker compose version >/dev/null 2>&1; then
    docker compose "$@"
  elif command -v docker-compose >/dev/null 2>&1; then
    docker-compose "$@"
  else
    echo "Docker Compose not found." >&2
    exit 1
  fi
}

random_secret() { openssl rand -hex 32; }
sed_repl() { printf '%s' "$1" | sed 's/[&|]/\\&/g'; }

install_packages
command -v docker >/dev/null || { echo "docker is required" >&2; exit 1; }
command -v curl >/dev/null || { echo "curl is required" >&2; exit 1; }
command -v jq >/dev/null || { echo "jq is required" >&2; exit 1; }
command -v openssl >/dev/null || { echo "openssl is required" >&2; exit 1; }

log "Installing source tree"
mkdir -p "$PREFIX"
# This profile is intended for a dedicated node. Preserve site-owned runtime/config
# files on rerun while refreshing application/templates.  When the installer is
# rerun from the installed tree itself, do not delete its own source files.
if [[ "$(readlink -f "$SOURCE_DIR")" != "$(readlink -f "$PREFIX")" ]]; then
  for item in rag prompts ontology docs clients requirements.txt requirements-super-light.txt versions.lock.yaml pyproject.toml README.md CHANGELOG.md SECURITY.md .dockerignore; do
    rm -rf "$PREFIX/$item"
    cp -a "$SOURCE_DIR/$item" "$PREFIX/$item"
  done
  # Merge installer templates instead of replacing install/ wholesale: TLS material,
  # generated.conf and the local super-light .env are site state and survive reruns.
  mkdir -p "$PREFIX/install"
  cp -a "$SOURCE_DIR/install/." "$PREFIX/install/"
fi
mkdir -p "$PREFIX/runtime" "$PREFIX/runtime/ca"
touch "$PREFIX/runtime/ca/.keep"
# Keep private trust anchors as site-owned runtime state.  The Docker build only
# consumes runtime/ca; other runtime secrets are excluded via .dockerignore.
if [[ ${#CA_CERTIFICATES[@]} -gt 0 ]]; then
  log "Installing private CA trust anchors for containerized middleware"
  rm -f "$PREFIX/runtime/ca"/installer-*.crt
  ca_index=0
  for ca_source in "${CA_CERTIFICATES[@]}"; do
    [[ -r "$ca_source" ]] || { echo "CA certificate is not readable: $ca_source" >&2; exit 2; }
    cert_count="$(grep -c -- '-----BEGIN CERTIFICATE-----' "$ca_source" || true)"
    [[ "$cert_count" -eq 1 ]] || {
      echo "--ca-certificate expects exactly one PEM certificate per file: $ca_source" >&2
      echo "Repeat --ca-certificate for root/intermediate certificates." >&2
      exit 2
    }
    openssl x509 -in "$ca_source" -noout >/dev/null 2>&1 || { echo "Invalid PEM X.509 certificate: $ca_source" >&2; exit 2; }
    ca_index=$((ca_index + 1))
    printf -v ca_name 'installer-%02d.crt' "$ca_index"
    cp "$ca_source" "$PREFIX/runtime/ca/$ca_name"
    chmod 0644 "$PREFIX/runtime/ca/$ca_name"
  done
fi

if [[ ! -f "$PREFIX/config.yaml" ]]; then
  cp "$PREFIX/install/super-light/config.super-light.yaml" "$PREFIX/config.yaml"
fi
if [[ $X509_STRICT -eq 1 ]]; then
  sed -i "/^tls:/,/^[^[:space:]]/ s/^  x509_strict:.*/  x509_strict: true/" "$PREFIX/config.yaml"
else
  sed -i "/^tls:/,/^[^[:space:]]/ s/^  x509_strict:.*/  x509_strict: false/" "$PREFIX/config.yaml"
fi
if [[ ! -f "$PREFIX/web.yaml" ]]; then
  cp "$PREFIX/install/super-light/web.super-light.yaml" "$PREFIX/web.yaml"
fi
if [[ ! -f "$PREFIX/provider.env" ]]; then
  cp "$PREFIX/install/super-light/provider.env.super-light.example" "$PREFIX/provider.env"
fi
if [[ ! -f "$PREFIX/runtime.env" ]]; then
  cp "$PREFIX/install/super-light/runtime.env.super-light.example" "$PREFIX/runtime.env"
fi

if [[ -n "$NEXTCLOUD_URL" ]]; then
  esc="$(sed_repl "${NEXTCLOUD_URL%/}")"
  sed -i "/^nextcloud:/,/^[^[:space:]]/ s|^  base_url:.*|  base_url: ${esc}/|" "$PREFIX/config.yaml"
fi
if [[ -n "$ELASTICSEARCH_URL" ]]; then
  esc="$(sed_repl "${ELASTICSEARCH_URL%/}")"
  sed -i "/^elasticsearch:/,/^[^[:space:]]/ s|^  url:.*|  url: ${esc}|" "$PREFIX/config.yaml"
fi
idx="$(sed_repl "$ELASTICSEARCH_INDEX")"
sed -i "/^elasticsearch:/,/^[^[:space:]]/ s|^  index:.*|  index: ${idx}|" "$PREFIX/config.yaml"

NEO4J_PASSWORD="$(sed -n 's/^NEO4J_PASSWORD=//p' "$PREFIX/runtime.env" | head -1)"
if [[ -z "$NEO4J_PASSWORD" || "$NEO4J_PASSWORD" == "replace-me" ]]; then
  NEO4J_PASSWORD="$(random_secret)"
  sed -i "s|^NEO4J_PASSWORD=.*|NEO4J_PASSWORD=${NEO4J_PASSWORD}|" "$PREFIX/runtime.env"
fi
PROVIDER_API_KEY="$(sed -n 's/^PROVIDER_API_KEY=//p' "$PREFIX/runtime.env" | head -1)"
if [[ -z "$PROVIDER_API_KEY" || "$PROVIDER_API_KEY" == "replace-me" ]]; then
  PROVIDER_API_KEY="$(random_secret)"
  sed -i "s|^PROVIDER_API_KEY=.*|PROVIDER_API_KEY=${PROVIDER_API_KEY}|" "$PREFIX/runtime.env"
fi
ADMIN_USER="$(sed -n 's/^RAG_ADMIN_USER=//p' "$PREFIX/runtime.env" | head -1)"
[[ -n "$ADMIN_USER" ]] || ADMIN_USER="admin"
ADMIN_PASSWORD="$(sed -n 's/^RAG_ADMIN_PASSWORD=//p' "$PREFIX/runtime.env" | head -1)"
if [[ -z "$ADMIN_PASSWORD" || "$ADMIN_PASSWORD" == "replace-me" ]]; then
  ADMIN_PASSWORD="$(random_secret)"
  sed -i "s|^RAG_ADMIN_PASSWORD=.*|RAG_ADMIN_PASSWORD=${ADMIN_PASSWORD}|" "$PREFIX/runtime.env"
fi
chmod 600 "$PREFIX/runtime.env" "$PREFIX/provider.env"

if [[ ! -s "$PREFIX/runtime/credential-master.key" ]]; then
  openssl rand -base64 32 > "$PREFIX/runtime/credential-master.key"
fi
chown -R 10001:10001 "$PREFIX/runtime"
chmod 700 "$PREFIX/runtime"
chmod 600 "$PREFIX/runtime/credential-master.key"

cat > "$PREFIX/install/super-light/.env" <<ENV
NEO4J_IMAGE=neo4j:5.26.29-community@sha256:d9dd3dc7d1c78fa959191ff02dbdcbefadceaf83eee23428fb92a58cac8ad3fe
OPENWEBUI_IMAGE=ghcr.io/open-webui/open-webui:v0.11.0@sha256:72c0ba641ba75e7aa52655cb242570906ececd09b1140fb736483038a22b3228
NGINX_IMAGE=nginx:1.30.4-alpine3.24@sha256:97d490c12ba55b4946b01546d1c3ed324e8d41ab1c9fcb2a616aa470620e5b46
NEO4J_PASSWORD=${NEO4J_PASSWORD}
OPENWEBUI_PROVIDER_API_KEY=${PROVIDER_API_KEY}
NEO4J_HTTP_PORT=7474
NEO4J_BOLT_PORT=7687
NEO4J_HEAP_INITIAL=256m
NEO4J_HEAP_MAX=512m
NEO4J_PAGECACHE=256m
PLAYWRIGHT_PORT=8090
OPENWEBUI_PORT=3000
ENV
chmod 600 "$PREFIX/install/super-light/.env"

if [[ $WITH_PROXY -eq 1 ]]; then
  log "Preparing nginx TLS/admin gate"
  TLS_DIR="$PREFIX/install/nginx/tls"
  mkdir -p "$TLS_DIR"
  if [[ ! -s "$TLS_DIR/server.crt" || ! -s "$TLS_DIR/server.key" ]]; then
    CERT_CN="$(hostname -f 2>/dev/null || hostname)"
    OPENSSL_CFG="$(mktemp)"
    cat > "$OPENSSL_CFG" <<EOFSSL
[req]
distinguished_name = dn
x509_extensions = v3
prompt = no
[dn]
CN = ${CERT_CN}
[v3]
subjectAltName = DNS:${CERT_CN},DNS:localhost,IP:127.0.0.1
EOFSSL
    openssl req -x509 -nodes -newkey rsa:2048 -sha256 -days 825 \
      -keyout "$TLS_DIR/server.key" -out "$TLS_DIR/server.crt" -config "$OPENSSL_CFG" >/dev/null 2>&1
    rm -f "$OPENSSL_CFG"
  fi
  chmod 600 "$TLS_DIR/server.key"
  chmod 644 "$TLS_DIR/server.crt"
  printf 'admin:%s\n' "$(openssl passwd -apr1 "$ADMIN_PASSWORD")" > "$PREFIX/install/nginx/htpasswd"
  chmod 644 "$PREFIX/install/nginx/htpasswd"
  if [[ $WITH_OPENWEBUI -eq 1 ]]; then
    cp "$PREFIX/install/nginx/nginx-openwebui.conf" "$PREFIX/install/nginx/generated.conf"
  else
    cp "$PREFIX/install/nginx/nginx.conf" "$PREFIX/install/nginx/generated.conf"
  fi

fi


# Generate the effective optional-service override. Keeping OpenWebUI/proxy out of
# the base compose file is important on legacy Compose: a later plain
# `docker-compose up` must not silently start optional heavy services.
OVERRIDE="$PREFIX/install/super-light/docker-compose.override.yml"
rm -f "$OVERRIDE"
if [[ $WITH_OPENWEBUI -eq 1 || $WITH_PROXY -eq 1 ]]; then
  cat > "$OVERRIDE" <<'EOFOVR'
version: "2.4"
services:
EOFOVR
  if [[ $WITH_OPENWEBUI -eq 1 ]]; then
    cat >> "$OVERRIDE" <<'EOFOVR'
  openwebui:
    image: ${OPENWEBUI_IMAGE:-ghcr.io/open-webui/open-webui:v0.11.0@sha256:72c0ba641ba75e7aa52655cb242570906ececd09b1140fb736483038a22b3228}
    restart: unless-stopped
    network_mode: host
    environment:
      HOST: "127.0.0.1"
      PORT: "${OPENWEBUI_PORT:-3000}"
      ENABLE_OLLAMA_API: "false"
      ENABLE_OPENAI_API: "true"
      ENABLE_FORWARD_USER_INFO_HEADERS: "false"
      ENABLE_PERSISTENT_CONFIG: "false"
      BYPASS_MODEL_ACCESS_CONTROL: "true"
      OPENAI_API_BASE_URL: "http://127.0.0.1:8766/v1"
      OPENAI_API_KEY: "${OPENWEBUI_PROVIDER_API_KEY:-}"
      OPENAI_API_CONFIGS: '{"0":{"enable":true,"headers":{"X-OpenWebUI-User-Id":"{{USER_ID}}"}}}'
    volumes:
      - openwebui_data:/app/backend/data
    depends_on:
      - provider
EOFOVR
  fi
  if [[ $WITH_PROXY -eq 1 ]]; then
    cat >> "$OVERRIDE" <<'EOFOVR'
  proxy:
    image: ${NGINX_IMAGE:-nginx:1.30.4-alpine3.24@sha256:97d490c12ba55b4946b01546d1c3ed324e8d41ab1c9fcb2a616aa470620e5b46}
    restart: unless-stopped
    network_mode: host
    volumes:
      - ../nginx/generated.conf:/etc/nginx/nginx.conf:ro
      - ../nginx/htpasswd:/etc/nginx/htpasswd:ro
      - ../nginx/tls:/etc/nginx/tls:ro
    depends_on:
      - provider
EOFOVR
  fi
  if [[ $WITH_OPENWEBUI -eq 1 ]]; then
    cat >> "$OVERRIDE" <<'EOFOVR'
volumes:
  openwebui_data:
EOFOVR
  fi
fi

log "Preparing Playwright Chromium seccomp profile"
"$PREFIX/install/components/playwright-renderer/prepare.sh"

cd "$PREFIX/install/super-light"
log "Building super-light provider and renderer images"
compose build api provider playwright-renderer


log "Registering default trusted provider client"
compose run --rm --no-deps provider python - <<'PYCLIENT'
import os
from rag.credential_store import CredentialStore
key = os.environ.get("PROVIDER_API_KEY", "").strip()
if len(key) < 24:
    raise SystemExit("PROVIDER_API_KEY missing/too short")
store = CredentialStore("runtime/users.sqlite")
store.register_client("default-client", key, name="Default trusted frontend", replace=True)
print("trusted provider client registered: default-client")
PYCLIENT

if [[ $START_STACK -eq 0 ]]; then
  log "Prepared. Edit $PREFIX/config.yaml, provider.env and runtime.env, then start with:"
  echo "  cd $PREFIX/install/super-light && docker-compose up -d api provider mail-worker neo4j playwright-renderer"
  exit 0
fi

log "Starting super-light stack"
SERVICES=(api provider mail-worker neo4j playwright-renderer)
[[ $WITH_OPENWEBUI -eq 1 ]] && SERVICES+=(openwebui)
[[ $WITH_PROXY -eq 1 ]] && SERVICES+=(proxy)
compose up -d --remove-orphans "${SERVICES[@]}"

log "Waiting for local endpoints"
for attempt in $(seq 1 90); do
  api_state=waiting
  provider_state=waiting
  playwright_state=waiting
  curl -fsS --max-time 2 http://127.0.0.1:8765/live >/dev/null 2>&1 && api_state=ready
  curl -fsS --max-time 2 http://127.0.0.1:8766/live >/dev/null 2>&1 && provider_state=ready
  curl -fsS --max-time 2 http://127.0.0.1:8090/live >/dev/null 2>&1 && playwright_state=ready
  if [[ "$api_state" == ready && "$provider_state" == ready && "$playwright_state" == ready ]]; then
    printf '  API: ready | Provider: ready | Playwright: ready\n'
    break
  fi
  if [[ $attempt -eq 1 || $((attempt % 10)) -eq 0 ]]; then
    printf '  API: %s | Provider: %s | Playwright: %s (attempt %d/90)\n' \
      "$api_state" "$provider_state" "$playwright_state" "$attempt"
  fi
  sleep 2
done
curl -fsS http://127.0.0.1:8765/live >/dev/null || { echo "RAG API did not become live" >&2; compose logs --tail=100 api; exit 1; }
curl -fsS http://127.0.0.1:8766/live >/dev/null || { echo "Provider did not become live" >&2; compose logs --tail=100 provider; exit 1; }
curl -fsS http://127.0.0.1:8090/live >/dev/null || { echo "Playwright renderer did not become live" >&2; compose logs --tail=100 playwright-renderer; exit 1; }

cat <<DONE

Super-light installation profile installed.

Local services:
  API:        http://127.0.0.1:8765
  Provider:   http://127.0.0.1:8766
  Neo4j:      bolt://127.0.0.1:7687 (Browser via SSH tunnel to 7474)
  Playwright: http://127.0.0.1:8090
  OpenWebUI:  $([[ $WITH_OPENWEBUI -eq 1 ]] && echo http://127.0.0.1:3000 || echo disabled)
  nginx:      $([[ $WITH_PROXY -eq 1 ]] && echo enabled || echo disabled)
  CA trust:   $([[ -d "$PREFIX/runtime/ca" ]] && find "$PREFIX/runtime/ca" -maxdepth 1 -name "*.crt" -type f 2>/dev/null | wc -l || echo 0) private certificate(s) baked into API/provider image
  X509 strict: $([[ $X509_STRICT -eq 1 ]] && echo enabled || echo disabled-compatibility-mode)

Generated credentials (store them now; both are also in $PREFIX/runtime.env):
  Admin user:       ${ADMIN_USER}
  Admin password:   ${ADMIN_PASSWORD}
  Provider API key: ${PROVIDER_API_KEY}

Before real use, configure the external model/provider credentials in:
  $PREFIX/runtime.env      # e.g. LLM_API_KEY, WEB_SEARCH_API_KEY when used
and review:
  $PREFIX/provider.env     # model/backend selection
  $PREFIX/config.yaml
  $PREFIX/web.yaml

Contact seeds:
  Per-user CardDAV seeds are managed under RAG Admin -> Users -> Kontakt-DB
  and use the Nextcloud credential already stored by the Login Flow. CLI:
  $PREFIX/install/super-light/contacts.sh sync --user NEXTCLOUD_LOGIN
  Missing credentials or contacts are a clean no-op. The legacy global
  NEXTCLOUD_USERNAME/NEXTCLOUD_APP_PASSWORD path is compatibility-only.
DONE
