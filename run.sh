#!/usr/bin/env bash
set -euo pipefail

CMD=${1:-start}

APP_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV="$APP_DIR/.venv"
PID_FILE_FRONT="$APP_DIR/.frontend.pid"
PID_FILE_BACK="$APP_DIR/.backend.pid"
LOG_FILE_FRONT="$APP_DIR/frontend.log"
LOG_FILE_BACK="$APP_DIR/backend.log"

FRONTEND_PORT=8080
BACKEND_PORT=9000

install_deps() {
    echo "Creating virtual environment..."
    python3 -m venv "$VENV"
    echo "Installing dependencies..."
    "$VENV/bin/pip" install -q --upgrade pip
    "$VENV/bin/pip" install -q -r "$APP_DIR/backend/requirements.txt"
    echo "Install complete."
}

deploy() {
    if [ ! -d "$VENV" ]; then
        echo "Virtual environment not found — run './run.sh install' first."
        exit 1
    fi
    echo "Pulling latest from repo..."
    cd "$APP_DIR"
    git pull
    echo "Updating dependencies..."
    "$VENV/bin/pip" install -q -r backend/requirements.txt
    echo "Deploy complete. Run './run.sh restart' to apply changes."
}

stop_services() {
    echo "Stopping services..."

    if [ -f "$PID_FILE_FRONT" ]; then
        PID=$(cat "$PID_FILE_FRONT")
        if kill -0 "$PID" 2>/dev/null; then
            kill "$PID" && echo "Frontend stopped (PID $PID)."
        fi
        rm -f "$PID_FILE_FRONT"
    else
        if lsof -ti:$FRONTEND_PORT >/dev/null 2>&1; then
            lsof -ti:$FRONTEND_PORT | xargs kill -9 2>/dev/null || true
            echo "Frontend stopped (port $FRONTEND_PORT)."
        fi
    fi

    if [ -f "$PID_FILE_BACK" ]; then
        PID=$(cat "$PID_FILE_BACK")
        if kill -0 "$PID" 2>/dev/null; then
            kill "$PID" && echo "Backend stopped (PID $PID)."
        fi
        rm -f "$PID_FILE_BACK"
    else
        if lsof -ti:$BACKEND_PORT >/dev/null 2>&1; then
            lsof -ti:$BACKEND_PORT | xargs kill -9 2>/dev/null || true
            echo "Backend stopped (port $BACKEND_PORT)."
        fi
    fi

    echo "Services stopped."
}

start_services() {
    echo "Starting frontend on port $FRONTEND_PORT..."
    cd "$APP_DIR/frontend"
    python3 -m http.server $FRONTEND_PORT < /dev/null >> "$LOG_FILE_FRONT" 2>&1 &
    echo $! > "$PID_FILE_FRONT"
    disown $!
    echo "Frontend started (PID $(cat "$PID_FILE_FRONT"))."

    echo "Starting backend on port $BACKEND_PORT..."
    cd "$APP_DIR/backend"
    "$VENV/bin/uvicorn" main:app --host 0.0.0.0 --port $BACKEND_PORT < /dev/null >> "$LOG_FILE_BACK" 2>&1 &
    echo $! > "$PID_FILE_BACK"
    disown $!
    echo "Backend started (PID $(cat "$PID_FILE_BACK"))."

    echo "Services running. Frontend: http://0.0.0.0:$FRONTEND_PORT  Backend: http://0.0.0.0:$BACKEND_PORT"
}

run_tests() {
    if [ ! -x "$VENV/bin/python" ]; then
        echo "Python venv not found. Run './run.sh install' first." >&2
        exit 1
    fi
    "$VENV/bin/python" "$APP_DIR/tests/run_tests.py"
}

case "$CMD" in
    install)
        install_deps
        ;;
    deploy)
        deploy
        ;;
    start)
        start_services
        ;;
    stop)
        stop_services
        ;;
    restart)
        stop_services
        sleep 1
        start_services
        ;;
    test)
        run_tests
        ;;
    *)
        echo "Usage: ./run.sh [install|deploy|start|stop|restart|test]" >&2
        exit 1
        ;;
esac
