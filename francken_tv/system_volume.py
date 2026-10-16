"""The TV PC's main sound output: the volume and mute in the menu's Settings (Esc).

Everything that makes sound on the TV PC goes through it: the speech and bieruur song (ffplay)
and Spotify (spotifyd, deploy/spotifyd.conf). Uses wpctl (PipeWire, Ubuntu 22.10 and newer) or
pactl (PulseAudio); without either, only the slideshow's own sounds follow the settings.
"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess

log = logging.getLogger(__name__)


class SystemVolume:
	def __init__(self) -> None:
		self.wpctl = shutil.which("wpctl")
		self.pactl = None if self.wpctl else shutil.which("pactl")
		if not (self.wpctl or self.pactl):
			log.warning("Neither wpctl nor pactl found: the volume in the menu only changes the slideshow's own sounds")

	@property
	def available(self) -> bool:
		return bool(self.wpctl or self.pactl)

	def get(self) -> tuple[int, bool] | None:
		"""(volume 0-100, muted) of the output right now, or None if it can't be read."""
		try:
			if self.wpctl:   # "Volume: 0.40" or "Volume: 0.40 [MUTED]"
				output = self.output([self.wpctl, "get-volume", "@DEFAULT_AUDIO_SINK@"])
				match = re.search(r"Volume:\s*([\d.]+)", output)
				return (round(float(match.group(1)) * 100), "MUTED" in output) if match else None
			if self.pactl:   # "Volume: front-left: 26214 /  40% / ..." and "Mute: yes"
				match = re.search(r"(\d+)%", self.output([self.pactl, "get-sink-volume", "@DEFAULT_SINK@"]))
				muted = "yes" in self.output([self.pactl, "get-sink-mute", "@DEFAULT_SINK@"])
				return (int(match.group(1)), muted) if match else None
		except (OSError, subprocess.SubprocessError) as error:
			log.warning("Could not read the sound output: %s", error)
		return None

	def set(self, volume: int, muted: bool) -> None:
		"""volume: 0-100."""
		if self.wpctl:
			self.run([self.wpctl, "set-volume", "@DEFAULT_AUDIO_SINK@", f"{volume / 100:.2f}"])
			self.run([self.wpctl, "set-mute", "@DEFAULT_AUDIO_SINK@", "1" if muted else "0"])
		elif self.pactl:
			self.run([self.pactl, "set-sink-volume", "@DEFAULT_SINK@", f"{volume}%"])
			self.run([self.pactl, "set-sink-mute", "@DEFAULT_SINK@", "1" if muted else "0"])

	def output(self, command: list[str]) -> str:
		return subprocess.run(command, check=True, capture_output=True, text=True, timeout=5).stdout

	def run(self, command: list[str]) -> None:
		try:
			subprocess.run(command, check=True, capture_output=True, timeout=5)
		except (OSError, subprocess.SubprocessError) as error:
			log.warning("Could not change the sound output (%s): %s", " ".join(command), error)
