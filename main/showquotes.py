import subprocess
import sys

from .config import PROJECT_DIR


class ShowQuotesMixin:
	def prepare_quote_slide(self) -> bool:
		if self.quote_image is None:
			return True
		if self.images[self.index] != self.quote_image:
			self.quote_generated_index = None
			return True
		if self.quote_generated_index == self.index:
			return True
		try:
			subprocess.run(
				[sys.executable, str(PROJECT_DIR / "quotes" / "quotes.py")],
				cwd=PROJECT_DIR / "quotes",
				check=True,
			)
		except (OSError, subprocess.CalledProcessError) as error:
			print(f"Could not generate quote image: {error}", file=sys.stderr)
			self.next_image()
			return False
		self.quote_generated_index = self.index
		return True