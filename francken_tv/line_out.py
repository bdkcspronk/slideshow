"""Keeps the sound on the TV PC's line-out (the speakers), not the TV's HDMI sound.

At startup the PC often picks HDMI (the TV is connected), and plugging in the speakers doesn't always
switch back. Every 30 seconds this checks the sound output and, if needed:
1. puts the sound card on its analog profile (on most PCs analog and HDMI are profiles of one card,
   and only one can be on),
2. picks its Line Out port when it has one that isn't unplugged,
3. makes that output the default, so Spotify, speech and the bieruur song play there.
In the sound settings that's e.g. "Line Out - Built-in Audio": the card's analog-output-lineout port.
Works with PipeWire (wpctl, pw-dump; Ubuntu 22.10 and newer) and PulseAudio (pactl; Ubuntu 22.04).
The decision (`plan`) is separate from reading and changing the sound, so it can be tested.

Settings: [sound] in config.toml.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime

from .slides import Job

log = logging.getLogger(__name__)

ANALOG_PROFILES = ["output:analog-stereo+input:analog-stereo", "output:analog-stereo"]   # best first
LINE_OUT = "lineout"   # in the port's name, e.g. "analog-output-lineout"


@dataclass
class Port:
	name: str
	available: bool | None   # None: unknown (no jack detection)
	index: int = 0           # PipeWire's route index


@dataclass
class Card:
	id: str                  # PipeWire object id or PulseAudio card name
	profiles: dict[str, bool | None]   # name -> available
	active_profile: str
	profile_index: dict[str, int] = field(default_factory=dict)   # PipeWire: name -> index


@dataclass
class Sink:
	id: str                  # PipeWire object id or PulseAudio sink name
	name: str
	card: str | None         # the card's id
	ports: list[Port]
	active_port: str | None


@dataclass
class Sound:
	cards: list[Card]
	sinks: list[Sink]
	default_sink: str | None   # its name


def plan(sound: Sound) -> list[tuple]:
	"""What to change to play on the line-out: ("profile", card, profile), ("port", sink, port) and/or
	("default", sink). Nothing when it's already right, or when there's no analog output at all."""
	analog = [sink for sink in sound.sinks if ".analog-" in sink.name]
	if not analog:
		# No analog output: the card may be on HDMI. Switch the first card that can do analog.
		for card in sound.cards:
			profile = next((p for p in ANALOG_PROFILES if p in card.profiles and card.profiles[p] is not False), None)
			if profile and card.active_profile != profile:
				return [("profile", card, profile)]
		return []
	sink = analog[0]
	steps: list[tuple] = []
	line_out = next((port for port in sink.ports if LINE_OUT in port.name and port.available is not False), None)
	if line_out and sink.active_port != line_out.name:
		steps.append(("port", sink, line_out))
	if sound.default_sink != sink.name:
		steps.append(("default", sink))
	return steps


# ---- PipeWire ---------------------------------------------------------------------------------

def available(value: str | None) -> bool | None:
	return {"yes": True, "no": False}.get(value or "")


def parse_pw_dump(objects: list[dict]) -> Sound:
	cards, sinks, default = [], [], None
	routes: dict[int, list[Port]] = {}
	active_routes: dict[int, str] = {}
	for o in objects:
		info, props = o.get("info") or {}, (o.get("info") or {}).get("props") or {}
		if o.get("type", "").endswith(":Device") and props.get("media.class") == "Audio/Device":
			params = info.get("params") or {}
			profiles = {p["name"]: available(p.get("available")) for p in params.get("EnumProfile", []) if "name" in p}
			active = next((p.get("name", "") for p in params.get("Profile", [])), "")
			cards.append(Card(str(o["id"]), profiles, active, {p["name"]: p["index"] for p in params.get("EnumProfile", []) if "name" in p}))
			routes[o["id"]] = [Port(r["name"], available(r.get("available")), r.get("index", 0))
				for r in params.get("EnumRoute", []) if r.get("direction") == "Output" and "name" in r]
			active_routes[o["id"]] = next((r.get("name") for r in params.get("Route", []) if r.get("direction") == "Output"), None)
		elif o.get("type", "").endswith(":Metadata") and (o.get("props") or props).get("metadata.name") == "default":
			for entry in o.get("metadata") or []:
				if entry.get("key") == "default.audio.sink":
					value = entry.get("value")
					default = value.get("name") if isinstance(value, dict) else None
	for o in objects:
		props = (o.get("info") or {}).get("props") or {}
		if props.get("media.class") == "Audio/Sink" and "node.name" in props:
			device = props.get("device.id")
			sinks.append(Sink(str(o["id"]), props["node.name"], str(device) if device is not None else None,
				routes.get(device, []), active_routes.get(device)))
	return Sound(cards, sinks, default)


# ---- PulseAudio -------------------------------------------------------------------------------

def parse_pactl(cards_text: str, sinks_text: str, default_sink: str) -> Sound:
	"""`pactl list cards`, `pactl list sinks` and `pactl get-default-sink`."""
	def blocks(text: str, start: str) -> list[list[str]]:
		found: list[list[str]] = []
		for line in text.splitlines():
			if line.startswith(start):
				found.append([])
			elif found:
				found[-1].append(line)
		return found

	def section(lines: list[str], title: str) -> list[str]:
		"""The lines under '\\tTitle:' (indented two tabs), e.g. the profiles or ports."""
		out, inside = [], False
		for line in lines:
			if line.startswith("\t") and not line.startswith("\t\t"):
				inside = line.strip() == f"{title}:"
			elif inside and line.startswith("\t\t") and not line.startswith("\t\t\t"):
				out.append(line)
		return out

	def value(lines: list[str], key: str) -> str | None:
		return next((line.split(":", 1)[1].strip() for line in lines if line.startswith(f"\t{key}:")), None)

	def item(line: str) -> tuple[str, bool | None]:
		name = line.strip().split(": ", 1)[0]   # "output:analog-stereo: Analog Stereo Output (...)"
		if "not available" in line or "available: no" in line:
			return name, False
		if "available: yes" in line or line.rstrip().endswith("available)"):
			return name, True
		return name, None

	cards = []
	for lines in blocks(cards_text, "Card #"):
		name = value(lines, "Name") or ""
		cards.append(Card(name, dict(item(line) for line in section(lines, "Profiles")), value(lines, "Active Profile") or ""))
	sinks = []
	for lines in blocks(sinks_text, "Sink #"):
		name = value(lines, "Name") or ""
		sinks.append(Sink(name, name, None, [Port(*item(line)) for line in section(lines, "Ports")], value(lines, "Active Port")))
	return Sound(cards, sinks, default_sink.strip() or None)


# ---- reading and changing the sound -----------------------------------------------------------

class LineOut(Job):
	name = "line_out"

	def __init__(self, settings: dict) -> None:
		self.enabled = settings.get("line_out", True)
		self.every = settings.get("check_seconds", 30)
		self.pw = shutil.which("pw-dump") and shutil.which("wpctl")
		self.pa = None if self.pw else shutil.which("pactl")
		self.next_check = 0.0
		if self.enabled and not (self.pw or self.pa):
			log.info("Neither PipeWire (pw-dump, wpctl) nor PulseAudio (pactl): the sound output isn't switched to the line-out")

	def tick(self, now: datetime) -> None:
		if not self.enabled or not (self.pw or self.pa) or time.monotonic() < self.next_check:
			return
		self.next_check = time.monotonic() + self.every
		for _ in range(3):   # a profile switch makes the analog output appear: then its port and default
			steps = plan(self.read())
			if not steps:
				return
			for step in steps:
				self.change(step)
			time.sleep(0.5)

	def output(self, *command: str) -> str:
		return subprocess.run(command, check=True, capture_output=True, text=True, timeout=5).stdout

	def read(self) -> Sound:
		if self.pw:
			return parse_pw_dump(json.loads(self.output("pw-dump")))
		return parse_pactl(self.output("pactl", "list", "cards"), self.output("pactl", "list", "sinks"),
			self.output("pactl", "get-default-sink"))

	def change(self, step: tuple) -> None:
		kind, target, *rest = step
		if kind == "profile":
			log.info("Sound: switching %s to %s (the line-out)", target.id, rest[0])
			if self.pw:
				command = ("wpctl", "set-profile", target.id, str(target.profile_index[rest[0]]))
			else:
				command = ("pactl", "set-card-profile", target.id, rest[0])
		elif kind == "port":
			log.info("Sound: using the %s port", rest[0].name)
			if self.pw:
				command = ("wpctl", "set-route", target.id, str(rest[0].index))
			else:
				command = ("pactl", "set-sink-port", target.id, rest[0].name)
		else:
			log.info("Sound: playing on %s", target.name)
			command = ("wpctl", "set-default", target.id) if self.pw else ("pactl", "set-default-sink", target.id)
		try:
			self.output(*command)
		except (OSError, subprocess.SubprocessError) as error:
			log.warning("Could not switch the sound (%s): %s", " ".join(command), error)
		if kind == "default" and self.pa:   # PulseAudio doesn't move what's already playing by itself
			for line in self.output("pactl", "list", "short", "sink-inputs").splitlines():
				self.output("pactl", "move-sink-input", line.split()[0], target.id)
