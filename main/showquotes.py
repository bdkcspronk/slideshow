import json
import re
import subprocess
import sys

from .config import (
	PROJECT_DIR,
	QUOTE_FILTER_FILE,
	QUOTE_METADATA_FILE,
	QUOTE_QUEUE_FILE,
)


class ShowQuotesMixin:
	def prepare_quote_slide(self) -> bool:
		if self.quote_image is None:
			return True
		if self.images[self.index] != self.quote_image:
			self.quote_generated_index = None
			return True
		if self.quote_generated_index == self.index:
			self.queue_quote_if_enabled()
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
		self.queue_quote_if_enabled()
		return True

	def queue_quote_if_enabled(self) -> None:
		if not self.quote_voice_enabled or self.quote_voice_queued_index == self.index:
			return
		try:
			metadata = json.loads(QUOTE_METADATA_FILE.read_text(encoding="utf-8"))
			quote = metadata["quote"]
			if self.quote_contains_filtered_word(quote):
				self.quote_voice_queued_index = self.index
				return
			spoken_text = quote
			try:
				subprocess.run(
					[
						sys.executable,
						str(PROJECT_DIR / "Sniffer" / "voice_announcer.py"),
						"--prepare-quote",
						spoken_text,
					],
					cwd=PROJECT_DIR / "Sniffer",
					check=True,
				)
			except (OSError, subprocess.CalledProcessError) as error:
				print(f"Could not preprocess quote narration: {error}", file=sys.stderr)
			with QUOTE_QUEUE_FILE.open("a", encoding="utf-8") as queue_file:
				queue_file.write(json.dumps({
					"type": "quote",
					"text": spoken_text,
				}) + "\n")
				queue_file.flush()
			self.quote_voice_queued_index = self.index
		except (OSError, KeyError, TypeError, json.JSONDecodeError) as error:
			print(f"Could not queue quote narration: {error}", file=sys.stderr)

	def quote_contains_filtered_word(self, quote: str) -> bool:
		try:
			blocked_words = [
				line.strip()
				for line in QUOTE_FILTER_FILE.read_text(encoding="utf-8").splitlines()
				if line.strip() and not line.lstrip().startswith("#")
			]
		except OSError:
			return False

		return any(
			re.search(rf"(?<!\w){re.escape(word)}(?!\w)", quote, re.IGNORECASE)
			for word in blocked_words
		)