#!/bin/bash
# Start the Francken TV slideshow: server, sniffer (if the ESP32 is plugged in) and a browser window.
# Press Ctrl+C here to stop everything. Ctrl+M = read quotes aloud on/off, Ctrl+R = reload devices.json.
#
#   ./start.sh                                   normal start, in a browser window
#   ./start.sh --fullscreen                      full screen (kiosk), as on the TV
#   ./start.sh --no-browser                      only the server; open http://127.0.0.1:8080 yourself
#   ./start.sh --fake-time "2026-10-16 15:57:30" pretend it's a different moment (other options go to the server too)

cd "$(dirname "$0")"
PYTHON=.venv/bin/python
[ -x "$PYTHON" ] || PYTHON=python3
SERIAL_PORT=/dev/ttyUSB0
URL=http://127.0.0.1:8080

browser=window
server_args=()
for arg in "$@"; do
	case "$arg" in
		--fullscreen) browser=kiosk ;;
		--window) browser=window ;;   # the default; still accepted
		--no-browser) browser=none ;;
		*) server_args+=("$arg") ;;
	esac
done

if systemctl --user is-active --quiet francken-tv 2>/dev/null; then
	echo "The slideshow already runs as a service (francken-tv, TV PC): open $URL,"
	echo "or 'systemctl --user start francken-tv-kiosk' for full screen. To run it from here instead:"
	echo "  systemctl --user stop francken-tv francken-tv-sniffer"
	exit 1
fi

pids=()
stop() {
	echo
	echo "Stopping..."
	kill "${pids[@]}" 2>/dev/null
	wait 2>/dev/null
	exit 0
}
trap stop INT TERM

if [ -e "$SERIAL_PORT" ]; then
	"$PYTHON" -m francken_tv.sniffer &
	pids+=($!)
else
	echo "No sniffer on $SERIAL_PORT: skipping presence tracking and greetings."
fi

# The "Francken TV" Spotify speaker, unless its service already runs it (TV PC).
SPOTIFYD="$HOME/.local/bin/spotifyd"
if systemctl --user is-active --quiet francken-tv-spotifyd 2>/dev/null; then
	:
elif [ -x "$SPOTIFYD" ] && [ -s data/spotifyd/oauth/credentials.json ]; then
	"$SPOTIFYD" --no-daemon --config-path deploy/spotifyd.conf --cache-path data/spotifyd >data/spotifyd.log 2>&1 &
	pids+=($!)
else
	echo "No Spotify speaker: songs only play on a Spotify app that's already playing. Install it with deploy/install_spotifyd.sh."
fi

case "$browser" in
	kiosk)
		deploy/kiosk.sh "$URL" &
		pids+=($!)
		echo "Slideshow opening full screen. Close it with Alt+F4, stop everything with Ctrl+C here."
		;;
	window)
		(
			until "$PYTHON" -c "import urllib.request; urllib.request.urlopen('$URL', timeout=2)" 2>/dev/null; do sleep 1; done
			xdg-open "$URL" >/dev/null 2>&1
		) &
		pids+=($!)
		;;
	none)
		echo "Open $URL in a browser."
		;;
esac

# The server runs in the foreground so it can read the keyboard shortcuts.
# When it stops, everything else stops too.
"$PYTHON" -m francken_tv "${server_args[@]}"
stop
