#!/bin/sh
# Opens the slideshow full-screen. Started by francken-tv-kiosk.service.
URL="${1:-http://127.0.0.1:8080}"

# Wait until the slideshow server answers.
until python3 -c "import urllib.request; urllib.request.urlopen('$URL', timeout=2)" 2>/dev/null; do
	sleep 2
done

for browser in chromium chromium-browser google-chrome; do
	if command -v "$browser" >/dev/null; then
		exec "$browser" --kiosk --noerrdialogs --disable-infobars --disable-session-crashed-bubble \
			--check-for-update-interval=31536000 --incognito "$URL"
	fi
done
exec firefox --kiosk --private-window "$URL"
