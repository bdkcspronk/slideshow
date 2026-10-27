"""The weekly dilemma: two options, vote on the TV or on your phone (QR code -> a Google Form).

The dilemmas are in a text file (config/dilemmas.txt), one per week in order, like the
commandments. Votes on phones go to a Google Form whose responses sheet is read every few minutes
(like the quotes sheet); both are added up, and a new week starts at zero. data/poll.json keeps
every week's dilemma and votes, so the slide can show last week's outcome.

The Google Form needs one multiple-choice question. Its answers are either the same texts as the
options in dilemmas.txt (then the form has to be changed along every week), or just "A" and "B"
("A: theory" is fine too), so the form can stay the same. Only responses from this week (by their
timestamp) count. See docs/setup/weekly-dilemma.md.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import re
import threading
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

import requests

from ..config import project_path
from ..slides import Provider, Slide
from .commandments import load_lines, week_index
from .quote import SHEET_CSV_URL

log = logging.getLogger(__name__)

TAP_COOLDOWN_SECONDS = 3   # taps on the TV closer together than this count once (no stuffing the ballot box)
LETTER = re.compile(r"^([ab])(?:$|\s*[:).\-\u2013])", re.IGNORECASE)   # "A", "A: theory", "B) ..." (but not "A cold shower")
TIMESTAMP = re.compile(r"(\d{1,4})[-/.](\d{1,2})[-/.](\d{1,4})\D+(\d{1,2}):(\d{2})")


@dataclass
class Dilemma:
	question: str
	a: str
	b: str


def parse_dilemma(line: str) -> Dilemma | None:
	"""'question | option A | option B'; None if the line isn't like that."""
	parts = [part.strip() for part in line.split("|")]
	return Dilemma(*parts) if len(parts) == 3 and all(parts) else None


def parse_timestamp(text: str, day_first: bool = True) -> datetime | None:
	"""A Google Sheets timestamp: 2026-10-19 14:03, or 19-10-2026 14:03:12 (day first, as in Dutch or
	British sheets), or 10/19/2026 14:03:12 (month first, American sheets)."""
	match = TIMESTAMP.search(text)
	if not match:
		return None
	first, second, third, hour, minute = (int(part) for part in match.groups())
	if first > 31:
		year, month, day = first, second, third
	else:
		day, month, year = (first, second, third) if day_first else (second, first, third)
	try:
		return datetime(year, month, day, hour, minute)
	except ValueError:
		return None


def simplified(text: str) -> str:
	return " ".join(re.sub(r"[^\w\s]", " ", text.lower()).split())


def form_answer(answer: str, dilemma: Dilemma | None) -> str | None:
	"""Which option a form answer is: "a", "b" or None. The option's text (in any case, without
	punctuation), a part of only one option's text ("very cold" for "always have a very cold shower",
	e.g. after the options were reworded), or its letter."""
	if dilemma:
		answer_text = simplified(answer)
		options = {key: simplified(getattr(dilemma, key)) for key in ("a", "b")}
		for key, text in options.items():
			if answer_text == text:
				return key
		if len(answer_text) >= 3:   # not a letter like "a", which is in almost every text
			containing = [key for key, text in options.items() if f" {answer_text} " in f" {text} "]
			if len(containing) == 1:
				return containing[0]
	letter = LETTER.match(answer.strip())
	return letter.group(1).lower() if letter else None


def sheet_is_day_first(timestamps: list[str], default: bool) -> bool:
	"""Whether the sheet writes 19-10-2026 (day first) or 10/19/2026 (month first): a number above 12
	in front means day first, in the middle month first. Only days up to the 12th: the default."""
	for text in timestamps:
		match = TIMESTAMP.search(text)
		if match and int(match.group(1)) <= 31:   # not 2026-10-19
			if int(match.group(1)) > 12:
				return True
			if int(match.group(2)) > 12:
				return False
	return default


def count_form_votes(csv_text: str, week_start: date, day_first: bool = True, dilemma: Dilemma | None = None) -> dict[str, int]:
	"""This week's responses in the form's sheet: timestamp in the first column, then the answer. A question
	made anew in the form gets a new column, so the first filled-in one after the timestamp counts."""
	votes = {"a": 0, "b": 0}
	week = (datetime.combine(week_start, datetime.min.time()), datetime.combine(week_start + timedelta(days=7), datetime.min.time()))
	rows = list(csv.reader(io.StringIO(csv_text.lstrip("\ufeff"))))[1:]   # without the header (and a byte order mark)
	day_first = sheet_is_day_first([row[0] for row in rows if row], day_first)
	for row in rows:
		filled = [cell for cell in row[1:] if cell.strip()]
		if not row or not filled:
			continue
		when = parse_timestamp(row[0], day_first)
		answer = form_answer(filled[0], dilemma)
		if when and week[0] <= when < week[1] and answer:
			votes[answer] += 1
	return votes


class PollProvider(Provider):
	name = "poll"
	title = "Weekly dilemma"
	nothing_to_show = "No dilemmas in config/dilemmas.txt, or the form's votes aren't read yet"

	def __init__(self, settings: dict, default_seconds: float, state_path: Path | None = None) -> None:
		self.path = project_path(settings.get("file", "config/dilemmas.txt"))
		self.seconds = settings.get("seconds", default_seconds)
		self.form_url = settings.get("form_url", "")      # the QR code links here; empty: vote on the TV only
		self.sheet_id = settings.get("sheet_id", "")      # the form's responses sheet, shared "anyone with the link"
		self.day_first = settings.get("timestamp_day_first", True)
		self.refresh_seconds = settings.get("refresh_minutes", 2) * 60 if self.sheet_id else None
		self.state_path = state_path   # every week's dilemma and votes (data/poll.json), for last week's outcome
		self.weeks: dict[str, dict] | None = None   # Monday "2026-10-19" -> {"question", "a", "b", "tv": {...}, "form": {...}}
		self.form_read = not self.sheet_id   # with a form: no slide until its votes have been read (after a start)
		self.last_tap = 0.0
		self.lock = threading.Lock()   # votes arrive from the web server's threads, the form's from refresh()

	@staticmethod
	def week_start(now: datetime) -> date:
		return now.date() - timedelta(days=now.weekday())   # Monday

	def dilemma(self, now: datetime) -> Dilemma | None:
		dilemmas = [d for d in map(parse_dilemma, load_lines(self.path)) if d]   # read every time: edits show up without a restart
		return dilemmas[week_index(now.date(), len(dilemmas))] if dilemmas else None

	def history(self) -> dict[str, dict]:
		if self.weeks is None:
			self.weeks = {}
			if self.state_path and self.state_path.exists():
				try:
					self.weeks = json.loads(self.state_path.read_text(encoding="utf-8")).get("weeks", {})
				except (OSError, ValueError, AttributeError) as error:
					log.warning("Ignoring unreadable poll history %s: %s", self.state_path, error)
		return self.weeks

	def save(self) -> None:
		if self.state_path is None:
			return
		self.state_path.parent.mkdir(parents=True, exist_ok=True)
		temporary = self.state_path.with_suffix(".tmp")
		temporary.write_text(json.dumps({"weeks": self.history()}, indent=1, ensure_ascii=False), encoding="utf-8")
		temporary.replace(self.state_path)   # in one go, so a restart while saving can't leave half a file

	def week(self, now: datetime) -> dict | None:
		"""This week's entry in the history, with the dilemma as it is in the file now (fixing a typo
		during the week is fine; last week's entry keeps the dilemma it had)."""
		dilemma = self.dilemma(now)
		if dilemma is None:
			return None
		entry = self.history().setdefault(self.week_start(now).isoformat(), {})
		entry.update(question=dilemma.question, a=dilemma.a, b=dilemma.b)
		entry.setdefault("tv", {"a": 0, "b": 0})
		entry.setdefault("form", {"a": 0, "b": 0})
		return entry

	def refresh(self, now: datetime) -> None:
		"""The votes on the form, for this week and last week (late responses to last week still count)."""
		response = requests.get(SHEET_CSV_URL.format(sheet_id=self.sheet_id), timeout=30)
		response.raise_for_status()
		sheet = response.content.decode("utf-8")
		with self.lock:
			self.week(now)
			for start in (self.week_start(now), self.week_start(now) - timedelta(days=7)):
				entry = self.history().get(start.isoformat())
				if entry and entry.get("question"):
					dilemma = Dilemma(entry["question"], entry["a"], entry["b"])
					entry["form"] = count_form_votes(sheet, start, self.day_first, dilemma)
			self.save()
			self.form_read = True

	@staticmethod
	def results(entry: dict) -> tuple[dict[str, int], int]:
		votes = {key: entry.get("tv", {}).get(key, 0) + entry.get("form", {}).get(key, 0) for key in ("a", "b")}
		return votes, votes["a"] + votes["b"]

	def options(self, entry: dict) -> list[dict]:
		"""The two options with their votes and share, for the bars."""
		votes, total = self.results(entry)
		return [{"key": key, "letter": key.upper(), "text": entry[key], "votes": votes[key],
			"percent": round(votes[key] / total * 100) if total else 0} for key in ("a", "b")]

	def last_week(self, now: datetime) -> dict | None:
		"""Last week's outcome: the question, the winning option (None: a tie), its share, and the bars."""
		entry = self.history().get((self.week_start(now) - timedelta(days=7)).isoformat())
		if not entry or not entry.get("question"):
			return None
		votes, total = self.results(entry)
		winner = None if votes["a"] == votes["b"] else max(("a", "b"), key=votes.get)
		return {"question": entry["question"], "total": total, "winner": entry[winner] if winner else None,
			"percent": round(votes[winner] / total * 100) if winner else 50, "a": entry["a"], "b": entry["b"],
			"options": [option | {"won": option["key"] == winner} for option in self.options(entry)]}

	def slide(self, now: datetime, voted: str | None = None) -> Slide | None:
		entry = self.week(now)
		if entry is None:
			return None
		_, total = self.results(entry)
		options = self.options(entry)
		return Slide("poll.html", self.seconds, {"question": entry["question"], "options": options, "total": total,
			"form_url": self.form_url, "voted": voted, "last_week": self.last_week(now)})

	def slides(self, now: datetime) -> list[Slide]:
		if not self.form_read:   # just started: the votes on the form would be missing
			return []
		slide = self.slide(now)
		return [slide] if slide else []

	def action(self, name: str, values: list[str], now: datetime) -> tuple[Slide | None, str | None]:
		"""'vote' with values = ["a"] or ["b"]: a vote on the TV."""
		if name != "vote" or not values or values[0] not in ("a", "b"):
			return None, None
		choice = values[0]
		with self.lock:
			entry = self.week(now)
			if entry and time.monotonic() - self.last_tap >= TAP_COOLDOWN_SECONDS:
				entry["tv"][choice] += 1
				self.last_tap = time.monotonic()
				self.save()
		return self.slide(now, voted=choice), None
