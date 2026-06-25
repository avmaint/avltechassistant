#!/usr/bin/env bash
# run.sh — local development helpers for avltechassistant
#
# Production operations (start, stop, deploy, sync-images, etc.) are managed
# by runbook/runbook.sh.
#
# Usage: ./run.sh <command>
#
# Commands:
#   install     Create venv and install backend dependencies
#   test        Run the test suite

set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV="$APP_DIR/.venv"

install_deps() {
    echo "Creating virtual environment..."
    python3 -m venv "$VENV"
    echo "Installing dependencies..."
    "$VENV/bin/pip" install -q --upgrade pip
    "$VENV/bin/pip" install -q -r "$APP_DIR/backend/requirements.txt"
    echo "Install complete."
}

run_tests() {
    if [[ ! -x "$VENV/bin/python" ]]; then
        echo "Python venv not found. Run './run.sh install' first." >&2
        exit 1
    fi
    "$VENV/bin/python" "$APP_DIR/tests/run_tests.py"
}

case "${1:-}" in
    install) install_deps ;;
    test)    run_tests ;;
    *)
        echo "Usage: ./run.sh [install|test]"
        echo ""
        echo "  install   Create venv and install backend dependencies"
        echo "  test      Run the test suite"
        echo ""
        echo "Production operations are managed by runbook/runbook.sh."
        exit 1
        ;;
esac
