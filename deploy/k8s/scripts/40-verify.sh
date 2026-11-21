#!/usr/bin/env bash
# Verify the deployment: Pods, in-Pod preflight (AO internal addresses with TLS,
# project/stream, ingest door, Agent Control, OpenAI, database), and the
# Ingress through the shared ingress-nginx NodePort (401 without, 200 with
# Basic Auth; the credentials are piped to curl, never shown).
set -euo pipefail
source "$(dirname "$0")/lib.sh"
start_log verify
load_settings
need curl
fail=0
pass() { log "PASS  $*"; }
bad()  { log "FAIL  $*"; fail=1; }

kc get pods -o wide
for kind in "deploy/$RELEASE-app" "statefulset/$RELEASE-postgres"; do
  kc rollout status "$kind" --timeout=60s >/dev/null 2>&1 && pass "$kind ready" || bad "$kind not ready"
done

log "in-Pod preflight: scripts/check_demo.py --in-cluster --live"
if kc exec "deploy/$RELEASE-app" -c app -- python scripts/check_demo.py --in-cluster --live; then
  pass "in-Pod preflight"
else
  bad "in-Pod preflight (see FAIL lines above)"
fi

# Shared ingress-nginx controller: read its Service only (NodePort for HTTPS).
port="$(kubectl -n "${INGRESS_SVC%%/*}" get svc "${INGRESS_SVC#*/}" -o jsonpath='{.spec.ports[?(@.name=="https")].nodePort}')"
node_ip="$(kubectl get nodes -o jsonpath='{.items[0].status.addresses[?(@.type=="InternalIP")].address}')"
url="https://$APP_HOST:$port/"
code="$(curl -sk -o /dev/null -w '%{http_code}' --resolve "$APP_HOST:$port:$node_ip" "$url")"
[[ "$code" == 401 ]] && pass "Ingress without credentials -> 401" || bad "Ingress without credentials -> $code (expected 401)"
code="$(secrets curl-auth | curl -sk -o /dev/null -w '%{http_code}' -K - --resolve "$APP_HOST:$port:$node_ip" "$url")"
[[ "$code" == 200 ]] && pass "Ingress with Basic Auth -> 200" || bad "Ingress with Basic Auth -> $code (expected 200)"
code="$(secrets curl-auth | curl -sk -o /dev/null -w '%{http_code}' -K - --resolve "$APP_HOST:$port:$node_ip" "${url}_stcore/health")"
[[ "$code" == 200 ]] && pass "Ingress /_stcore/health -> 200" || bad "Ingress /_stcore/health -> $code"

if [[ $fail -eq 0 ]]; then log "ALL PASS"; else log "SOME CHECKS FAILED"; exit 1; fi
