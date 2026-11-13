"""Second-hand books for sale, scraped from professorfrancken.nl/study/books.

All books for sale stand in a bookcase in the background (room for CASE_SIZE); each slide takes the next few
out of it (as 3D books: static/books_3d.js) and shows them side by side, with the title and price below
them. The next round takes out the next few, further along the shelf. Copies of the same book (same ISBN) are shown once, with the
lowest price. Covers come from Open Library by ISBN; books without one get a drawn cover, as do books whose
cover there is a blank page (a scan of a plain title page) or isn't a picture that can be read.

If the website's layout changes, only parse_books() needs fixing.
Test it with: python -m unittest tests.test_books
"""

from __future__ import annotations

import hashlib
import logging
import random
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from PIL import Image, UnidentifiedImageError

from ..slides import Provider, Slide, media_url

log = logging.getLogger(__name__)

PRICE = re.compile(r"€\s*(\d+)(?:[,.](\d{2}))?")
ISBN = re.compile(r"ISBN:\s*([0-9Xx-]+)")
COVER_URL = "https://covers.openlibrary.org/b/isbn/{isbn}-L.jpg?default=false"   # 404 when there's none
MAX_PAGES = 20   # the website shows 20 books per page
CASE_SIZE = 100   # books in the bookcase; with more for sale it holds the CASE_SIZE around the ones taken out
BLANK_CONTRAST = 64   # a cover whose darkest and lightest parts differ less than this (of 255, shrunk to 32x32) is blank


@dataclass
class Book:
	title: str
	authors: str
	isbn: str
	cents: int                 # the cheapest copy
	copies: int = 1
	cover: str | None = None   # url of the downloaded cover, None: draw one
	cover_colour: str | None = None   # the cover's average colour, a bit darker

	@property
	def price(self) -> str:
		"""€15 or €2,50"""
		euros, cents = divmod(self.cents, 100)
		return f"€{euros}" if cents == 0 else f"€{euros},{cents:02d}"

	@property
	def hue(self) -> int:
		"""A stable colour for the drawn cover."""
		return int(hashlib.md5(self.title.encode()).hexdigest(), 16) % 360

	@property
	def cloth(self) -> str:
		"""The colour of the spine, the edges and the back: the cover's, or of the drawn cover."""
		return self.cover_colour or f"hsl({self.hue}, 30%, 30%)"   # with commas: Three.js reads only those

	@property
	def shape(self) -> tuple[float, float]:
		"""(size, thickness), stable per book, so the bookcase doesn't look like a row of copies: size 0.82 to 1
		times the normal book (--w and --h in style.css), thickness 0.55 to 1.35 times the normal (--d)."""
		digest = hashlib.md5(f"shape {self.title}".encode()).digest()
		return round(0.82 + 0.18 * digest[0] / 255, 3), round(0.55 + 0.8 * digest[1] / 255, 3)

	def on_shelf(self) -> dict:
		"""What the bookcase needs of a book (in the page as JSON)."""
		size, thickness = self.shape
		return {"title": self.title, "cloth": self.cloth, "size": size, "thickness": thickness}


def parse_books(html: str) -> list[Book]:
	"""The books on one page of the website, one entry per copy, in the website's order."""
	soup = BeautifulSoup(html, "html.parser")
	books = []
	for article in soup.select("article.preview-item"):
		heading, button = article.find("h3"), article.find("a", class_="btn")
		price = PRICE.search(button.get_text()) if button else None
		if heading is None or price is None:
			continue
		authors = heading.find("small")
		if authors:
			authors = authors.extract().get_text(" ", strip=True)
		isbn = ISBN.search(article.get_text(" "))
		books.append(Book(
			title=heading.get_text(" ", strip=True),
			authors=authors or "",
			isbn=isbn.group(1).replace("-", "").upper() if isbn else "",
			cents=int(price.group(1)) * 100 + int(price.group(2) or 0),
		))
	return books


def combine_copies(books: list[Book]) -> list[Book]:
	"""One entry per book (by ISBN, or title without one), with the lowest price. Free copies are left
	out: on the website that means no price was filled in."""
	combined: dict[str, Book] = {}
	for book in books:
		if book.cents == 0:
			continue
		key = book.isbn or book.title.lower()
		if key in combined:
			kept = combined[key]
			kept.copies += 1
			kept.cents = min(kept.cents, book.cents)
		else:
			combined[key] = Book(book.title, book.authors, book.isbn, book.cents)
	return list(combined.values())


def is_blank(path: Path) -> bool:
	"""A cover that shows nothing: almost one colour (e.g. Open Library's scan of a plain title page), or not a picture."""
	try:
		with Image.open(path) as image:
			darkest, lightest = image.convert("L").resize((32, 32)).getextrema()
	except (OSError, UnidentifiedImageError):
		return True
	return lightest - darkest < BLANK_CONTRAST


def average_colour(path: Path) -> str:
	"""A cover's average colour, a bit darker (70%): the cloth of its spine."""
	with Image.open(path) as image:
		r, g, b = image.convert("RGB").resize((1, 1), Image.Resampling.BOX).getpixel((0, 0))
	return f"rgb({round(r * 0.7)}, {round(g * 0.7)}, {round(b * 0.7)})"


class BooksProvider(Provider):
	name = "books"
	title = "Books for sale"
	nothing_to_show = "No books for sale found"

	def __init__(self, settings: dict, cache_folder: Path) -> None:
		self.url = settings.get("url", "https://professorfrancken.nl/study/books")
		self.books_per_slide = settings.get("books_per_slide", 3)
		self.seconds = settings.get("seconds", 15)
		self.refresh_seconds = settings.get("refresh_hours", 6) * 3600
		self.cache_folder = cache_folder
		self.books: list[Book] = []
		self.next = 0   # where the next slide continues in self.books

	def refresh(self, now: datetime) -> None:
		found: list[Book] = []
		for page in range(1, MAX_PAGES + 1):
			response = requests.get(self.url, params={"page": page}, timeout=30)
			response.raise_for_status()
			books = parse_books(response.text)
			if not books:
				break
			found.extend(books)
		books = combine_copies(found)
		if not books:
			raise ValueError(f"No books found on {self.url}; did the website layout change?")
		self.cache_folder.mkdir(parents=True, exist_ok=True)
		for book in books:
			book.cover = self.download_cover(book.isbn)
			if book.cover:
				book.cover_colour = average_colour(self.cache_folder / f"{book.isbn}.jpg")
		random.shuffle(books)   # a different order after every refresh, so all books get their turn
		self.books, self.next = books, 0
		log.info("Found %d books for sale (%d copies), %d with a cover", len(books), len(found),
			sum(book.cover is not None for book in books))

	def download_cover(self, isbn: str) -> str | None:
		if not isbn:
			return None
		path = self.cache_folder / f"{isbn}.jpg"
		if not path.exists():
			try:
				response = requests.get(COVER_URL.format(isbn=isbn), timeout=30)
			except requests.RequestException as error:
				log.warning("Could not download the cover of %s: %s", isbn, error)
				return None
			if response.status_code != 200 or not response.content:
				return None   # Open Library has no cover: a drawn one (tried again at the next refresh)
			path.write_bytes(response.content)
		if is_blank(path):
			return None   # drawn instead; checked again on every refresh, so a better scan on Open Library gets used
		return media_url(path)

	def slides(self, now: datetime) -> list[Slide]:
		if not self.books:
			return []
		case, taken = self.bookcase()
		self.next = (self.next + len(taken)) % len(self.books)
		books = [(case[slot], slot) for slot in taken]
		return [Slide("books.html", self.seconds, {
			"books": books, "case": [book.on_shelf() for book in case], "case_size": CASE_SIZE})]

	def bookcase(self) -> tuple[list[Book], list[int]]:
		"""The books in the bookcase, in order, and the places in it of the ones this slide takes out.

		All books fit: they stand in the order they are shown, so each slide takes out the books next to the last
		slide's. With more than CASE_SIZE, the bookcase holds them a caseful at a time."""
		total = len(self.books)
		count = min(self.books_per_slide, total)
		if total <= CASE_SIZE:
			return self.books, [(self.next + i) % total for i in range(count)]
		start = self.next - self.next % (CASE_SIZE - CASE_SIZE % count)   # a caseful of whole slides
		if self.next - start + count > CASE_SIZE:   # after going round, the books no longer line up with the slides
			start = self.next
		case = [self.books[(start + i) % total] for i in range(CASE_SIZE)]
		return case, [self.next - start + i for i in range(count)]
