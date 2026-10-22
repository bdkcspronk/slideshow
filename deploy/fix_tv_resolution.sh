#!/bin/bash
# Fixes the wrong resolution after a restart of the TV PC (fine after unplugging and plugging the HDMI
# cable): at startup the TV doesn't always tell the PC its resolutions (its EDID), and the PC falls back
# to a low one. This saves the TV's EDID while it works and makes the PC use that copy, and the right
# resolution, at every start (Linux kernel settings in GRUB).
#
# Run it on the TV PC while the resolution IS right (so after re-plugging the cable):
#   deploy/fix_tv_resolution.sh              # asks before changing anything; then reboot
#   deploy/fix_tv_resolution.sh --dry-run    # only shows what it would do
#   deploy/fix_tv_resolution.sh --undo       # back to how it was
# Options: --port HDMI-A-1 (when several screens are connected), --mode 1920x1080 (else the TV's own),
#          --no-edid (only force the resolution, when the TV's EDID can't be read at all).
set -euo pipefail

GRUB_FILE="${GRUB_FILE:-/etc/default/grub}"
DRM="${DRM_DIR:-/sys/class/drm}"   # the screens (GRUB_FILE and DRM_DIR can be set for testing)
EDID_FILE=/lib/firmware/edid/francken-tv.bin
HOOK_FILE=/etc/initramfs-tools/hooks/francken-tv-edid   # puts the EDID copy in the early boot image too

dry_run=false undo=false no_edid=false port="" mode=""
while [ $# -gt 0 ]; do
	case "$1" in
		--dry-run) dry_run=true ;;
		--undo) undo=true ;;
		--no-edid) no_edid=true ;;   # only force the resolution (when the EDID can't be read at all)
		--port) port="$2"; shift ;;
		--mode) mode="$2"; shift ;;
		*) echo "Unknown option $1 (see the top of this file)"; exit 1 ;;
	esac
	shift
done

# The GRUB line with the kernel settings, without ours (video=... and drm.edid_firmware=... of any port).
current_line() { grep -E '^GRUB_CMDLINE_LINUX_DEFAULT=' "$GRUB_FILE" | head -1; }
without_ours() { current_line | sed -E 's/ ?(video|drm\.edid_firmware)=[^" ]*//g'; }

write_grub() {   # write_grub NEW_LINE: replace the line (a backup goes next to it first)
	local new="$1"
	echo "GRUB, before: $(current_line)"
	echo "GRUB, after:  $new"
	if $dry_run; then return; fi
	sudo cp "$GRUB_FILE" "$GRUB_FILE.before-francken-tv"
	sudo sed -i -E "s|^GRUB_CMDLINE_LINUX_DEFAULT=.*|$new|" "$GRUB_FILE"
}

finish() {
	if $dry_run; then echo "(dry run: nothing changed)"; return; fi
	sudo update-grub
	sudo update-initramfs -u
	echo "Done. Reboot to see the result: sudo reboot"
}

if $undo; then
	write_grub "$(without_ours)"
	$dry_run || sudo rm -f "$EDID_FILE" "$HOOK_FILE"
	finish
	exit 0
fi

# 1. The HDMI port the TV is on: the connected one (or --port).
if [ -z "$port" ]; then
	connected=()
	for status in $DRM/card*-*/status; do
		[ "$(cat "$status")" = connected ] && connected+=("$(basename "$(dirname "$status")")")
	done
	if [ ${#connected[@]} -ne 1 ]; then
		echo "Found ${#connected[@]} connected screens (${connected[*]:-none}). Plug in only the TV, or pick one with --port HDMI-A-1."
		exit 1
	fi
	folder="${connected[0]}"            # e.g. card1-HDMI-A-1
	port="${folder#card*-}"             # e.g. HDMI-A-1
else
	folder="$(basename "$(dirname "$(ls $DRM/card*-"$port"/status | head -1)")")"
fi
echo "The TV is on port $port ($folder)"

# 2. Its resolution: the TV's own (first in its list), or --mode.
[ -n "$mode" ] || mode="$(head -1 "$DRM/$folder/modes")"
if ! [[ "$mode" =~ ^[0-9]+x[0-9]+$ ]]; then
	echo "Couldn't read the TV's resolution (got '$mode'). Is the resolution right now? Else give it with --mode 1920x1080."
	exit 1
fi
echo "Resolution: $mode at 60 Hz"

# 3. The TV's EDID, saved now that it works (unless --no-edid).
if $no_edid; then
	line="$(without_ours)"
	$dry_run || { read -r -p "Force $mode on $port at every start? [y/N] " answer; [ "$answer" = y ] || [ "$answer" = Y ] || { echo "Nothing changed."; exit 0; }; }
	write_grub "${line%\"} video=$port:$mode@60\""
	finish
	exit 0
fi
# Read it (not stat: files in /sys say 0 bytes even when they have data). Some drivers (NVIDIA's)
# leave it empty: then from xrandr --verbose (X11), which shows it in hex.
edid="$(mktemp)"
trap 'rm -f "$edid"' EXIT
cat "$DRM/$folder/edid" > "$edid" 2>/dev/null || true
if [ "$(wc -c < "$edid")" -lt 128 ] && command -v xrandr >/dev/null && [ -n "${DISPLAY:-}" ]; then
	echo "The driver doesn't give the EDID; reading it from xrandr instead"
	xrandr --verbose | python3 -c '
import sys
hex_lines, reading, connected = [], False, False
for line in sys.stdin:
	if not line.startswith((" ", "\t")):          # an output: "HDMI-1 connected ..."
		if hex_lines: break                         # the connected one had an EDID: done
		connected = " connected" in line
		continue
	if connected and line.strip() == "EDID:":
		reading = True
	elif reading and all(c in "0123456789abcdef" for c in line.strip()) and line.strip():
		hex_lines.append(line.strip())
	else:
		reading = False
sys.stdout.buffer.write(bytes.fromhex("".join(hex_lines)))' > "$edid" || true
fi
size=$(wc -c < "$edid")
if [ "$size" -lt 128 ]; then
	echo "The TV's EDID can't be read right now ($size bytes). Unplug and plug the cable, check the picture is right, and run this again."
	echo "Still nothing? Then use only the resolution: deploy/fix_tv_resolution.sh --no-edid"
	exit 1
fi
echo "Saving the TV's EDID ($size bytes) as $EDID_FILE"

if ! $dry_run; then
	read -r -p "Change the startup settings like this? [y/N] " answer
	[ "$answer" = y ] || [ "$answer" = Y ] || { echo "Nothing changed."; exit 0; }
	sudo mkdir -p "$(dirname "$EDID_FILE")"
	sudo cp "$edid" "$EDID_FILE"
	sudo tee "$HOOK_FILE" >/dev/null <<'HOOK'
#!/bin/sh
# Puts the TV's saved EDID (deploy/fix_tv_resolution.sh in the slideshow) in the early boot image.
case "$1" in prereqs) exit 0 ;; esac
. /usr/share/initramfs-tools/hook-functions
mkdir -p "$DESTDIR/lib/firmware/edid"
cp /lib/firmware/edid/francken-tv.bin "$DESTDIR/lib/firmware/edid/"
HOOK
	sudo chmod +x "$HOOK_FILE"
fi

# 4. GRUB: use the saved EDID and the resolution on that port, from the start.
line="$(without_ours)"
write_grub "${line%\"} video=$port:$mode@60 drm.edid_firmware=$port:edid/francken-tv.bin\""
finish
