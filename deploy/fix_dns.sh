#!/bin/bash
# Fixes the TV PC losing the internet for minutes at a time ("Temporary failure in name resolution",
# MaxRetryError in the slideshow's log): the network gives the PC two DNS servers, an IPv4 and an IPv6
# one, and the IPv6 one (from VirtualBox) sometimes stops answering while the PC keeps asking it. This
# makes the PC ignore the IPv6 DNS server; IPv6 itself keeps working, and the IPv4 DNS server is used.
#
# Run it on the TV PC:
#   deploy/fix_dns.sh              # asks before changing anything; the network drops for a second or two
#   deploy/fix_dns.sh --dry-run    # only shows what it would do
#   deploy/fix_dns.sh --undo       # back to how it was
# Option: --connection NAME (else the connection that's in use, see `nmcli connection show --active`).
set -euo pipefail

dry_run=false undo=false connection=""
while [ $# -gt 0 ]; do
	case "$1" in
		--dry-run) dry_run=true ;;
		--undo) undo=true ;;
		--connection) connection="$2"; shift ;;
		*) echo "Unknown option $1 (see the top of this file)"; exit 1 ;;
	esac
	shift
done

if ! command -v nmcli >/dev/null; then
	echo "This PC doesn't use NetworkManager (no nmcli): nothing to do here."
	exit 1
fi

if [ -z "$connection" ]; then   # the wired or wireless connection in use (not lo, not a VPN)
	connection="$(nmcli -t -f NAME,TYPE connection show --active | awk -F: '$2 ~ /ethernet|wireless/ { print $1; exit }')"
	if [ -z "$connection" ]; then
		echo "No wired or wireless connection is in use. Pick one with --connection NAME:"
		nmcli connection show
		exit 1
	fi
fi

ignore="$($undo && echo no || echo yes)"
current="$(nmcli -g ipv6.ignore-auto-dns connection show "$connection")"
echo "Connection: $connection"
echo "DNS servers now: $(resolvectl dns 2>/dev/null | grep -v '^Global' | sed 's/^[^:]*: *//' | tr '\n' ' ')"
if [ "$current" = "$ignore" ]; then
	echo "Already done: the IPv6 DNS server is $($undo && echo used || echo ignored). Nothing changed."
	exit 0
fi
echo "$($undo && echo "Use the IPv6 DNS server again" || echo "Ignore the IPv6 DNS server, keep the IPv4 one") (ipv6.ignore-auto-dns $current -> $ignore)."
echo "The network reconnects: it drops for a second or two."
if $dry_run; then echo "(dry run: nothing changed)"; exit 0; fi
read -r -p "Go ahead? [y/N] " answer
[ "$answer" = y ] || [ "$answer" = Y ] || { echo "Nothing changed."; exit 0; }

sudo nmcli connection modify "$connection" ipv6.ignore-auto-dns "$ignore"
sudo nmcli connection up "$connection" >/dev/null

for _ in $(seq 20); do   # back online?
	if getent hosts professorfrancken.nl >/dev/null; then
		echo "Done. DNS servers now: $(resolvectl dns 2>/dev/null | grep -v '^Global' | sed 's/^[^:]*: *//' | tr '\n' ' ')"
		echo "Names resolve again (professorfrancken.nl works). Undo with: deploy/fix_dns.sh --undo"
		exit 0
	fi
	sleep 1
done
echo "Changed, but names don't resolve yet after 20 seconds. Check the network, or undo with: deploy/fix_dns.sh --undo"
exit 1
