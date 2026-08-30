#!/usr/bin/env bash

cd "$(dirname "$0")" || exit 1

if [ -f ./update-dragonisles.sh ]; then
    # shellcheck source=update-dragonisles.sh
    . ./update-dragonisles.sh
fi

pause_and_exit() {
    echo "$1"
    read -n 1 -r -p "Press any key to close this window..."
    echo
    exit 1
}

if command -v dragonisles_self_update >/dev/null 2>&1; then
    dragonisles_self_update
fi
if [ "${DRAGONISLES_REEXEC:-}" = 1 ]; then
    exec "$0" "$@"
fi

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

TOOLS_DIR=".tools"
CLOUDFLARED=""
if command -v cloudflared >/dev/null 2>&1; then
    CLOUDFLARED="$(command -v cloudflared)"
else
    if command -v brew >/dev/null 2>&1; then
        echo "cloudflared was not found; installing it with Homebrew..."
        if ! brew install cloudflared; then
            pause_and_exit "Could not install cloudflared with Homebrew."
        fi
        CLOUDFLARED="$(command -v cloudflared || true)"
    else
        case "$(uname -s):$(uname -m)" in
            Darwin:arm64)
                CLOUDFLARED_ASSET="cloudflared-darwin-arm64.tgz"
                CLOUDFLARED_IS_ARCHIVE=1
                ;;
            Darwin:x86_64)
                CLOUDFLARED_ASSET="cloudflared-darwin-amd64.tgz"
                CLOUDFLARED_IS_ARCHIVE=1
                ;;
            Linux:x86_64)
                CLOUDFLARED_ASSET="cloudflared-linux-amd64"
                CLOUDFLARED_IS_ARCHIVE=0
                ;;
            Linux:aarch64|Linux:arm64)
                CLOUDFLARED_ASSET="cloudflared-linux-arm64"
                CLOUDFLARED_IS_ARCHIVE=0
                ;;
            *)
                pause_and_exit "No cloudflared download is available for this computer."
                ;;
        esac
        if ! command -v curl >/dev/null 2>&1; then
            pause_and_exit "curl is required to install cloudflared."
        fi
        if [ "$CLOUDFLARED_IS_ARCHIVE" = 1 ] &&
            ! command -v tar >/dev/null 2>&1; then
            pause_and_exit "tar is required to install cloudflared on macOS."
        fi
        mkdir -p "$TOOLS_DIR" || pause_and_exit "Could not create the .tools directory."
        CLOUDFLARED="$TOOLS_DIR/cloudflared"
        if [ ! -x "$CLOUDFLARED" ]; then
            echo "Downloading cloudflared..."
            if [ "$CLOUDFLARED_IS_ARCHIVE" = 1 ]; then
                archive="$TOOLS_DIR/$CLOUDFLARED_ASSET"
                if ! curl -fsSL \
                    "https://github.com/cloudflare/cloudflared/releases/latest/download/$CLOUDFLARED_ASSET" \
                    -o "$archive"; then
                    pause_and_exit "Could not download cloudflared."
                fi
                if ! tar -xzf "$archive" -C "$TOOLS_DIR"; then
                    pause_and_exit "Could not unpack cloudflared."
                fi
            elif ! curl -fsSL \
                "https://github.com/cloudflare/cloudflared/releases/latest/download/$CLOUDFLARED_ASSET" \
                -o "$CLOUDFLARED"; then
                pause_and_exit "Could not download cloudflared."
            fi
            chmod +x "$CLOUDFLARED" || pause_and_exit "Could not make cloudflared executable."
        fi
    fi
fi

if [ -z "$CLOUDFLARED" ] || ! "$CLOUDFLARED" --version >/dev/null 2>&1; then
    pause_and_exit "cloudflared is unavailable or could not run."
fi

SERVER_PID=""
TUNNEL_PID=""
cleanup() {
    if [ -n "$TUNNEL_PID" ]; then
        kill "$TUNNEL_PID" 2>/dev/null || true
        wait "$TUNNEL_PID" 2>/dev/null || true
    fi
    if [ -n "$SERVER_PID" ]; then
        kill "$SERVER_PID" 2>/dev/null || true
        wait "$SERVER_PID" 2>/dev/null || true
    fi
}
trap cleanup EXIT
trap 'exit 130' INT TERM

mkdir -p "$TOOLS_DIR" || pause_and_exit "Could not create the .tools directory."
SERVER_LOG="$TOOLS_DIR/dragonisles-web.log"
TUNNEL_LOG="$TOOLS_DIR/cloudflared.log"
PASSPHRASE="$(
    .venv/bin/python -c 'import secrets; print(secrets.token_urlsafe(24))'
)" || pause_and_exit "Could not generate a game passphrase."
if [ -z "$PASSPHRASE" ]; then
    pause_and_exit "Could not generate a game passphrase."
fi

echo "Starting the DragonIsles server..."
DRAGONISLES_PASSPHRASE="$PASSPHRASE" \
    .venv/bin/python -m dragonisles.web \
    --mode versus \
    --port 8190 \
    --secure-cookie \
    --state-file "$HOME/dragonisles-save.dat" \
    >"$SERVER_LOG" 2>&1 &
SERVER_PID=$!

server_ready=""
for _ in $(seq 1 100); do
    if curl -fsS -o /dev/null http://127.0.0.1:8190/ 2>/dev/null; then
        server_ready=1
        break
    fi
    if ! kill -0 "$SERVER_PID" 2>/dev/null; then
        pause_and_exit "The DragonIsles server stopped before it was ready."
    fi
    sleep 0.2
done
if [ -z "$server_ready" ]; then
    pause_and_exit "The DragonIsles server did not become ready in time."
fi

echo "Starting the Cloudflare quick tunnel..."
: >"$TUNNEL_LOG" || pause_and_exit "Could not create the cloudflared log."
"$CLOUDFLARED" tunnel --url http://127.0.0.1:8190 --no-autoupdate \
    > >(tee "$TUNNEL_LOG") 2>&1 &
TUNNEL_PID=$!

TUNNEL_URL=""
for _ in $(seq 1 150); do
    TUNNEL_URL="$(
        grep -Eo 'https://[A-Za-z0-9.-]+\.trycloudflare\.com' "$TUNNEL_LOG" |
            head -n 1 || true
    )"
    if [ -n "$TUNNEL_URL" ]; then
        break
    fi
    if ! kill -0 "$TUNNEL_PID" 2>/dev/null; then
        pause_and_exit "cloudflared stopped before it provided a tunnel URL."
    fi
    sleep 0.2
done
if [ -z "$TUNNEL_URL" ]; then
    pause_and_exit "cloudflared did not provide a tunnel URL within 30 seconds."
fi

printf '\n========================================\n'
printf 'DragonIsles friend game is ready\n'
printf 'Link: %s\n' "$TUNNEL_URL"
printf 'Passphrase: %s\n' "$PASSPHRASE"
printf 'Send both the link and passphrase to your friend.\n'
printf '========================================\n\n'

case "$(uname -s)" in
    Darwin)
        if ! command -v open >/dev/null 2>&1; then
            pause_and_exit "The macOS open command was not found."
        fi
        open "$TUNNEL_URL" || pause_and_exit "Could not open the tunnel URL."
        ;;
    Linux)
        if ! command -v xdg-open >/dev/null 2>&1; then
            pause_and_exit "The Linux xdg-open command was not found."
        fi
        xdg-open "$TUNNEL_URL" >/dev/null 2>&1 &
        ;;
    *)
        pause_and_exit "This computer's browser launcher is not supported."
        ;;
esac

echo "Close this window or press Ctrl+C to stop the game."
wait "$TUNNEL_PID"
