import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

from francken_tv.providers.instagram import InstagramProvider, count, parse_posts

NOW = datetime(2026, 10, 26, 20, 0)
MEDIA = {"data": [
	{"id": "1", "media_type": "IMAGE", "media_url": "https://cdn.example/a.jpg?x=1", "permalink": "https://instagram.com/p/a",
		"timestamp": "2026-10-26T17:00:00+0000", "like_count": 12345, "comments_count": 3, "caption": "Borrel!"},
	{"id": "2", "media_type": "VIDEO", "media_url": "https://cdn.example/v.mp4", "thumbnail_url": "https://cdn.example/v.jpg",
		"permalink": "https://instagram.com/p/v", "timestamp": "2026-10-20T10:00:00+0000", "comments_count": 0},
]}


class Response:
	def __init__(self, status=200, data=None, content=b"jpeg"):
		self.status_code, self.data, self.content = status, data, content
		self.ok = status < 400
		self.text = json.dumps(data) if data is not None else ""

	def json(self):
		return self.data

	def raise_for_status(self):
		if not self.ok:
			import requests
			raise requests.HTTPError(str(self.status_code))


def instagram(url, params=None, **kwargs):
	"""A fake Instagram: the token renewal, the profile, the posts and the pictures."""
	if "refresh_access_token" in url:
		return Response(data={"access_token": "renewed", "token_type": "bearer", "expires_in": 5184000})
	if url.endswith("/me"):
		return Response(data={"username": "tfvprofessorfrancken", "name": "T.F.V. 'Professor Francken'",
			"profile_picture_url": "https://cdn.example/me.jpg", "followers_count": 812, "media_count": 140})
	if url.endswith("/me/media"):
		return Response(data=MEDIA)
	return Response(content=b"picture")


class InstagramTest(unittest.TestCase):
	def setUp(self):
		self.folder = Path(tempfile.mkdtemp())
		self.credentials = self.folder / "instagram.json"
		self.provider = InstagramProvider({"posts": 6, "username": "@tfvprofessorfrancken"}, self.credentials, self.folder / "pictures", 20)
		patcher = mock.patch("francken_tv.providers.instagram.media_url", side_effect=lambda path: f"/files/{path.name}")
		patcher.start()
		self.addCleanup(patcher.stop)

	def test_parse_posts(self):
		image, video = parse_posts(MEDIA)
		self.assertEqual((image.picture_url, image.likes, image.caption), ("https://cdn.example/a.jpg?x=1", 12345, "Borrel!"))
		self.assertEqual((video.picture_url, video.likes, video.kind), ("https://cdn.example/v.jpg", None, "VIDEO"))   # a video: its cover
		self.assertEqual(image.time.date(), datetime(2026, 10, 26).date())

	def test_count(self):
		self.assertEqual([count(812), count(1234), count(12345), count(20000), count(None)], ["812", "1,234", "12.3K", "20K", ""])

	def test_not_connected(self):
		with self.assertRaises(RuntimeError):
			self.provider.refresh(NOW)
		[slide] = self.provider.slides(NOW)   # the account all the same, with empty tiles instead of posts
		self.assertEqual((slide.data["username"], slide.data["link"], slide.data["posts"], slide.data["tiles"]),
			("tfvprofessorfrancken", "https://www.instagram.com/tfvprofessorfrancken/", [], 9))
		no_account = InstagramProvider({}, self.credentials, self.folder / "pictures", 20)
		self.assertEqual(no_account.slides(NOW), [])

	def test_refresh_renews_the_token_and_shows_the_posts(self):
		self.credentials.write_text(json.dumps({"access_token": "from-the-dashboard"}))
		with mock.patch("francken_tv.providers.instagram.requests.get", side_effect=instagram):
			self.provider.refresh(NOW)
		saved = json.loads(self.credentials.read_text())
		self.assertEqual((saved["access_token"], saved["renewed_at"]), ("renewed", "2026-10-26T20:00:00"))
		[slide] = self.provider.slides(NOW)
		self.assertEqual((slide.data["username"], slide.data["followers"], slide.data["link"]), ("tfvprofessorfrancken", "812", "https://www.instagram.com/tfvprofessorfrancken/"))
		self.assertEqual([post["likes"] for post in slide.data["posts"]], ["12.3K", ""])
		self.assertRegex(slide.data["posts"][0]["ago"], r"^\d hours ago$")   # 17:00 UTC: how many hours depends on the time zone
		self.assertTrue(all(post["picture"].startswith("/files/") for post in slide.data["posts"]))
		self.assertEqual(len(list((self.folder / "pictures").iterdir())), 3)   # the profile picture and two posts

	def test_the_token_is_renewed_once_a_week(self):
		self.credentials.write_text(json.dumps({"access_token": "fresh", "renewed_at": (NOW - timedelta(days=3)).isoformat()}))
		with mock.patch("francken_tv.providers.instagram.requests.get", side_effect=instagram) as get:
			self.provider.refresh(NOW)
		self.assertFalse(any("refresh_access_token" in call.args[0] for call in get.call_args_list))
		self.assertEqual(json.loads(self.credentials.read_text())["access_token"], "fresh")

	def test_a_slide_made_before_the_posts_came_in_shows_them(self):
		[slide] = self.provider.slides(NOW)   # e.g. the first round after a restart: not fetched yet
		self.assertEqual(slide.data["posts"], [])
		self.credentials.write_text(json.dumps({"access_token": "t", "renewed_at": NOW.isoformat()}))
		with mock.patch("francken_tv.providers.instagram.requests.get", side_effect=instagram):
			self.provider.refresh(NOW)
		self.assertEqual(len(slide.update(NOW)["posts"]), 2)   # when it's shown, it has the posts

	def test_a_token_too_young_to_renew_is_tried_again_the_next_day(self):
		self.credentials.write_text(json.dumps({"access_token": "new"}))
		too_young = lambda url, **kwargs: Response(400, {"error": {"message": "too young"}}) if "refresh" in url else instagram(url, **kwargs)
		with mock.patch("francken_tv.providers.instagram.requests.get", side_effect=too_young) as get:
			self.provider.refresh(NOW)
			self.provider.refresh(NOW + timedelta(hours=2))   # not again yet
		self.assertEqual(sum("refresh_access_token" in call.args[0] for call in get.call_args_list), 1)
		saved = json.loads(self.credentials.read_text())
		self.assertEqual((saved["access_token"], saved["renew_tried_at"]), ("new", "2026-10-26T20:00:00"))
		self.assertEqual(len(self.provider.slides(NOW)), 1)   # the posts show all the same

	def test_without_captions_when_instagram_refuses_them(self):
		self.credentials.write_text(json.dumps({"access_token": "t", "renewed_at": NOW.isoformat()}))
		def no_captions(url, params=None, **kwargs):
			if url.endswith("/me/media") and "caption" in params["fields"]:
				return Response(400, {"error": {"message": "Tried accessing nonexisting field (caption)"}})
			return instagram(url, params, **kwargs)
		with mock.patch("francken_tv.providers.instagram.requests.get", side_effect=no_captions):
			self.provider.refresh(NOW)
		self.assertFalse(self.provider.captions)
		self.assertEqual(len(self.provider.slides(NOW)[0].data["posts"]), 2)


if __name__ == "__main__":
	unittest.main()
