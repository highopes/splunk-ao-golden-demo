#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [ ! -x .venv/bin/python ]; then
  echo "Create .venv and install requirements.txt using the README first."
  exit 1
fi

# The app starts even without a database, but RAG and SQL then fail per query.
if ! .venv/bin/python scripts/db.py check; then
  if [ -f .runtime/postgres/PG_VERSION ]; then
    echo "Starting this project's native PostgreSQL: scripts/db.py start"
    if ! .venv/bin/python scripts/db.py start || ! .venv/bin/python scripts/db.py check; then
      echo "PostgreSQL is still unreachable; see .runtime/postgres.log and README troubleshooting (section 7)." >&2
      exit 1
    fi
  else
    # Do not initdb here: an empty cluster has no domain data and may shadow a Docker database.
    echo "No initialized native cluster in .runtime/postgres." >&2
    echo "First install: scripts/db.py start, then helpers/setup_vectordb.py <domain> (README 3.2-3.3)." >&2
    echo "Docker: start the Compose database as in README 3.2, then rerun this script." >&2
    exit 1
  fi
fi

exec .venv/bin/python -m streamlit run app.py "$@"
