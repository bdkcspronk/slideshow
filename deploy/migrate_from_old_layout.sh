#!/bin/bash
# One-time move from the old slideshow layout (slides/, audio/, Sniffer/, quotes/) to the new one.
# Run it from the project folder after `git pull`:  deploy/migrate_from_old_layout.sh
# Nothing is deleted: files that aren't needed any more go to data/legacy/.
set -u
cd "$(dirname "$0")/.."

moved=0
move() {   # move SOURCE DESTINATION, without overwriting anything
	[ -e "$1" ] || return 0
	mkdir -p "$(dirname "$2")"
	if [ -e "$2" ]; then
		echo "  skip $1 ($2 already exists)"
	else
		mv "$1" "$2" && echo "  $1 -> $2" && moved=$((moved + 1))
	fi
}

echo "Slides, songs and images:"
# The vrijmibo GIF was in git; `git pull` removed it, so restore it from history.
if [ ! -e media/vrijmibo.gif ] && [ ! -e slides/vrijmibo.gif ]; then
	mkdir -p media
	git show e60b270:slides/vrijmibo.gif > media/vrijmibo.gif 2>/dev/null \
		&& echo "  restored media/vrijmibo.gif from git history" || rm -f media/vrijmibo.gif
fi
move slides/vrijmibo.gif media/vrijmibo.gif
for generated in slides/sniffer_slide.png slides/activities.png slides/eventpicture_* slides/events; do
	move "$generated" "data/legacy/$generated"   # made by the old code; the new code makes its own
done
for file in slides/*; do
	move "$file" "media/slides/$(basename "$file")"
done
for file in audio/*; do
	move "$file" "media/bieruur/$(basename "$file")"
done
move quotes/images/background.png media/quote_background.png
move Sniffer/resources/nyancat.png media/nyancat.png
for file in Sniffer/voicefiles/*; do
	move "$file" "media/voices/$(basename "$file")"
done

echo "Settings and data:"
move Sniffer/filter.json config/devices.json
move quotes/quotes.csv data/quotes.csv
move Sniffer/platformio.ini firmware/platformio.ini
move Sniffer/.pio firmware/.pio
if [ -e Sniffer/filtered_output.jsonl ] && [ ! -e data/presence.sqlite3 ]; then
	PYTHON=.venv/bin/python; [ -x "$PYTHON" ] || PYTHON=python3
	"$PYTHON" -m francken_tv.sniffer --import Sniffer/filtered_output.jsonl && echo "  imported the old sniffer log"
fi

echo "Everything else from the old layout -> data/legacy/:"
for old in Sniffer quotes slides audio main start_slideshow.py; do
	[ -e "$old" ] && move "$old" "data/legacy/old/$old"
done

echo "Done ($moved moved). Check data/legacy/ and delete it when everything works."
