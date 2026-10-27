"""The manual (docs/) stays true: when a slide type or a login is added, this says where to write it down.

The people who maintain the slideshow change every few years, so the manual is all they have.
"""

import re
import unittest
from pathlib import Path

from francken_tv.config import PROJECT_DIR

DOCS = PROJECT_DIR / "docs"
MANUAL = [PROJECT_DIR / "README.md", *sorted(DOCS.rglob("*.md"))]


def all_text() -> str:
	return "\n".join(page.read_text(encoding="utf-8") for page in MANUAL)


class ManualTest(unittest.TestCase):
	def test_every_slide_type_is_in_the_readme_table(self):
		readme = (PROJECT_DIR / "README.md").read_text(encoding="utf-8")
		providers = {path.stem for path in (PROJECT_DIR / "francken_tv" / "providers").glob("*.py") if path.stem != "__init__"}
		missing = sorted(name for name in providers if f"{name}.py" not in readme)
		self.assertEqual(missing, [], "add these to the slide table in README.md (docs/04-common-changes.md, 'Add a new slide type')")

	def test_every_login_file_is_in_the_accounts_page(self):
		accounts = (DOCS / "02-accounts-and-secrets.md").read_text(encoding="utf-8")
		code = "\n".join(path.read_text(encoding="utf-8") for path in (PROJECT_DIR / "francken_tv").rglob("*.py"))
		code += (PROJECT_DIR / "config" / "config.toml").read_text(encoding="utf-8")
		logins = set(re.findall(r"~/\.config/slideshow/([\w.]+\.json)", code))
		missing = sorted(name for name in logins if name not in accounts)
		self.assertEqual(missing, [], "describe these logins in docs/02-accounts-and-secrets.md")

	def test_every_file_kept_out_of_git_is_in_the_handover(self):
		handover = (DOCS / "01-handover.md").read_text(encoding="utf-8")
		ignored = [line.strip() for line in (PROJECT_DIR / ".gitignore").read_text().splitlines()
			if line.strip().startswith(("config/", "media/"))]
		missing = [path for path in ignored if path.rstrip("/") not in handover]
		self.assertEqual(missing, [], "list these in docs/01-handover.md, 'Not everything is in git'")

	def test_links_between_the_pages_work(self):
		broken = []
		for page in MANUAL:
			for target in re.findall(r"\]\(([^)#\s]+)(?:#[^)]*)?\)", page.read_text(encoding="utf-8")):
				if target.startswith(("http://", "https://", "mailto:")):
					continue
				if not (page.parent / target).resolve().exists():
					broken.append(f"{page.relative_to(PROJECT_DIR)} -> {target}")
		self.assertEqual(broken, [])

	def test_the_paths_the_manual_names_exist(self):
		for path in ("deploy/fix_dns.sh", "deploy/fix_tv_resolution.sh", "config/dilemmas.txt", "config/commandments.txt",
				"config/quote_filter.txt", "tests/fixtures", "firmware"):
			self.assertTrue((PROJECT_DIR / path).exists(), f"the manual mentions {path}")
			self.assertIn(path, all_text())


if __name__ == "__main__":
	unittest.main()
