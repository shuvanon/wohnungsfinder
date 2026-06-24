#!/usr/bin/env bash
#
# run-tests.sh — Run the full test suite.
#
# Usage:
#   ./run-tests.sh            # run everything
#   ./run-tests.sh -v         # extra args are passed through (e.g. verbose)
#   ./run-tests.sh tests/test_llm.py   # or target a single file (pytest)
#
# Safe to run anytime, including on the deployment server: every test mocks
# HTTP and uses in-memory SQLite, so it never touches settings.json, the live
# database, or sends Telegram messages.

set -euo pipefail

# Always run from the project root (this script's directory).
cd "$(dirname "$0")"

# Activate a local virtualenv if one exists (setup.sh creates ./venv).
if [ -f venv/bin/activate ]; then
    # shellcheck disable=SC1091
    source venv/bin/activate
fi

PYTHON="${PYTHON:-python3}"

# Prefer pytest if available; fall back to stdlib unittest (no extra deps).
if "$PYTHON" -c "import pytest" >/dev/null 2>&1; then
    exec "$PYTHON" -m pytest tests/ "$@"
else
    echo "pytest not found — using unittest. (pip install pytest for nicer output.)"
    exec "$PYTHON" -m unittest discover -s tests "$@"
fi
