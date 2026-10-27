"""All sound: spoken greetings and quotes (text-to-speech with piper) and the bieruur song.

Speech is queued and played one sentence at a time in a background thread.
Music plays immediately, independently of speech.

The voice is a piper model in media/voices/. If it is missing it is downloaded, once (tried again
every 10 minutes if that fails); until it is there nothing is spoken. /status and /health say so.
"""

from __future__ import annotations

import hashlib
import importlib.util
import io
import logging
import queue
import re
import shutil
import subprocess
import threading
import time
import wave
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

log = logging.getLogger(__name__)

# Silence before and after speech, so the speaker doesn't cut off the first word.
PADDING_SECONDS = 0.3

VOICES_URL = "https://huggingface.co/rhasspy/piper-voices/resolve/main"
DOWNLOAD_RETRY_SECONDS = 600   # a voice that couldn't be downloaded is tried again this often (when something is spoken)


def voice_urls(voice: str) -> list[str]:
	"""Where piper's voice "en_US-ryan-high" is: the .onnx.json first, so a .onnx on disk is always complete."""
	language, name, quality = voice.split("-", 2)
	base = f"{VOICES_URL}/{language.split('_')[0]}/{language}/{name}/{quality}/{voice}"
	return [base + ".onnx.json", base + ".onnx"]


class Announcer:
	def __init__(self, settings: dict, voices_folder: Path, cache_folder: Path) -> None:
		self.voice = settings.get("voice", "en_US-ryan-high")
		self.voices_folder = voices_folder
		self.volume = settings.get("volume", 100)
		self.length_scale = settings.get("length_scale", 1.2)   # >1 speaks slower
		self.cache_folder = cache_folder
		self.cache_folder.mkdir(parents=True, exist_ok=True)
		self.quotes_enabled = False   # QuoteProvider sets this from quote.narrate in config.toml
		self.greetings_enabled = True
		self.muted = False            # no sound at all (the menu: Esc -> Settings)
		self.speech_queue: queue.Queue[tuple[str, bool]] = queue.Queue()
		self.synthesize_lock = threading.Lock()
		self.preparer = ThreadPoolExecutor(max_workers=1, thread_name_prefix="tts-prepare")
		self.music_process: subprocess.Popen | None = None
		self.player = shutil.which("ffplay")
		self.has_piper = importlib.util.find_spec("piper") is not None
		self.voice_model = None   # loaded once; loading takes a few seconds
		self.download_voice = settings.get("download_voice", True)   # fetch a missing voice model by itself
		self.download_lock = threading.Lock()
		self.last_download_try: float | None = None   # time.monotonic()
		if self.player is None:
			log.warning("ffplay not found: sound is disabled (install ffmpeg)")
		if not self.has_piper:
			log.warning("piper not found: speech is disabled (pip install piper-tts)")
		elif not self.voice_file().exists():
			log.warning("Voice model %s is missing from %s: %s", self.voice, self.voices_folder,
				"downloading it; nothing is spoken until then" if self.download_voice else "nothing is spoken (set [announcer] download_voice = true)")
		threading.Thread(target=self.speech_loop, name="speech", daemon=True).start()
		if self.has_piper:
			self.preparer.submit(self.prepare_voice)

	# Public API -------------------------------------------------------------

	def greet(self, text: str) -> None:
		if self.greetings_enabled and not self.muted:
			self.speech_queue.put((text, False))

	def say_quote(self, text: str) -> None:
		if self.quotes_enabled and not self.muted:
			self.speech_queue.put((text, True))

	def prepare(self, text: str) -> None:
		"""Generate speech ahead of time so it plays without delay later."""
		self.preparer.submit(self.synthesize, text)

	def toggle_quotes(self) -> bool:
		self.quotes_enabled = not self.quotes_enabled
		log.info("Reading quotes aloud %s", "enabled" if self.quotes_enabled else "disabled")
		return self.quotes_enabled

	def mute(self, muted: bool) -> None:
		self.muted = muted
		if muted:
			self.stop_music()

	def play_music(self, path: Path) -> bool:
		"""Starts the song (in the background); False if it can't play (no player, or muted)."""
		if self.player is None or self.muted:
			return False
		self.stop_music()
		log.info("Playing %s", path.name)
		self.music_process = subprocess.Popen(self.play_command(path), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
		return True

	def music_playing(self) -> bool:
		return self.music_process is not None and self.music_process.poll() is None

	def stop_music(self) -> None:
		if self.music_process is not None and self.music_process.poll() is None:
			self.music_process.terminate()

	def warnings(self) -> list[str]:
		"""For /status and /health: speech that can't work because the voice model is missing."""
		if self.player is None or not self.has_piper or self.voice_file().exists():
			return []   # no sound or no piper at all (a laptop): logged at startup, not a problem to report
		return [f"nothing can be spoken: the voice model {self.voice} is missing from {self.voices_folder} and could not be "
			f"downloaded (docs/06-tv-pc.md, \"The text-to-speech voice\")"]

	# Internals --------------------------------------------------------------

	def voice_file(self) -> Path:
		return self.voices_folder / f"{self.voice}.onnx"

	def prepare_voice(self) -> None:
		"""In the background: get the voice model if it's missing, then load it."""
		if not self.voice_file().exists():
			self.fetch_voice()
		if self.voice_file().exists():
			self.load_voice()

	def download_again_later(self) -> None:
		"""A voice that is still missing is tried again every few minutes, when something wants to be said."""
		if not self.download_voice or self.download_lock.locked():
			return
		if self.last_download_try is None or time.monotonic() - self.last_download_try >= DOWNLOAD_RETRY_SECONDS:
			self.last_download_try = time.monotonic()
			self.preparer.submit(self.prepare_voice)

	def fetch_voice(self) -> bool:
		if not self.download_voice:
			return False
		with self.download_lock:
			if self.voice_file().exists():
				return True
			self.last_download_try = time.monotonic()
			try:
				self.voices_folder.mkdir(parents=True, exist_ok=True)
				for url in voice_urls(self.voice):
					target = self.voices_folder / url.rsplit("/", 1)[-1]
					temporary = target.with_name(target.name + ".part")
					log.info("Downloading %s", url)
					with requests.get(url, stream=True, timeout=60) as response:
						response.raise_for_status()
						with temporary.open("wb") as file:
							for chunk in response.iter_content(1 << 20):
								file.write(chunk)
					temporary.replace(target)
			except (requests.RequestException, OSError, ValueError) as error:
				log.warning("Could not download the voice %s: %s. Trying again in %d minutes", self.voice, error, DOWNLOAD_RETRY_SECONDS // 60)
				return False
			log.info("Downloaded the voice %s: speech works", self.voice)
			return True

	def speech_loop(self) -> None:
		while True:
			text, is_quote = self.speech_queue.get()
			if self.muted:   # muted while it was waiting its turn
				self.speech_queue.task_done()
				continue
			log.info("Saying: %s", text)
			try:
				path = self.synthesize(text)
				if path is not None and self.player is not None:
					subprocess.run(self.play_command(path), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
				if path is not None and is_quote:
					path.unlink(missing_ok=True)   # quotes are rarely repeated; greetings stay cached
			except Exception:
				log.exception("Could not say %r", text)
			finally:
				self.speech_queue.task_done()

	def speech_path(self, text: str) -> Path:
		slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40]
		digest = hashlib.sha256(f"{self.voice}\n{self.length_scale}\n{text}".encode()).hexdigest()[:12]
		return self.cache_folder / f"{slug}-{digest}.wav"

	def load_voice(self):
		with self.synthesize_lock:
			if self.voice_model is None:
				from piper import PiperVoice
				self.voice_model = PiperVoice.load(self.voices_folder / f"{self.voice}.onnx")
				log.info("Loaded voice %s", self.voice)
			return self.voice_model

	def synthesize(self, text: str) -> Path | None:
		path = self.speech_path(text)
		if path.exists() or not self.has_piper:
			return path if path.exists() else None
		if not self.voice_file().exists():
			self.download_again_later()   # nothing to speak with yet: it is fetched in the background
			return None
		voice = self.load_voice()
		with self.synthesize_lock:
			if path.exists():
				return path
			buffer = io.BytesIO()
			with wave.open(buffer, "wb") as raw:
				from piper import SynthesisConfig
				voice.synthesize_wav(text, raw, syn_config=SynthesisConfig(length_scale=self.length_scale))
			buffer.seek(0)
			with wave.open(buffer, "rb") as raw:
				params, frames = raw.getparams(), raw.readframes(raw.getnframes())
			silence = b"\0" * (int(params.framerate * PADDING_SECONDS) * params.sampwidth * params.nchannels)
			temporary = path.with_suffix(".tmp")
			with wave.open(str(temporary), "wb") as padded:
				padded.setparams(params)
				padded.writeframes(silence + frames + silence)
			temporary.replace(path)
			return path

	def play_command(self, path: Path) -> list[str]:
		return [self.player, "-nodisp", "-autoexit", "-loglevel", "error", "-volume", str(self.volume), str(path)]
