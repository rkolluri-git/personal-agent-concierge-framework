# Personal Agent / Concierge Framework

A self-hosted Python framework for personal and household tasks, calendar views,
reviewed concierge requests, reminders, departure planning, and event discovery.
FastAPI and PostgreSQL run in Docker; optional integrations are configured privately.

This standardized publication includes the current implementation and its
administrator authentication fixes. It contains source and synthetic examples,
not an installed household's configuration, database, credentials, or message history.

## Quick start

Install Git and Docker Desktop with Compose v2. Docker supplies Python 3.12 and
PostgreSQL 16; separate host installations are unnecessary for the core application.

```sh
git clone https://github.com/rkolluri-git/personal-agent-concierge-framework.git
cd personal-agent-concierge-framework
cp .env.example .env
```

Edit `.env`: choose a unique database password and set your country, locale,
timezone, and units. Then run:

```sh
./preflight.sh
./start.sh
```

Open `http://localhost:8000/dashboard`. Retrieve the installation login key locally:

```sh
docker compose exec -T family-agent-api python auth_service.py --show-key
```

Do not share that key. See [PRIVACY.md](PRIVACY.md) for authentication and backups.

On Windows, copy `.env.example` to `.env`, edit it, then run in PowerShell:

```powershell
.\windows\preflight.ps1
.\windows\start.ps1
```

The preflight reports missing dependencies; it does not silently install system
software. Optional native macOS workers require host Python and relevant macOS
permissions. See [FRAMEWORK.md](FRAMEWORK.md) and [MESSAGING_SETUP.md](MESSAGING_SETUP.md).

## Capabilities

| Capability | Included behavior |
| --- | --- |
| Tasks | Assignments, due dates, reminders, weekly recurrence |
| Calendars | Google/iCloud views, assignments, conflict checks; explicit iCloud writes and local archives |
| Concierge | Unified workspace, schedule queries, task/calendar drafts, multiple activities, follow-ups and review |
| Interpretation | Local rules by default; optional local Ollama interpretation |
| Messaging | macOS iMessage; optional Twilio SMS/WhatsApp or OpenClaw bridge |
| Briefings | Activities, tasks, weather, configurable recipients and recovery ledger |
| Departures | Home/return planning, recurring commutes, one-time and appointment-driven traffic checks |
| Events | Configurable concert sources, shortlists, artist/genre/budget/age preferences |
| Operations | Preflight, health checks, scoped workers, bounded local recovery |

See [CAPABILITIES.md](CAPABILITIES.md) for the module/skill list and platform limits.
DeepSeek Harness is not integrated in this release.

## Regional and optional configuration

Set `FAMILY_LOCALE`, `FAMILY_COUNTRY`, `FAMILY_TIMEZONE`, and `FAMILY_UNITS` in `.env`.
For example, use `en-IN`, `IN`, `Asia/Kolkata`, and `metric`. The interface and
rule-based conversation parser are currently English; numeric slash dates in
concierge requests use month/day order. Prefer ISO dates (`YYYY-MM-DD`) to avoid
ambiguity. Locale settings do not translate the interface or parser.

School calendars default to `none`. Choose `custom` with a private calendar file,
or explicitly select the legacy Cobb County adapter if it applies to your installation.

Concert discovery starts with no venue sources. Copy `examples/event-sources.json`
to `config/event-sources.json`, set a three-letter currency, and add named HTTPS
venue URLs under `sources`. Restart the API after changes. Supported pages must
publish compatible MusicEvent structured data; arbitrary sites are not guaranteed.
Budget matching uses the configured currency without currency conversion. Event
coverage extends through the current calendar year. Verify listings at the venue.

Set `FAMILY_LLM_PROVIDER=none` for local rules or `ollama` for a downloaded local
model. The current implementation accepts only local HTTP Ollama endpoints,
disables proxies and redirects, and rejects cloud-named models. Hosted provider
interpretation is not included in this baseline. Requests, member names and selected
draft context reach the configured local model; its logs require local protection.
Optional Google Places sends address queries to Google. Both features are disabled
by default. Interpretation produces validated drafts and does not directly book activities.

## Messaging and review

Saved, enabled contacts can submit `FA` requests through the supported intake.
The iMessage worker can queue acknowledgments and follow-up questions. Drafts remain subject to review. Explicit iCloud save actions can create events
from reviewed requests or create/update supported appointments. Conditional writes
and readback checks detect conflicting or mismatched saves; Google access remains
read-only. Editing existing recurring, invited or all-day events is restricted;
use Apple Calendar for unsupported changes. The local archive retains eligible
ended events for up to 90 days and does not delete provider events.

Initial iMessage requests default to twice-daily ingestion; explicit dialog replies
are checked on worker runs. Private `config/imessage-ingest.json` can select
`scheduled`, `hourly`, or `testing` mode. All modes require the relevant macOS
permissions. See [MESSAGING_SETUP.md](MESSAGING_SETUP.md) for dedicated numbers,
Windows/OpenClaw setup, provider consent and transport limits.

## Appointment traffic and wake support

Appointment checks reconcile fresh calendar results, track selected recipients,
and queue departure advice through the Mac worker. Missing contacts, stale or
incomplete calendars, cancelled events and failed ETA lookup have explicit states.
Install `install-appointment-wake.command` only on a Mac where you want automatic
wake scheduling. It installs a root-owned helper and a copy of the scoped worker
key; it does not receive an administrator key. Reinstall after worker-key rotation.
Actual wake and delivery depend on power, sleep/lid state, an available desktop
session and running Docker. Publication does not install or activate the helper.

## Development and validation

```sh
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements.txt pytest httpx
PYTHONPATH=backend:macos .venv/bin/python -m pytest -q
node --check backend/static/dashboard.js
node --check backend/static/concierge-workspace.js
node tests/test_openclaw_hook.mjs
```

Tests use synthetic data and mock external transports. See [VALIDATION.md](VALIDATION.md)
for results and limitations, [CONTRIBUTING.md](CONTRIBUTING.md) for changes, and
[LESSONS_LEARNED.md](LESSONS_LEARNED.md) for implementation lessons.

## Package layout

- `backend/`: API, workflows, persistence, integrations, dashboard.
- `macos/`: native message/traffic workers and recovery checks.
- `windows/`: PowerShell preflight and startup helpers.
- `integrations/openclaw/`: optional inbound hook.
- `examples/`: synthetic integration templates.
- `tests/`: offline regression suite.
- `config/`: private runtime files; only `.gitkeep` is published.

Legacy `FAMILY_*` settings and `family-agent-*` Docker names remain for compatibility.
Public source does not expose or deploy the running household installation.
The MIT license is in [LICENSE](LICENSE).
