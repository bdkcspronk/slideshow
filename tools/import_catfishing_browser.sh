#!/bin/sh
# Copies the catfishing.net games played in Firefox on this PC into the TV's archive calendar,
# then restarts the slideshow so it sees them. See import_catfishing_browser.py for the details.
# Run on the TV PC: sh tools/import_catfishing_browser.sh
set -e
cd "$(dirname "$0")/.."
PYTHON=.venv/bin/python
[ -x "$PYTHON" ] || PYTHON=python3

# Stop the slideshow first: while it runs it would write its old history back over the import.
systemctl --user stop francken-tv 2>/dev/null && STOPPED=1 || STOPPED=
"$PYTHON" tools/import_catfishing_browser.py --write || STATUS=$?
if [ -n "$STOPPED" ]; then
	systemctl --user start francken-tv
	echo "Slideshow started again."
fi
exit "${STATUS:-0}"
