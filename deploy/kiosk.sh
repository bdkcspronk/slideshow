#!/bin/sh
# Opens the slideshow full-screen. Started by start.sh or francken-tv-kiosk.service.
# Firefox only. Its own messages (GPU, dbus, ...) go to data/kiosk-browser.log, not the terminal.
URL="${1:-http://127.0.0.1:8080}"
LOG="$(dirname "$0")/../data/kiosk-browser.log"
mkdir -p "$(dirname "$LOG")"

# Wait until the slideshow server answers.
until python3 -c "import urllib.request; urllib.request.urlopen('$URL', timeout=2)" 2>/dev/null; do
	sleep 2
done

# Firefox gets its own profile and --no-remote, so it runs as a separate process instead of handing the URL
# to a Firefox that is already open and exiting at once (systemd would then restart it every few seconds).
PROFILE="$(dirname "$0")/../data/kiosk-firefox-profile"
mkdir -p "$PROFILE"
cp "$(dirname "$0")/firefox-user.js" "$PROFILE/user.js"
exec firefox --kiosk --no-remote --profile "$(realpath "$PROFILE")" --private-window "$URL" >"$LOG" 2>&1
