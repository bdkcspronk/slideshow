# Francken TV

The slideshow on the TV in the Francken room. It shows:

| Slide | Where it comes from | Code |
|---|---|---|
| Posters and announcements | images in `media/slides/` | `providers/images.py` |
| Upcoming activities | professorfrancken.nl/association/activities | `providers/activities.py` |
| A photo from one of the last 3 events | Nextcloud `images/albums/` | `providers/event_photos.py` |
| Who was in the room today (animated chart) | the ESP32 sniffer | `providers/presence.py`, `activity_chart.py` |
| This week's leaderboard: most time in the room | the ESP32 sniffer | `providers/presence.py` |
| A random quote (read aloud) | the quotes Google Sheet | `providers/quote.py` |
| What's playing on Spotify (only while something plays) | Spotify | `providers/spotify.py` |
| Daily puzzles: Connections \| Wordle \| Catfishing, with today's status; tap one to play it | nytimes.com, catfishing.net | `providers/puzzles.py`, `connections.py`, `wordle.py`, `catfishing.py` |
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

In the terminal: **Ctrl+M** (or Enter) turns reading quotes aloud on/off, **Ctrl+R** reloads
`config/devices.json`, **Ctrl+C** stops everything.
Alt+F4 closes the full-screen browser.
Without `start.sh`: `python3 -m francken_tv`, then open http://127.0.0.1:8080.

- http://127.0.0.1:8080/status shows each slide type, when it last refreshed, and its last error.
- http://127.0.0.1:8080/preview/activities shows one slide (also `quote`, `presence`, `bieruur_countdown`, ...).
- Keys in the slideshow: →/↓ next, ←/↑ previous, space pause, `m` toggle reading quotes aloud.
- Tapping a puzzle on the Daily puzzles slide opens it and pauses the slideshow so people can play
  (Wordle also takes the keyboard); it continues after a minute without input, 15 seconds after the
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

The Spotify slide shows what's playing (it only appears while something plays). One-time setup:

1. At https://developer.spotify.com/dashboard, log in and **Create app**. Any name and description;
   **Redirect URI**: `http://127.0.0.1:8080/spotify/callback` (exactly this; `127.0.0.1`, not
   `localhost`); tick **Web API**.
2. Open the app's **Settings** and put its **Client ID** and **Client secret** in
   `~/.config/slideshow/spotify.json` on the TV PC:
   `{"client_id": "...", "client_secret": "..."}`
3. Start the slideshow and open http://127.0.0.1:8080/spotify/login **on the TV PC**; log in with
   the Spotify account whose music should be shown. The slideshow adds a refresh token to that
   file (no password is stored). It keeps working after restarts.

## Updating a PC that ran the old slideshow

```sh
git pull
deploy/migrate_from_old_layout.sh   # moves slides/, audio/, Sniffer/filter.json, ... to the new places
```

Then follow the steps below (venv, piper) and start it with `./start.sh --fullscreen`.

## Running on the TV PC

```sh
sudo apt install python3-jinja2 python3-requests python3-bs4 python3-pil python3-serial python3-venv ffmpeg chromium
sudo usermod -aG dialout $USER                      # serial port access for the sniffer; log in again after
git clone <this repo> ~/slideshow && cd ~/slideshow
python3 -m venv --system-site-packages .venv        # uses the apt packages above
.venv/bin/pip install piper-tts tomli               # text-to-speech; tomli is only needed on Python 3.10
mkdir -p ~/.config/systemd/user && cp deploy/*.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now francken-tv francken-tv-sniffer francken-tv-kiosk
sudo loginctl enable-linger $USER                   # keep running without anyone logged in
```

Logs: `journalctl --user -u francken-tv -f` (or `-u francken-tv-sniffer`).
After changing `config.toml`: `systemctl --user restart francken-tv`.

To import the logs of the old sniffer: `python3 -m francken_tv.sniffer --import filtered_output.jsonl`.

The sniffer firmware lives in `firmware/` (PlatformIO).
