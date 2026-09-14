#!/bin/sh
# Read-only dependency checks. Never source .env or print credentials.
set -u
project_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd) || exit 1
cd "$project_dir" || exit 1
bridge=0
intake=0
for argument in "$@"; do
    case "$argument" in
        --macos) bridge=1 ;;
        --intake) bridge=1; intake=1 ;;
        --help|-h)
            echo 'Usage: ./preflight.sh [--macos] [--intake]'
            echo 'Default: Docker dashboard. --macos: Messages/traffic bridge. --intake: incoming FA access too.'
            exit 0 ;;
        *) echo "Unknown option: $argument" >&2; exit 2 ;;
    esac
done
failures=0
pass() { printf 'PASS  %s\n' "$1"; }
fail() { printf 'FAIL  %s\n' "$1"; failures=$((failures + 1)); }
note() { printf 'NOTE  %s\n' "$1"; }

printf 'Family Agent preflight\n\n'
for file in Dockerfile docker-compose.yml backend/requirements.txt backend/regional_settings.py; do
    if [ ! -r "$file" ]; then fail "Missing package file: $file. Download the complete source package."; fi
done
if [ -d config ]; then
    if [ -w config ]; then pass 'Private configuration directory is writable.'
    else fail 'config/ is not writable. Give your account write access to this directory.'; fi
elif [ -w . ]; then pass 'Project is writable; Docker can create config/.'
else fail 'Project is not writable. Move it into a directory owned by your account.'; fi

if [ -r .env ]; then
    pass '.env exists and is readable.'
    # Detect the shipped placeholder without echoing the value or executing shell content.
    if awk '
        /^[[:space:]]*(export[[:space:]]+)?POSTGRES_PASSWORD[[:space:]]*=/ {
            sub(/^[^=]*=[[:space:]]*/, ""); gsub(/[\047\042]/, "");
            sub(/[[:space:]]+#.*/, ""); gsub(/[[:space:]]+$/, "");
            if ($0 == "replace-with-a-long-random-password") bad=1
        }
        END {exit !bad}' .env; then
        fail 'Replace the example POSTGRES_PASSWORD in .env with a unique password.'
    fi
else
    fail 'Missing .env. Copy .env.example to .env and set your password and regional settings.'
fi

# Read only the provider selector; never evaluate .env as a shell program.
selected_provider=${FAMILY_MESSAGING_PROVIDER:-}
if [ -z "$selected_provider" ] && [ -r .env ]; then
    selected_provider=$(awk -F= '/^[[:space:]]*FAMILY_MESSAGING_PROVIDER[[:space:]]*=/ {value=$2; gsub(/[[:space:]\047\042]/,"",value)} END {print value}' .env)
fi
case "${selected_provider:-imessage}" in
    imessage) ;;
    twilio-sms|twilio-whatsapp|openclaw)
        if [ -r config/messaging.json ]; then
            pass 'Private messaging configuration is readable; startup will validate its fields.'
        else
            fail 'Create config/messaging.json from the matching messaging example before enabling this provider.'
        fi ;;
    *) fail 'Unsupported FAMILY_MESSAGING_PROVIDER. See MESSAGING_SETUP.md.' ;;
esac

if command -v docker >/dev/null 2>&1; then
    pass 'Docker CLI is installed.'
    if docker compose version >/dev/null 2>&1; then
        pass 'Docker Compose v2 is available.'
        if docker compose config --quiet >/dev/null 2>&1; then
            pass 'Compose configuration and required password resolve successfully.'
        else
            fail 'Compose configuration is invalid. Check .env and POSTGRES_PASSWORD; run docker compose config --quiet locally for details.'
        fi
    else
        fail 'Docker Compose v2 is missing. Install Docker Desktop or the Docker Compose plugin.'
    fi
    if docker info >/dev/null 2>&1; then
        pass 'Docker engine is running and accessible.'
        for image in python:3.12-slim postgres:16; do
            if docker image inspect "$image" >/dev/null 2>&1; then pass "$image is cached."
            else note "$image is not cached; the first build will download it."; fi
        done
        for container in family-agent-api family-agent-db; do
            owner=$(docker inspect --format '{{index .Config.Labels "com.docker.compose.project.working_dir"}}' "$container" 2>/dev/null) || owner=''
            if [ -n "$owner" ] && [ "$owner" != "$project_dir" ]; then
                fail "$container belongs to another project directory. Use that installation or resolve the container-name conflict first."
            fi
        done
    else
        fail 'Cannot access Docker engine. Start Docker Desktop/the Docker service and check your Docker permissions.'
    fi
else
    fail 'Docker is missing. Install Docker Desktop (macOS/Windows), or Docker Engine plus Compose (Linux).'
fi
note 'Host Python and PostgreSQL are not required for the dashboard.'
note 'First build needs internet access for Docker images and Python packages; network availability is not verified here.'

if [ "$bridge" -eq 1 ]; then
    if [ "$(uname -s)" != Darwin ]; then
        fail 'The optional iMessage/Apple Maps bridge requires macOS. Run without --macos/--intake for the dashboard only.'
    else
        if command -v python3 >/dev/null 2>&1 && python3 -c 'import sys, sqlite3, ssl, urllib.request; sys.exit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1; then
            pass 'Host Python 3.10+ and required standard-library modules are available.'
            python_ok=1
        else
            fail 'Install host Python 3.10 or newer with SQLite and SSL support for the macOS bridge.'
            python_ok=0
        fi
        for utility in osascript launchctl plutil caffeinate; do
            if command -v "$utility" >/dev/null 2>&1; then pass "$utility is available."
            else fail "Required macOS utility is missing: $utility."; fi
        done
        if command -v xcrun >/dev/null 2>&1 && xcrun --find clang >/dev/null 2>&1 && xcrun --show-sdk-path >/dev/null 2>&1; then
            pass 'Apple compiler and SDK are available for traffic estimates.'
        else
            fail 'Apple command-line developer tools are missing. Run xcode-select --install for the traffic bridge.'
        fi
        note 'Sign in to Messages and allow Messages automation when prompted. This check sends no messages and cannot verify delivery permission.'
        note 'Keep the Mac system time zone aligned with FAMILY_TIMEZONE for wake and intake schedules.'
        if [ "$intake" -eq 1 ] && [ "$python_ok" -eq 1 ]; then
            if python3 - <<'PY'
from pathlib import Path
import sqlite3
import sys
try:
    path = Path.home() / 'Library/Messages/chat.db'
    with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=2) as db:
        # Check accessibility and schema only; do not read personal messages.
        columns = {row[1] for row in db.execute('PRAGMA table_info(message)')}
        if not {'guid', 'text', 'attributedBody', 'handle_id'} <= columns:
            raise ValueError('Unsupported Messages schema')
except Exception:
    sys.exit(1)
PY
            then pass 'Incoming Messages database is readable with the expected schema.'
            else fail 'Incoming Messages database is unavailable. Sign in to Messages and grant Full Disk Access to this Python executable; background access must also be checked after installation.'; fi
        fi
    fi
fi
printf '\n'
if [ "$failures" -gt 0 ]; then
    printf '%s required check(s) failed. Resolve them and rerun preflight.\n' "$failures"
    exit 1
fi
echo 'Required dependency checks passed. Review the notes before starting.'
