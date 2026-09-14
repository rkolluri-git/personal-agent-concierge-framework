#!/bin/zsh
set -e

project_dir="$(cd -- "$(dirname -- "$0")" && pwd)"
"$project_dir/preflight.sh" --macos
python_path="$(command -v python3)"
agent_dir="$HOME/Library/LaunchAgents"
plist_path="$agent_dir/com.familyagent.imessage-alerts.plist"
label="com.familyagent.imessage-alerts"
domain="gui/$(id -u)"

mkdir -p "$agent_dir"
mkdir -p "$project_dir/config"
chmod 700 "$project_dir/config"
touch "$project_dir/config/imessage-alerts.log" "$project_dir/config/imessage-alerts-error.log"
chmod 600 "$project_dir/config/imessage-alerts.log" "$project_dir/config/imessage-alerts-error.log"
cat > "$plist_path" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$label</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/caffeinate</string>
        <string>-i</string>
        <string>$python_path</string>
        <string>$project_dir/macos/imessage_worker.py</string>
    </array>
    <key>WorkingDirectory</key>
    <string>$project_dir</string>
    <key>RunAtLoad</key>
    <true/>
    <key>StartInterval</key>
    <integer>60</integer>
    <key>ProcessType</key>
    <string>Background</string>
    <key>StandardOutPath</key>
    <string>$project_dir/config/imessage-alerts.log</string>
    <key>StandardErrorPath</key>
    <string>$project_dir/config/imessage-alerts-error.log</string>
</dict>
</plist>
PLIST

plutil -lint "$plist_path"
launchctl bootout "$domain" "$plist_path" 2>/dev/null || true
launchctl bootstrap "$domain" "$plist_path"
launchctl kickstart -k "$domain/$label"

echo "Automatic Family Agent iMessage delivery is active."
echo "Due alerts will be checked every minute."
echo "The Mac will remain awake while each delivery check is running."
echo "Incoming FA messages will be ingested at 7:05 AM and 7:00 PM."
echo "A private validation and safe-repair check will run Sunday after 7:00 AM."
echo "For incoming requests, allow Full Disk Access for: $python_path"
