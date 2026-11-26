"""Try the voice commands without the slideshow: what the speech model hears, and the command it makes of it.

	.venv/bin/python tools/voice_test.py                              listen to the microphone (Ctrl+C to stop)
	.venv/bin/python tools/voice_test.py --say "hey katinka pause"    let the TV's own voice (piper) say it
	.venv/bin/python tools/voice_test.py --file recording.wav         a recording (16-bit mono WAV)
	.venv/bin/python tools/voice_test.py --list                       everything it listens for

Uses [voice] in config/config.toml (the model, the recorder, the wake words), also while enabled = false there.
Each line shows what Vosk heard, how sure it was of each word (0-1, below min_confidence it's ignored), and the
command, if any. "[unk]" is speech that isn't a command: that is what most talk in the room should give.
A good test: play music on the TV, talk across the room, and see that nothing turns into a command.
"""

from __future__ import annotations

import argparse
import io
import subprocess
import sys
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from francken_tv.config import load_config, project_path   # noqa: E402
from francken_tv.menu import EXTRA   # noqa: E402
from francken_tv.voice import RATE, SLIDE_NAMES, Listener, Settings, Understanding, grammar, phrases   # noqa: E402


def spoken(text: str) -> tuple[int, bytes]:
	"""The TV's voice saying `text`: (sample rate, 16-bit mono sound)."""
	from piper import PiperVoice
	announcer = load_config().get("announcer", {})
	voice = PiperVoice.load(str(project_path(announcer.get("voices_folder", "media/voices")) / f"{announcer.get('voice', 'en_US-ryan-high')}.onnx"))
	buffer = io.BytesIO()
	with wave.open(buffer, "wb") as file:
		voice.synthesize_wav(text, file)
	buffer.seek(0)
	return read_wav(buffer)


def read_wav(file) -> tuple[int, bytes]:
	with wave.open(file) as recording:
		if recording.getnchannels() != 1 or recording.getsampwidth() != 2:
			raise SystemExit("Needs a 16-bit mono WAV (ffmpeg -i in.wav -ac 1 -ar 16000 -sample_fmt s16 out.wav)")
		return recording.getframerate(), recording.readframes(recording.getnframes())


def main() -> None:
	parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
	group = parser.add_mutually_exclusive_group()
	group.add_argument("--say", metavar="TEXT", help="say this with piper instead of listening")
	group.add_argument("--file", type=Path, help="a 16-bit mono WAV recording instead of the microphone")
	group.add_argument("--list", action="store_true", help="print every phrase it listens for")
	args = parser.parse_args()

	settings = Settings.from_config({**load_config().get("voice", {}), "enabled": True})
	# Every slide type with a spoken name, as if they were all in the rotation.
	slides = {name: name.replace("_", " ").capitalize() for name in SLIDE_NAMES}
	slides.update({extra: label or extra.capitalize() for extras in EXTRA.values() for extra, label in extras})
	commands = phrases(slides)
	if args.list:
		print("\n".join(f"{settings.wake} {phrase}" for phrase in commands))
		return

	def heard(command: dict) -> None:
		print(f"    -> {command}" if command["do"] != "listening" else "    (listening...)", flush=True)

	def trace(result: dict) -> None:
		words = result.get("result") or []
		sure = " ".join(f"{word['word']}({word['conf']:.2f})" for word in words) or result["text"]
		print(f"heard: {sure}", flush=True)

	listener = Listener(settings, commands, heard)
	loaded = listener.load()
	if loaded is None:
		raise SystemExit(listener.problem)
	vosk, model = loaded
	understanding = Understanding(settings, commands)
	print(f"{len(grammar(settings.wake, commands))} phrases; say \"{settings.wake}\" and a command", flush=True)
	if args.say or args.file:
		rate, sound = spoken(args.say) if args.say else read_wav(args.file)
		listener.follow(io.BytesIO(sound), listener.recognizer(vosk, model, rate), understanding, trace)
		return
	process = subprocess.Popen(settings.record, stdout=subprocess.PIPE)
	print(f"Recording with: {' '.join(settings.record)} (Ctrl+C to stop)", flush=True)
	try:
		listener.follow(process.stdout, listener.recognizer(vosk, model, RATE), understanding, trace)
	except KeyboardInterrupt:
		pass
	finally:
		process.kill()
	if process.wait() not in (0, -9) and process.returncode is not None:
		print(f"The recorder stopped (exit code {process.returncode}): is a microphone plugged in? (arecord -l)")


if __name__ == "__main__":
	main()
