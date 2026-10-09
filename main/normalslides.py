from __future__ import annotations

import time
import sys
from pathlib import Path

import tkinter as tk
from PIL import Image, ImageOps, ImageTk

from .config import BEER_HOUR_SLIDE, SNIFFER_FILENAME
from .files import find_images


class NormalSlidesMixin:
	def display_current(self, _event: tk.Event | None = None) -> None:
		self.refresh_images()
		if not self.images:
			return
		self.cancel_timer()
		self.close_animation()
		if self.beer_hour_index is not None and self.images[self.index] == BEER_HOUR_SLIDE:
			if self.beer_hour_started_at == 0.0:
				self.beer_hour_started_at = time.monotonic()
			self.display_beer_hour()
			return
		self.beer_hour_started_at = 0.0
		if not self.prepare_quote_slide():
			self.next_image()
			return
		path = self.images[self.index]
		if path.name.lower() == SNIFFER_FILENAME:
			try:
				with Image.open(path) as image:
					self.photo = self.show_frame(image)
			except (OSError, EOFError, ValueError) as error:
				print(f"Skipping {path}: {error}", file=sys.stderr)
				self.next_image()
				return
			self.show_photo()
			self.schedule_next()
			return
		if path in self.cached_animations:
			cached_photos, cached_durations, self.animation_loop_count = self.cached_animations[path]
			self.animation_photos = list(cached_photos)
			self.animation_durations = list(cached_durations)
			self.animation_loop = 0
			self.animation_frames = len(self.animation_photos)
			self.display_animation_frame()
			return
		if path in self.cached_photos:
			self.photo = self.cached_photos[path]
			self.show_photo()
			self.schedule_next()
			return
		try:
			image = Image.open(path)
			self.animation_frames = getattr(image, "n_frames", 1)
			if self.animation_frames > 1:
				self.animation_image = image
				loop_count = image.info.get("loop", 0)
				self.animation_loop_count = 1 if path == self.vrijmibo_image else loop_count + 1 if loop_count else 1
				self.animation_loop = 0
				self.preload_animation_frame()
				return
			with image:
				self.photo = self.show_frame(image)
		except (OSError, EOFError, ValueError) as error:
			print(f"Skipping {self.images[self.index]}: {error}", file=sys.stderr)
			self.next_image()
			return
		self.show_photo()
		self.schedule_next()

	def preprocess_images(self) -> None:
		for path in self.images:
			if path == self.quote_image or path == BEER_HOUR_SLIDE or path.name.lower() == SNIFFER_FILENAME:
				continue
			try:
				with Image.open(path) as image:
					frame_count = getattr(image, "n_frames", 1)
					if frame_count > 1:
						photos: list[ImageTk.PhotoImage] = []
						durations: list[float] = []
						loop_count = image.info.get("loop", 0)
						loop_count = 1 if path == self.vrijmibo_image else loop_count + 1 if loop_count else 1
						for frame_index in range(frame_count):
							image.seek(frame_index)
							frame = ImageOps.exif_transpose(image).convert("RGB")
							photos.append(ImageTk.PhotoImage(frame))
							durations.append(max(0.01, image.info.get("duration", 100) / 1000))
						self.cached_animations[path] = (photos, durations, loop_count)
					else:
						self.cached_photos[path] = self.show_frame(image)
			except (OSError, EOFError, ValueError) as error:
				print(f"Could not preprocess {path}: {error}")

	def refresh_images(self) -> None:
		current_path = self.images[self.index] if self.images else None
		new_images = find_images(self.image_folder)
		if self.vrijmibo_image is not None:
			new_images = [path for path in new_images if path != self.vrijmibo_image]
		known_images = set(self.images)
		self.images.extend(path for path in new_images if path not in known_images)
		if current_path in self.images:
			self.index = self.images.index(current_path)

	def show_frame(self, image: Image.Image, fit_to_screen: bool = True) -> ImageTk.PhotoImage:
		image = ImageOps.exif_transpose(image).convert("RGB")
		if fit_to_screen:
			available_width = max(self.root.winfo_width(), self.root.winfo_screenwidth())
			available_height = max(self.root.winfo_height(), self.root.winfo_screenheight())
			scale = min(available_width / image.width, available_height / image.height)
			if scale != 1:
				image = image.resize((round(image.width * scale), round(image.height * scale)), Image.LANCZOS)
		return ImageTk.PhotoImage(image)

	def preload_animation_frame(self) -> None:
		if self.animation_image is None or len(self.animation_photos) >= self.animation_frames:
			return
		try:
			self.animation_image.seek(len(self.animation_photos))
			frame = ImageOps.exif_transpose(self.animation_image).convert("RGB")
			self.animation_photos.append(ImageTk.PhotoImage(frame))
			self.animation_durations.append(max(0.01, self.animation_image.info.get("duration", 100) / 1000))
		except (OSError, EOFError, ValueError) as error:
			print(f"Skipping {self.images[self.index]}: {error}")
			self.next_image()
			return
		if len(self.animation_photos) == 1:
			self.display_animation_frame()
		if len(self.animation_photos) < self.animation_frames:
			self.root.after_idle(self.preload_animation_frame)

	def display_animation_frame(self) -> None:
		if not self.animation_photos:
			return
		try:
			now = time.monotonic()
			if self.animation_deadline == 0:
				self.animation_deadline = now + self.animation_durations[self.animation_frame]
			while self.animation_frame < self.animation_frames - 1 and self.animation_frame + 1 < len(self.animation_photos) and now >= self.animation_deadline:
				self.animation_deadline += self.animation_durations[self.animation_frame]
				self.animation_frame += 1
			if self.animation_frame < self.animation_frames - 1 and self.animation_frame + 1 >= len(self.animation_photos) and now >= self.animation_deadline:
				self.timer_id = self.root.after(1, self.display_animation_frame)
				return
			self.photo = self.animation_photos[self.animation_frame]
		except (IndexError, OSError, ValueError) as error:
			print(f"Skipping {self.images[self.index]}: {error}")
			self.next_image()
			return
		self.show_photo()
		if self.animation_frame < self.animation_frames - 1:
			self.schedule_animation_frame()
		elif self.animation_loop + 1 < self.animation_loop_count:
			self.animation_loop += 1
			self.animation_frame = 0
			self.animation_deadline = 0.0
			self.schedule_animation_frame()
		else:
			self.timer_id = self.root.after(0, self.next_image)

	def show_photo(self) -> None:
		self.beer_hour_frame.place_forget()
		self.label.configure(image=self.photo, text="", background="black")
		if self.quote_image is not None and self.images[self.index] == self.quote_image:
			self.queue_quote_if_enabled()
		else:
			self.preprocess_next_quote()

	def schedule_animation_frame(self) -> None:
		self.timer_id = self.root.after(max(1, round((self.animation_deadline - time.monotonic()) * 1000)), self.display_animation_frame)

	def schedule_next(self) -> None:
		self.cancel_timer()
		if not self.paused:
			self.timer_id = self.root.after(round(self.seconds * 1000), self.next_image)

	def cancel_timer(self) -> None:
		if self.timer_id is not None:
			self.root.after_cancel(self.timer_id)
			self.timer_id = None
		if self.beer_hour_timer_id is not None:
			self.root.after_cancel(self.beer_hour_timer_id)
			self.beer_hour_timer_id = None

	def close_animation(self) -> None:
		if self.animation_image is not None:
			self.animation_image.close()
			self.animation_image = None
		self.animation_photos.clear()
		self.animation_durations.clear()
		self.animation_frame = 0
		self.animation_frames = 0
		self.animation_loop = 0
		self.animation_loop_count = 1
		self.animation_deadline = 0.0

	def next_image(self, _event: tk.Event | None = None) -> None:
		self.index = (self.index + 1) % len(self.images)
		if self.index == self.vrijmibo_index and len(self.images) > 1:
			self.index = (self.index + 1) % len(self.images)
		self.display_current()

	def previous_image(self, _event: tk.Event | None = None) -> None:
		self.index = (self.index - 1) % len(self.images)
		if self.index == self.vrijmibo_index and len(self.images) > 1:
			self.index = (self.index - 1) % len(self.images)
		self.display_current()

	def toggle_pause(self, _event: tk.Event | None = None) -> None:
		self.paused = not self.paused
		if self.animation_frames > 1:
			if self.paused:
				self.cancel_timer()
			else:
				self.display_animation_frame()
		else:
			self.schedule_next()