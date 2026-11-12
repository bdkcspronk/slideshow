#!/bin/bash
# Sets up the slideshow on a new (Ubuntu/Debian) PC: packages, Python environment, the files that are not
# in git (copy them by hand, docs/01-handover.md) and the services.
#
#   git clone <this repo> ~/slideshow && ~/slideshow/deploy/setup.sh
#
# Options: --no-services  only packages and the Python environment (e.g. on a laptop)
# Safe to run again.
set -euo pipefail
cd "$(dirname "$0")/.."

services=true
for arg in "$@"; do
	case "$arg" in
		--no-services) services=false ;;
		*) echo "Unknown option $arg (see the top of this file)"; exit 1 ;;
	esac
done

if [ "$services" = true ] && [ "$(realpath .)" != "$(realpath ~/slideshow 2>/dev/null)" ]; then
	echo "The services expect the project in ~/slideshow, but it is in $(realpath .)."
	echo "Move it there, or use --no-services."
	exit 1
fi

echo "== Packages (asks for your sudo password)"
sudo apt install -y python3-jinja2 python3-requests python3-bs4 python3-pil python3-serial python3-venv \
	ffmpeg firefox poppler-utils
sudo usermod -aG dialout "$USER"   # serial port access for the sniffer; takes effect after logging in again

echo "== Python environment"
[ -d .venv ] || python3 -m venv --system-site-packages .venv
.venv/bin/pip install --quiet piper-tts tomli
chmod +x start.sh deploy/*.sh

echo "== The Spotify speaker (open the login link it prints)"
deploy/install_spotifyd.sh || echo "Spotify speaker not set up: run deploy/install_spotifyd.sh later."

if [ "$services" = true ]; then
	echo "== Services"
	mkdir -p ~/.config/systemd/user
	cp deploy/*.service deploy/*.timer ~/.config/systemd/user/
	systemctl --user daemon-reload
	systemctl --user enable --now francken-tv francken-tv-sniffer francken-tv-kiosk francken-tv-spotifyd
	sudo loginctl enable-linger "$USER"   # keep running without anyone logged in
fi

echo
echo "Done. Log out and in once (serial port access). Check http://127.0.0.1:8080/status and /health."
