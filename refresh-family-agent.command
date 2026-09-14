#!/bin/zsh
set -e

cd -- "$(dirname -- "$0")"

echo "Updating Family Agent…"
DOCKER_BUILDKIT=0 ./start.sh

echo
echo "Family Agent is ready."
open "http://localhost:8000/dashboard#alerts"

echo
echo "Press Return to close."
read -r
