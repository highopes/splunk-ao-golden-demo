# shellcheck shell=bash
# Shared helpers for deploy/k8s/scripts. Run the numbered scripts with "bash <script>";
# do not source them into an interactive shell (they use set -euo pipefail).
#
# Every setting comes from the app's single configuration file
# .streamlit/secrets.toml ([k8s] table for deployment settings). Secret values
# only travel through pipes into kubectl/openssl/curl; they are never printed,
# never placed on a command line and never written to disk.

GOLDEN_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
SECRETS_TOOL="$GOLDEN_ROOT/deploy/k8s/scripts/secrets_tool.py"
CHART_DIR="$GOLDEN_ROOT/deploy/helm/splunk-ao-golden-demo"
LOG_DIR="$GOLDEN_ROOT/.work/logs"

log()  { printf '%s %s\n' "$(date '+%H:%M:%S')" "$*"; }
die()  { log "ERROR: $*" >&2; exit 1; }
need() { command -v "$1" >/dev/null 2>&1 || die "$1 is required"; }

secrets() { python3 "$SECRETS_TOOL" "$@"; }
k8s_value() { secrets k8s "$@"; }

load_settings() {
  need python3; need kubectl
  secrets check >/dev/null || { secrets check | grep -v ': set$' >&2; die ".streamlit/secrets.toml is missing deployment keys (values not shown)"; }
  NS="$(k8s_value namespace)"
  RELEASE="$(k8s_value release "$NS")"
  APP_HOST="$(k8s_value app_host)"
  INGRESS_CLASS="$(k8s_value ingress_class)"
  IMAGE_REPO="$(k8s_value image)"
  PG_NODE="$(k8s_value postgres_node "")"
  AO_CA="$(k8s_value ao_ca_configmap)"
  AO_CA_NS="${AO_CA%%/*}"
  AO_CA_NAME="${AO_CA#*/}"
  [[ "$AO_CA" == */* ]] || die "[k8s].ao_ca_configmap must be <namespace>/<configmap>"
  # Shared ingress-nginx controller Service (read only, for the NodePort check).
  INGRESS_SVC="$(k8s_value ingress_controller_service "$AO_CA_NS/ingress-nginx-controller")"
  export NS RELEASE APP_HOST INGRESS_CLASS IMAGE_REPO PG_NODE AO_CA_NS AO_CA_NAME INGRESS_SVC
}

kc() { kubectl -n "$NS" "$@"; }

# kubectl apply of a client-side generated object (idempotent create-or-update).
apply_stdin() { kubectl apply -f - >/dev/null; }

start_log() {
  mkdir -p "$LOG_DIR"; chmod 700 "$GOLDEN_ROOT/.work" "$LOG_DIR" 2>/dev/null || true
  LOG_FILE="$LOG_DIR/$1-$(date '+%Y%m%d-%H%M%S').log"
  exec > >(tee -a "$LOG_FILE") 2>&1
  log "log: ${LOG_FILE#$GOLDEN_ROOT/}"
}
