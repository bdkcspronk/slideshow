#!/bin/bash
# Installs spotifyd as ~/.local/bin/spotifyd and logs it in once, so this PC becomes the Spotify speaker
# "Francken TV" (deploy/spotifyd.conf). Run it again to update to VERSION; with --login to log in again.
# Started by francken-tv-spotifyd.service on the TV PC, or by start.sh elsewhere. See README.md ("Spotify").
set -euo pipefail
cd "$(dirname "$0")/.."

VERSION=v0.4.2
BIN="$HOME/.local/bin/spotifyd"
CACHE=data/spotifyd

case "$(uname -m)" in
	x86_64) arch=x86_64 ;;
	aarch64|arm64) arch=aarch64 ;;
	armv7l) arch=armv7 ;;
	*) echo "No spotifyd build for $(uname -m)" >&2; exit 1 ;;
esac

if [ "$("$BIN" --version 2>/dev/null)" != "spotifyd ${VERSION#v}" ]; then
	name="spotifyd-linux-$arch-default"
	url="https://github.com/Spotifyd/spotifyd/releases/download/$VERSION/$name"
	tmp="$(mktemp -d)"
	trap 'rm -rf "$tmp"' EXIT
	echo "Downloading spotifyd $VERSION ($arch)..."
	# python3 instead of curl/wget: it's always there.
	python3 -c "import sys, urllib.request; [urllib.request.urlretrieve(u, f) for u, f in zip(sys.argv[1::2], sys.argv[2::2])]" \
		"$url.tar.gz" "$tmp/$name.tar.gz" "$url.sha512" "$tmp/$name.sha512"
	(cd "$tmp" && sha512sum --quiet -c "$name.sha512")
	tar xzf "$tmp/$name.tar.gz" -C "$tmp"
	mkdir -p "$(dirname "$BIN")"
	install -m 755 "$tmp/spotifyd" "$BIN"   # not executable in the download
	echo "Installed $BIN"
fi

if [ ! -s "$CACHE/oauth/credentials.json" ] || [ "${1:-}" = "--login" ]; then
	echo "Log in with the Spotify account whose music should play: open the link below on this PC."
	mkdir -p "$CACHE"
	"$BIN" authenticate --config-path deploy/spotifyd.conf --cache-path "$CACHE"
fi

# The slideshow runs as a service here (TV PC): run the speaker as one too. Otherwise start.sh starts it.
if systemctl --user is-enabled --quiet francken-tv 2>/dev/null; then
	mkdir -p ~/.config/systemd/user
	cp deploy/francken-tv-spotifyd.service ~/.config/systemd/user/
	systemctl --user daemon-reload
	systemctl --user reenable francken-tv-spotifyd   # reenable: moves an older install to [Install] in the file
	if systemctl --user is-active --quiet francken-tv; then
		systemctl --user restart francken-tv-spotifyd   # restart: picks up a new version or login
	fi
	echo "spotifyd runs with the slideshow (francken-tv-spotifyd.service)."
else
	echo "spotifyd is ready; start.sh starts it."
fi
