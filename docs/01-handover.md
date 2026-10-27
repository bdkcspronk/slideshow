# 1. Handover

Read this when you take over the slideshow. It takes about fifteen minutes.

## What this is

A web page, shown full screen on the TV in the Francken room, that cycles through slides:
posters, upcoming activities, photos, news, weather, buses, the presence chart, puzzles, Spotify and
more (the full list is in the [README](../README.md)). A small Python program on the TV PC
decides what to show and a browser in kiosk mode displays it. Nobody has to touch it for it to run:
it starts itself, updates itself from GitHub, and recovers from a dropped internet connection.

## The mental model

Three words are enough to read the code:

- A **provider** makes the slides of one kind (`providers/activities.py` makes the activities slides).
- The **scheduler** picks what's on screen next. A **takeover** (bieruur, vrijmibo) can interrupt it.
- The **browser** only draws what the server sends it.

More in [5. Architecture](05-architecture.md).

## What you need access to

Fill this table in and keep it current. When you hand over, hand over *every* row.

| What | Why you need it | Held by (name, date) |
|---|---|---|
| GitHub repository `bdkcspronk/slideshow` | the code; the TV PC pulls updates from here. **It is on a private account of the current maintainer, not the association's:** when that person leaves, the repository must be transferred first (see [2. Accounts and secrets](02-accounts-and-secrets.md), the GitHub row) | the current maintainer (private GitHub account `bdkcspronk`) |
| The TV PC: location, login and how to reach it | fixing anything that isn't a code change | *fill in* |
| The accounts in [2. Accounts and secrets](02-accounts-and-secrets.md) | Instagram, Spotify, Nextcloud, Google Form. Spotify, Instagram/Meta and Nextcloud belong to the board: ask the board for access | the board (Spotify, Instagram, Nextcloud); *fill in* for the Google Form and Sheets |
| The backup of the files that are not in git (see below) | rebuilding the TV PC | *fill in* |

## Not everything is in git

Personal data and big files are deliberately kept out of the repository and live only on the TV PC,
in the project folder `~/slideshow/` (the cloned repository, with these files added to it) and in
`~/.config/slideshow/` (the logins). These files exist only there, apart from the backup (below):

| Path (on the TV PC) | What | Why not in git |
|---|---|---|
| `media/slides/` | the posters | large files |
| `media/vrijmibo.gif`, `media/bieruur/*.mp3` | the vrijmibo GIF and bieruur songs | large files |
| `media/quote_background.png`, `media/nyancat.png` | images for the quote slide and chart | large files |
| `media/voices/` | the text-to-speech voice | large files; **not in the backup** either: the slideshow downloads it again by itself ([6. The TV PC](06-tv-pc.md#the-text-to-speech-voice)) |
| `config/devices.json` | phone MAC addresses → names | personal data |
| `config/confidential.json`, `media/confidential/` | the confidential contact persons | personal data |
| `config/extern.json`, `media/extern/` | the extern's contact details | personal data |
| `~/.config/slideshow/*.json` | logins and tokens | secrets |
| `data/poll.json`, `data/settings.json`, `data/puzzles/highscores.json` | the weekly dilemma votes and history, the choices made on the TV, the puzzle high scores | history |
| `data/spotifyd/` | the login of the "Francken TV" Spotify speaker | secrets |

## The backup

These files are copied **every Monday night** to the board's Nextcloud (`backups/francken-tv/`), by the
`francken-tv-backup` timer on the TV PC (`francken_tv/backup.py`). Only the newest backup is kept: a new one replaces
the old one once it has been uploaded. The archives are **encrypted** with a passphrase, because the
Nextcloud folder may be visible to others (the photo committee, for instance) and the backup holds logins.

| | |
|---|---|
| **What is in it** | everything in the table above except the voice, in two archives: `secrets` (logins, personal data, settings; changes weekly because the Instagram token is renewed) and `media` (only uploaded again when something in it changed) |
| **Where** | Nextcloud, folder `backups/francken-tv/`, as `secrets-<date>.tar.gz.gpg` and `media-<date>.tar.gz.gpg` |
| **The passphrase** | on the TV PC in `~/.config/slideshow/backup.passphrase` (not itself in the backup), and **with the board, in their KeePass**. If both are lost, the backups cannot be opened. |
| **The Nextcloud login** | with the board. A new TV PC doesn't have it yet (it is in the backup), so restoring asks for it. |
| **Is it working?** | `/health` warns when no backup has run for 10 days, or none was ever set up. `journalctl --user -u francken-tv-backup` has the log. |
| **Restoring** | see [6. The TV PC](06-tv-pc.md#restoring-the-files-that-arent-in-git) |

Since only one backup is kept, a backup made while something was broken replaces the good one. If you are
about to change or delete something big (the posters, `devices.json`), do it after checking that the last
backup is what you want to keep, or copy the files by hand first.

## Your first week

1. Open `/status` on the TV PC and look at it. Everything works? Then you know what "good" looks like.
2. Find the logs: `journalctl --user -u francken-tv -f`. Skim a few minutes of them.
3. Read [3. When something breaks](03-when-something-breaks.md) so that you know it exists.
4. Check that the backup works (see "The backup" above): `python -m francken_tv.backup list` shows what is on Nextcloud, and `/health` says so if it has stopped. Do a restore on a spare PC once, so that you know it works before you need it.
5. Fill in the tables in this page and in [2. Accounts and secrets](02-accounts-and-secrets.md).

## When you hand over

Fill in the "held by" column, move the people in it to the new maintainer, and add the date. Then
change the passwords and tokens that were known to the old one: a login is only as private as the
last person who had it.
