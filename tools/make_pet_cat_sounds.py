"""Makes francken_tv/static/pet/cat/*.ogg, the sounds of the Francken pet when it's a cat (providers/pet.py, CAT_SOUNDS):
real cat recordings from Wikimedia Commons, all public domain or CC0 (no credit needed, but it's listed below anyway),
cut to one or two meows and made equally loud.

	python3 tools/make_pet_cat_sounds.py

Needs ffmpeg and the internet. Wikimedia rate-limits its API, so this fetches the files straight from upload.wikimedia.org.
"""

import hashlib
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "francken_tv" / "static" / "pet" / "cat"

# Each sound: the file on Wikimedia Commons (its licence), and the parts to keep (start, end in seconds; None: all of it).
SOUNDS = {
	# Wants attention (low health, and when the slide comes round): two pleading meows, the pause between them shortened.
	"attention": ("Meow of a pleading cat.oga", [(0.25, 1.6), (3.55, 4.9)]),          # public domain
	"feed": ("Maullido de gata hembra joven.ogg", None),                                # CC0, a young female cat
	"play": ("Meow of a Siamese cat - freemaster2.wav", None),                          # CC0
	"water": ("2015-11-24.νιαούρισμα.Νιάου.noise reduced.flac", None),                 # CC0
	"clean": ("Purring cat bertie.ogg", [(1.0, 3.6)]),                                  # public domain, a purr
	"hatch": ("MeowUSA.wav", None),                                                     # CC0, a kitten-ish meow
}
LOUDNESS = "loudnorm=I=-16:TP=-1.5:LRA=11"   # all about as loud as each other


def commons_url(name: str) -> str:
	name = name.replace(" ", "_")
	digest = hashlib.md5(name.encode()).hexdigest()
	return f"https://upload.wikimedia.org/wikipedia/commons/{digest[0]}/{digest[:2]}/{urllib.parse.quote(name)}"


def download(url: str) -> bytes:
	"""The file, waiting a bit before each try: Wikimedia answers "too many requests" (429) quickly."""
	request = urllib.request.Request(url, headers={"User-Agent": "francken-tv-sound-maker/1.0"})
	for attempt in range(6):
		time.sleep(5 * attempt + 2)
		try:
			return urllib.request.urlopen(request, timeout=30).read()
		except urllib.error.HTTPError as error:
			if error.code != 429 or attempt == 5:
				raise


def main() -> None:
	OUT.mkdir(parents=True, exist_ok=True)
	with tempfile.TemporaryDirectory() as folder:
		for sound, (name, parts) in SOUNDS.items():
			source = Path(folder) / f"{sound}{Path(name).suffix}"
			source.write_bytes(download(commons_url(name)))
			if parts:
				cuts = "".join(f"[0:a]atrim={start}:{end},asetpts=PTS-STARTPTS,afade=t=in:d=0.05,afade=t=out:st={end - start - 0.15}:d=0.15[p{i}];"
					for i, (start, end) in enumerate(parts))
				chain = f"{cuts}{''.join(f'[p{i}]' for i in range(len(parts)))}concat=n={len(parts)}:v=0:a=1,{LOUDNESS}[out]"
			else:
				chain = f"[0:a]{LOUDNESS}[out]"
			subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(source), "-filter_complex", chain, "-map", "[out]",
				"-ac", "1", "-ar", "44100", "-c:a", "libvorbis", "-q:a", "4", str(OUT / f"{sound}.ogg")], check=True)
			print(f"{OUT / sound}.ogg  <-  {name}")


if __name__ == "__main__":
	main()
