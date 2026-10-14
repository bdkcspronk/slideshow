from __future__ import annotations

import os
import queue
import random
import signal
import subprocess
import sys
import threading
from datetime import date
from pathlib import Path
from typing import Callable

import tkinter as tk
from PIL import Image, ImageTk

from .bieruurcountdown import BieruurCountdownMixin
from .bieruursound import BieruurSoundMixin
from .normalslides import NormalSlidesMixin
from .nextcloud import choose_random_event_image
from .showquotes import ShowQuotesMixin
from .vrijmibogif import VrijmiboGifMixin


class Slideshow(
	VrijmiboGifMixin,
	BieruurCountdownMixin,
	BieruurSoundMixin,
	ShowQuotesMixin,
	NormalSlidesMixin,
):
	def __init__(self, root: tk.Tk, images: list[Path], image_folder: Path, seconds: float,
		shuffle: bool, quote_image: Path | None = None, vrijmibo_image: Path | None = None,
		audio: list[Path] | None = None, system_process: subprocess.Popen[bytes] | None = None,
		nextcloud_images: list[Path] | None = None,
		nextcloud_sync: Callable[[], list[Path]] | None = None,
		activity_image: Path | None = None,
		activity_sync: Callable[[], Path] | None = None) -> None:
		self.root = root
		self.images = images[:]
		self.image_folder = image_folder
		self.nextcloud_images = nextcloud_images or []
		self.nextcloud_image_index: int | None = None
		self.nextcloud_sync = nextcloud_sync
		self.nextcloud_refresh_in_progress = False
		self.nextcloud_refresh_timer: str | None = None
		self.nextcloud_poll_timer: str | None = None
		self.nextcloud_results: queue.Queue[tuple[list[Path] | None, str | None]] = queue.Queue()
		self.activity_image = activity_image
		self.activity_sync = activity_sync
		self.activity_refresh_timer: str | None = None
		self.activity_refresh_in_progress = False
		self.activity_results: queue.Queue[tuple[Path | None, str | None]] = queue.Queue()
		self.quote_image = quote_image
		self.vrijmibo_image = vrijmibo_image
		self.quote_generated_index: int | None = None
		self.quote_audio_prepared_index: int | None = None
		self.quote_voice_queued_index: int | None = None
		self.quote_voice_enabled = True
		self.vrijmibo_index: int | None = None
		self.beer_hour_index: int | None = None
		self.last_vrijmibo_slot: tuple[date, int, int] | None = None
		self.audio = audio or []
		self.selected_song: Path | None = None
		self.selected_audio_date: date | None = None
		self.last_audio_date: date | None = None
		self.audio_check_started = False
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
		if self.nextcloud_images:
			self.nextcloud_image_index = next(
				(index for index, path in enumerate(self.images) if path in self.nextcloud_images),
				None,
			)
		if self.nextcloud_image_index is None:
			self.nextcloud_image_index = next(
				(index for index, path in enumerate(self.images) if path.name.startswith("eventpicture_")),
				None,
			)
		self.update_beer_hour_slide()
		
		root.configure(background="black", cursor="none")
		root.attributes("-fullscreen", True)
		root.title("slideshow")
		root.bind("<Escape>", lambda _event: self.close())
		root.bind("q", lambda _event: self.close())
		root.bind("<space>", self.toggle_pause)
		root.bind("<Control-m>", self.toggle_quote_voice)
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
		if self.nextcloud_sync is not None:
			self.nextcloud_refresh_timer = root.after(0, self.refresh_nextcloud)
		if self.activity_sync is not None:
			self.activity_refresh_timer = root.after(15 * 60 * 1000, self.refresh_activities)
		if self.nextcloud_sync is not None or self.activity_sync is not None:
			self.nextcloud_poll_timer = root.after(1000, self.poll_nextcloud_refresh)

	def close(self) -> None:
		if self.closed:
			return
		self.closed = True
		if self.nextcloud_refresh_timer is not None:
			try:
				self.root.after_cancel(self.nextcloud_refresh_timer)
			except tk.TclError:
				pass
		if self.nextcloud_poll_timer is not None:
			try:
				self.root.after_cancel(self.nextcloud_poll_timer)
			except tk.TclError:
				pass
		if self.activity_refresh_timer is not None:
			try:
				self.root.after_cancel(self.activity_refresh_timer)
			except tk.TclError:
				pass
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

	def refresh_nextcloud(self) -> None:
		if self.closed or self.nextcloud_sync is None:
			return
		self.nextcloud_refresh_timer = self.root.after(15 * 60 * 1000, self.refresh_nextcloud)
		if self.nextcloud_refresh_in_progress:
			return
		self.nextcloud_refresh_in_progress = True
		threading.Thread(target=self._sync_nextcloud, daemon=True).start()

	def _sync_nextcloud(self) -> None:
		try:
			images = self.nextcloud_sync()
		except RuntimeError as error:
			self.nextcloud_results.put((None, str(error)))
		else:
			self.nextcloud_results.put((images, None))

	def refresh_activities(self) -> None:
		if self.closed or self.activity_sync is None:
			return
		self.activity_refresh_timer = self.root.after(15 * 60 * 1000, self.refresh_activities)
		if self.activity_refresh_in_progress:
			return
		self.activity_refresh_in_progress = True
		threading.Thread(target=self._sync_activities, daemon=True).start()

	def _sync_activities(self) -> None:
		try:
			image = self.activity_sync()
		except RuntimeError as error:
			self.activity_results.put((None, str(error)))
		else:
			self.activity_results.put((image, None))

	def poll_nextcloud_refresh(self) -> None:
		if self.closed:
			return
		try:
			images, error = self.nextcloud_results.get_nowait()
		except queue.Empty:
			pass
		else:
			self.finish_nextcloud_refresh(images, error)
		try:
			activity_image, activity_error = self.activity_results.get_nowait()
		except queue.Empty:
			pass
		else:
			self.finish_activity_refresh(activity_image, activity_error)
		self.nextcloud_poll_timer = self.root.after(1000, self.poll_nextcloud_refresh)

	def finish_activity_refresh(self, image: Path | None, error: str | None) -> None:
		self.activity_refresh_in_progress = False
		if self.closed:
			return
		if error is not None:
			print(f"Activities refresh failed: {error}", file=sys.stderr)
			return
		if image is None:
			return
		self.activity_image = image
		self.cached_photos.pop(image, None)
		self.cached_animations.pop(image, None)
		self.preprocess_images()
		if self.images and self.images[self.index] == image:
			self.display_current()

	def finish_nextcloud_refresh(self, images: list[Path] | None, error: str | None) -> None:
		self.nextcloud_refresh_in_progress = False
		if self.closed:
			return
		if error is not None:
			print(f"Nextcloud refresh failed: {error}", file=sys.stderr)
			return
		if images:
			self.nextcloud_images = images
			if self.nextcloud_image_index is None:
				new_image = choose_random_event_image(images)
				insert_at = min(self.index, len(self.images))
				self.images.insert(insert_at, new_image)
				if self.vrijmibo_index is not None and self.vrijmibo_index >= insert_at:
					self.vrijmibo_index += 1
				if self.beer_hour_index is not None and self.beer_hour_index >= insert_at:
					self.beer_hour_index += 1
				self.nextcloud_image_index = insert_at
				self.preprocess_images()
				self.index = insert_at
				self.display_current()
				return
		if self.nextcloud_image_index >= len(self.images):
			self.nextcloud_image_index = None
			return
		old_path = self.images[self.nextcloud_image_index]
		self.images[self.nextcloud_image_index] = choose_random_event_image(images)
		self.cached_photos.pop(old_path, None)
		self.cached_animations.pop(old_path, None)

	def toggle_quote_voice(self, _event: tk.Event | None = None) -> None:
		self.quote_voice_enabled = not self.quote_voice_enabled
		state = "enabled" if self.quote_voice_enabled else "disabled"
		print(f"Quote narration {state}", flush=True)