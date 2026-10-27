"""The latest Francken Vrij, the association's magazine: an opened magazine whose pages turn by themselves,
pausing on the cover, the table of contents and the start of each article (templates/slides/francken_vrij.html).

Put the PDF of the latest issue in media/francken-vrij/; the newest PDF there is shown (the website's links to
the PDFs don't work, so it can't be fetched). Its pages are turned into images once (data/cache/francken_vrij)
with pdftoppm, and its bookmarks and text are read with pdftohtml: both from poppler (sudo apt install
poppler-utils). The pauses: the cover, a page among the first few that says "Contents" or "Inhoud", and the
first page of each bookmark (if the PDF has bookmarks: most exported magazines do).
"""

from __future__ import annotations

import hashlib
import html
import logging
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from PIL import Image

from ..config import project_path
from ..slides import Provider, Slide, media_url

log = logging.getLogger(__name__)

PAGE_HEIGHT = 1100      # pixels: sharp on the TV, a page is about 80 % of the screen high
CONTENTS = re.compile(r"\b(contents|inhoud|inhoudsopgave|in this issue|in dit nummer)\b", re.IGNORECASE)
CONTENTS_WITHIN = 6     # the table of contents is looked for among the first pages
START = 1.0             # seconds: the slide fades in first


@dataclass
class Issue:
	title: str                  # e.g. "Volume 29 · Issue 3"
	pages: list[Path]           # the pages as images, in order
	aspect: float               # a page's width / height
	pauses: set[int] = field(default_factory=set)   # page numbers (from 1) to pause on


def issue_title(pdf: Path) -> str:
	"""'29-3-3.pdf' (as the website names them: volume, issue, version) -> 'Volume 29 · Issue 3'."""
	match = re.match(r"(\d+)-(\d+)", pdf.stem)
	return f"Volume {match[1]} · Issue {match[2]}" if match else pdf.stem.replace("-", " ").replace("_", " ")


def read_pauses(xml: str, page_count: int) -> set[int]:
	"""The pages to pause on, from pdftohtml -xml: the cover, the table of contents and each bookmark's page."""
	pauses = {1}
	for number, text in re.findall(r'<page number="(\d+)"(.*?)</page>', xml, re.S)[:CONTENTS_WITHIN]:
		if CONTENTS.search(html.unescape(re.sub(r"<[^>]+>", " ", text))):
			pauses.add(int(number))
			break
	pauses.update(int(page) for page in re.findall(r'<item page="(\d+)"', xml))
	return {page for page in pauses if 1 <= page <= page_count}


def timeline(page_count: int, pauses: set[int], turn: float, pause: float, glance: float) -> tuple[list[float], float]:
	"""When each leaf starts to turn, and how long it all takes. A leaf is a sheet with a page on each side
	(leaf k: pages 2k+1 and 2k+2). First the closed magazine (the cover), then a leaf turns, the spread it
	opens stays `pause` seconds if one of its pages is a pause, else `glance`, and so on. With an even number of
	pages the last leaf turns too (the back cover alone); with an odd number the last spread is the end."""
	leaves = (page_count + 1) // 2
	turns = leaves if page_count % 2 == 0 else leaves - 1
	t = START + pause   # the cover
	starts = []
	for k in range(turns):
		starts.append(round(t, 2))
		t += turn
		shown = {2 * k + 2, 2 * k + 3} & set(range(1, page_count + 1))   # the spread this turn opens
		t += pause if shown & pauses else glance
	return starts, round(t, 2)


def run(*command: str) -> subprocess.CompletedProcess:
	if shutil.which(command[0]) is None:
		raise RuntimeError(f"{command[0]} not found: sudo apt install poppler-utils")
	return subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", check=True, timeout=300)


class FranckenVrijProvider(Provider):
	name = "francken_vrij"
	title = "Francken Vrij"
	nothing_to_show = "No Francken Vrij PDF in media/francken-vrij/"
	refresh_seconds = 10 * 60   # a new PDF in the folder shows up within this

	def __init__(self, settings: dict, cache_folder: Path) -> None:
		self.folder = project_path(settings.get("folder", "media/francken-vrij"))
		self.cache_folder = cache_folder
		self.turn = settings.get("turn_seconds", 0.9)       # one page turning over
		self.pause = settings.get("pause_seconds", 5)       # on the cover, the contents, an article's start
		self.glance = settings.get("glance_seconds", 0.7)   # on the other spreads
		self.issue: Issue | None = None
		self.source: tuple[str, float] | None = None        # (the PDF's name, its time) the issue was made from

	def newest_pdf(self) -> Path | None:
		pdfs = [path for path in self.folder.glob("*") if path.suffix.lower() == ".pdf"] if self.folder.is_dir() else []
		return max(pdfs, key=lambda path: path.stat().st_mtime, default=None)

	def refresh(self, now: datetime) -> None:
		pdf = self.newest_pdf()
		if pdf is None:
			self.issue, self.source = None, None
			return
		source = (pdf.name, pdf.stat().st_mtime)
		if source == self.source:
			return
		pages_folder = self.cache_folder / hashlib.sha1(f"{source}".encode()).hexdigest()[:12]
		if not any(pages_folder.glob("page-*.jpg")):
			pages_folder.mkdir(parents=True, exist_ok=True)
			log.info("Turning the pages of %s into images", pdf.name)
			run("pdftoppm", "-jpeg", "-jpegopt", "quality=85", "-scale-to-y", str(PAGE_HEIGHT), "-scale-to-x", "-1",
				str(pdf), str(pages_folder / "page"))
		pages = sorted(pages_folder.glob("page-*.jpg"), key=lambda path: int(path.stem.rsplit("-", 1)[1]))
		if not pages:
			raise RuntimeError(f"pdftoppm made no pages of {pdf.name}")
		xml = run("pdftohtml", "-xml", "-i", "-q", "-stdout", str(pdf)).stdout
		with Image.open(pages[0]) as first:
			aspect = first.width / first.height
		self.issue = Issue(issue_title(pdf), pages, aspect, read_pauses(xml, len(pages)))
		self.source = source
		for old in self.cache_folder.iterdir():   # an older issue's pages
			if old.is_dir() and old != pages_folder:
				shutil.rmtree(old, ignore_errors=True)

	def slides(self, now: datetime) -> list[Slide]:
		issue = self.issue
		if issue is None:
			return []
		starts, end = timeline(len(issue.pages), issue.pauses, self.turn, self.pause, self.glance)
		urls = [media_url(path) for path in issue.pages]
		leaves = [{"front": urls[2 * k], "back": urls[2 * k + 1] if 2 * k + 1 < len(urls) else "",
			"turns_at": starts[k] if k < len(starts) else None} for k in range((len(urls) + 1) // 2)]
		return [Slide("francken_vrij.html", end + 1, {
			"title": issue.title, "leaves": leaves, "aspect": round(issue.aspect, 4), "turn": self.turn,
			"opens_at": starts[0] if starts else None,
			"closes_at": starts[-1] if len(urls) % 2 == 0 and len(starts) > 1 else None,   # the back cover alone
		})]
