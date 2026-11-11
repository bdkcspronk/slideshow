"""Makes francken_tv/static/pet/cry.wav, the Francken pet's cry (providers/pet.py): two sad, squeaky chirps,
"mi-iew... miiieeuw", synthesised so there's no sound file with a licence to worry about.

	python3 tools/make_pet_cry.py
"""

import math
import struct
import wave
from pathlib import Path

RATE = 22050
OUT = Path(__file__).resolve().parent.parent / "francken_tv" / "static" / "pet" / "cry.wav"

# Each chirp: (start, length, pitch at its start, at its top, at its end), seconds and Hz.
CHIRPS = [(0.0, 0.32, 780, 1150, 900), (0.42, 0.62, 950, 1250, 560)]


def pitch(t: float, start: float, top: float, end: float) -> float:
	"""Up to the top in the first third, then down; with a wobble that grows towards the end (a whimper)."""
	base = start + (top - start) * t / 0.3 if t < 0.3 else top + (end - top) * (t - 0.3) / 0.7
	return base * (1 + 0.035 * t * math.sin(2 * math.pi * 11 * t))


def main() -> None:
	total = int(RATE * (max(s + l for s, l, *_ in CHIRPS) + 0.05))
	samples = [0.0] * total
	for start, length, *pitches in CHIRPS:
		phase = 0.0
		for i in range(int(RATE * length)):
			t = i / (RATE * length)
			phase += 2 * math.pi * pitch(t, *pitches) / RATE
			envelope = min(1.0, t / 0.08) * min(1.0, (1 - t) / 0.25)   # soft start, longer fade
			voice = math.sin(phase) + 0.45 * math.sin(2 * phase) + 0.18 * math.sin(3 * phase) + 0.08 * math.sin(4 * phase)
			samples[int(RATE * start) + i] += 0.5 * envelope * voice
	peak = max(abs(s) for s in samples)
	OUT.parent.mkdir(parents=True, exist_ok=True)
	with wave.open(str(OUT), "wb") as file:
		file.setnchannels(1)
		file.setsampwidth(2)
		file.setframerate(RATE)
		file.writeframes(b"".join(struct.pack("<h", int(s / peak * 0.8 * 32767)) for s in samples))
	print(OUT)


if __name__ == "__main__":
	main()
