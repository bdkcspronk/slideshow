"""What is wrong right now, in plain words, and where in the manual to look.

Used by /health (one line per problem) and the top of /status. A problem is one of:
- a slide type whose last refresh failed (background.py records it),
- a provider's own warning (Provider.warnings(): e.g. a login that is about to expire),
- speech without its voice model (announcer.py),
- the backup of the files that aren't in git not set up or not running (backup.py),
- the automatic update from GitHub not working (updater.py).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

BREAKS = "docs/03-when-something-breaks.md"
ACCOUNTS = "docs/02-accounts-and-secrets.md"


@dataclass
class Problem:
	what: str     # the slide type or part that has the problem
	detail: str   # what is wrong
	manual: str   # the page of the manual to read


def problems(app, now: datetime) -> list[Problem]:
	found = []
	for name, provider in app.providers.items():
		status = app.runner.status.get(name)
		if status and status.last_error:
			found.append(Problem(name, f"last refresh failed: {status.last_error}", BREAKS))
		for warning in provider.warnings(now):
			found.append(Problem(name, warning, ACCOUNTS))
	announcer = getattr(app, "announcer", None)
	if announcer:
		found += [Problem("speech", warning, BREAKS) for warning in announcer.warnings()]
	if app.backup_warnings:
		found += [Problem("backup", warning, BREAKS) for warning in app.backup_warnings(now)]
	updater = app.updater
	if updater and ("not updating" in updater.last_result or "failed" in updater.last_result):
		found.append(Problem("updates", updater.last_result, BREAKS + " (\"The slideshow is on an old version\")"))
	return found


def as_text(app, now: datetime) -> str:
	found = problems(app, now)
	if not found:
		return "OK: every slide type works\n"
	lines = [f"{len(found)} problem(s):"]
	lines += [f"- {p.what}: {p.detail}  (see {p.manual})" for p in found]
	return "\n".join(lines) + "\n"
