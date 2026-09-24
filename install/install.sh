#!/usr/bin/env bash
set -euo pipefail

# Single public installer entry point for all deployment profiles.
# Profile implementations live below install/profiles/ so profile-specific host
# requirements do not leak into other profiles (notably old-OS super-light).

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
printf -v SUNAQ_INSTALL_INVOCATION '%q ' "$0" "$@"
SUNAQ_INSTALL_INVOCATION="${SUNAQ_INSTALL_INVOCATION% }"
# Compatibility for older profile implementations and reruns.
AKI_INSTALL_INVOCATION="$SUNAQ_INSTALL_INVOCATION"
export SUNAQ_INSTALL_INVOCATION AKI_INSTALL_INVOCATION
PROFILE="standard"
PROFILE_EXPLICIT=0
DEPLOYMENT=""
FORWARD=()

usage() {
  cat <<'USAGE'
Usage: sudo ./install/install.sh [--profile PROFILE] [profile options]

Profiles:
  standard      Native Python >=3.10 middleware; optional Qdrant/Neo4j/OpenWebUI
  super-light   Containerized middleware for older/smaller hosts; Elasticsearch
                document retrieval, Neo4j Graph-Lite, no host Python requirement

Global options:
  --profile standard|super-light
  --deployment native|dockerized
                                deployment mechanism (default depends on profile)
  --super-light                 shorthand for --profile super-light
  --profiles                    list profiles and exit
  -h, --help                    show this overview

Examples:
  sudo ./install/install.sh --profile standard --plan
  sudo ./install/install.sh --profile super-light --plan \
    --nextcloud-url https://cloud.example.org/nextcloud \
    --elasticsearch-url http://127.0.0.1:9200
  sudo ./install/install.sh --super-light -y \
    --nextcloud-url https://cloud.example.org/nextcloud \
    --elasticsearch-url http://127.0.0.1:9200

For profile-specific options:
  ./install/install.sh --profile standard --help
  ./install/install.sh --profile super-light --help
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --profile)
      [[ $# -ge 2 ]] || { echo "--profile requires a value" >&2; exit 2; }
      PROFILE="$2"; PROFILE_EXPLICIT=1; shift 2 ;;
    --profile=*)
      PROFILE="${1#*=}"; PROFILE_EXPLICIT=1; shift ;;
    --super-light)
      PROFILE="super-light"; PROFILE_EXPLICIT=1; shift ;;
    --deployment)
      [[ $# -ge 2 ]] || { echo "--deployment requires a value" >&2; exit 2; }
      DEPLOYMENT="$2"; shift 2 ;;
    --deployment=*)
      DEPLOYMENT="${1#*=}"; shift ;;
    --profiles)
      printf 'standard\nsuper-light\n'; exit 0 ;;
    -h|--help)
      if [[ $PROFILE_EXPLICIT -eq 0 ]]; then
        usage; exit 0
      fi
      FORWARD+=("$1"); shift ;;
    *)
      FORWARD+=("$1"); shift ;;
  esac
done

case "$PROFILE" in
  standard|default) PROFILE="standard" ;;
  super-light|superlight) PROFILE="super-light" ;;
  *)
    echo "Unknown installation profile: $PROFILE" >&2
    usage >&2
    exit 2 ;;
esac

if [[ -z "$DEPLOYMENT" ]]; then
  [[ "$PROFILE" == "super-light" ]] && DEPLOYMENT="dockerized" || DEPLOYMENT="native"
fi
case "$DEPLOYMENT" in native|dockerized) ;; *) echo "Unknown deployment mode: $DEPLOYMENT" >&2; exit 2 ;; esac

# 0.8.6 keeps profile and deployment explicit independent concepts while only
# advertising combinations that have been regression-tested.
if [[ "$PROFILE:$DEPLOYMENT" == "standard:native" ]]; then
  exec "$SCRIPT_DIR/profiles/install-standard.sh" "${FORWARD[@]}"
elif [[ "$PROFILE:$DEPLOYMENT" == "super-light:dockerized" ]]; then
  exec "$SCRIPT_DIR/profiles/install-super-light.sh" "${FORWARD[@]}"
else
  echo "Unsupported 0.8.6 combination: profile=$PROFILE deployment=$DEPLOYMENT" >&2
  echo "Supported: standard+native, super-light+dockerized" >&2
  exit 2
fi
