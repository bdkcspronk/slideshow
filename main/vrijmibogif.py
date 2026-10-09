from datetime import datetime


class VrijmiboGifMixin:
	def check_vrijmibo(self) -> None:
		now = datetime.now()
		slot = (now.date(), now.hour, now.minute // 15)
		if self.vrijmibo_index is not None and now.weekday() == 4 and slot != self.last_vrijmibo_slot:
			self.last_vrijmibo_slot = slot
			self.index = self.vrijmibo_index
			self.display_current()
		self.root.after(60_000, self.check_vrijmibo)