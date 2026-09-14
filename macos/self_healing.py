#!/usr/bin/env python3
"""Bounded weekly validation and safe recovery for a local Family Agent install."""
from datetime import datetime
import fcntl
import json
import os
from pathlib import Path
try:
    from api_auth import worker_headers
except ModuleNotFoundError:
    from macos.api_auth import worker_headers
import shutil
import subprocess
import time
from types import SimpleNamespace
from urllib.error import URLError
from urllib.request import ProxyHandler, Request, build_opener


PROJECT_DIR = Path(__file__).resolve().parents[1]
CONFIG_DIR = PROJECT_DIR / "config"
STATE_PATH = CONFIG_DIR / "self-healing-state.json"
LOG_PATH = CONFIG_DIR / "self-healing.log"
LOCK_PATH = CONFIG_DIR / "self-healing.lock"
API = "http://127.0.0.1:8000"
LOCAL_OPENER = build_opener(ProxyHandler({}))
def local_headers():
    return {'Content-Type': 'application/json', **worker_headers()}



def weekly_slot(local_now=None):
    local_now = local_now or datetime.now().astimezone()
    if local_now.weekday() != 6 or (local_now.hour, local_now.minute) < (7, 0):
        return None
    iso_year, iso_week, _ = local_now.isocalendar()
    return f"{iso_year}-W{iso_week:02d}"


def read_state():
    try:
        value = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_state(value):
    CONFIG_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = STATE_PATH.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    temporary.chmod(0o600)
    temporary.replace(STATE_PATH)


def docker_path():
    candidates = [
        shutil.which("docker"), "/usr/local/bin/docker", "/opt/homebrew/bin/docker",
        str(Path.home() / ".docker" / "bin" / "docker"),
    ]
    return next((value for value in candidates if value and Path(value).is_file()), None)


def run_command(arguments, timeout=120):
    try:
        return subprocess.run(
            arguments, cwd=PROJECT_DIR, capture_output=True, text=True, timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired):
        return SimpleNamespace(returncode=1, stdout="", stderr="")


def api_json(path, timeout=8):
    with LOCAL_OPENER.open(Request(API + path, headers=local_headers()), timeout=timeout) as response:
        return json.load(response)


def api_is_healthy():
    try:
        return api_json("/health", 5).get("status") == "ok"
    except (OSError, URLError, ValueError, json.JSONDecodeError):
        return False


def wait_for_api(seconds=30):
    for _ in range(seconds // 2):
        if api_is_healthy():
            return True
        time.sleep(2)
    return api_is_healthy()


def repair_private_permissions(actions):
    CONFIG_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    if (CONFIG_DIR.stat().st_mode & 0o777) != 0o700:
        CONFIG_DIR.chmod(0o700)
        actions.append("Repaired private config directory permissions.")
    env_path = PROJECT_DIR / ".env"
    private_files = [path for path in CONFIG_DIR.iterdir() if path.name != ".gitkeep"]
    if env_path.exists():
        private_files.append(env_path)
    repaired = 0
    for path in private_files:
        expected_mode = 0o700 if path.name == "traffic_eta" else 0o600
        if path.is_file() and (path.stat().st_mode & 0o777) != expected_mode:
            path.chmod(expected_mode)
            repaired += 1
    if repaired:
        actions.append(f"Repaired permissions on {repaired} private file(s).")


def validate_integrations(checks, issues):
    try:
        api_json("/health/database")
        checks.append("Database query succeeded.")
    except Exception:
        issues.append("Database validation failed; inspect the API and database containers.")
        return
    try:
        calendar = api_json("/calendar/events?refresh=true", 60)
        failed = [row.get("source", "calendar") for row in calendar.get("sources", []) if row.get("status") == "error"]
        if failed:
            issues.append("Calendar connection needs attention: " + ", ".join(failed) + ".")
        else:
            checks.append("Calendar connections responded.")
    except Exception:
        issues.append("Calendar validation could not complete.")
    try:
        api_json("/weather/forecast", 30)
        checks.append("Weather service responded.")
    except Exception:
        issues.append("Weather validation could not complete.")
    try:
        school = api_json("/commutes/school-calendar?refresh=true", 45)
        if school.get("status") == "disabled":
            checks.append("School calendar filtering is disabled.")
        elif school.get("status") == "ready":
            checks.append("Configured school calendar refreshed.")
        else:
            issues.append("Configured school calendar needs attention.")
    except Exception:
        issues.append("Configured school calendar validation could not complete.")


def run_weekly_validation(local_now=None):
    local_now = local_now or datetime.now().astimezone()
    slot = weekly_slot(local_now)
    actions, checks, issues = [], [], []
    repair_private_permissions(actions)
    docker = docker_path()
    if docker is None:
        issues.append("Docker command was not found.")
    else:
        result = run_command([docker, "compose", "ps", "--status", "running", "--services"])
        running = set(result.stdout.split()) if result.returncode == 0 else set()
        required = {"family-agent-api", "family-agent-db"}
        if not required.issubset(running):
            recovery = run_command([docker, "compose", "up", "-d"])
            if recovery.returncode == 0:
                actions.append("Started stopped Family Agent Docker services.")
            else:
                issues.append("Docker services could not be started automatically.")
        if not wait_for_api():
            recovery = run_command([docker, "compose", "restart", "family-agent-api"])
            if recovery.returncode == 0 and wait_for_api():
                actions.append("Restarted the unresponsive Family Agent API.")
            else:
                issues.append("Family Agent API remains unavailable after recovery.")
        else:
            checks.append("Family Agent API is healthy.")
    if api_is_healthy():
        validate_integrations(checks, issues)
    launch = run_command(["/bin/launchctl", "print", f"gui/{os.getuid()}/com.familyagent.imessage-alerts"], 15)
    if launch.returncode == 0:
        checks.append("iMessage background service is loaded.")
    else:
        issues.append("iMessage background service is not loaded; rerun the installer.")
    status = "attention_needed" if issues else "repaired" if actions else "healthy"
    report = {
        "slot": slot,
        "status": status,
        "checked_at": local_now.isoformat(),
        "checks": checks,
        "actions": actions,
        "issues": issues,
    }
    save_state(report)
    with LOG_PATH.open("a", encoding="utf-8") as log:
        log.write(f"{report['checked_at']} {status}: {len(actions)} action(s), {len(issues)} issue(s)\n")
    LOG_PATH.chmod(0o600)
    return report


def maybe_run_weekly_validation(local_now=None):
    local_now = local_now or datetime.now().astimezone()
    slot = weekly_slot(local_now)
    if slot is None:
        return None
    CONFIG_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    with LOCK_PATH.open("a+", encoding="utf-8") as lock:
        LOCK_PATH.chmod(0o600)
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return None
        if read_state().get("slot") == slot:
            return None
        return run_weekly_validation(local_now)
