#!/bin/zsh
cd "${0:A:h}" || exit 1
docker compose exec family-agent-api python connect_calendars.py icloud
printf '\nPress Return to close. '
read -r reply
