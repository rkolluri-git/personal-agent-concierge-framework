#!/bin/zsh
set -e

cd -- "$(dirname -- "$0")"
echo "Checking Family Agent for due iMessage alerts…"
/usr/bin/env python3 macos/imessage_worker.py

echo
echo "The first run may ask permission to control Messages."
echo "Allow it in System Settings if prompted."
echo
echo "Press Return to close."
read -r
