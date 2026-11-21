#!/usr/bin/env bash
# Create the data initialization Job on demand (not a Helm hook: embeddings are
# billed, so upgrades never re-run it). Idempotent; re-run to rebuild the data.
#   bash deploy/k8s/scripts/30-init-data.sh [domain ...]   (default: all five)
set -euo pipefail
source "$(dirname "$0")/lib.sh"
start_log init-data
load_settings
need helm

image="$(kc get deploy "$RELEASE-app" -o jsonpath='{.spec.template.spec.containers[0].image}')" \
  || die "deploy the release first (20-deploy.sh)"
job="$RELEASE-init-$(date '+%Y%m%d%H%M%S')"
args=(--set initJob.enabled=true --set-string "initJob.name=$job"
      --set-string "image.repository=${image%:*}" --set-string "image.tag=${image##*:}"
      --set-string "ingress.host=$APP_HOST")
if [[ $# -gt 0 ]]; then
  list="$(printf '%s,' "$@")"; args+=(--set "initJob.domains={${list%,}}")
fi

kc rollout status statefulset "$RELEASE-postgres" --timeout=5m
log "job $job ($image)"
helm template "$RELEASE" "$CHART_DIR" -n "$NS" "${args[@]}" --show-only templates/init-job.yaml \
  | kc apply -f -
if ! kc wait --for=condition=complete "job/$job" --timeout=60m; then
  kc logs "job/$job" --tail=80 || true
  die "job $job did not complete"
fi
kc logs "job/$job" | grep -E '^== init|✓|❌|INIT_DONE|Loaded|documents|rows' | tail -60
log "done"
