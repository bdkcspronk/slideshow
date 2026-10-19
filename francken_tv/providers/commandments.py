"""This week's commandment of Jeff de Hosson, our honorary member.

One commandment per week, in the order of the text file, starting over after the last one, so
every commandment gets its turn. The week changes on Monday at midnight.
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

from ..config import project_path
from ..slides import Provider, Slide

FIRST_MONDAY = date(2026, 10, 19)   # commandment I is shown this week (a Monday); before it, the cycle runs backwards
ROMAN = ["I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "XI", "XII"]


def load_lines(path: Path) -> list[str]:   # also used for the dilemmas (poll.py)
	"""One commandment per line; lines starting with # are comments."""
	try:
		lines = path.read_text(encoding="utf-8").splitlines()
	except OSError:
		return []
	return [line.strip() for line in lines if line.strip() and not line.lstrip().startswith("#")]


def week_index(day: date, count: int) -> int:
	"""Which commandment is shown in the week of `day`: the next one every Monday."""
	return (day - FIRST_MONDAY).days // 7 % count


class CommandmentsProvider(Provider):
	name = "commandments"
	title = "Jeff's commandments"
	nothing_to_show = "No commandments in config/commandments.txt"

	def __init__(self, settings: dict, default_seconds: float) -> None:
		self.path = project_path(settings.get("file", "config/commandments.txt"))
		self.seconds = settings.get("seconds", default_seconds)

	def slides(self, now: datetime) -> list[Slide]:
		commandments = load_lines(self.path)   # read every time: edits show up without a restart
		if not commandments:
			return []
		index = week_index(now.date(), len(commandments))
		return [Slide("commandments.html", self.seconds, {
			"commandment": commandments[index],
			"number": ROMAN[index] if index < len(ROMAN) else str(index + 1),
			"count": len(commandments),
		})]
