from __future__ import annotations

import os
import random
import signal
import shutil
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

import tkinter as tk
from PIL import Image, ImageTk

from .bieruurcountdown import BieruurCountdownMixin
from .config import AUDIO_OFFSETS
from .normalslides import NormalSlidesMixin
from .showquotes import ShowQuotesMixin
from .vrijmibogif import VrijmiboGifMixin


class Slideshow(
	VrijmiboGifMixin,
	BieruurCountdownMixin,
	ShowQuotesMixin,
	NormalSlidesMixin,
):
	def __init__(self, root: tk.Tk, images: list[Path], image_folder: Path, seconds: float,
		shuffle: bool, quote_image: Path | None = None, vrijmibo_image: Path | None = None,
		audio: list[Path] | None = None, system_process: subprocess.Popen[bytes] | None = None) -> None:
		self.root = root
		self.images = images[:]
		self.image_folder = image_folder
		self.quote_image = quote_image
		self.vrijmibo_image = vrijmibo_image
		self.quote_generated_index: int | None = None
		self.vrijmibo_index: int | None = None
		self.beer_hour_index: int | None = None
		self.last_vrijmibo_slot: tuple[date, int, int] | None = None
		self.audio = audio or []
		self.last_audio_date: date | None = None
		self.audio_process: subprocess.Popen[bytes] | None = None
		self.system_process = system_process
		self.closed = False
		self.seconds = seconds
		self.index = 0
		self.paused = False
		self.timer_id: str | None = None
		self.beer_hour_timer_id: str | None = None
		self.beer_hour_started_at = 0.0
		self.photo: ImageTk.PhotoImage | None = None
		self.animation_image: Image.Image | None = None
		self.animation_photos: list[ImageTk.PhotoImage] = []
		self.animation_durations: list[float] = []
		self.animation_frame = 0
		self.animation_frames = 0
		self.animation_loop = 0
		self.animation_loop_count = 1
		self.animation_deadline = 0.0
		self.cached_photos: dict[Path, ImageTk.PhotoImage] = {}
		self.cached_animations: dict[Path, tuple[list[ImageTk.PhotoImage], list[float], int]] = {}
		self.label = tk.Label(root, background="black")
		self.label.pack(fill="both", expand=True)
		self.beer_hour_frame = tk.Frame(root, background="white")
		self.beer_hour_countdown = tk.Label(self.beer_hour_frame, background="white", foreground="black", font=("DejaVu Sans", 180, "bold"))
		self.beer_hour_countdown.pack()
		self.beer_hour_subtitle = tk.Label(self.beer_hour_frame, background="white", foreground="black", font=("DejaVu Sans", 72))
		self.beer_hour_subtitle.pack()
		self.beer_hour_frame.place_forget()

		if shuffle:
			random.shuffle(self.images)
		if quote_image is not None:
			self.images.append(quote_image)
		if vrijmibo_image is not None:
			self.vrijmibo_index = len(self.images)
			self.images.append(vrijmibo_image)
		self.update_beer_hour_slide()

		root.title("slideshow")
		root.configure(background="black", cursor="none")
		root.attributes("-fullscreen", True)
		root.bind("<Escape>", lambda _event: self.close())
		root.bind("q", lambda _event: self.close())
		root.bind("<space>", self.toggle_pause)
		root.bind("<Right>", self.next_image)
		root.bind("<Down>", self.next_image)
		root.bind("<Left>", self.previous_image)
		root.bind("<Up>", self.previous_image)
		root.bind("<Configure>", self.display_current)
		root.protocol("WM_DELETE_WINDOW", self.close)
		root.focus_force()
		root.update_idletasks()
		self.preprocess_images()
		self.display_current()
		self.check_vrijmibo()
		self.check_beer_hour()
		self.check_audio()

	def check_audio(self) -> None:
		now = datetime.now()
		if self.audio and now.hour == 16 and now.minute == 0 and now.date() != self.last_audio_date:
			self.last_audio_date = now.date()
			self.play_random_song()
		self.root.after(15_000, self.check_audio)

	def play_random_song(self) -> None:
		player = shutil.which("ffplay")
		if player is None:
			print("Could not play audio: ffplay was not found", file=sys.stderr)
			return
		song = random.choice(self.audio)
		if self.audio_process is not None and self.audio_process.poll() is None:
			self.audio_process.terminate()
		self.audio_process = subprocess.Popen(
			[player, "-nodisp", "-autoexit", "-loglevel", "error", "-ss", str(AUDIO_OFFSETS.get(song.name, 0.0)), str(song)],
			stdout=subprocess.DEVNULL,
			stderr=subprocess.PIPE,
		)

	def close(self) -> None:
		if self.closed:
			return
		self.closed = True
		if self.audio_process is not None and self.audio_process.poll() is None:
			self.audio_process.terminate()
		if self.system_process is not None and self.system_process.poll() is None:
			try:
				os.killpg(self.system_process.pid, signal.SIGTERM)
				self.system_process.wait(timeout=5)
			except (OSError, subprocess.TimeoutExpired):
				try:
					os.killpg(self.system_process.pid, signal.SIGKILL)
				except OSError:
					self.system_process.terminate()
		try:
			self.root.destroy()
		except tk.TclError:
			pass