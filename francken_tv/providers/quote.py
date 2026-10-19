"""A random quote from the quotes Google Sheet, optionally read aloud."""

from __future__ import annotations

import csv
import io
import logging
import random
import re
from datetime import datetime
from pathlib import Path

import requests

from ..announcer import Announcer
from ..config import project_path
from ..slides import Provider, Slide, media_url

log = logging.getLogger(__name__)

TYPING_STARTS_MS = 800      # after the slide has faded in
AUTHOR_FADE_SECONDS = 1.5
SHEET_CSV_URL = "https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv"


def load_blocked_words(path: Path) -> list[str]:
	"""One word or phrase per line; lines starting with # are comments."""
	try:
		lines = path.read_text(encoding="utf-8").splitlines()
	except OSError:
		return []
	return [line.strip() for line in lines if line.strip() and not line.lstrip().startswith("#")]


def contains_blocked_word(text: str, blocked_words: list[str]) -> bool:
	return any(re.search(rf"(?<!\w){re.escape(word)}(?!\w)", text, re.IGNORECASE) for word in blocked_words)


DOUBLE_QUOTES = re.compile(r'["\u201c\u201d\u201e\u201f\u00ab\u00bb]')
WRAPPING_SINGLE_QUOTES = re.compile(r"^['\u2018\u2019](.*)['\u2018\u2019]$", re.S)


def clean_quote(text: str) -> str:
	"""The quote without the quotation marks people sometimes type into the sheet (the slide adds its
	own): all double ones, and single ones around the whole quote (inside it they're apostrophes)."""
	text = DOUBLE_QUOTES.sub("", text).strip()
	text = WRAPPING_SINGLE_QUOTES.sub(r"\1", text).strip()
	return re.sub(r"\s{2,}", " ", text)


def read_quotes(csv_text: str) -> list[dict[str, str]]:
	rows = csv.DictReader(io.StringIO(csv_text.lstrip("﻿")))
	quotes = [{"quote": clean_quote(row.get("Quote") or ""), "author": (row.get("name") or "").strip()} for row in rows]
	return [quote for quote in quotes if quote["quote"]]


class QuoteProvider(Provider):
	name = "quote"
	title = "Quotes"

	def __init__(self, settings: dict, csv_path: Path, announcer: Announcer, default_seconds: float) -> None:
		self.sheet_id = settings.get("sheet_id")
		self.background = project_path(settings.get("background", "media/quote_background.png"))
		self.blocked_words_path = project_path(settings.get("blocked_words", "config/quote_filter.txt"))
		self.seconds = settings.get("seconds", default_seconds)        # reading time after the quote is typed
		self.letter_ms = settings.get("letter_ms", 45)                     # typing speed
		self.max_typing_seconds = settings.get("max_typing_seconds", 8)    # long quotes type faster
		self.refresh_seconds = settings.get("refresh_hours", 6) * 3600
		self.csv_path = csv_path
		self.announcer = announcer
		announcer.quotes_enabled = settings.get("narrate", False)
		self.quotes: list[dict[str, str]] = []
		self.last_quote: dict[str, str] | None = None

	def refresh(self, now: datetime) -> None:
		"""Download the sheet; if that fails, keep using the last downloaded copy."""
		try:
			response = requests.get(SHEET_CSV_URL.format(sheet_id=self.sheet_id), timeout=30)
			response.raise_for_status()
			quotes = read_quotes(response.content.decode("utf-8"))
			if quotes:
				self.csv_path.parent.mkdir(parents=True, exist_ok=True)
				self.csv_path.write_bytes(response.content)
				self.quotes = quotes
				return
		except (requests.RequestException, UnicodeDecodeError, KeyError) as error:
			log.warning("Could not download quotes, using saved copy: %s", error)
		if not self.quotes and self.csv_path.exists():
			self.quotes = read_quotes(self.csv_path.read_text(encoding="utf-8"))

	def slides(self, now: datetime) -> list[Slide]:
		blocked_words = load_blocked_words(self.blocked_words_path)   # read every time: edits apply at once
		allowed = [quote for quote in self.quotes if not contains_blocked_word(quote["quote"], blocked_words)]
		if not allowed:
			return []
		choices = [quote for quote in allowed if quote != self.last_quote] or allowed
		quote = self.last_quote = random.choice(choices)   # never the same quote twice in a row
		announce = quote["quote"]
		if self.announcer.quotes_enabled:
			self.announcer.prepare(announce)
		letters = len(quote["quote"]) + 2   # with the quotation marks
		letter_ms = min(self.letter_ms, self.max_typing_seconds * 1000 / letters)
		typing_ms = TYPING_STARTS_MS + letters * letter_ms
		return [Slide("quote.html", typing_ms / 1000 + AUTHOR_FADE_SECONDS + self.seconds, {
			"quote": quote["quote"],
			"letter_ms": round(letter_ms),
			"typing_ms": round(typing_ms),
			"author": quote["author"],
			"background": media_url(self.background) if self.background.exists() else None,
		}, announce=announce)]
