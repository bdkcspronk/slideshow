"""The confidential contact persons slide (made-up people: the real ones aren't in git)."""

import json
import unittest
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from francken_tv.config import DATA_DIR
from francken_tv.providers.confidential import ConfidentialProvider

NOW = datetime(2026, 10, 22, 12, 0)


class ConfidentialTest(unittest.TestCase):
	def setUp(self):
		DATA_DIR.mkdir(exist_ok=True)
		self.folder = TemporaryDirectory(dir=DATA_DIR)   # inside the project, like media/confidential/
		self.addCleanup(self.folder.cleanup)
		self.path = Path(self.folder.name) / "confidential.json"
		self.photo = Path(self.folder.name) / "alex.jpg"
		self.photo.write_bytes(b"jpg")

	def write(self, data):
		self.path.write_text(json.dumps(data), encoding="utf-8")
		return ConfidentialProvider({"file": str(self.path)}, 15)

	def test_the_people_with_their_photos(self):
		provider = self.write({"email": "team@example.com", "website": "https://example.com/help", "people": [
			{"name": "Alex", "email": "alex@example.com", "photo": str(self.photo)},
			{"name": "Sam", "email": "sam@example.com", "photo": str(Path(self.folder.name) / "missing.jpg")},
		]})
		[slide] = provider.slides(NOW)
		alex, sam = slide.data["people"]
		self.assertEqual((alex["name"], alex["email"]), ("Alex", "alex@example.com"))
		self.assertEqual(alex["email_parts"], ["alex", "@example.com"])   # breaks only after a dot or before the @, the domain whole
		self.assertTrue(alex["photo"].startswith("/files/"))
		self.assertIsNone(sam["photo"])   # a missing photo: the first letter instead
		self.assertEqual((slide.data["email"], slide.data["title"]), ("team@example.com", "Confidential contact persons"))

	def test_email_parts(self):
		from francken_tv.providers.confidential import email_parts
		self.assertEqual(email_parts("alex.example.person@example.com"), ["alex.", "example.", "person", "@example.com"])
		self.assertEqual(email_parts("no-at-sign"), ["no-at-sign"])

	def test_no_file_or_nobody_no_slide(self):
		self.assertEqual(ConfidentialProvider({"file": str(self.path)}, 15).slides(NOW), [])
		self.assertEqual(self.write({"people": []}).slides(NOW), [])


if __name__ == "__main__":
	unittest.main()
