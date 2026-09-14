#!/bin/zsh
set -euo pipefail

current_schedule="$(pmset -g sched)"
if ! print -r -- "$current_schedule" | grep -q '^Repeating power events:'; then
    print "No repeating wake schedule is configured."
    exit 0
fi

if ! print -r -- "$current_schedule" | grep -Eq 'wake(poweron|orpoweron).*6:59|wakepoweron.*6:59'; then
    print "The current repeating schedule does not look like the Family Agent 6:59 AM wake."
    print "No changes made, so another power schedule is not removed accidentally."
    exit 1
fi

print "Administrator approval is required to remove the Family Agent wake schedule."
sudo /usr/bin/pmset repeat cancel
print "Family Agent morning wake removed."
