#!/usr/bin/env bash

cd "$(dirname "$0")" || exit 1

pause_and_exit() {
    echo "$1"
    read -n 1 -r -p "Press any key to close this window..."
    echo
    exit 1
}

if ! command -v python3 >/dev/null 2>&1; then
    pause_and_exit "Python 3 is required to play DragonIsles, but it was not found."
fi

if [ ! -d ".venv" ]; then
    echo "First-time setup, this takes a minute..."
    if ! python3 -m venv .venv; then
        pause_and_exit "Could not create the DragonIsles virtual environment."
    fi
    if ! .venv/bin/python -m pip install -e '.[dev]'; then
        pause_and_exit "Could not install the DragonIsles dependencies."
    fi
fi

(sleep 2 && open http://127.0.0.1:8190) &
echo "Close this window or press Ctrl+C to stop the game."
.venv/bin/python -m dragonisles.web --port 8190
