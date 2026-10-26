import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

import requests

from francken_tv.providers.news import Headline, NewsProvider, ago, article_paragraphs, html_paragraphs, larger_image, parse_feed

SUNDAY_EVENING = datetime(2026, 10, 18, 19, 30)

RSS = """<?xml version="1.0"?><rss><channel>
<item><title><![CDATA[Older news]]></title><pubDate>Sun, 18 Oct 2026 12:07:31 GMT</pubDate></item>
<item><title>Newest news</title><link>https://example.org/new</link><pubDate>Sun, 18 Oct 2026 19:15:00 +0200</pubDate>
<description><![CDATA[<p>First.</p><h2>A heading</h2><p>Second.</p>]]></description>
<enclosure type="image/webp" url="https://images.cdn.nos.nl/a-1024x576.webp"/></item>
<item><title>BBC style</title><pubDate>Sun, 18 Oct 2026 10:00:00 GMT</pubDate>
<media:thumbnail xmlns:media="http://search.yahoo.com/mrss/" width="240" url="https://ichef.bbci.co.uk/ace/standard/240/x.jpg"/></item>
<item><title></title></item>
<item><title>An ad</title><category><![CDATA[Commerciële content]]></category><pubDate>Sun, 18 Oct 2026 19:20:00 +0200</pubDate></item>
<item><title>Another ad</title><link>https://www.dvhn.nl/commerciele-content/x/1.html</link></item>
</channel></rss>"""


class NewsTest(unittest.TestCase):
	def test_newest_first(self):
		headlines = parse_feed(RSS)
		self.assertEqual([headline.title for headline in headlines], ["Newest news", "Older news", "BBC style"])
		self.assertEqual(ago(headlines[0].time, SUNDAY_EVENING), "15 min ago")

	def test_link_and_text_from_the_feed(self):
		newest = parse_feed(RSS)[0]
		self.assertEqual((newest.link, newest.paragraphs), ("https://example.org/new", ["First.", "A heading", "Second."]))
		self.assertEqual(html_paragraphs("Only a summary, no tags."), ["Only a summary, no tags."])

	def test_pictures(self):
		headlines = {headline.title: headline for headline in parse_feed(RSS)}
		self.assertEqual(headlines["Newest news"].image_url, "https://images.cdn.nos.nl/a-1024x576.webp")
		self.assertEqual(headlines["BBC style"].image_url, "https://ichef.bbci.co.uk/ace/standard/976/x.jpg")   # larger than the feed's
		self.assertEqual(headlines["Older news"].image_url, "")
		self.assertEqual(larger_image("https://images.nu.nl/m/abc_sqr256/444/0/1/1/x.jpg"), "https://images.nu.nl/m/abc_wd1280/x.jpg")   # without the square's crop: not squeezed

	def test_article_page(self):
		long = "A sentence that is long enough to count as article text, not a menu item."
		page = f"<html><nav><p>{long} (menu)</p></nav><article><p>{long}</p><figure><p>{long} (caption)</p></figure>" \
			f"<p>Short.</p><p>{long} Two.</p></article></html>"
		self.assertEqual(article_paragraphs(page), [long, long + " Two."])
		self.assertEqual(article_paragraphs("<html><div class='consent'><p>Accept cookies</p></div></html>"), [])

	def test_ago(self):
		self.assertEqual(ago(datetime(2026, 10, 18, 19, 29), SUNDAY_EVENING), "just now")
		self.assertEqual(ago(datetime(2026, 10, 18, 16, 0), SUNDAY_EVENING), "3 hours ago")
		self.assertEqual(ago(datetime(2026, 10, 17, 12, 0), SUNDAY_EVENING), "yesterday")


class NewsProviderTest(unittest.TestCase):
	def setUp(self):
		self.provider = NewsProvider({}, 15)

	def test_a_slide_with_the_headlines(self):
		self.provider.news = {"NOS": [Headline("Nieuws", datetime(2026, 10, 18, 19, 0))]}
		[slide] = self.provider.slides(SUNDAY_EVENING)
		self.assertEqual((slide.template, slide.data["headlines"][0]["ago"]), ("news.html", "30 min ago"))

	def test_the_next_feed_each_time(self):
		self.provider.news = {"NOS": [Headline("A", None)], "BBC": [Headline("B", None)], "Empty": [], "NU.nl": [Headline("C", None)]}
		feeds = [self.provider.slides(SUNDAY_EVENING)[0].data["feed"] for _ in range(4)]
		self.assertEqual(feeds, ["NOS", "BBC", "NU.nl", "NOS"])   # a feed without headlines is skipped
		for _ in range(3):   # the menu, the shortcut key, the preview: the feed shown last, and the rotation goes on
			self.assertEqual(self.provider.shortcut_slide(SUNDAY_EVENING).data["feed"], "NOS")
		self.assertEqual(self.provider.slides(SUNDAY_EVENING)[0].data["feed"], "BBC")
		[slide] = self.provider.slides(SUNDAY_EVENING)            # NU.nl
		self.provider.news = {"BBC": [Headline("B", None)]}       # NU.nl gone after a refresh: the first feed instead
		self.assertEqual(slide.update(SUNDAY_EVENING)["feed"], "BBC")

	def test_open_an_article_and_go_back(self):
		long = "A sentence that is long enough to count as article text, not a menu item."
		self.provider.news = {
			"NOS": [Headline("Whole", None, "https://nos.example/1", ["One.", "Two.", "Three."])],
			"BBC": [Headline("Page", None, "https://bbc.example/2", ["Summary."])],
			"NU.nl": [Headline("Walled", None, "https://nu.example/3", ["Summary only."])],
		}
		with mock.patch("francken_tv.providers.news.requests.get") as get:
			slide, _ = self.provider.action("article", ["https://nos.example/1"], SUNDAY_EVENING)
			get.assert_not_called()   # the feed has the whole article
		self.assertEqual((slide.template, slide.data["paragraphs"], slide.data["whole"]), ("news_article.html", ["One.", "Two.", "Three."], True))
		page = mock.Mock(status_code=200, text=f"<article><p>{long}</p><p>{long}</p></article>")
		with mock.patch("francken_tv.providers.news.requests.get", return_value=page):
			slide, _ = self.provider.action("article", ["https://bbc.example/2"], SUNDAY_EVENING)
		self.assertEqual((len(slide.data["paragraphs"]), slide.data["whole"]), (2, True))
		wall = mock.Mock(status_code=200, text="<div>Accept our cookies</div>")
		with mock.patch("francken_tv.providers.news.requests.get", return_value=wall):
			slide, _ = self.provider.action("article", ["https://nu.example/3"], SUNDAY_EVENING)
		self.assertEqual((slide.data["paragraphs"], slide.data["whole"]), (["Summary only."], False))
		slide, _ = self.provider.action("news", ["NU.nl"], SUNDAY_EVENING)
		self.assertEqual((slide.template, slide.data["feed"]), ("news.html", "NU.nl"))   # back to the feed of the article
		self.assertIn("no longer", self.provider.action("article", ["https://gone.example"], SUNDAY_EVENING)[1])

	def test_pictures_are_downloaded_and_old_ones_removed(self):
		folder = Path(tempfile.mkdtemp())
		self.addCleanup(lambda: [path.unlink() for path in folder.iterdir()] and None)
		(folder / "old.jpg").write_bytes(b"gone")
		provider = NewsProvider({}, 15, folder)
		good, broken = Headline("A", None, image_url="https://img.example/a.jpg"), Headline("B", None, image_url="https://img.example/b.jpg")
		def get(url, **kwargs):
			if "b.jpg" in url:
				raise requests.ConnectionError("down")
			return mock.Mock(status_code=200, content=b"jpeg", headers={"Content-Type": "image/jpeg"}, raise_for_status=lambda: None)
		with mock.patch("francken_tv.providers.news.requests.get", side_effect=get), \
				mock.patch("francken_tv.providers.news.media_url", side_effect=lambda path: f"/files/{path.name}"):
			provider.download_images([good, broken])
		self.assertTrue(good.image.startswith("/files/") and good.image.endswith(".jpg"))
		self.assertEqual(broken.image, "")   # no picture rather than a broken one
		self.assertEqual([path.name for path in folder.iterdir()], [good.image.removeprefix("/files/")])

	def test_nothing_fetched_yet(self):
		self.assertEqual(self.provider.slides(SUNDAY_EVENING), [])


if __name__ == "__main__":
	unittest.main()
