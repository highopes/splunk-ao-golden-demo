#!/usr/bin/env bash
# Build, smoke-test, scan and push the app image on the build host (Docker + buildx).
#
#   bash deploy/k8s/build/build-image.sh build <repository>   # e.g. <dockerhub-user>/sao-golden
#   bash deploy/k8s/build/build-image.sh smoke <repository>
#   bash deploy/k8s/build/build-image.sh scan  <repository>
#   bash deploy/k8s/build/build-image.sh push  <repository>
#   bash deploy/k8s/build/build-image.sh all   <repository>   # build + smoke + scan (push stays separate)
#
# Tag: ${VERSION:-1.0.0}-<git short sha>. The working tree must be clean so the
# tag identifies the exact source. Only Docker objects named sao-golden-smoke-*
# and labelled org.opencontainers.image.title=sao-golden are created and removed;
# nothing else on the build host is touched (no prune).
set -euo pipefail
cd "$(dirname "$0")/../../.."

TITLE=sao-golden
CMD="${1:-}"
REPO="${2:-}"
log() { printf '%s %s\n' "$(date '+%H:%M:%S')" "$*"; }
die() { log "ERROR: $*" >&2; exit 1; }
[[ -n "$CMD" && -n "$REPO" ]] || { sed -n '2,14p' "$0"; exit 2; }
[[ -z "$(git status --porcelain)" ]] || die "working tree is not clean; commit/pull first"
VERSION="${VERSION:-1.0.0}"
TAG="$VERSION-$(git rev-parse --short HEAD)"
IMG="$REPO:$TAG"
mkdir -p .work/logs && chmod 700 .work .work/logs
LOG_FILE=".work/logs/build-$CMD-$(date '+%Y%m%d-%H%M%S').log"
exec > >(tee -a "$LOG_FILE") 2>&1
log "image $IMG  (log: $LOG_FILE)"

build() {
  log "docker buildx build --platform linux/amd64"
  local started=$SECONDS
  docker buildx build --platform linux/amd64 \
    --label "org.opencontainers.image.title=$TITLE" \
    --label "org.opencontainers.image.version=$TAG" \
    --label "org.opencontainers.image.revision=$(git rev-parse HEAD)" \
    --label "org.opencontainers.image.source=https://github.com/highopes/splunk-ao-golden-demo" \
    --label "org.opencontainers.image.created=$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    -t "$IMG" --load .
  log "built in $((SECONDS - started))s; size $(docker image inspect -f '{{.Size}}' "$IMG" | awk '{printf "%.0f MB", $1/1e6}')"
  docker run --rm --entrypoint uv "$IMG" pip check --python /opt/venv/bin/python
}

smoke() {
  local net=sao-golden-smoke-net pg=sao-golden-smoke-pg app=sao-golden-smoke-app vol=sao-golden-smoke-pgdata
  local label="org.opencontainers.image.title=$TITLE" dir pw i
  cleanup() {
    docker rm -f "$app" "$pg" >/dev/null 2>&1 || true
    docker network rm "$net" >/dev/null 2>&1 || true
    docker volume rm "$vol" >/dev/null 2>&1 || true
    rm -rf "${dir:-}" .work/smoke.env
  }
  trap cleanup EXIT
  cleanup
  dir="$(mktemp -d .work/smoke.XXXXXX)"
  pw="$(python3 -c 'import secrets; print(secrets.token_hex(16))')"
  (umask 077; printf 'POSTGRES_PASSWORD=%s\n' "$pw" > .work/smoke.env)
  # Throwaway settings: a resolvable profile, no real credentials.
  cat > "$dir/secrets.toml" <<EOF
backend_profile = "imlab-onprem"
galileo_console_url = "https://console.example.invalid"
galileo_api_key = "smoke-test-placeholder"
agent_control_agent_name = "smoke-test"
agent_control_api_key_header = "Splunk-AO-API-Key"
openai_api_key = "smoke-test-placeholder"
embedding_provider = "hosted"
postgres_host = "$pg"
postgres_port = "5432"
postgres_user = "postgres"
postgres_password = "$pw"
postgres_db = "vectordb"
environment = "smoke"
EOF
  chmod 644 "$dir/secrets.toml"

  docker network create --label "$label" "$net" >/dev/null
  docker volume create --label "$label" "$vol" >/dev/null
  docker run -d --name "$pg" --label "$label" --network "$net" --env-file .work/smoke.env \
    -e POSTGRES_DB=vectordb -v "$vol:/var/lib/postgresql/data" pgvector/pgvector:pg17 >/dev/null
  docker run -d --name "$app" --label "$label" --network "$net" --read-only \
    --tmpfs /tmp --tmpfs /home/app:uid=10001,gid=10001 --tmpfs /data:uid=10001,gid=10001 \
    -v "$PWD/$dir/secrets.toml:/app/.streamlit/secrets.toml:ro" -v "$PWD/tests:/app/tests:ro" \
    "$IMG" >/dev/null

  for i in $(seq 1 60); do docker exec "$pg" pg_isready -U postgres -d vectordb -q && break; sleep 2; done
  for i in $(seq 1 60); do
    docker exec "$app" python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health', timeout=3)" 2>/dev/null && break
    sleep 2
  done
  docker exec -i "$app" python - <<'EOF'
import sys, urllib.request
for path in ("/_stcore/health", "/"):
    status = urllib.request.urlopen("http://127.0.0.1:8501" + path, timeout=5).status
    print(f"PASS  GET {path} -> {status}" if status == 200 else f"FAIL  GET {path} -> {status}")
    if status != 200:
        sys.exit(1)
EOF
  docker exec "$app" test -s /etc/ssl/certs/ca-certificates.crt && log "PASS  system CA bundle present"
  docker exec -w /app "$app" python -m unittest tests.test_runtime tests.test_onprem_k8s 2>&1 | tail -4
  docker exec -i "$app" python - <<'EOF'
from setup_env import setup_environment
setup_environment()
from sqlalchemy import create_engine, text
from helpers.pgvector_utils import get_postgres_connection_string
engine = create_engine(get_postgres_connection_string())
with engine.connect() as conn:
    print("PASS  PostgreSQL", conn.execute(text("SELECT version()")).scalar().split(" on ")[0])
EOF
  log "smoke OK; removing smoke containers, network and volume"
  cleanup
  trap - EXIT
}

scan() {
  log "image contents"
  docker run --rm --entrypoint sh "$IMG" -c '
    ls -la /app /app/.streamlit
    for p in /app/.git /app/.venv /app/.runtime /app/.work /app/data /app/.agent-context /app/tests /app/.streamlit/secrets.toml; do
      [ -e "$p" ] && { echo "FAIL  $p present"; exit 1; }
    done
    ls /app/.streamlit | grep -v -E "^(config\.toml|secrets\.toml\.example)$" && { echo "FAIL  unexpected .streamlit file"; exit 1; }
    echo "PASS  no secrets, VCS or local state in /app"'
  if docker history --no-trunc --format '{{.CreatedBy}}' "$IMG" | grep -iE 'password|token|secret|api[_-]?key' ; then
    die "docker history mentions a credential-like build argument"
  fi
  log "PASS  docker history has no credential-like build arguments"
  local cid tmp
  cid="$(docker create --label "org.opencontainers.image.title=$TITLE" "$IMG")"
  tmp="$(mktemp -d)"
  docker export "$cid" | tar -x -C "$tmp" app
  docker rm "$cid" >/dev/null
  bash scripts/check-public-hygiene.sh --path "$tmp/app" || { rm -rf "$tmp"; die "image /app failed the hygiene check"; }
  rm -rf "$tmp"
}

push() {
  docker image inspect "$IMG" >/dev/null 2>&1 || die "$IMG not built on this host"
  docker push "$IMG"
  log "pushed $(docker image inspect -f '{{index .RepoDigests 0}}' "$IMG")"
}

case "$CMD" in
  build) build ;;
  smoke) smoke ;;
  scan) scan ;;
  push) push ;;
  all) build; smoke; scan ;;
  *) die "unknown command $CMD" ;;
esac
log "done: $CMD $IMG"
