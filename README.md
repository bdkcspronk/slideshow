# Francken TV

The slideshow on the TV in the Francken room. It shows:

| Slide | Where it comes from | Code |
|---|---|---|
| Posters and announcements | images in `media/slides/` | `providers/images.py` |
| Upcoming activities | professorfrancken.nl/association/activities | `providers/activities.py` |
| A photo from one of the last 3 events | Nextcloud `images/albums/` | `providers/event_photos.py` |
| Who was in the room today (animated chart) | the ESP32 sniffer | `providers/presence.py`, `activity_chart.py` |
| This week's leaderboard: most time in the room | the ESP32 sniffer | `providers/presence.py` |
| Second-hand books for sale: three at a time, as 3D books flying onto a shelf, with title and price | professorfrancken.nl/study/books, covers from openlibrary.org | `providers/books.py` |
| Info, in turn: news (Dagblad van het Noorden, NU.nl, BBC World), weather and rain at Zernike, buses from Aletta Jacobshal, today's Applied Physics timetable | RSS feeds, open-meteo.com, Buienradar, OVapi, rooster.rug.nl | `providers/info.py` |
| A random quote (read aloud) | the quotes Google Sheet | `providers/quote.py` |
| The commandment of the week by Jeff de Hosson, our honorary member (the next one each Monday) | `config/commandments.txt` | `providers/commandments.py` |
| The dilemma of the week: vote by tapping A or B, or scan the QR code and vote on your phone | `config/dilemmas.txt`, a Google Form | `providers/poll.py` |
| The latest xkcd comic, with its hover text | xkcd.com | `providers/xkcd.py` |
| What's playing on Spotify (only while something plays) | Spotify | `providers/spotify.py` |
| Daily puzzles: Connections \| Wordle \| Catfishing \| TimeGuessr, with today's status; tap one to play it. Left out once all are done for the day | nytimes.com, catfishing.net, timeguessr.com (map: OpenStreetMap) | `providers/puzzles.py`, `connections.py`, `wordle.py`, `catfishing.py`, `timeguessr.py` |
| Bieruur countdown; full screen from 15:58 to 16:02, with a song | | `providers/bieruur.py` |
| The vrijmibo GIF, every 15 minutes on Fridays | `media/vrijmibo.gif` | `providers/vrijmibo.py` |

Everything you'd want to change (times, durations, order, URLs) is in **`config/config.toml`**.

## How it fits together

```
 ESP32 ──serial──> sniffer.py ──> data/presence.sqlite3 ──┐
                                                          │
                     python -m francken_tv                ▼
   providers/*  ──slides──>  scheduler.py  ──>  server.py  ──HTTP──>  browser (kiosk)
   (refresh in background)   (+ takeovers)      (renders templates)
                                    announcer.py: greetings, quotes, bieruur song (ffplay)
```

- A **provider** contributes slides to each round (images, activities, ...). Slow work
  (downloading, drawing the chart) happens in its `refresh()`, in the background.
- A **takeover** grabs the screen at certain moments (bieruur, vrijmibo).
- A **job** does something at certain moments without a slide (bieruur song, greetings).
- The **scheduler** asks the takeovers first, otherwise shows the next slide of the round.
- The **browser** only displays what the server sends. You shouldn't need to touch `static/player.js`.

Each slide type is one Python file plus one small HTML template in `francken_tv/templates/slides/`.

### Adding a slide type

1. Write a `Provider` in `francken_tv/providers/` (copy `images.py` as a starting point).
2. Write its template in `francken_tv/templates/slides/` and add styles to `static/style.css`.
3. Create it in `build_app()` in `francken_tv/app.py`.
4. Add its name to `rotation.order` in `config/config.toml`.
5. Check it at http://127.0.0.1:8080/preview/your_name.

## Running it on your laptop

```sh
./start.sh                                    # server + sniffer (if plugged in) + a browser window
./start.sh --fullscreen                       # full screen (kiosk), as on the TV
./start.sh --fake-time "2026-10-16 15:57:30"  # pretend it's Friday just before bieruur
```

In the terminal: **Ctrl+M** (or Enter) turns reading quotes aloud on/off, **Ctrl+R** restarts the
slideshow (reads new code and `config.toml` again, e.g. after a `git pull`), **Ctrl+C** stops everything.
`config/devices.json` is reloaded under Esc -> Settings.
Alt+F4 closes the full-screen browser.
Without `start.sh`: `python3 -m francken_tv`, then open http://127.0.0.1:8080.

- http://127.0.0.1:8080/status shows each slide type, when it last refreshed, and its last error.
- http://127.0.0.1:8080/preview/activities shows one slide (also `quote`, `presence`, `bieruur_countdown`, ...).
- Keys in the slideshow: →/↓ next, ←/↑ previous, space pause, `m` mute/unmute all sound,
  `1` Daily puzzles, `2` Spotify, `3` today's activity chart (change these under `[shortcuts]` in
  `config/config.toml`).
- **Esc** opens the menu: live previews of those slide types (arrow keys + Enter, or click), plus
  - **Settings**: mute all sound, read quotes aloud, greet people, volume, slide speed, which slide
    types are shown, start one or all of today's puzzles over, reload `devices.json`. Volume and
    mute are the TV PC's main sound output (Spotify too; needs `wpctl` or `pactl`, standard on
    Ubuntu). The rest is saved in `data/settings.json`, which wins over `config.toml`; delete it to
    go back to the config.
  - **Power**: shut down or restart the TV PC (press twice). The commands are under `[power]` in
    `config/config.toml`.

  Esc again (or a minute without input) closes it and the slideshow continues.
- Tapping a puzzle on the Daily puzzles slide opens it and pauses the slideshow so people can play
  (Wordle also takes the keyboard); it continues after 4 minutes without input, 15 seconds after the
  game ends, or when bieruur starts. One shared game per day for each puzzle. To add a puzzle, see
  the top of `providers/puzzles.py`.

Run the tests with `python3 -m unittest`.

## Files that are not in git

Copy these to the TV PC by hand:

| Path | What |
|---|---|
| `media/slides/` | posters shown in the slideshow |
| `media/vrijmibo.gif` | the vrijmibo GIF |
| `media/bieruur/*.mp3` | bieruur songs (start offsets in `config.toml`) |
| `media/quote_background.png`, `media/nyancat.png` | images for the quote slide and chart |
| `media/voices/en_US-ryan-high.onnx(.json)` | piper text-to-speech voice |
| `config/devices.json` | phone MAC addresses → names, chart styles, greetings (personal data!) |
| `~/.config/slideshow/nextcloud.credentials.json` | Nextcloud login |

`data/` is created automatically: the presence database, caches and the downloaded quotes.

## Spotify

The Spotify slide shows what's playing and the next song (it only appears while something plays).
Its buttons skip songs, pause and change the volume; **Playlists** shows the account's playlists and
their songs, and **Search** finds songs by typing. Tapping a song plays it. The buttons need Spotify
Premium, and music already playing on some device. One-time setup:

1. At https://developer.spotify.com/dashboard, log in and **Create app**. Any name and description;
   **Redirect URI**: `http://127.0.0.1:8080/spotify/callback` (exactly this; `127.0.0.1`, not
   `localhost`); tick **Web API**.
2. Open the app's **Settings** and put its **Client ID** and **Client secret** in
   `~/.config/slideshow/spotify.json` on the TV PC:
   `{"client_id": "...", "client_secret": "..."}`
3. Start the slideshow and open http://127.0.0.1:8080/spotify/login **on the TV PC**; log in with
   the Spotify account whose music should be shown. The slideshow adds a refresh token to that
   file (no password is stored). It keeps working after restarts. Connected before changing
   playlists was possible? Log in once more, so Spotify allows it.
4. So music plays from the PC itself (not from a Spotify tab somewhere): `deploy/install_spotifyd.sh`
   installs [spotifyd](https://github.com/Spotifyd/spotifyd) as `~/.local/bin/spotifyd` and logs it
   in once (open the link it prints on that PC; `--login` logs in again). The TV PC runs it with
   `francken-tv-spotifyd.service` (see "Running on the TV PC"); elsewhere `start.sh` starts it (log:
   `data/spotifyd.log`). The PC is then a Spotify speaker called "Francken TV"; when nothing plays,
   the slide starts music there, and "Play on TV" moves music playing elsewhere to it. Without it,
   songs only play when a Spotify app somewhere is already playing.

## Weekly dilemma

The dilemmas are in `config/dilemmas.txt` (`question | option A | option B`, one per line, the next
one every Monday). Tapping A or B on the TV counts a vote. To also vote on phones (the QR code):

1. Make a Google Form with one multiple-choice question, e.g. "Answer", with the answers **A)** and
   **B)** ("A", "A: ..." work too): then the same form works every week, and only `dilemmas.txt`
   decides what A and B are. (Answers with the options' own texts also count, but then the form has
   to be changed every Monday.) Don't collect email addresses, and don't restrict it to an
   organisation: then it needs no login.
2. *Responses* -> *Link to Sheets*: a new sheet. Share that sheet as "Anyone with the link can view".
3. In `config/config.toml`, `[poll]`: `form_url` = the form's link (*Send* -> link, shortened is fine),
   `sheet_id` = the long code in the sheet's link (`/spreadsheets/d/<sheet_id>/edit`).
4. Restart the slideshow. Only this week's responses count (by their timestamp), so the same form
   works every week. The date order of the sheet's timestamps is worked out from the sheet; for the first
   days of a month it uses `timestamp_day_first` (false: American dates, 10/19/2026).

Both kinds of votes are added up on the slide, with last week's outcome below. `data/poll.json` keeps
every week's dilemma and votes (keep it when moving the slideshow to another PC).

## Running on the TV PC

The slideshow updates itself: every 10 minutes it checks GitHub for new commits, pulls them (only
when the TV PC has no changes of its own), runs the tests and restarts, never during bieruur. A
commit whose tests fail is not taken; the log says why. Switch it off with `[update] auto = false`.

```sh
sudo apt install python3-jinja2 python3-requests python3-bs4 python3-pil python3-serial python3-venv ffmpeg firefox
sudo usermod -aG dialout $USER                      # serial port access for the sniffer; log in again after
git clone <this repo> ~/slideshow && cd ~/slideshow
python3 -m venv --system-site-packages .venv        # uses the apt packages above
.venv/bin/pip install piper-tts tomli               # text-to-speech; tomli is only needed on Python 3.10
deploy/install_spotifyd.sh                          # the "Francken TV" Spotify speaker; open the login link it prints
mkdir -p ~/.config/systemd/user && cp deploy/*.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now francken-tv francken-tv-sniffer francken-tv-kiosk francken-tv-spotifyd
sudo loginctl enable-linger $USER                   # keep running without anyone logged in
```

Logs: `journalctl --user -u francken-tv -f` (or `-u francken-tv-sniffer`).
After changing `config.toml`: `systemctl --user restart francken-tv`.
Closed the full-screen slideshow with Alt+F4? It stays closed; bring it back with `systemctl --user start francken-tv-kiosk`
(`stop` to close it from a terminal). Starting `francken-tv` also opens it, and starts the Spotify speaker
(`francken-tv-spotifyd`); stopping `francken-tv` stops the speaker too.

The sniffer firmware lives in `firmware/` (PlatformIO).
