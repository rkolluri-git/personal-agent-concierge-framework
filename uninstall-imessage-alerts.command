#!/bin/zsh
set -e

plist_path="$HOME/Library/LaunchAgents/com.familyagent.imessage-alerts.plist"
domain="gui/$(id -u)"

if [[ -f "$plist_path" ]]; then
    launchctl bootout "$domain" "$plist_path" 2>/dev/null || true
    rm "$plist_path"
fi

echo "Automatic Family Agent iMessage delivery is disabled."
echo "Saved contacts and alert history remain in Family Agent."
