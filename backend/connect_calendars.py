"""Run interactively in Docker; never paste account secrets into chat."""
import argparse
import getpass
import json
import sys

import caldav
from google.auth.transport.requests import AuthorizedSession
from google_auth_oauthlib.flow import InstalledAppFlow

from calendar_service import CONFIG, SCOPES, save_config, icloud_client


def choose(calendars):
    if not calendars:
        raise ValueError("No calendars found")
    for i, calendar in enumerate(calendars, 1):
        print(f'{i}. {calendar["name"]}')
    while True:
        raw = input("Choose calendars by number, separated by commas: ").strip()
        try:
            indices = sorted(set(int(value.strip()) - 1 for value in raw.split(",")))
            if not indices or any(i < 0 or i >= len(calendars) for i in indices):
                raise ValueError()
            return [calendars[i] for i in indices]
        except ValueError:
            print("Enter numbers from the list above.")


def google():
    path = CONFIG / "google-client.json"
    if not path.exists():
        print("First save your Google Desktop OAuth client JSON as config/google-client.json.")
        return 1
    flow = InstalledAppFlow.from_client_secrets_file(str(path), SCOPES, autogenerate_code_verifier=True)
    credentials = flow.run_local_server(host="127.0.0.1", bind_addr="0.0.0.0", port=8765,
                                       open_browser=False, timeout_seconds=300, prompt="consent")
    calendars, page = [], None
    with AuthorizedSession(credentials) as session:
        while True:
            response = session.get("https://www.googleapis.com/calendar/v3/users/me/calendarList",
                                   params={"maxResults": 250, **({"pageToken": page} if page else {})}, timeout=20)
            response.raise_for_status()
            data = response.json()
            calendars.extend({"id": c["id"], "name": c.get("summary", "Calendar")} for c in data.get("items", []) if not c.get("deleted"))
            page = data.get("nextPageToken")
            if not page:
                break
    selected = choose(calendars)
    save_config("google-token.json", json.loads(credentials.to_json()))
    save_config("google-calendars.json", selected)
    print("Google connected. Refresh the calendar in Family Agent.")
    return 0


def validate_icloud_input(username, password=None):
    if username.count("@") != 1 or any(c.isspace() or c in "\\/" for c in username):
        raise ValueError("Enter your Apple Account email without backslashes or spaces (use @, not \\@).")
    if not all(username.split("@")):
        raise ValueError("Enter your full Apple Account email address.")
    if password is not None and (not password or any(c.isspace() for c in password)):
        raise ValueError("Paste the app-specific password exactly as Apple displayed it, without spaces.")


def connection_error(exc, stage):
    # Never print exception messages, response bodies, URLs, or credential values.
    from caldav.lib.error import AuthorizationError, RateLimitError
    if isinstance(exc, AuthorizationError):
        reason = "Apple rejected sign-in. Check the Apple Account email and its app-specific password."
    elif isinstance(exc, RateLimitError):
        reason = "Apple is limiting requests. Wait a few minutes before trying again."
    elif isinstance(exc, PermissionError):
        reason = "The local connection settings could not be saved. Ask me to check config folder permissions."
    elif type(exc).__name__ in {"Timeout", "ReadTimeout", "ConnectTimeout", "ConnectionError", "ConnectTimeoutError", "ReadTimeoutError"}:
        reason = "The connection timed out or could not reach Apple. Check your network and try again."
    elif type(exc).__name__ == "SSLError":
        reason = "The secure connection to Apple could not be verified. Do not disable certificate checks."
    else:
        reason = "The calendar service returned an unexpected response. Share this diagnostic line for troubleshooting."
    print(f"Connection failed during {stage}. {reason}")
    print(f"Diagnostic: {type(exc).__name__}. No credentials are included.")


def icloud():
    username = input("Apple Account email: ").strip()
    try:
        validate_icloud_input(username)
    except ValueError as exc:
        print(str(exc))  # Only our fixed validation messages, never user input.
        return 1
    password = getpass.getpass("Apple app-specific password (hidden): ").strip()
    try:
        validate_icloud_input(username, password)
    except ValueError as exc:
        print(str(exc))
        return 1
    stage = "Apple sign-in"
    try:
        print("Signing in to iCloud…", flush=True)
        with icloud_client(username, password) as client:
            principal = client.principal()
            stage = "calendar discovery"
            print("Finding calendars…", flush=True)
            calendars = [
                {"id": str(calendar.url), "name": str(calendar.get_display_name() or "Calendar")}
                for calendar in principal.calendars()
            ]
            if not calendars:
                print("Sign-in succeeded, but no iCloud calendars were found. Check that you have calendars under iCloud in Apple Calendar.")
                return 1
            stage = "calendar selection"
            selected = choose(calendars)
        stage = "saving the connection on your Mac"
        save_config("icloud.json", {"username": username, "password": password, "calendars": selected})
    except (EOFError, KeyboardInterrupt):
        print("Setup cancelled before the connection was saved.")
        return 1
    except Exception as exc:
        connection_error(exc, stage)
        return 1
    print("iCloud connected. Refresh the calendar in Family Agent.")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("source", choices=["google", "icloud"])
    args = parser.parse_args()
    try:
        sys.exit(google() if args.source == "google" else icloud())
    except Exception:
        print("Connection failed. Check your account setup, credentials, and network, then try again. No credentials will be printed.")
        sys.exit(1)
