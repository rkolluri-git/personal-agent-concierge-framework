#!/bin/zsh
set -euo pipefail
cd "${0:A:h}"
helper='/Library/PrivilegedHelperTools/com.familyagent.appointment-wake'
plist='/Library/LaunchDaemons/com.familyagent.appointment-wake.plist'
sudo /usr/bin/install -d -o root -g wheel -m 755 /Library/PrivilegedHelperTools
sudo /usr/bin/install -o root -g wheel -m 600 config/worker-auth.key /Library/PrivilegedHelperTools/com.familyagent.access.key
print 'Install appointment wake checks (administrator approval required).'
print 'This adds wake-only events and preserves the daily 6:59 AM wake schedule.'
sudo /usr/bin/install -o root -g wheel -m 755 macos/appointment_wake.sh "$helper"
tmp=$(/usr/bin/mktemp)
trap '/bin/rm -f "$tmp"' EXIT
cat > "$tmp" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>Label</key><string>com.familyagent.appointment-wake</string>
<key>ProgramArguments</key><array><string>/bin/zsh</string><string>/Library/PrivilegedHelperTools/com.familyagent.appointment-wake</string></array>
<key>RunAtLoad</key><true/><key>StartInterval</key><integer>60</integer>
</dict></plist>
PLIST
/usr/bin/plutil -lint "$tmp"
sudo /usr/bin/install -o root -g wheel -m 644 "$tmp" "$plist"
sudo /bin/launchctl bootout system "$plist" 2>/dev/null || true
sudo /bin/launchctl bootstrap system "$plist"
print 'Appointment wake scheduling installed. Keep the Mac connected to power; it must remain logged in and Docker available. A closed lid or shutdown can prevent delivery.'
