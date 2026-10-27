# 4. Common changes

Recipes for the jobs that come up. After changing `config/config.toml`, restart the slideshow:
`systemctl --user restart francken-tv` (or `Ctrl+R` in the terminal). Posters and the text files below
are read again every round: no restart.

## Posters and announcements

Copy the image into `media/slides/` on the TV PC. It shows up in the next round. Delete it to remove it.
GIFs and short animations work; their length decides how long they're shown.

## The weekly dilemma

Add a line to `config/dilemmas.txt`: `question | option A | option B`. One per line; the slideshow
shows the next line every Monday. Commit and push (the TV PC picks it up). If phone votes use the
Google Form, see [the dilemma setup](setup/weekly-dilemma.md).

## The commandment of the week

Add a line to `config/commandments.txt`; the next one is shown every Monday.

## Quotes

They come from the Google Sheet named in `[quote] sheet_id`. Add a row there. To keep certain words
out, add them to `config/quote_filter.txt`.

## Change when or how long something is shown

All in `config/config.toml`, each with a comment: `seconds` per slide type, `rotation.order` (the
order and which types appear), `daytime_from` / `daytime_until`, the bieruur time, and the day and
frequency of the vrijmibo GIF.

## Add a bieruur song

Put the `.mp3` in `media/bieruur/`. If the song's "drop" doesn't land on bieruur, add an offset under
`[bieruur.song_offsets]` (seconds; negative starts earlier).

## Who is who on the presence chart

`config/devices.json` on the TV PC (not in git: personal data) maps phone MAC addresses to names,
colours and greetings. Reload it with `Esc` → Settings.

## Change the bus stop, the timetable or the weather location

`[buses]`, `[timetable]` and `[weather]` in `config/config.toml`. The comments there explain how to
find the stop codes and programme names.

## Add a new slide type

1. Write a `Provider` in `francken_tv/providers/` (copy `images.py` as a starting point; it's the
   smallest).
2. Write its template in `francken_tv/templates/slides/` and its styles in `static/style.css`.
3. Create it in `build_app()` in `francken_tv/app.py`.
4. Add its name to `rotation.order` in `config/config.toml`, and a `[section]` with its settings and
   comments.
5. Preview it at <http://127.0.0.1:8080/preview/your_name>.
6. Add a row to the slide table in the [README](../README.md) (a test fails until you do), and, if
   it needs a login or a website, a row in [2. Accounts and secrets](02-accounts-and-secrets.md).
7. Write a test in `tests/` (look at `tests/test_xkcd.py`, a small one).
8. `python3 -m unittest` must pass: the TV PC refuses to update to a commit that fails it.

## Remove a slide type

Take its name out of `rotation.order`. That's enough; the code can stay.

## Renew or replace a login

See [2. Accounts and secrets](02-accounts-and-secrets.md); each row says where the login is and how
to renew it.

## Run it on your laptop to try something

```sh
./start.sh --fake-time "2026-10-16 15:57:30"   # pretend it's Friday just before bieruur
python3 -m unittest                             # all tests
```

The slideshow is made for Linux (the TV PC runs Ubuntu). **On Windows about 17 tests fail** for platform
reasons (a date format and file permissions), so run the tests on Linux, WSL, or the TV PC itself
before pushing: the TV PC will refuse a commit that fails them.

More in the [README](../README.md).
