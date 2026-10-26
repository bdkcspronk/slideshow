"""The news slide: the latest headlines of a few RSS feeds (Dagblad van het Noorden, NU.nl, BBC World by
default; [news] feeds in config.toml), one feed at a time: each time the slide comes round it shows the
next feed's headlines, large, each with its picture. One of the info slides: the scheduler shows one of
news, weather, buses and timetable per round (rotation.take_turns).

Tapping a headline opens the article: from the feed when it has the whole text, else from the article's
page (BBC), else the feed's summary (NU.nl and DvhN block fetching their pages). The slideshow downloads
each headline's picture itself (data/cache/news): one that can't be fetched is left out, instead of a
broken image making the player skip the slide.
"""

from __future__ import annotations

import hashlib
import logging
import re
import xml.etree.ElementTree as ElementTree
from dataclasses import dataclass, field
from datetime import datetime
from email.utils import parsedate_to_datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from ..slides import Provider, Slide, media_url

log = logging.getLogger(__name__)

HEADERS = {"User-Agent": "FranckenTV-slideshow/1.0 (the TV in the T.F.V. 'Professor Francken' room)"}
NEWS_FEEDS = [
	["Dagblad van het Noorden", "https://www.dvhn.nl/rss"],
	["NU.nl", "https://www.nu.nl/rss/Algemeen"],
	["BBC World", "https://feeds.bbci.co.uk/news/world/rss.xml"],
]
ADS = re.compile(r"commerci[eë]le[ -]content|advertorial|sponsored|gesponsord|partnercontent", re.IGNORECASE)


@dataclass
class Headline:
	title: str
	time: datetime | None   # local time
	link: str = ""
	paragraphs: list[str] = field(default_factory=list)   # the article, or its summary, from the feed
	image_url: str = ""   # the feed's picture, in a size fit for the TV (larger_image)
	image: str = ""       # the downloaded copy, as a /files/ url; "" if there's none


def is_ad(item: ElementTree.Element) -> bool:
	"""Whether a feed item is sponsored content: by its category or link (DvhN's "Commerciële content")."""
	text = " ".join([item.findtext("link") or ""] + [category.text or "" for category in item.iter("category")])
	return bool(ADS.search(text))


def parse_feed(xml: bytes | str) -> list[Headline]:
	"""The items of an RSS feed, newest first, without the ads."""
	headlines = []
	for item in ElementTree.fromstring(xml).iter("item"):
		title = (item.findtext("title") or "").strip()
		if not title or is_ad(item):
			continue
		try:
			time = parsedate_to_datetime(item.findtext("pubDate") or "").astimezone().replace(tzinfo=None)
		except (TypeError, ValueError):
			time = None
		headlines.append(Headline(title, time, (item.findtext("link") or "").strip(), html_paragraphs(item.findtext("description") or ""),
			larger_image(feed_image(item))))
	return sorted(headlines, key=lambda headline: headline.time or datetime.min, reverse=True)


def feed_image(item: ElementTree.Element) -> str:
	"""The picture of a feed item: an <enclosure> (NOS, NU.nl) or <media:thumbnail>/<media:content> (BBC)."""
	for child in item:
		tag = child.tag.rsplit("}", 1)[-1]
		url = child.attrib.get("url", "")
		if url and (tag in ("thumbnail", "content") or (tag == "enclosure" and child.attrib.get("type", "image").startswith("image"))):
			return url
	return ""


def larger_image(url: str) -> str:
	"""The same picture in a size for the TV: NU.nl's feed has 256x256 squares and the BBC's 240 pixels
	wide, while both sites also have larger versions at nearly the same address. NU.nl's square comes
	with the crop that made it square (x/y/width/height): left out, else the wide version is squeezed."""
	url = re.sub(r"_sqr\d+/(?:\d+/){4}|_sqr\d+/", "_wd1280/", url) if "images.nu.nl" in url else url
	return re.sub(r"/standard/\d+/", "/standard/976/", url) if "ichef.bbci.co.uk" in url else url


def html_paragraphs(html: str) -> list[str]:
	"""The text of a feed description or page part, as paragraphs."""
	soup = BeautifulSoup(html, "html.parser")
	paragraphs = [text for p in soup.find_all(["p", "h2", "h3", "li"]) if (text := p.get_text(" ", strip=True))]
	if not paragraphs and (text := soup.get_text(" ", strip=True)):
		paragraphs = [text]   # plain text, no tags
	return paragraphs


ARTICLE_SKIP = ["script", "style", "aside", "nav", "footer", "figure", "header", "form", "button"]


def article_paragraphs(html: str) -> list[str]:
	"""The paragraphs of an article page: those in its <article> (or <main>), leaving out captions,
	menus and the like, and lines too short to be text."""
	soup = BeautifulSoup(html, "html.parser")
	for tag in soup(ARTICLE_SKIP):
		tag.decompose()
	box = soup.find("article") or soup.find("main")
	if box is None:
		return []
	return [text for p in box.find_all("p") if len(text := p.get_text(" ", strip=True)) > 40]


def ago(time: datetime | None, now: datetime) -> str:
	"""'just now', '12 min ago', '3 hours ago', 'yesterday'"""
	if time is None:
		return ""
	minutes = int((now - time).total_seconds() // 60)
	if minutes < 2:
		return "just now"
	if minutes < 60:
		return f"{minutes} min ago"
	if minutes < 24 * 60:
		hours = minutes // 60
		return f"{hours} hour{'s' if hours > 1 else ''} ago"
	return "yesterday" if minutes < 48 * 60 else f"{minutes // (24 * 60)} days ago"


class NewsProvider(Provider):
	name = "news"
	title = "News"
	nothing_to_show = "No news yet"
	refresh_seconds = 15 * 60

	def __init__(self, settings: dict, default_seconds: float, image_folder: Path | None = None) -> None:
		self.image_folder = image_folder   # the news pictures; None: no pictures
		self.seconds = settings.get("seconds", default_seconds)
		self.feeds = settings.get("feeds", NEWS_FEEDS)
		self.headlines_per_feed = settings.get("headlines_per_feed", 3)
		self.news: dict[str, list[Headline]] = {}
		self.turn = 0   # which feed the slide shows next
		self.articles: dict[str, list[str]] = {}   # fetched article pages by link (see article_text)

	def refresh(self, now: datetime) -> None:
		news = {}
		for name, url in self.feeds:
			try:
				response = requests.get(url, headers=HEADERS, timeout=20)
				response.raise_for_status()
				news[name] = parse_feed(response.content)[: self.headlines_per_feed]
			except Exception as error:   # one feed down: the others still show
				log.warning("Could not read the %s feed: %s", name, error)
				if name in self.news:
					news[name] = self.news[name]
		if not news:
			raise RuntimeError("no news feed could be read")
		self.download_images([headline for headlines in news.values() for headline in headlines])
		self.news = news
		links = {headline.link for headlines in news.values() for headline in headlines}
		self.articles = {link: text for link, text in self.articles.items() if link in links}   # only what can still be opened

	def download_images(self, headlines: list[Headline]) -> None:
		"""Download the headlines' pictures (once each) and delete those of headlines that are gone."""
		if self.image_folder is None:
			return
		self.image_folder.mkdir(parents=True, exist_ok=True)
		keep = set()
		for headline in headlines:
			if not headline.image_url:
				continue
			suffix = Path(headline.image_url.split("?")[0]).suffix.lower() or ".jpg"
			path = self.image_folder / (hashlib.sha1(headline.image_url.encode()).hexdigest()[:16] + suffix)
			if not path.exists():
				try:
					response = requests.get(headline.image_url, headers=HEADERS, timeout=20)
					response.raise_for_status()
					if not response.headers.get("Content-Type", "").startswith("image/"):
						raise ValueError(f"not an image: {response.headers.get('Content-Type')}")
					path.write_bytes(response.content)
				except (requests.RequestException, ValueError) as error:
					log.warning("Could not fetch the picture %s: %s", headline.image_url, error)
					continue
			keep.add(path.name)
			headline.image = media_url(path)
		for old in self.image_folder.iterdir():
			if old.name not in keep:
				old.unlink()

	def slides(self, now: datetime) -> list[Slide]:
		feeds = self.feed_names()
		if not feeds:
			return []
		feed = feeds[self.turn % len(feeds)]   # the next feed each time the slide comes round
		self.turn += 1
		data = self.news_data(now, feed)
		return [Slide("news.html", self.seconds, data, update=lambda when: self.news_data(when, feed) or data)]

	def feed_names(self) -> list[str]:
		return [name for name, headlines in self.news.items() if headlines]

	def news_data(self, now: datetime, feed: str = "") -> dict | None:
		"""The headlines of one feed (the first if `feed` has none, e.g. after a refresh)."""
		feeds = self.feed_names()
		if not feeds:
			return None
		feed = feed if feed in feeds else feeds[0]
		return {"feed": feed, "feeds": feeds, "headlines": [{"title": headline.title, "ago": ago(headline.time, now),
			"link": headline.link, "image": headline.image} for headline in self.news[feed]]}

	def action(self, name: str, values: list[str], now: datetime) -> tuple[Slide | None, str | None]:
		"""'article' (values = [its link]): the article to read; 'news' (values = [the feed]): back to its headlines."""
		if name == "article" and values:
			found = next(((feed, headline) for feed, headlines in self.news.items() for headline in headlines
				if headline.link == values[0]), None)
			if found is None:
				return None, "That article is no longer in the news"
			feed, headline = found
			paragraphs, whole = self.article_text(headline)
			return Slide("news_article.html", self.seconds, {"feed": feed, "headline": headline, "ago": ago(headline.time, now),
				"paragraphs": paragraphs, "whole": whole}), None
		data = self.news_data(now, values[0] if values else "")
		return (Slide("news.html", self.seconds, data) if data else None), None

	def article_text(self, headline: Headline) -> tuple[list[str], bool]:
		"""The article's paragraphs, and whether that's the whole article (not only a summary)."""
		if len(headline.paragraphs) >= 3:   # the feed has the whole article
			return headline.paragraphs, True
		if headline.link not in self.articles:
			try:
				response = requests.get(headline.link, headers=HEADERS, timeout=15)
				response.raise_for_status()
				self.articles[headline.link] = article_paragraphs(response.text)
			except requests.RequestException as error:
				log.warning("Could not fetch the article %s: %s", headline.link, error)
				return headline.paragraphs, False
		paragraphs = self.articles[headline.link]
		return (paragraphs, True) if len(paragraphs) >= 2 else (headline.paragraphs, False)
