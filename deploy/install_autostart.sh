#!/bin/bash
# Start the slideshow at login in a terminal (deploy/autostart.sh) instead of as background services.
# Run once on the TV PC: deploy/install_autostart.sh   (undo: deploy/install_autostart.sh --undo)
set -e
cd "$(dirname "$0")/.."
desktop="$HOME/.config/autostart/francken-tv.desktop"

if [ "$1" = "--undo" ]; then
	rm -f "$desktop"
	systemctl --user enable --now francken-tv francken-tv-sniffer francken-tv-kiosk 2>/dev/null || true
	echo "Back to the background services."
	exit 0
fi

mkdir -p "$(dirname "$desktop")"
cat > "$desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=Francken TV
Comment=The slideshow, in a terminal (deploy/autostart.sh)
Exec=$(realpath deploy/autostart.sh)
X-GNOME-Autostart-enabled=true
DESKTOP
chmod +x deploy/autostart.sh start.sh deploy/kiosk.sh

# The services would run a second slideshow next to it; the Spotify speaker service can stay.
systemctl --user disable --now francken-tv francken-tv-sniffer francken-tv-kiosk 2>/dev/null || true
echo "Done: at the next login the slideshow starts in a terminal. Start it now with: deploy/autostart.sh"
