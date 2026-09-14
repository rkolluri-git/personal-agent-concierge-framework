# Connecting family calendars

The dashboard's Calendar tab reads the next 14 days from selected calendars.
Nothing is written to Google or iCloud. Calendar events are fetched live on
refresh, not stored in PostgreSQL. Both providers remain disconnected until you
complete their setup. One account per provider is supported in this first version;
choose calendars shared with that account to include other family members.

After connecting or sharing calendars, open the Calendar tab and use **Family
Calendars** to assign each calendar to one or more people. Individual morning
briefings use these assignments. A shared family calendar can be assigned to
everyone, while a child's personal calendar can be assigned only to that child.

## iCloud (start here)

1. Visit https://account.apple.com and sign in privately.
2. Under Sign-In and Security, choose App-Specific Passwords and generate one
   named Personal Agent. Apple requires two-factor authentication.
3. In Finder, open the family-agent folder and double-click
   `connect-icloud.command`. Enter your Apple Account email and the app-specific
   password when prompted. The password entry is hidden.
4. Choose the calendar numbers you want to show. These setup numbers are only
   used once; the dashboard displays names.
5. Refresh Calendar in the dashboard.

The integration reads calendars and supports explicit create/update actions in
the reviewed iCloud editor. Apple's app-specific password is not scoped to
read-only use. It is stored in `config/icloud.json`
with owner-only file permissions; the config folder is also owner-only, excluded
from Git and Docker images, and never served as a web asset. Revoke the password
in your Apple account when you no longer want this access. Don't use your normal
Apple Account password, paste credentials into chat, or make a calendar public.

Apple instructions: https://support.apple.com/102654

## Google

1. In Google Cloud Console, create/select a project and enable Google Calendar API.
2. Configure the Google Auth Platform consent screen. For a personal account,
   use an External audience and add your own Google account as a test user while
   the project is in Testing. Request only `calendar.readonly`.
3. Create an OAuth client of type Desktop app. Download its JSON and save it as
   `config/google-client.json` in this project.
4. Double-click `connect-google.command`. Open the displayed Google authorization
   link yourself, sign in, and review the read-only calendar permission.
5. Return to Terminal and select the calendars to display, then refresh Calendar.

The temporary callback is bound only to 127.0.0.1:8765 on your Mac. Tokens are
stored privately in `config/google-token.json`, outside Git and the Docker image.
Calendar selections are in `config/google-calendars.json`. Depending on Google's
OAuth project status, you may need to reconnect when authorization expires.
Never upload these files to chat or source control.

Google setup: https://developers.google.com/workspace/calendar/api/quickstart/python

## Local operation

- Open http://localhost:8000/dashboard and choose Calendar.
- Times use America/New_York, configured as FAMILY_TIMEZONE in docker-compose.yml.
- All-day event dates retain their original calendar dates.
- Calendars shared through both providers can show duplicate events; source
  labels distinguish them. Only select one copy when setting up connections.
- Failed connections display an error; successful sources can still show events.
- Refresh retries reads. Run the appropriate connection script again to reconnect
  or choose a different set of calendars.
- The dashboard now listens only on this Mac. Authentication and secure remote
  family access remain separate future steps.
- Local tests: `docker compose exec -T family-agent-api python < tests/test_calendars.py`

Live account authorization and real recurring-event behavior must be verified
with your accounts after connection. Fixture tests do not establish a live link.
