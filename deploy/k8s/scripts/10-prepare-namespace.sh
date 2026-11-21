#!/usr/bin/env bash
# Prepare the app namespace (idempotent): namespace, AO internal CA ConfigMap,
# self-signed TLS Secret (reused if present), PostgreSQL / app / Basic Auth Secrets.
# Writes only to the app namespace. In the AO namespace it only reads the CA
# ConfigMap named by [k8s].ao_ca_configmap (a public certificate).
# Re-run after changing .streamlit/secrets.toml (e.g. a new Basic Auth password).
set -euo pipefail
source "$(dirname "$0")/lib.sh"
start_log prepare-namespace
load_settings
need openssl

log "namespace $NS"
kubectl create namespace "$NS" --dry-run=client -o yaml | apply_stdin
kubectl label namespace "$NS" app.kubernetes.io/part-of=splunk-ao-golden-demo --overwrite >/dev/null

log "AO internal CA: $AO_CA_NS/$AO_CA_NAME -> $NS/ao-internal-ca (read-only copy of the public certificate)"
ca="$(kubectl -n "$AO_CA_NS" get configmap "$AO_CA_NAME" -o jsonpath='{.data.ca\.crt}')"
[[ -n "$ca" ]] || die "ConfigMap $AO_CA_NS/$AO_CA_NAME has no ca.crt"
printf '%s\n' "$ca" | openssl x509 -noout -subject -enddate | sed 's/^/  /'
printf '%s\n' "$ca" | kubectl -n "$NS" create configmap ao-internal-ca --from-file=ca.crt=/dev/stdin \
  --dry-run=client -o yaml | apply_stdin
unset ca

if kc get secret "$RELEASE-tls" >/dev/null 2>&1; then
  log "TLS secret $RELEASE-tls exists (reused)"
else
  log "TLS secret $RELEASE-tls: new self-signed certificate for $APP_HOST (3 years)"
  tmp="$(mktemp -d)"; chmod 700 "$tmp"
  trap 'rm -rf "$tmp"' EXIT
  openssl req -x509 -newkey rsa:2048 -nodes -days 1095 -subj "/CN=$APP_HOST" \
    -addext "subjectAltName=DNS:$APP_HOST" -keyout "$tmp/tls.key" -out "$tmp/tls.crt" 2>/dev/null
  kc create secret tls "$RELEASE-tls" --cert="$tmp/tls.crt" --key="$tmp/tls.key" >/dev/null
  rm -rf "$tmp"; trap - EXIT
fi
kc get secret "$RELEASE-tls" -o jsonpath='{.data.tls\.crt}' | base64 -d | openssl x509 -noout -subject -enddate | sed 's/^/  /'

log "secret $RELEASE-postgres (postgres_password)"
secrets value postgres_password | kc create secret generic "$RELEASE-postgres" \
  --from-file=postgres-password=/dev/stdin --dry-run=client -o yaml | apply_stdin

log "secret $RELEASE-app (secrets.toml without the [k8s] table)"
secrets app-secret | kc create secret generic "$RELEASE-app" \
  --from-file=secrets.toml=/dev/stdin --dry-run=client -o yaml | apply_stdin

log "secret $RELEASE-basic-auth (apr1 hash of [k8s].basic_auth_password)"
user="$(k8s_value basic_auth_user)"
hash="$(secrets k8s-secret basic_auth_password | openssl passwd -apr1 -stdin)"
[[ "$hash" == '$apr1$'* ]] || die "openssl passwd failed"
printf '%s:%s\n' "$user" "$hash" | kc create secret generic "$RELEASE-basic-auth" \
  --from-file=auth=/dev/stdin --dry-run=client -o yaml | apply_stdin
unset hash

kc get configmap ao-internal-ca -o name
kc get secret "$RELEASE-tls" "$RELEASE-postgres" "$RELEASE-app" "$RELEASE-basic-auth" \
  -o custom-columns=NAME:.metadata.name,TYPE:.type --no-headers | sed 's/^/  /'
log "done"
