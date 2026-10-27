# Francken TV

The slideshow on the TV in the Francken room.

**Maintaining it? The manual is in [docs/](docs/README.md)**: handover, accounts and logins, what to do when something breaks, and how to change things.

It shows:

| Slide | Where it comes from | Code |
|---|---|---|
| Posters and announcements | images in `media/slides/` | `providers/images.py` |
| Upcoming activities | professorfrancken.nl/association/activities | `providers/activities.py` |
| Practice sessions in the next two weeks, as a poster with a ticket per session (only while there are some) | the upcoming activities | `providers/practice.py` |
| A photo from one of the last 3 events | Nextcloud `images/albums/` | `providers/event_photos.py` |
| Who was in the room today (animated chart) | the ESP32 sniffer | `providers/presence.py`, `activity_chart.py` |
| This week's leaderboard: most time in the room | the ESP32 sniffer | `providers/presence.py` |
| Second-hand books for sale: three at a time, as 3D books flying onto a shelf, with title and price | professorfrancken.nl/study/books, covers from openlibrary.org | `providers/books.py` |
| Info, one per round in turn (`rotation.take_turns`): | | |
| &nbsp;&nbsp;News: Dagblad van het Noorden, NU.nl, BBC World; tap a headline to read it | RSS feeds | `providers/news.py` |
| &nbsp;&nbsp;Weather and rain at Zernike; after bieruur only a rain warning | open-meteo.com, Buienradar | `providers/weather.py` |
| &nbsp;&nbsp;Buses from Aletta Jacobshal | OVapi | `providers/buses.py` |
| &nbsp;&nbsp;Today's Applied Physics timetable | rooster.rug.nl | `providers/timetable.py` |
| The confidential contact persons: who they are and how to reach them (left out without the data file) | `config/confidential.json` (personal data, not in git) | `providers/confidential.py` |
| The extern: "Internship? Job? Thesis?" and how to reach them (left out without the data file) | `config/extern.json` (personal data, not in git) | `providers/extern.py` |
| A random quote (read aloud) | the quotes Google Sheet | `providers/quote.py` |
| The commandment of the week by Jeff de Hosson, our honorary member (the next one each Monday) | `config/commandments.txt` | `providers/commandments.py` |
| The dilemma of the week: vote by tapping A or B, or scan the QR code and vote on your phone | `config/dilemmas.txt`, a Google Form | `providers/poll.py` |
| The latest xkcd comic, with its hover text | xkcd.com | `providers/xkcd.py` |
| An animated graafmachine digging a hole and dumping the earth on a heap | | `providers/graafmachine.py` |
| The Compucie's promo, Matrix style: code rain, the name decoding, a terminal typing who we are | | `providers/compucie.py` |
| Our latest Instagram posts on a phone, with a QR code to follow us | Instagram (a Meta app) | `providers/instagram.py` |
| What's playing on Spotify (only while something plays) | Spotify | `providers/spotify.py` |
| Daily puzzles: Connections \| Wordle \| Catfishing \| TimeGuessr, with today's status; tap one to play it. Left out once all are done for the day | nytimes.com, catfishing.net, timeguessr.com (map: OpenStreetMap) | `providers/puzzles.py`, `connections.py`, `wordle.py`, `catfishing.py`, `timeguessr.py` |
| Bieruur countdown; full screen from 15:58 to 16:02, with a song (Spotify on the TV turns down meanwhile) | | `providers/bieruur.py` |
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
- Keys in the slideshow: →/↓ next, ←/↑ previous, space pause (it goes on by itself after 4 minutes,
  unless "Pause until unpaused" is on in the settings), `m` mute/unmute all sound,
  `1` Daily puzzles, `2` Spotify, `3` today's activity chart, `4`-`7` news, weather, buses, timetable (change these under `[shortcuts]` in
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

Media, personal data and logins live only on the TV PC. The list, and what to do if it dies: [docs/01-handover.md](docs/01-handover.md#not-everything-is-in-git).
