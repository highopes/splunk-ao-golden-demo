#!/usr/bin/env bash
# Install or upgrade the Helm release with an immutable image tag:
#   bash deploy/k8s/scripts/20-deploy.sh <version>-<git-sha>
# Settings come from the [k8s] table (passed with --set); credentials are only
# referenced by Secret name, so the release history holds no secret.
set -euo pipefail
source "$(dirname "$0")/lib.sh"
TAG="${1:-}"
[[ -n "$TAG" && "$TAG" != latest ]] || die "usage: $0 <immutable image tag, e.g. 1.0.0-abc1234>"
start_log deploy
load_settings
need helm
kc get secret "$RELEASE-app" "$RELEASE-postgres" "$RELEASE-tls" "$RELEASE-basic-auth" >/dev/null \
  || die "run 10-prepare-namespace.sh first"

checksum="$(secrets checksum)"
args=(
  --set-string "image.repository=$IMAGE_REPO"
  --set-string "image.tag=$TAG"
  --set-string "ingress.host=$APP_HOST"
  --set-string "ingress.className=$INGRESS_CLASS"
  --set-string "app.configChecksum=$checksum"
)
[[ -n "$PG_NODE" ]] && args+=(--set-string "postgres.nodeName=$PG_NODE")

log "helm upgrade --install $RELEASE (namespace $NS, image $IMAGE_REPO:$TAG)"
helm upgrade --install "$RELEASE" "$CHART_DIR" -n "$NS" "${args[@]}" \
  --history-max 20 --wait --timeout 15m
helm -n "$NS" history "$RELEASE" --max 5
kc get pods -o wide
log "done"
