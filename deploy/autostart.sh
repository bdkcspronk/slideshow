#!/bin/bash
# Started at login (~/.config/autostart/francken-tv.desktop, see deploy/install_autostart.sh): opens a
# terminal with the slideshow (start.sh --fullscreen) in it, so Ctrl+C, Ctrl+M and Ctrl+R work there.
# The full-screen browser is on top; Alt+Tab gets to the terminal.
cd "$(dirname "$0")/.." || exit 1

if [ "$1" != "--in-terminal" ]; then
	# Open whichever terminal this desktop has, running this script again inside it.
	self="$(realpath "$0")"
	for terminal in gnome-terminal xfce4-terminal konsole mate-terminal x-terminal-emulator xterm; do
		command -v "$terminal" >/dev/null || continue
		case "$terminal" in
			gnome-terminal) exec gnome-terminal --title="Francken TV" -- "$self" --in-terminal ;;
			xfce4-terminal) exec xfce4-terminal --title="Francken TV" -x "$self" --in-terminal ;;
			*) exec "$terminal" -e "$self" --in-terminal ;;
		esac
	done
	echo "No terminal found to run the slideshow in" >&2
	exit 1
fi

# Inside the terminal: run the slideshow; when it stops, offer to start it again (the window stays).
while true; do
	./start.sh --fullscreen
	echo
	read -r -p "The slideshow stopped. Press Enter to start it again, or close this window. "
done
