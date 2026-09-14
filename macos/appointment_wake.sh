#!/bin/zsh
# Installed root-owned; only schedules bounded, wake-only power events.
set -eu
owner='com.familyagent.appointment-traffic'
state='/var/db/com.familyagent.appointment-wakes'
key_file="${FAMILY_ACCESS_KEY_FILE:-/Library/PrivilegedHelperTools/com.familyagent.access.key}"
[[ -r "$key_file" ]] || exit 0
json=$(/usr/bin/curl --fail --silent --max-time 8 --max-filesize 65536 --header "Authorization: Bearer $(<"$key_file")" http://127.0.0.1:8000/departure/traffic/wake-plan) || exit 0
/usr/bin/printf '%s' "$json" | /usr/bin/plutil -extract wake_times json -o - - >/dev/null || exit 0
now=$(/bin/date +%s)
next=''
for i in {0..9}; do
 epoch=$(/usr/bin/printf '%s' "$json" | /usr/bin/plutil -extract "wake_times.$i" raw -o - - 2>/dev/null) || break
 [[ "$epoch" == <-> ]] || continue
 (( epoch > now && epoch < now + 1209600 )) || continue
 next+="$epoch"$'\n'
done
previous=''
[[ -f "$state" ]] && previous=$(<"$state")
[[ "$previous" == "${next%$'\n'}" ]] && exit 0
for epoch in ${(f)previous}; do
 [[ "$epoch" == <-> ]] || continue
 (( epoch > now )) || continue
 stamp=$(/bin/date -r "$epoch" '+%m/%d/%y %H:%M:%S')
 /usr/bin/pmset schedule cancel wake "$stamp" "$owner" >/dev/null 2>&1 || true
done
successful=''
for epoch in ${(f)next}; do
 [[ "$epoch" == <-> ]] || continue
 stamp=$(/bin/date -r "$epoch" '+%m/%d/%y %H:%M:%S')
 if /usr/bin/pmset schedule wake "$stamp" "$owner"; then successful+="$epoch"$'\n'; fi
done
umask 077
/usr/bin/printf '%s' "$successful" > "$state"
