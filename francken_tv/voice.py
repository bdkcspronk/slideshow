"""Voice commands: say "Hey Katinka, ..." (Katinka is the TV PC) near the TV PC's microphone.

	pause, stop                     pause the music          play, resume, continue   play the music (Spotify)
	pause the slides / slideshow    pause the slideshow      play the slides, ...     go on with the slides
	next, next slide                the next slide           back, previous           the slide before
	skip, next song                 the next song (Spotify)  previous song            the song before (Spotify)
	mute, sound off                 all sound off            sound on                 all sound on
	menu                            open the menu (Esc)      close, close the menu    close it
	go to <slide>, show me <slide>  that slide now, e.g. "go to the weather", "show me spotify"
	help, what can I say            a panel of examples; it then listens HELP_SECONDS without "Hey Katinka"

"Hey Katinka" on its own, or after a command, keeps listening for follow_up_seconds: then the next command
works without "Hey Katinka" ("Hey Katinka" ... "next" ... "next" ... "pause"). Several in one go work too:
"Hey Katinka, next, next".

Speech recognition is Vosk (pip install vosk), offline: the sound never leaves the TV PC and nothing is kept.
It only listens for the phrases below, so anything else people say comes out as "[unk]" and is ignored. The
model (media/voice-model/, not in git) is a download: see docs/setup/voice.md. The microphone is read with
arecord ([voice] record in config.toml).

Mute, sound on, pause, play, skip and previous song (the music on Spotify, not the slideshow) are done here; the rest goes to the browser
through /api/voice (player.js, "Voice commands"), which does what the same key would do. Every command goes there,
to show what was heard; one that failed as {"do": "failed", "said": why}.
"""

from __future__ import annotations

import json
import logging
import subprocess
import threading
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable

from .config import project_path

if TYPE_CHECKING:
	from .app import App

log = logging.getLogger(__name__)

RATE = 16000                 # samples per second: what the recorder sends and Vosk expects
CHUNK = RATE // 4 * 2        # a quarter of a second of 16-bit sound
RETRY_SECONDS = 30           # the microphone gone (unplugged): try again this often
WAIT_SECONDS = 20            # /api/voice waits this long for a command before answering "nothing"
HELP_SECONDS = 20            # after "help": the examples stay this long, and one works without "Hey Katinka"
# The slides "help" gives as examples of "go to ...": the first four of these there are, and what to say.
HELP_SLIDES = {"weather": "the weather", "buses": "the buses", "spotify": "the music", "puzzles": "the puzzles",
	"news": "the news", "activities": "the activities", "event_photos": "the photos", "leaderboard": "the leaderboard"}

# What to say for each slide type, after "go to" or "show me". Only words the speech model knows: Vosk drops
# a word it doesn't know ("wordle", "catfishing", "compucie"), so those get a word that sounds the same, or
# none. Check a new name with tools/voice_test.py --say "hey katinka go to ...".
SLIDE_NAMES = {
	"images": ["posters", "the posters"],
	"activities": ["activities", "the activities"],
	"practice": ["practice", "practice sessions"],
	"news": ["news", "the news"],
	"weather": ["weather", "the weather"],
	"rain": ["rain", "the rain"],
	"buses": ["buses", "the buses", "the bus"],
	"timetable": ["timetable", "the timetable"],
	"event_photos": ["photos", "the photos"],
	"presence": ["presence", "who is here"],
	"leaderboard": ["leaderboard", "the leaderboard"],
	"puzzles": ["puzzles", "the puzzles"],
	"connections": ["connections"],
	"wordle": ["world"],                      # "wordle" isn't a word it knows: it hears "world"
	"catfishing": ["cat fishing"],
	"timeguessr": ["time guesser"],
	"spotify": ["spotify", "music", "the music"],
	"spotify-lyrics": ["lyrics", "the lyrics"],
	"books": ["books", "the books"],
	"quote": ["quote", "a quote"],
	"commandments": ["commandments", "the commandment"],
	"confidential": ["confidential", "confidential contacts"],
	"ero": ["emergency", "emergency response"],
	"poll": ["poll", "dilemma", "the dilemma"],
	"pet": ["pet", "the pet"],
	"xkcd": ["xkcd"],
	"graafmachine": ["digger", "the digger", "excavator"],
	"membership": ["membership"],
	"socks": ["socks", "the socks"],
	"socials": ["socials"],
	"instagram": ["instagram"],
	"bieruur_countdown": ["countdown", "beer hour", "the countdown"],
}
GO = ["go to", "show me", "open"]
COMMANDS = {
	"pause": ["pause", "stop", "pause the music", "stop the music"],
	"resume": ["play", "resume", "continue", "play the music", "play music"],
	"next": ["next", "next slide"],
	"skip": ["skip", "skip the song", "skip this song", "next song"],
	"previous_song": ["previous song", "the previous song", "last song", "the last song", "the song before", "song before"],
	"previous": ["back", "previous", "go back"],
	# "slide show" too: in case the speech model only knows the two words
	"pause_slides": [f"{verb} {the}{slides}" for verb in ("pause", "stop") for the in ("", "the ") for slides in ("slides", "slideshow", "slide show")],
	"resume_slides": [f"{verb} {the}{slides}" for verb in ("play", "resume", "continue", "start") for the in ("", "the ")
		for slides in ("slides", "slideshow", "slide show")],
	"mute": ["mute", "sound off"],
	"unmute": ["sound on"],
	"menu": ["menu", "open the menu"],
	"close": ["close", "close the menu"],
	"help": ["help", "what can i say", "what can you do"],
}
SAID = {"pause": "Pause the music", "resume": "Play the music", "skip": "Skip the song", "previous_song": "The song before", "pause_slides": "Pause the slideshow", "resume_slides": "Play the slideshow", "next": "Next", "previous": "Back", "mute": "Sound off",
	"unmute": "Sound on", "menu": "Menu", "close": "Close", "help": "Help"}   # what the screen shows was heard


@dataclass
class Settings:
	enabled: bool = False
	model: str = "media/voice-model/vosk-model-small-en-us-0.15"
	record: list[str] = field(default_factory=lambda: ["arecord", "-q", "-t", "raw", "-f", "S16_LE", "-c", "1", "-r", str(RATE)])
	# The English model knows "katinka" and hears a Dutch "Kathinka" as it, but often misses a Dutch "Hé" or "Hee"
	# (or hears "he"): so "Katinka" alone wakes it too.
	wake: list[str] = field(default_factory=lambda: ["hey katinka", "he katinka", "katinka"])
	follow_up_seconds: float = 8
	min_confidence: float = 0.75   # every word of the command at least this sure: lower ones are talk that sounds like it
	wake_confidence: float = 0.5   # the wake words: a Dutch "Kathinka" scores lower than an English one, and talk doesn't get here

	def __post_init__(self) -> None:
		if isinstance(self.wake, str):
			self.wake = [self.wake]

	@classmethod
	def from_config(cls, config: dict) -> Settings:
		known = {name for name in cls.__dataclass_fields__}
		unknown = sorted(set(config) - known)
		if unknown:
			raise SystemExit(f"Unknown settings in [voice]: {unknown}. Known: {sorted(known)}")
		return cls(**config)


def phrases(slides: dict[str, str]) -> dict[str, dict]:
	"""Everything that can be said after the wake words -> the command: {"do": ...} and for "go", "slide" and
	"label". `slides`: slide type -> its name on screen, for the slide types there are."""
	found = {}
	for do, said in COMMANDS.items():
		for phrase in said:
			found[phrase] = {"do": do, "said": SAID[do]}
	for slide, label in slides.items():
		for name in SLIDE_NAMES.get(slide, []):
			for go in GO:
				found[f"{go} {name}"] = {"do": "go", "slide": slide, "said": f"Go to {label}"}
	return found


def grammar(wakes: list[str], commands: dict[str, dict]) -> list[str]:
	"""Vosk's list of what it may hear: the wake words with or without a command, a command on its own (a follow-up),
	and "[unk]" for everything else."""
	return [*wakes, *(f"{wake} {phrase}" for wake in wakes for phrase in commands), *commands, "[unk]"]


class Commands:
	"""The commands heard, numbered, for the browser to fetch (/api/voice). Keeps the last few."""

	def __init__(self) -> None:
		self.items: list[tuple[int, dict]] = []
		self.last = 0
		self.changed = threading.Condition()

	def put(self, command: dict) -> None:
		with self.changed:
			self.last += 1
			self.items = [*self.items[-19:], (self.last, command)]
			self.changed.notify_all()

	def after(self, number: int, wait: float = WAIT_SECONDS) -> dict:
		"""{"commands": [...], "last": n}: those after `number`, waiting up to `wait` seconds for one. A number
		that isn't ours (-1, or from before a restart) gets no old commands, only the number to go on from."""
		with self.changed:
			if not 0 <= number <= self.last:
				return {"commands": [], "last": self.last}
			self.changed.wait_for(lambda: self.last > number, timeout=wait)
			return {"commands": [command for n, command in self.items if n > number], "last": self.last}


class Understanding:
	"""From what Vosk heard to a command: needs the wake words, or a command within follow_up_seconds of the last one."""

	def __init__(self, settings: Settings, commands: dict[str, dict], clock: Callable[[], float] = time.monotonic) -> None:
		self.settings = settings
		self.commands = commands
		self.wakes = [wake.split() for wake in settings.wake]
		self.clock = clock
		self.awake_until = 0.0

	def hear(self, result: dict) -> list[dict]:
		"""A Vosk result ({"text", "result": [{"word", "conf"}, ...]}) -> the commands in it (in the order said),
		[{"do": "listening"}] for the wake words alone, [{"do": "unclear"}] for the wake words and something it
		couldn't make out, or []."""
		words = result.get("result") or [{"word": word} for word in result.get("text", "").split()]
		said = [word["word"] for word in words]
		wake = self.wake_at(said)
		start, end = wake or (len(said), len(said))
		sure = [self.settings.wake_confidence if start <= at < end else self.settings.min_confidence for at in range(len(said))]
		if any(word.get("conf", 1) < least for word, least in zip(words, sure) if word["word"] != "[unk]"):
			log.debug("Not sure enough: %s", words)
			return []
		if wake is not None:
			said = said[end:]   # what was said before "Hey Katinka" wasn't for us
		elif self.clock() > self.awake_until:
			return []   # a command without the wake words: only right after another one
		if wake is None and (not said or "[unk]" in said):
			return []   # talk, while it was still listening for a next command
		self.awake_until = self.clock() + self.settings.follow_up_seconds
		if not said:
			return [{"do": "listening"}]
		commands = self.split(said)
		if commands is None:
			return [{"do": "unclear"}]
		if commands[-1]["do"] == "help":   # time to read the examples and say one
			self.awake_until = self.clock() + max(HELP_SECONDS, self.settings.follow_up_seconds)
		return commands

	def wake_at(self, said: list[str]) -> tuple[int, int] | None:
		"""Where the (last) wake words are in what was said, (start, end), or None. Of "hey katinka" and "katinka" at
		the same place, the longer."""
		found = [(at, at + len(wake)) for wake in self.wakes for at in range(len(said) - len(wake) + 1)
			if said[at:at + len(wake)] == wake]
		return max(found, key=lambda place: (place[1], -place[0])) if found else None

	def split(self, said: list[str]) -> list[dict] | None:
		"""The commands one after another ("next next" is two), or None if anything else is in it."""
		commands = []
		at = 0
		while at < len(said):
			for end in range(len(said), at, -1):   # the longest phrase first: "go back", not "go"
				command = self.commands.get(" ".join(said[at:end]))
				if command is not None:
					commands.append(dict(command))
					at = end
					break
			else:
				return None
		return commands


class Listener:
	"""Reads the microphone in the background and hands each command to `heard` (Voice.heard)."""

	def __init__(self, settings: Settings, commands: dict[str, dict], heard: Callable[[dict], None]) -> None:
		self.settings = settings
		self.commands = commands
		self.heard = heard
		self.problem: str | None = None   # for /health
		self.process: subprocess.Popen | None = None
		self.stopped = threading.Event()

	def start(self) -> None:
		threading.Thread(target=self.run, name="voice", daemon=True).start()

	def stop(self) -> None:
		self.stopped.set()
		if self.process:
			self.process.kill()

	def load(self):
		try:
			import vosk
		except ImportError:
			self.problem = "vosk is not installed (.venv/bin/pip install vosk)"
			return None
		path = project_path(self.settings.model)
		if not path.is_dir():
			self.problem = f"the speech model {path} is missing (docs/setup/voice.md)"
			return None
		vosk.SetLogLevel(-1)
		return vosk, vosk.Model(str(path))

	def run(self) -> None:
		loaded = self.load()
		if loaded is None:
			log.warning("No voice commands: %s", self.problem)
			return
		vosk, model = loaded
		understanding = Understanding(self.settings, self.commands)
		log.info("Listening for \"%s\" (%d commands)", self.settings.wake[0], len(self.commands))
		while not self.stopped.is_set():
			try:
				self.listen(self.recognizer(vosk, model), understanding)
			except OSError as error:
				self.problem = f"can't record from the microphone: {error}"
			if not self.stopped.is_set():
				log.warning("Voice commands: %s; trying again in %d s", self.problem, RETRY_SECONDS)
				self.stopped.wait(RETRY_SECONDS)

	def recognizer(self, vosk, model, rate: int = RATE):
		recognizer = vosk.KaldiRecognizer(model, rate, json.dumps(grammar(self.settings.wake, self.commands)))
		recognizer.SetWords(True)   # each word with how sure it is
		return recognizer

	def listen(self, recognizer, understanding: Understanding) -> None:
		"""Until the recorder stops (the microphone unplugged)."""
		self.process = subprocess.Popen(self.settings.record, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
		self.follow(self.process.stdout, recognizer, understanding)
		error = self.process.stderr.read().decode(errors="replace").strip() if self.process.stderr else ""
		self.process.wait()
		self.problem = f"the recorder stopped ({error or f'exit code {self.process.returncode}'})"

	def follow(self, sound_in, recognizer, understanding: Understanding, trace: Callable[[dict], None] | None = None) -> None:
		"""Feed the sound from `sound_in` (16-bit mono) to Vosk until it ends, and hand on each command.
		`trace` gets every sentence Vosk made of it (tools/voice_test.py shows them)."""
		woke = False   # the wake words heard in this sentence already: the screen shows it's listening
		while not self.stopped.is_set():
			sound = sound_in.read(CHUNK)
			if not sound:
				break
			self.problem = None
			if recognizer.AcceptWaveform(sound):
				self.understand(json.loads(recognizer.Result()), understanding, trace, woke)
				woke = False
			elif not woke and any(wake in json.loads(recognizer.PartialResult()).get("partial", "") for wake in self.settings.wake):
				woke = True
				self.heard({"do": "listening"})   # before the sentence is finished: it feels quicker
		self.understand(json.loads(recognizer.FinalResult()), understanding, trace, woke)

	def understand(self, result: dict, understanding: Understanding, trace: Callable[[dict], None] | None, woke: bool = False) -> None:
		"""`woke`: the screen shows it's listening (the wake words were in the sentence so far). Then it always gets
		an answer: if the sentence came to nothing (not sure enough, or the name turned out to be another word), "unclear"."""
		if trace and result.get("text"):
			trace(result)
		commands = understanding.hear(result)
		if woke and not commands:
			commands = [{"do": "unclear"}]
		for command in commands:
			self.heard(command)


class Voice:
	"""The voice commands of the slideshow: the listener, and the commands for the browser."""

	def __init__(self, app: App, settings: Settings) -> None:
		self.app = app
		self.settings = settings
		self.commands = Commands()
		labels = slide_labels(app)
		self.listener = Listener(settings, phrases(labels), self.heard)
		self.help_slides = [said for slide, said in HELP_SLIDES.items() if slide in labels][:4]   # "go to ..." examples

	def start(self) -> None:
		self.listener.start()

	def warnings(self) -> list[str]:
		problem = self.listener.problem
		return [problem] if problem else []

	def heard(self, command: dict) -> None:
		if command["do"] == "listening":
			command = {**command, "seconds": self.settings.follow_up_seconds}   # the screen: "didn't hear anything" after that
		elif command["do"] == "help":
			command = {**command, "seconds": max(HELP_SECONDS, self.settings.follow_up_seconds), "slides": self.help_slides}
		elif command["do"] != "unclear":
			log.info("Heard: %s", command["said"])
		if command["do"] in ("mute", "unmute"):
			try:
				self.app.read_sound()
				self.app.change_settings({"muted": command["do"] == "mute"})
			except Exception:
				log.exception("Voice command %s failed", command["do"])
		if command["do"] in ("pause", "resume", "skip", "previous_song"):
			command = self.music(command)
		self.commands.put(command)

	def music(self, command: dict) -> dict:
		"""Pause or play the music on Spotify, as its ⏯ button does (providers/spotify.py: "toggle"; with nothing
		played yet it starts the account's last music on our speaker), or skip the song (⏭) or go back one (⏮). The command back,
		or "failed" and why."""
		spotify = self.app.providers.get("spotify")
		if spotify is None or not spotify.connected:
			return {"do": "failed", "said": "Spotify isn't connected"}
		pause = command["do"] == "pause"
		playing = bool(spotify.playing and spotify.playing.is_playing)
		if command["do"] in ("skip", "previous_song"):
			if not spotify.playing:
				return {**command, "said": "No music is playing"}
		elif pause and not playing:
			return {**command, "said": "The music is already paused" if spotify.playing else "No music is playing"}
		elif not pause and playing:
			return {**command, "said": "The music is already playing"}
		try:
			action = {"skip": "skip", "previous_song": "previous"}.get(command["do"], "toggle")   # the names in providers/spotify.py
			_, error = spotify.action(action, [], self.app.clock.now())
		except Exception:
			log.exception("Voice command %s failed", command["do"])
			error = "Spotify can't be reached right now"
		return {"do": "failed", "said": error} if error else command


def slide_labels(app: App) -> dict[str, str]:
	"""Every slide type there is and the extra slides of the menu (wordle, rain) -> its name on screen. One out of season
	(membership) gets the menu's "nothing to show right now"."""
	from .menu import EXTRA
	labels = {}
	for name, provider in app.providers.items():
		labels[name] = provider.title or name.replace("_", " ").capitalize()
		for extra, label in EXTRA.get(name, []):
			known = app.providers.get(extra)
			labels[extra] = label or (known.title if known else "") or extra.capitalize()
	return labels
