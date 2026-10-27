"""The speech voice: a missing piper model is downloaded, and until then nothing is spoken (without errors)."""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

import requests

from francken_tv import announcer
from francken_tv.announcer import Announcer, voice_urls


def fake_response(chunks=(b"data",), error=None):
	response = mock.MagicMock()
	response.__enter__.return_value = response
	response.raise_for_status.side_effect = error
	response.iter_content.return_value = list(chunks)
	return response


class VoiceDownloadTest(unittest.TestCase):
	def setUp(self):
		self.folder = TemporaryDirectory()
		self.voices = Path(self.folder.name) / "voices"
		self.cache = Path(self.folder.name) / "cache"

	def tearDown(self):
		self.folder.cleanup()

	def announcer(self, download_voice=True):
		# Made with downloading off: on a PC with piper installed, the constructor would start a real download.
		made = Announcer({"voice": "en_US-ryan-high", "download_voice": False}, self.voices, self.cache)
		made.has_piper, made.player = True, "ffplay"   # whatever this PC has installed
		made.download_voice = download_voice
		return made

	def test_where_piper_voices_are(self):
		self.assertEqual(voice_urls("en_US-ryan-high"), [
			"https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/ryan/high/en_US-ryan-high.onnx.json",
			"https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/ryan/high/en_US-ryan-high.onnx"])

	def test_a_missing_voice_is_downloaded_with_the_model_last(self):
		with mock.patch.object(announcer.requests, "get", side_effect=lambda *a, **k: fake_response()) as get:
			made = self.announcer()
			self.assertTrue(made.fetch_voice())
		self.assertEqual([call.args[0].rsplit("/", 1)[-1] for call in get.call_args_list], ["en_US-ryan-high.onnx.json", "en_US-ryan-high.onnx"])
		self.assertTrue((self.voices / "en_US-ryan-high.onnx").exists())
		self.assertEqual(made.warnings(), [])

	def test_a_failed_download_leaves_no_half_model_and_says_so(self):
		with mock.patch.object(announcer.requests, "get", side_effect=requests.ConnectionError("offline")):
			made = self.announcer()
			self.assertFalse(made.fetch_voice())
		self.assertFalse((self.voices / "en_US-ryan-high.onnx").exists())
		self.assertIn("nothing can be spoken", made.warnings()[0])

	def test_an_interrupted_download_is_not_taken_for_a_voice(self):
		broken = fake_response(error=requests.HTTPError("503"))
		with mock.patch.object(announcer.requests, "get", return_value=broken):
			self.assertFalse(self.announcer().fetch_voice())
		self.assertEqual([path.name for path in self.voices.glob("*.onnx")], [])

	def test_nothing_is_downloaded_when_switched_off(self):
		with mock.patch.object(announcer.requests, "get") as get:
			self.assertFalse(self.announcer(download_voice=False).fetch_voice())
		get.assert_not_called()

	def test_speaking_without_the_model_is_silent_not_an_error(self):
		made = self.announcer(download_voice=False)
		self.assertIsNone(made.synthesize("Hello"))

	def test_nothing_to_report_without_sound_or_piper(self):
		made = self.announcer()
		made.player = None
		self.assertEqual(made.warnings(), [])


if __name__ == "__main__":
	unittest.main()
