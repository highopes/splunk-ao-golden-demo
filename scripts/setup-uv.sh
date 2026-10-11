#!/usr/bin/env bash
# Reproduce the complete, validated macOS arm64 environment without upgrading it.
set -euo pipefail
cd "$(dirname "$0")/.."
command -v uv >/dev/null || { echo "Install uv first: brew install uv" >&2; exit 1; }

if [[ ! -f .venv/pyvenv.cfg ]]; then
  if [[ -e .venv || -L .venv ]]; then
    echo "Refusing to replace an existing non-venv .venv path." >&2
    exit 1
  fi
  uv venv --python 3.12.14 --no-python-downloads .venv
fi

version="$(.venv/bin/python -c 'import sys; print(".".join(map(str, sys.version_info[:3])))')"
if [[ "$version" != "3.12.14" ]]; then
  echo "This snapshot was validated with Python 3.12.14; found $version. Review before changing Python." >&2
  exit 1
fi

# Exact synchronization removes packages absent from this complete snapshot.
uv pip sync --python .venv/bin/python --link-mode hardlink requirements.uv-snapshot.txt
uv pip check --python .venv/bin/python
echo 'Environment ready. Run: PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest discover -s tests -v'
