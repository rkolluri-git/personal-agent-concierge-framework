#!/bin/zsh
cd "${0:A:h}" || exit 1
docker compose run --rm --no-deps -p 127.0.0.1:8765:8765 family-agent-api python connect_calendars.py google
printf '\nPress Return to close. '
read -r reply
