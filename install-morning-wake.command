#!/bin/zsh
set -euo pipefail

wake_time="06:59:00"
weekdays="MTWRFSU"
current_schedule="$(pmset -g sched)"

if print -r -- "$current_schedule" | grep -q '^Repeating power events:'; then
    print "This Mac already has a repeating power schedule:"
    print -r -- "$current_schedule" | sed -n '/^Repeating power events:/,/^Scheduled power events:/p'
    print
    print "macOS supports only one repeating power-event pair."
    read "answer?Replace it with the Family Agent 6:59 AM daily wake schedule? [y/N] "
    [[ "$answer" == [yY] ]] || { print "No changes made."; exit 0; }
fi

print "Administrator approval is required to schedule the daily wake."
sudo /usr/bin/pmset repeat wakeorpoweron "$weekdays" "$wake_time"

print
print "Family Agent morning wake is active."
print "The Mac will wake every day at 6:59 AM."
print "The existing Family Agent service will send due 7:00 AM iMessages."
print "After delivery, normal idle-sleep settings will put the Mac back to sleep."
print "Keep the Mac connected to power. A closed laptop lid can prevent scheduled wake."
print
/usr/bin/pmset -g sched
