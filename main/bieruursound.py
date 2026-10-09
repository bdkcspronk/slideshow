import random
import shutil
import subprocess
import sys
from datetime import datetime, timedelta

from .config import (
	AUDIO_BIERUUR_HOUR,
	AUDIO_BIERUUR_MINUTE,
	AUDIO_OFFSETS,
	AUDIO_SELECTION_MINUTES_BEFORE,
)


class BieruurSoundMixin:
	def choose_song(self, now: datetime) -> None:
		if not self.audio or self.selected_audio_date == now.date():
			return
		selection_time = now.replace(
			hour=AUDIO_BIERUUR_HOUR,
			minute=AUDIO_BIERUUR_MINUTE,
			second=0,
			microsecond=0,
		) - timedelta(minutes=AUDIO_SELECTION_MINUTES_BEFORE)
		if now >= selection_time:
			self.selected_song = random.choice(self.audio)
			self.selected_audio_date = now.date()

	def check_audio(self) -> None:
		now = datetime.now()
		self.choose_song(now)
		if self.selected_song is not None and self.last_audio_date != now.date():
			bieruur = now.replace(
				hour=AUDIO_BIERUUR_HOUR,
				minute=AUDIO_BIERUUR_MINUTE,
				second=0,
				microsecond=0,
			)
			offset = AUDIO_OFFSETS.get(self.selected_song.name, 0.0)
			if now >= bieruur + timedelta(seconds=offset):
				if self.play_selected_song():
					self.last_audio_date = now.date()
		self.root.after(15_000, self.check_audio)

	def play_selected_song(self) -> bool:
		player = shutil.which("ffplay")
		if player is None:
			print("Could not play audio: ffplay was not found", file=sys.stderr)
			return False
		if self.selected_song is None:
			return False
		if self.audio_process is not None and self.audio_process.poll() is None:
			self.audio_process.terminate()
		self.audio_process = subprocess.Popen(
			[
				player,
				"-nodisp",
				"-autoexit",
				"-loglevel",
				"error",
				str(self.selected_song),
			],
			stdout=subprocess.DEVNULL,
			stderr=subprocess.PIPE,
		)
		return True