#!/usr/bin/env bash
# Roll the Helm release back (non-destructive; data and Secrets are kept):
#   bash deploy/k8s/scripts/90-rollback.sh            # previous revision
#   bash deploy/k8s/scripts/90-rollback.sh <revision>
# Full removal is deliberately not scripted: "helm uninstall" and deleting the
# namespace/PVC are destructive and need an explicit decision (see KUBERNETES.md).
set -euo pipefail
source "$(dirname "$0")/lib.sh"
start_log rollback
load_settings
need helm
helm -n "$NS" history "$RELEASE" --max 10
log "helm rollback $RELEASE ${1:-<previous>}"
helm -n "$NS" rollback "$RELEASE" ${1:+"$1"} --wait --timeout 15m
helm -n "$NS" history "$RELEASE" --max 3
kc get pods -o wide
log "done"
