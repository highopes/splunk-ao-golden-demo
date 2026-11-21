#!/usr/bin/env bash
# Public repository hygiene check. Run before every push (the repository is public),
# and on exported image file systems before an image is pushed.
#
#   bash scripts/check-public-hygiene.sh             # files Git would publish
#                                                     # (tracked + untracked, not ignored)
#   bash scripts/check-public-hygiene.sh --path DIR   # every file under DIR
#
# Fails on generic patterns (private IPv4 addresses, private keys, API key /
# token formats, htpasswd hashes, JWTs) and on environment-specific terms that
# are read at run time from LOCAL, Git-ignored sources only:
#   - .streamlit/secrets.toml and .streamlit/secrets.toml.<backend>: every secret
#     value (keys containing key/password/token/secret), the non-generic host
#     names of every URL, and [k8s] app_host / basic_auth_user / postgres_node;
#   - .work/hygiene-terms.txt: one extra term per line (e.g. jump host, public IP).
# Terms and matches are never printed; a finding shows rule, file and line only.
# A line containing "hygiene: allow" is exempt from the generic patterns (not from local terms).
set -euo pipefail
cd "$(dirname "$0")/.."
PY=python3
[[ -x .venv/bin/python ]] && PY=.venv/bin/python
exec "$PY" - "$@" <<'PYEOF'
import os, re, subprocess, sys
from pathlib import Path

try:
    import tomllib
except ImportError:  # Python < 3.11: simple key = "value" parsing below
    tomllib = None

GENERIC = {
    "private IPv4 address": r"\b(?:10(?:\.\d{1,3}){3}|172\.(?:1[6-9]|2\d|3[01])(?:\.\d{1,3}){2}|192\.168(?:\.\d{1,3}){2})\b",
    "private key": r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |ENCRYPTED )?PRIVATE KEY-----",
    "OpenAI-style key": r"\bsk-(?:proj-|svcacct-|admin-)?[A-Za-z0-9_-]{20,}",
    "AWS access key": r"\bAKIA[0-9A-Z]{16}\b",
    "GitHub token": r"\bgh[pousr]_[A-Za-z0-9]{30,}",
    "Docker Hub token": r"\bdckr_pat_[A-Za-z0-9_-]{20,}",
    "htpasswd hash": r"\$apr1\$[./0-9A-Za-z]{1,8}\$",
    "JWT": r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.",
}
GENERIC = {name: re.compile(rx) for name, rx in GENERIC.items()}
GENERIC_HOST_SUFFIXES = (
    ".svc.cluster.local", "galileocloud.io", "openai.com", "galileo.ai", "splunk.com",
    "amazonaws.com", "example", "example.com", "example.test", "invalid",
)
SECRET_KEY_RX = re.compile(r"(key|password|token|secret)", re.I)
PLACEHOLDER_RX = re.compile(r"^(YOUR_|<|\.\.\.$|sk-\.\.\.)|FILL IN", re.I)


def load_toml(path):
    text = path.read_text(encoding="utf-8", errors="ignore")
    if tomllib:
        try:
            return tomllib.loads(text)
        except Exception:
            pass
    data, current = {}, None
    for line in text.splitlines():
        m = re.match(r"^\s*\[([^\]]+)\]\s*$", line)
        if m:
            current = data.setdefault(m.group(1).strip(), {})
            continue
        m = re.match(r'^\s*([A-Za-z0-9_]+)\s*=\s*"(.*)"\s*(#.*)?$', line)
        if m:
            (current if current is not None else data)[m.group(1)] = m.group(2)
    return data


def hosts_in(value):
    for m in re.finditer(r"[a-z][a-z0-9+.-]*://([^/:\s\"']+)", value, re.I):
        yield m.group(1).lower()


def local_terms():
    terms = set()
    sources = [p for p in Path(".streamlit").glob("secrets.toml*") if p.name != "secrets.toml.example"]
    for path in sources:
        data = load_toml(path)

        def walk(mapping, table=""):
            for key, value in mapping.items():
                if isinstance(value, dict):
                    walk(value, key)
                    continue
                text = str(value).strip()
                if not text or PLACEHOLDER_RX.search(text):
                    continue
                if SECRET_KEY_RX.search(key) and not key.endswith("_header") and len(text) >= 8:
                    terms.add(text)
                for host in hosts_in(text):
                    if host.endswith(GENERIC_HOST_SUFFIXES) or "." not in host or host == "localhost":
                        continue
                    parts = host.split(".")
                    terms.add(".".join(parts[1:]) if len(parts) > 2 else host)
                    if len(parts) >= 2 and len(parts[-2]) >= 4:
                        terms.add(parts[-2])
                if table == "k8s" and key in ("app_host", "basic_auth_user", "postgres_node"):
                    terms.add(text)
        walk(data)
    extra = Path(".work/hygiene-terms.txt")
    if extra.is_file():
        for line in extra.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                terms.add(line)
    return sorted((t for t in terms if len(t) >= 4), key=len, reverse=True), len(sources)


def candidate_files(argv):
    if argv[:1] == ["--path"]:
        root = Path(argv[1])
        return [p for p in root.rglob("*") if p.is_file() and not p.is_symlink()], str(root)
    out = subprocess.run(["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
                         check=True, capture_output=True).stdout.decode()
    return [Path(p) for p in out.split("\0") if p and Path(p).is_file()], "git publishable files"


def main(argv):
    terms, sources = local_terms()
    folded_terms = [t.casefold() for t in terms]
    files, scope = candidate_files(argv)
    findings = 0
    for path in files:
        if path.stat().st_size > 5_000_000:
            continue
        raw = path.read_bytes()
        name = str(path).casefold()
        for term in folded_terms:
            if term in name:
                print(f"FAIL  local term in file name: {path}")
                findings += 1
                break
        if b"\0" in raw[:8192]:
            continue
        for number, line in enumerate(raw.decode("utf-8", errors="ignore").splitlines(), 1):
            folded = line.casefold()
            if any(term in folded for term in folded_terms):
                print(f"FAIL  local environment term or secret value: {path}:{number}")
                findings += 1
            if "hygiene: allow" in line:
                continue
            for rule, rx in GENERIC.items():
                if rx.search(line):
                    print(f"FAIL  {rule}: {path}:{number}")
                    findings += 1
    summary = f"{len(files)} files ({scope}), {len(terms)} local terms from {sources} secrets file(s)"
    if findings:
        print(f"HYGIENE FAILED: {findings} finding(s); {summary}")
        return 1
    print(f"HYGIENE PASS: {summary}")
    if not terms:
        print("WARNING: no local terms loaded; only generic patterns were checked")
    return 0


sys.exit(main(sys.argv[1:]))
PYEOF
