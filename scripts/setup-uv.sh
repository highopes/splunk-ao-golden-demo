#!/usr/bin/env bash
# Reproduce the complete, validated macOS arm64 environment without upgrading it.
# The real venv lives outside OneDrive; the project's .venv is only a symlink to it,
# because OneDrive rejects venv files such as ".lock" and should not sync ~1 GB of packages.
set -euo pipefail
cd "$(dirname "$0")/.."
command -v uv >/dev/null || { echo "Install uv first: brew install uv" >&2; exit 1; }

if [[ -L .venv ]]; then
  venv_dir="$(readlink .venv)"
elif [[ -e .venv ]]; then
  echo "A real .venv directory exists in the project; move it out of OneDrive first (see README)." >&2
  exit 1
else
  venv_dir="${SPLUNK_AO_VENV_DIR:-$HOME/.venvs/splunk-ao-golden-demo}"
  ln -s "$venv_dir" .venv
fi

if [[ ! -f "$venv_dir/pyvenv.cfg" ]]; then
  if [[ -e "$venv_dir" ]]; then
    echo "Refusing to replace an existing non-venv path: $venv_dir" >&2
    exit 1
  fi
  mkdir -p "$(dirname "$venv_dir")"
  uv venv --python 3.12.14 --no-python-downloads "$venv_dir"
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
