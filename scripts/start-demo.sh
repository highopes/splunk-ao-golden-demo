#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [ ! -x .venv/bin/python ]; then
  echo "Create .venv and install requirements.txt using the README first."
  exit 1
fi
exec .venv/bin/python -m streamlit run app.py "$@"
