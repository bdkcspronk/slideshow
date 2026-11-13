import io
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

from PIL import Image, ImageDraw

from francken_tv.providers.books import CASE_SIZE, Book, BooksProvider, average_colour, combine_copies, is_blank, parse_books

FIXTURE = Path(__file__).parent / "fixtures" / "books.html"
NOW = datetime(2026, 10, 17, 12, 0)


def jpeg(draw_something: bool) -> bytes:
	"""A cover: a pale page, with a dark block on it or blank."""
	image = Image.new("RGB", (330, 500), (235, 230, 220))
	if draw_something:
		ImageDraw.Draw(image).rectangle((40, 60, 290, 200), fill=(20, 40, 120))
	out = io.BytesIO()
	image.save(out, "JPEG")
	return out.getvalue()


COVER, BLANK = jpeg(True), jpeg(False)


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
				return FakeResponse(200, content=COVER) if "1938168186" in url else FakeResponse(404)
			return FakeResponse(200, page if params["page"] <= 2 else "<main></main>")

		with mock.patch("francken_tv.providers.books.requests.get", side_effect=get) as request, \
				mock.patch("francken_tv.providers.books.media_url", side_effect=lambda path: f"/files/{path.name}"):
			self.provider.refresh(NOW)
		pages = [call.kwargs["params"]["page"] for call in request.call_args_list if call.kwargs.get("params")]
		self.assertEqual(pages, [1, 2, 3])
		self.assertEqual(len(self.provider.books), len(combine_copies(parse_books(page))))   # page 2 = the same copies again
		covers = {book.isbn: book for book in self.provider.books}
		self.assertEqual(covers["1938168186"].cover, "/files/1938168186.jpg")
		self.assertTrue(covers["1938168186"].cloth.startswith("rgb("))   # the spine in the cover's colour
		self.assertIsNone(covers["9781292114064"].cover)
		self.assertTrue(covers["9781292114064"].cloth.startswith("hsl("))

	def test_blank_or_unreadable_covers_are_drawn_instead(self):
		folder = Path(self.folder.name)
		for name, content, blank in [("cover", COVER, False), ("blank", BLANK, True), ("broken", b"not a jpeg", True)]:
			(folder / f"{name}.jpg").write_bytes(content)
			self.assertEqual(is_blank(folder / f"{name}.jpg"), blank, name)
		with mock.patch("francken_tv.providers.books.requests.get", return_value=FakeResponse(200, content=BLANK)):
			self.assertIsNone(self.provider.download_cover("1234567890"))

	def test_average_colour_is_darker(self):
		path = Path(self.folder.name) / "orange.png"
		Image.new("RGB", (10, 10), (200, 100, 0)).save(path)
		self.assertEqual(average_colour(path), "rgb(140, 70, 0)")

	def test_each_slide_takes_the_next_books_out_of_the_bookcase(self):
		self.provider.books = [Book(f"Book {i}", "", str(i), 1000) for i in range(5)]
		slides = [self.provider.slides(NOW)[0] for _ in range(2)]
		taken = [[(book.title, slot) for book, slot in slide.data["books"]] for slide in slides]
		self.assertEqual(taken, [[("Book 0", 0), ("Book 1", 1), ("Book 2", 2)], [("Book 3", 3), ("Book 4", 4), ("Book 0", 0)]])
		for slide in slides:   # always all books, in the same order
			self.assertEqual([book["title"] for book in slide.data["case"]], [f"Book {i}" for i in range(5)])
		self.assertEqual(slides[0].seconds, 15)

	def test_more_books_than_fit_in_the_bookcase(self):
		self.provider.books = [Book(f"Book {i}", "", str(i), 1000) for i in range(250)]
		for _ in range(200):   # round and round: the books taken out are always those in the bookcase at their place
			slide = self.provider.slides(NOW)[0]
			case = slide.data["case"]
			self.assertEqual(len(case), CASE_SIZE)
			for book, slot in slide.data["books"]:
				self.assertEqual(case[slot]["title"], book.title)

	def test_a_book_keeps_its_shape(self):
		book = Book("Calculus", "", "1", 1000)
		size, thickness = book.shape
		self.assertEqual(Book("Calculus", "x", "2", 500).shape, (size, thickness))
		self.assertTrue(0.82 <= size <= 1 and 0.55 <= thickness <= 1.35)

	def test_fewer_books_than_a_slide_holds(self):
		self.provider.books = [Book("Only", "", "1", 1000)]
		[slide] = self.provider.slides(NOW)
		self.assertEqual(len(slide.data["books"]), 1)

	def test_no_slide_without_books(self):
		self.assertEqual(self.provider.slides(NOW), [])


if __name__ == "__main__":
	unittest.main()
