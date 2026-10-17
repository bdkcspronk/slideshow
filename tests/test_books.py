import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

from francken_tv.providers.books import Book, BooksProvider, combine_copies, parse_books

FIXTURE = Path(__file__).parent / "fixtures" / "books.html"
NOW = datetime(2026, 10, 17, 12, 0)


class FakeResponse:
	def __init__(self, status_code, text="", content=b""):
		self.status_code, self.text, self.content = status_code, text, content

	def raise_for_status(self):
		pass


class ParseBooksTest(unittest.TestCase):
	def setUp(self):
		self.books = parse_books(FIXTURE.read_text(encoding="utf-8"))

	def test_reads_title_authors_isbn_and_price(self):
		self.assertEqual(len(self.books), 20)
		first = self.books[0]
		self.assertEqual(first.title, "[Physics of the Quantum Universe] University Physics Volume 2")
		self.assertEqual(first.authors, "Samuel J. Ling, Jeff Sanny and William Moebs")
		self.assertEqual((first.isbn, first.cents, first.price), ("1938168186", 1500, "€15"))

	def test_price_with_cents(self):
		self.assertEqual(Book("x", "", "", 250).price, "€2,50")

	def test_copies_of_a_book_are_shown_once_at_the_lowest_price(self):
		books = combine_copies(self.books)
		electronics = [book for book in books if book.isbn == "9781292114064"]
		self.assertEqual([(book.copies, book.price) for book in electronics], [(3, "€15")])

	def test_free_copies_are_left_out(self):
		self.assertIn(0, [book.cents for book in self.books])
		self.assertNotIn(0, [book.cents for book in combine_copies(self.books)])


class BooksProviderTest(unittest.TestCase):
	def setUp(self):
		self.folder = tempfile.TemporaryDirectory()
		self.addCleanup(self.folder.cleanup)
		self.provider = BooksProvider({"books_per_slide": 3, "seconds": 15}, Path(self.folder.name))

	def test_refresh_reads_all_pages_and_downloads_covers(self):
		page = FIXTURE.read_text(encoding="utf-8")

		def get(url, params=None, timeout=None):
			if "openlibrary" in url:   # a cover for one book only
				return FakeResponse(200, content=b"jpeg") if "1938168186" in url else FakeResponse(404)
			return FakeResponse(200, page if params["page"] <= 2 else "<main></main>")

		with mock.patch("francken_tv.providers.books.requests.get", side_effect=get) as request, \
				mock.patch("francken_tv.providers.books.media_url", side_effect=lambda path: f"/files/{path.name}"):
			self.provider.refresh(NOW)
		pages = [call.kwargs["params"]["page"] for call in request.call_args_list if call.kwargs.get("params")]
		self.assertEqual(pages, [1, 2, 3])
		self.assertEqual(len(self.provider.books), len(combine_copies(parse_books(page))))   # page 2 = the same copies again
		covers = {book.isbn: book.cover for book in self.provider.books}
		self.assertEqual(covers["1938168186"], "/files/1938168186.jpg")
		self.assertIsNone(covers["9781292114064"])

	def test_each_slide_shows_the_next_books(self):
		self.provider.books = [Book(f"Book {i}", "", str(i), 1000) for i in range(5)]
		titles = [[book.title for book in self.provider.slides(NOW)[0].data["books"]] for _ in range(2)]
		self.assertEqual(titles, [["Book 0", "Book 1", "Book 2"], ["Book 3", "Book 4", "Book 0"]])
		self.assertEqual(self.provider.slides(NOW)[0].seconds, 15)

	def test_fewer_books_than_a_slide_holds(self):
		self.provider.books = [Book("Only", "", "1", 1000)]
		[slide] = self.provider.slides(NOW)
		self.assertEqual(len(slide.data["books"]), 1)

	def test_no_slide_without_books(self):
		self.assertEqual(self.provider.slides(NOW), [])


if __name__ == "__main__":
	unittest.main()
