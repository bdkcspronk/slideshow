# Francken TV: the manual

This folder is the manual for whoever looks after the slideshow on the TV in the Francken room.
You don't need to know the code, or to have met the people who built it. Pick your situation:

| You are... | Read |
|---|---|
| **New here**, taking over the slideshow | [1. Handover](01-handover.md), then skim the rest once |
| **Seeing something wrong** (slide missing, TV black, no sound, ...) | [3. When something breaks](03-when-something-breaks.md) |
| **Wanting to change something** (a poster, a time, a new slide) | [4. Common changes](04-common-changes.md) |
| **Wondering which passwords and accounts exist**, or one has expired | [2. Accounts and secrets](02-accounts-and-secrets.md) |
| **Reading the code** for the first time | [5. Architecture](05-architecture.md) |
| **Setting up the TV PC** again (it died, or we got a new one) | [6. The TV PC](06-tv-pc.md), including restoring the backup |

Step-by-step setup guides for the outside services are in [setup/](setup/):
[Spotify](setup/spotify.md), [Instagram](setup/instagram.md), [the weekly dilemma](setup/weekly-dilemma.md).

The [main README](../README.md) lists every slide and how to run the slideshow on a laptop.

## The two rules

1. **Look at `/status` first.** Open <http://127.0.0.1:8080/status> on the TV PC (or `/health`
   for a short summary). It shows which slide types work, which don't and why, and which logins
   are about to expire.
2. **Everything you'd want to change is in `config/config.toml`**, and every setting there has a
   comment. You rarely need to touch the code.

## Keeping this manual true

A test (`tests/test_docs.py`) fails if a slide type, a login file or a file kept out of git is not described here or in
the README, or if a link in the manual is broken. If you add one, the test tells you where to write it down. Please do:
the next person will have only this to go on.
