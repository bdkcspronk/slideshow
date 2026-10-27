"""The backup to Nextcloud: what is uploaded and kept, restoring without overwriting, and the warnings."""

import io
import json
import shutil
import tarfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from francken_tv import backup
from francken_tv.nextcloud import Entry

NOW = datetime(2026, 10, 27, 3, 30)


class FakeNextcloud:
	"""Files in a dict: the same calls as nextcloud.Nextcloud."""

	def __init__(self):
		self.files: dict[str, bytes] = {}

	def make_folder(self, path):
		pass

	def upload(self, path, source):
		self.files[path] = Path(source).read_bytes()

	def download(self, path, destination):
		Path(destination).write_bytes(self.files[path])

	def delete(self, path):
		del self.files[path]

	def list_folder(self, path):
		return [Entry(name, False) for name in self.files if name.startswith(path + "/")]


class FakeCrypto:
	"""Not encryption: only checks that the passphrase is passed along and checked (gpg itself is tested below)."""

	def encrypt(self, source, destination, passphrase):
		Path(destination).write_bytes(passphrase.encode() + b"\n" + Path(source).read_bytes())

	def decrypt(self, source, destination, passphrase):
		head, _, body = Path(source).read_bytes().partition(b"\n")
		if head.decode() != passphrase:
			raise RuntimeError("wrong passphrase")
		Path(destination).write_bytes(body)


class BackupTest(unittest.TestCase):
	def setUp(self):
		self.folder = TemporaryDirectory()
		self.dir = Path(self.folder.name)
		(self.dir / "project" / "media").mkdir(parents=True)
		(self.dir / "project" / "config").mkdir()
		(self.dir / "home").mkdir()
		for patch in [mock.patch.object(backup, "PROJECT_DIR", self.dir / "project"),
				mock.patch.object(backup, "HOME_CONFIG", self.dir / "home")]:
			patch.start()
			self.addCleanup(patch.stop)
		(self.dir / "project" / "media" / "poster.png").write_bytes(b"poster")
		(self.dir / "project" / "media" / "voices").mkdir()
		(self.dir / "project" / "media" / "voices" / "voice.onnx").write_bytes(b"large")
		(self.dir / "project" / "config" / "devices.json").write_text('{"aa": "Ann"}')
		(self.dir / "home" / "spotify.json").write_text('{"client_id": "x"}')
		(self.dir / "home" / "backup.passphrase").write_text("secret")
		self.state = self.dir / "state.json"
		self.nextcloud = FakeNextcloud()

	def tearDown(self):
		self.folder.cleanup()

	def backup(self, now=NOW, keep=4):
		return backup.run_backup(self.nextcloud, "b", keep, "secret", now, self.state, FakeCrypto())

	def test_secrets_and_media_are_two_archives(self):
		self.backup()
		self.assertEqual(sorted(self.nextcloud.files), ["b/media-2026-10-27.tar.gz.gpg", "b/secrets-2026-10-27.tar.gz.gpg"])

	def test_the_passphrase_file_is_never_in_the_backup(self):
		names = [name for _, name in backup.part_files("secrets")]
		self.assertEqual(sorted(names), ["config/devices.json", "home-config/spotify.json"])

	def test_the_text_to_speech_voice_is_left_out(self):
		names = [name for _, name in backup.part_files("media")]
		self.assertEqual(names, ["media/poster.png"])

	def test_restoring_needs_the_right_passphrase(self):
		self.backup()
		with self.assertRaises(RuntimeError):
			backup.run_restore(self.nextcloud, "b", "wrong", crypto=FakeCrypto())

	def test_unchanged_parts_are_not_uploaded_again(self):
		self.backup()
		later = self.backup(NOW + timedelta(days=7))
		self.assertEqual(len(self.nextcloud.files), 2)
		self.assertTrue(all("unchanged" in message for message in later))
		self.assertEqual(backup.read_state(self.state)["last_success"], (NOW + timedelta(days=7)).isoformat(timespec="seconds"))

	def test_a_changed_part_is_uploaded_and_only_the_newest_are_kept(self):
		self.backup(keep=2)
		for week in range(1, 4):
			(self.dir / "home" / "spotify.json").write_text(json.dumps({"week": week}))
			self.backup(NOW + timedelta(days=7 * week), keep=2)
		secrets = [name for name in self.nextcloud.files if "secrets" in name]
		self.assertEqual(sorted(secrets), ["b/secrets-2026-11-10.tar.gz.gpg", "b/secrets-2026-11-17.tar.gz.gpg"])
		self.assertEqual(len([name for name in self.nextcloud.files if "media" in name]), 1)

	def test_restore_on_a_new_pc_puts_everything_back(self):
		self.backup()
		shutil.rmtree(self.dir / "project")
		shutil.rmtree(self.dir / "home")
		backup.run_restore(self.nextcloud, "b", "secret", crypto=FakeCrypto())
		self.assertEqual((self.dir / "project" / "media" / "poster.png").read_bytes(), b"poster")
		self.assertEqual((self.dir / "project" / "config" / "devices.json").read_text(), '{"aa": "Ann"}')
		self.assertEqual((self.dir / "home" / "spotify.json").read_text(), '{"client_id": "x"}')

	def test_restore_leaves_existing_files_alone_unless_forced(self):
		self.backup()
		(self.dir / "project" / "config" / "devices.json").write_text("newer")
		messages = backup.run_restore(self.nextcloud, "b", "secret", crypto=FakeCrypto())
		self.assertEqual((self.dir / "project" / "config" / "devices.json").read_text(), "newer")
		self.assertTrue(any("left 1 existing" in message for message in messages))
		backup.run_restore(self.nextcloud, "b", "secret", force=True, crypto=FakeCrypto())
		self.assertEqual((self.dir / "project" / "config" / "devices.json").read_text(), '{"aa": "Ann"}')

	def test_restore_refuses_an_archive_that_writes_outside_the_project(self):
		evil = self.dir / "evil.tar.gz"
		with tarfile.open(evil, "w:gz") as archive:
			info = tarfile.TarInfo("../outside.txt")
			info.size = 1
			archive.addfile(info, io.BytesIO(b"x"))
		with self.assertRaises(RuntimeError):
			backup.extract(evil, force=True)
		self.assertFalse((self.dir / "outside.txt").exists())

	def test_without_a_backup_restore_says_so(self):
		messages = backup.run_restore(self.nextcloud, "b", "secret", crypto=FakeCrypto())
		self.assertIn("no backup", messages[0])


class WarningsTest(unittest.TestCase):
	def setUp(self):
		self.folder = TemporaryDirectory()
		self.state = Path(self.folder.name) / "state.json"
		self.passphrase = Path(self.folder.name) / "backup.passphrase"

	def tearDown(self):
		self.folder.cleanup()

	def test_no_passphrase_means_no_backup_is_set_up(self):
		self.assertIn("setup", backup.warnings(NOW, self.state, self.passphrase)[0])

	def test_set_up_but_never_run(self):
		self.passphrase.write_text("x")
		self.assertIn("no backup has run", backup.warnings(NOW, self.state, self.passphrase)[0])

	def test_a_recent_backup_is_fine_and_an_old_one_is_not(self):
		self.passphrase.write_text("x")
		backup.write_state({"last_success": (NOW - timedelta(days=8)).isoformat()}, self.state)
		self.assertEqual(backup.warnings(NOW, self.state, self.passphrase), [])
		backup.write_state({"last_success": (NOW - timedelta(days=12)).isoformat()}, self.state)
		self.assertIn("12 days ago", backup.warnings(NOW, self.state, self.passphrase)[0])


@unittest.skipUnless(shutil.which("gpg"), "gpg is not installed")
class GpgTest(unittest.TestCase):
	def test_round_trip_and_wrong_passphrase(self):
		with TemporaryDirectory() as folder:
			plain, encrypted, back = (Path(folder) / name for name in ("plain", "encrypted", "back"))
			plain.write_bytes(b"the Instagram token")
			backup.Gpg().encrypt(plain, encrypted, "correct horse")
			self.assertNotIn(b"Instagram", encrypted.read_bytes())
			backup.Gpg().decrypt(encrypted, back, "correct horse")
			self.assertEqual(back.read_bytes(), b"the Instagram token")
			with self.assertRaises(RuntimeError):
				backup.Gpg().decrypt(encrypted, Path(folder) / "other", "wrong")


if __name__ == "__main__":
	unittest.main()
