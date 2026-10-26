"""Our Instagram: the latest posts on a phone, with a QR code to the account (templates/slides/instagram.html).

Read with the Instagram API with Instagram Login (a Meta app; setup: README, section "Instagram"). That
needs a professional (Business or Creator) account. The access token from Meta's dashboard is valid for
60 days; the slideshow renews it every week (REFRESH_EVERY), so it keeps working without logging in again.
The token lives in the credentials file ({"access_token": "..."}), together with when it was renewed.

The posts' pictures are downloaded (data/cache/instagram): Instagram's links to them expire.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import requests

from ..slides import Provider, Slide, media_url
from .news import ago

log = logging.getLogger(__name__)

API = "https://graph.instagram.com/v26.0"
REFRESH_URL = "https://graph.instagram.com/refresh_access_token"
PROFILE_FIELDS = "user_id,username,name,profile_picture_url,followers_count,media_count"
POST_FIELDS = "id,media_type,media_url,thumbnail_url,permalink,timestamp,like_count,comments_count"
REFRESH_EVERY = timedelta(days=7)      # renew the token (valid 60 days) this often
RETRY_REFRESH = timedelta(days=1)      # a token can only be renewed once it's a day old


@dataclass
class Post:
	picture_url: str        # Instagram's link to the picture (a video's cover), "" if there's none
	permalink: str
	time: datetime | None   # local time
	likes: int | None       # None when the likes are hidden
	comments: int
	caption: str = ""
	kind: str = "IMAGE"     # IMAGE, VIDEO or CAROUSEL_ALBUM
	picture: str = ""       # the downloaded copy, as a /files/ url


def parse_posts(data: dict) -> list[Post]:
	"""The posts from /me/media, newest first; a video shows its cover, an album its first picture."""
	posts = []
	for item in data.get("data") or []:
		kind = item.get("media_type", "IMAGE")
		picture = item.get("thumbnail_url") if kind == "VIDEO" else item.get("media_url")
		try:
			time = datetime.fromisoformat(item["timestamp"].replace("+0000", "+00:00")).astimezone().replace(tzinfo=None)
		except (KeyError, ValueError):
			time = None
		posts.append(Post(picture or item.get("thumbnail_url") or "", item.get("permalink", ""), time,
			item.get("like_count"), item.get("comments_count", 0), (item.get("caption") or "").strip(), kind))
	return posts


def count(number: int | None) -> str:
	"""1234 -> '1,234'; 12345 -> '12.3K', as Instagram writes them."""
	if number is None:
		return ""
	if number >= 10_000:
		return f"{number / 1000:.1f}".rstrip("0").rstrip(".") + "K"
	return f"{number:,}"


class InstagramProvider(Provider):
	name = "instagram"
	title = "Instagram"
	nothing_to_show = 'Not connected to Instagram (README, "Instagram")'
	refresh_seconds = 30 * 60

	def __init__(self, settings: dict, credentials_path: Path, image_folder: Path, default_seconds: float) -> None:
		self.credentials_path = credentials_path
		self.image_folder = image_folder
		self.seconds = settings.get("seconds", default_seconds)
		self.posts_shown = settings.get("posts", 6)
		self.profile: dict = {}
		self.posts: list[Post] = []
		self.captions = True   # Instagram may refuse captions to this kind of app; then we stop asking

	def credentials(self) -> dict:
		try:
			return json.loads(self.credentials_path.read_text(encoding="utf-8"))
		except FileNotFoundError:
			return {}

	def save_credentials(self, credentials: dict) -> None:
		self.credentials_path.parent.mkdir(parents=True, exist_ok=True)
		self.credentials_path.write_text(json.dumps(credentials, indent=1), encoding="utf-8")
		os.chmod(self.credentials_path, 0o600)   # only readable by this user

	def keep_token_fresh(self, credentials: dict, now: datetime) -> dict:
		"""Renew the token every week, so it never reaches its 60 days. Returns the credentials to use."""
		last = credentials.get("renewed_at") or credentials.get("renew_tried_at")
		wait = RETRY_REFRESH if "renew_tried_at" in credentials else REFRESH_EVERY
		if last and now - datetime.fromisoformat(last) < wait:
			return credentials
		response = requests.get(REFRESH_URL, params={"grant_type": "ig_refresh_token", "access_token": credentials["access_token"]}, timeout=20)
		if response.ok:
			token = response.json()
			credentials = {"access_token": token["access_token"], "renewed_at": now.isoformat(timespec="seconds"),
				"expires_at": (now + timedelta(seconds=token.get("expires_in", 0))).isoformat(timespec="seconds")}
			log.info("Renewed the Instagram token; valid until %s", credentials["expires_at"])
		else:   # e.g. less than a day old: try again tomorrow
			log.warning("Could not renew the Instagram token (%s): %s", response.status_code, response.text[:200])
			credentials = {key: value for key, value in credentials.items() if key != "renewed_at"} | {"renew_tried_at": now.isoformat(timespec="seconds")}
		self.save_credentials(credentials)
		return credentials

	def refresh(self, now: datetime) -> None:
		credentials = self.credentials()
		if not credentials.get("access_token"):
			raise RuntimeError(f"no Instagram token in {self.credentials_path} (README, \"Instagram\")")
		credentials = self.keep_token_fresh(credentials, now)
		token = credentials["access_token"]
		response = requests.get(f"{API}/me", params={"fields": PROFILE_FIELDS, "access_token": token}, timeout=20)
		response.raise_for_status()
		profile = response.json()
		posts = self.fetch_posts(token)
		profile["picture"], *pictures = self.download([profile.get("profile_picture_url") or ""] + [post.picture_url for post in posts])
		for post, picture in zip(posts, pictures):
			post.picture = picture
		self.profile, self.posts = profile, [post for post in posts if post.picture]   # a post without its picture is left out

	def fetch_posts(self, token: str) -> list[Post]:
		fields = POST_FIELDS + (",caption" if self.captions else "")
		response = requests.get(f"{API}/me/media", params={"fields": fields, "limit": self.posts_shown, "access_token": token}, timeout=20)
		if response.status_code == 400 and self.captions and "caption" in response.text:
			self.captions = False   # not for this kind of app: the posts without their captions
			return self.fetch_posts(token)
		response.raise_for_status()
		return parse_posts(response.json())

	def download(self, urls: list[str]) -> list[str]:
		"""Download pictures (once each), as /files/ urls ("" for one that can't be fetched), and delete the
		ones no longer needed."""
		self.image_folder.mkdir(parents=True, exist_ok=True)
		names, result = set(), []
		for url in urls:
			if not url:
				result.append("")
				continue
			path = self.image_folder / (hashlib.sha1(url.split("?")[0].encode()).hexdigest()[:16] + ".jpg")
			if not path.exists():
				try:
					response = requests.get(url, timeout=20)
					response.raise_for_status()
					path.write_bytes(response.content)
				except requests.RequestException as error:
					log.warning("Could not fetch an Instagram picture: %s", error)
					result.append("")
					continue
			names.add(path.name)
			result.append(media_url(path))
		for old in self.image_folder.iterdir():
			if old.name not in names:
				old.unlink()
		return result

	def slides(self, now: datetime) -> list[Slide]:
		if not self.profile or not self.posts:
			return []
		username = self.profile.get("username", "")
		return [Slide("instagram.html", self.seconds, {
			"username": username,
			"name": self.profile.get("name") or username,
			"picture": self.profile.get("picture", ""),
			"followers": count(self.profile.get("followers_count")),
			"post_count": count(self.profile.get("media_count")),
			"link": f"https://www.instagram.com/{username}/",
			"scroll_seconds": max(self.seconds - 5, 5),   # the posts scroll by, after a moment and with a moment left
			"posts": [{"picture": post.picture, "likes": count(post.likes), "comments": count(post.comments), "caption": post.caption,
				"ago": ago(post.time, now), "kind": post.kind} for post in self.posts],
		})]
