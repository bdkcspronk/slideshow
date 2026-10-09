import time
from datetime import datetime, timedelta

from .config import BEER_HOUR_PREVIEW_SECONDS, BEER_HOUR_SLIDE


class BieruurCountdownMixin:
	def update_beer_hour_slide(self) -> None:
		now = datetime.now()
		should_include = now.hour < 18
		if should_include and self.beer_hour_index is None:
			self.beer_hour_index = len(self.images)
			self.images.append(BEER_HOUR_SLIDE)
		elif not should_include and self.beer_hour_index is not None:
			removed_index = self.beer_hour_index
			self.images.pop(removed_index)
			self.beer_hour_index = None
			if self.index == removed_index:
				self.index = 0
				if not self.images:
					self.cancel_timer()
					self.label.configure(image="", text="")
					return
				self.display_current()
			elif self.index > removed_index:
				self.index -= 1
		if self.beer_hour_index is not None:
			target = now.replace(hour=16, minute=0, second=0, microsecond=0)
			hold_starts = target - timedelta(minutes=2)
			hold_ends = target + timedelta(minutes=1)
			if hold_starts <= now < hold_ends and self.index != self.beer_hour_index:
				self.index = self.beer_hour_index
				self.display_current()

	def check_beer_hour(self) -> None:
		self.update_beer_hour_slide()
		self.root.after(1_000, self.check_beer_hour)

	def display_beer_hour(self) -> None:
		now = datetime.now()
		target = now.replace(hour=16, minute=0, second=0, microsecond=0)
		remaining_seconds = int((target - now).total_seconds())
		if remaining_seconds <= 0:
			self.beer_hour_countdown.configure(text="Het is Bieruur!", font=("DejaVu Sans", 120, "bold"))
			self.beer_hour_subtitle.configure(text="")
		else:
			hours, remainder = divmod(remaining_seconds, 3_600)
			minutes, seconds = divmod(remainder, 60)
			self.beer_hour_countdown.configure(text=f"{hours:02d}:{minutes:02d}:{seconds:02d}", font=("DejaVu Sans", 180, "bold"))
			self.beer_hour_subtitle.configure(text="until bieruur")
		self.label.configure(image="", text="", background="white")
		self.beer_hour_frame.place(relx=0.5, rely=0.5, anchor="center")
		self.preprocess_next_quote()
		if remaining_seconds <= 0:
			hold_ends = target + timedelta(minutes=1)
			self.beer_hour_timer_id = self.root.after(
				max(1, round((hold_ends - now).total_seconds() * 1000)), self.next_image
			)
		elif remaining_seconds <= 120 or time.monotonic() < self.beer_hour_started_at + BEER_HOUR_PREVIEW_SECONDS:
			self.beer_hour_timer_id = self.root.after(1_000, self.display_current)
		else:
			self.next_image()