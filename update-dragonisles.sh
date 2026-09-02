#!/usr/bin/env bash

dragonisles_self_update() {
    if [ -n "${DRAGONISLES_NO_UPDATE:-}" ] ||
        [ -n "${DRAGONISLES_UPDATED+x}" ]; then
        return 0
    fi
    command -v git >/dev/null 2>&1 || return 0

    local launch_root repo_root remote branch status old_head new_head
    launch_root="$(pwd -P)"
    repo_root="$(git rev-parse --show-toplevel 2>/dev/null)" || {
        echo "Skipping the update check: this folder is not a Git checkout."
        return 0
    }
    if [ "$repo_root" != "$launch_root" ]; then
        echo "Skipping the update check: launch from the repository folder."
        return 0
    fi
    if ! git remote get-url origin >/dev/null 2>&1; then
        echo "Skipping the update check: no GitHub origin is configured."
        return 0
    fi
    branch="$(git symbolic-ref --short -q HEAD 2>/dev/null)" || return 0
    if [ "$branch" != "main" ]; then
        echo "Skipping the update check: checkout is on '$branch', not 'main'."
        return 0
    fi
    status="$(git status --porcelain 2>/dev/null)" || return 0
    if [ -n "$status" ]; then
        echo "Skipping the update check: you have local changes."
        return 0
    fi

    echo "Checking for updates..."
    export GIT_TERMINAL_PROMPT=0
    export GIT_SSH_COMMAND='ssh -oBatchMode=yes'
    local fetch_pid fetch_status=""
    git fetch origin main >/dev/null 2>&1 &
    fetch_pid=$!
    for _ in $(seq 1 100); do
        if ! kill -0 "$fetch_pid" 2>/dev/null; then
            if wait "$fetch_pid"; then
                fetch_status=0
            else
                fetch_status=$?
            fi
            break
        fi
        sleep 0.2
    done
    if [ -z "$fetch_status" ]; then
        kill "$fetch_pid" 2>/dev/null || true
        wait "$fetch_pid" 2>/dev/null || true
        fetch_status=124
    fi
    if [ "$fetch_status" -ne 0 ]; then
        echo "Could not check for updates; starting the game you have."
        return 0
    fi

    old_head="$(git rev-parse HEAD)" || return 0
    if ! git merge --ff-only origin/main >/dev/null 2>&1; then
        echo "Could not check for updates; starting the game you have."
        return 0
    fi
    new_head="$(git rev-parse HEAD)" || return 0
    if [ "$old_head" = "$new_head" ]; then
        return 0
    fi

    echo "Updated to the latest version."
    if git diff --name-only "$old_head" "$new_head" | grep -Fxq "pyproject.toml" &&
        [ -x ".venv/bin/python" ]; then
        if ! .venv/bin/python -m pip install -e '.[dev]'; then
            pause_and_exit "Could not install the updated DragonIsles dependencies."
        fi
    fi
    export DRAGONISLES_UPDATED=1
    DRAGONISLES_REEXEC=1
}
