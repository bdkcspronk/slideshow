"""Second-hand books for sale, scraped from professorfrancken.nl/study/books.

Each slide shows a few books side by side (the cover as a 3D book flying in, the title and price
below it); the next round shows the next few. Copies of the same book (same ISBN) are shown once, with the
lowest price. Covers come from Open Library by ISBN; books without one get a drawn cover.

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

from ..slides import Provider, Slide, media_url

log = logging.getLogger(__name__)

PRICE = re.compile(r"€\s*(\d+)(?:[,.](\d{2}))?")
ISBN = re.compile(r"ISBN:\s*([0-9Xx-]+)")
COVER_URL = "https://covers.openlibrary.org/b/isbn/{isbn}-L.jpg?default=false"   # 404 when there's none
MAX_PAGES = 20   # the website shows 20 books per page


@dataclass
class Book:
	title: str
	authors: str
	isbn: str
	cents: int                 # the cheapest copy
	copies: int = 1
	cover: str | None = None   # url of the downloaded cover, None: draw one

	@property
	def price(self) -> str:
		"""€15 or €2,50"""
		euros, cents = divmod(self.cents, 100)
		return f"€{euros}" if cents == 0 else f"€{euros},{cents:02d}"

	@property
	def hue(self) -> int:
		"""A stable colour for the drawn cover."""
		return int(hashlib.md5(self.title.encode()).hexdigest(), 16) % 360


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
		return media_url(path)

	def slides(self, now: datetime) -> list[Slide]:
		if not self.books:
			return []
		count = min(self.books_per_slide, len(self.books))
		shown = [self.books[(self.next + i) % len(self.books)] for i in range(count)]
		self.next = (self.next + count) % len(self.books)
		return [Slide("books.html", self.seconds, {"books": shown})]
