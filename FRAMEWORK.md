# Extending Personal Agent

The FastAPI application owns family members, tasks, scheduling, and delivery state.
Service modules isolate external systems: `calendar_service.py` (Google/iCloud),
`weather_service.py` (Open-Meteo), and `school_calendar_service.py` (school days).
`regional_settings.py` provides validated installation settings to these modules
and the dashboard through `GET /settings/regional`. No family names belong in
application rules: use member IDs and roles.

The macOS worker is an optional platform adapter for Messages and Apple Maps.
Future delivery adapters should follow the existing claim/complete API, preserving
bounded retries and uncertain delivery handling. Optional Twilio and OpenClaw adapters now follow this flow; see
`MESSAGING_SETUP.md` for configuration and deployment. Google calendar access remains read-only. The iCloud editor supports explicit,
reviewed create/update actions with conditional writes and readback verification.

## Regional configuration

Set all five values in `.env`, then rebuild with `docker compose up -d --build`:

| Installation | Locale | Country | Time zone | Units | School calendar |
| --- | --- | --- | --- | --- | --- |
| India | en-IN | IN | Asia/Kolkata | metric | custom or none |
| UK | en-GB | GB | Europe/London | metric | custom or none |
| Germany | de-DE | DE | Europe/Berlin | metric | custom or none |
| USA | en-US | US | America/New_York | imperial | custom, none, or cobb |

Variables are `FAMILY_LOCALE`, `FAMILY_COUNTRY`, `FAMILY_TIMEZONE`,
`FAMILY_UNITS`, and `FAMILY_SCHOOL_CALENDAR`. The locale controls browser date
formatting; country scopes weather location searches. Time zone controls backend
calendar and reminder scheduling. Units control weather output, dashboard weather
threshold entry, and commute distances. The weather API's existing threshold
fields retain Fahrenheit for database/API compatibility; the dashboard converts
these values. Forecast responses include explicit unit metadata.

This is regional formatting, not translated content: interface labels, message
text, and Concierge parsing currently use English. Browser datetime input fields
use the browser's local time; macOS wake/intake/weekly maintenance schedules use
the Mac's system time zone. Keep the host and household time zones aligned.

Compose defaults to US/New York, imperial units, and no school-calendar filtering.
Set regional variables explicitly for your installation. New consumers should copy `.env.example`, which
explicitly disables school-day filtering until configured.

## School calendars outside Cobb County

Copy `examples/school-calendar.json` to `config/school-calendar.json`, enter your
school's verified date coverage and holidays, and set `FAMILY_SCHOOL_CALENDAR=custom`.
Weekdays are Monday=0 through Sunday=6, so different school weeks are supported.
The example is illustrative, not an official school calendar. Keep private calendar
files out of Git. The file is read at each check; expired coverage or invalid data
pauses filtered commutes rather than assuming an ordinary school day. `none`
disables school-day filtering; `cobb` retains the existing district PDF adapter.
Custom calendars require manual maintenance and do not download school holidays.

## Development

Use Python 3.12. Install `backend/requirements.txt` and `pytest` in a virtual
environment, then run `PYTHONPATH=backend:macos python -m pytest -q`.
The CI workflow runs this suite and checks dashboard JavaScript syntax.

This is an early framework foundation, not a supported hosted service. See the
[PRIVACY.md](PRIVACY.md) for administrator/worker authorization and deployment
limits, and the README for migration limitations.

Save international iMessage contacts with their full country code (for example,
`+44…` or `+91…`). Matching preserves the country code. US installations also
accept their domestic ten-digit form with an optional leading `1`.
