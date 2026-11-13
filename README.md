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
| The emergency response officers: round photos with their names (left out without pictures) | pictures in `media/ERO/`, the file name is the name | `providers/ero.py` |
| The extern: "Internship? Job? Thesis?" and how to reach them (left out without the data file) | `config/extern.json` (personal data, not in git) | `providers/extern.py` |
| A random quote (read aloud) | the quotes Google Sheet | `providers/quote.py` |
| The commandment of the week by Jeff de Hosson, our honorary member (the next one each Monday) | `config/commandments.txt` | `providers/commandments.py` |
| The dilemma of the week: vote by tapping A or B, or scan the QR code and vote on your phone | `config/dilemmas.txt`, a Google Form | `providers/poll.py` |
| The Francken pet: a tamagotchi to feed, play with and clean by tapping. Pick its shape, colour and name (a name used before gets II, III, ...); it gets needy faster the more people are in the room (but three visits a day are always enough), sleeps when nobody's there, cries on the speakers below half health, and dies when neglected. Finishing a daily puzzle is fun for it: it pops up on the puzzle and cheers. Every snack or drink streeped feeds it, and it pops up over the slideshow to say thank you. A beer (thanked by the streeper's first name or nickname) is fun instead of food, but makes it less sober (it sways and hiccups); a glass of water helps. Only shown while a bar is below half | the ESP32 sniffer, the streep system (consumption-counter.professorfrancken.nl), `data/pet.json` | `providers/pet.py`, `pet_streep.py` |
| The latest xkcd comic, with its hover text | xkcd.com | `providers/xkcd.py` |
| An animated graafmachine digging a hole and dumping the earth on a heap | | `providers/graafmachine.py` |
| The Compucie's promo, Matrix style: code rain, the name decoding, a terminal typing who we are | | `providers/compucie.py` |
| The Borrelcie's promo after the Beatles: a piano keyboard playing, then THE BORRELCIE landing letter by letter | | `providers/borrelcie.py` |
| The Fotocie's promo: their logo with the animation of the Fotocie app's start screen (looking through a camera, pulling focus, the flashbulb firing) | | `providers/fotocie.py` |
| The Sjaarscie's promo: the first-year questions, then "Join the Sjaarscie!" with the Zwitsal baby, on baby blue and pink | | `providers/sjaarscie.py` |
| The MScie's promo, the committee for master students by master students: silhouettes of arms throwing black graduation caps in the air once, then the name | | `providers/mscie.py` |
| A graphics test (Three.js): 3D scenes from simple to complex, plus tests of triangles, shadows and overdraw on their own,, each with a live frames-per-second readout, to see what the TV PC can handle (take `three` out of the rotation when done) | | `providers/three.py`, `static/widgets.js` |
| Become a member: €5 a year, free coffee, events, and a QR code to the sign-up form, animated (only in August to October and February) | professorfrancken.nl/register | `providers/membership.py` |
| Francken socks for sale: the price, legs in our socks rising out of the title, and a QR code to text the seller on WhatsApp | wa.me link in `config.toml` | `providers/socks.py` |
| Find us online: QR codes to the WhatsApp announcement group, LinkedIn, Instagram and the website, as polaroids dropping onto a washing line | links in `config.toml` | `providers/socials.py` |
| Streep your food: the glass-door fridge drawing itself and, next to it, the PC with the streep system, a cursor tapping snacks and the total going up | | `providers/streep.py` |
| The latest Francken Vrij, its pages turning by themselves, pausing on the cover, the contents and each article | a PDF in `media/francken-vrij/` | `providers/francken_vrij.py` |
| The Francken Vrij on paper: how to opt in on the website, a cursor doing it, the latest cover jumping out, and a QR code to the page | professorfrancken.nl/profile/francken-vrij, the cover from the Francken Vrij PDF | `providers/francken_vrij_subscribe.py` |
| Our latest Instagram posts on a phone, with a QR code to follow us | Instagram (a Meta app) | `providers/instagram.py` |
| What's playing on Spotify (only while something plays) | Spotify | `providers/spotify.py` |
| A lyric video of the playing song: the line being sung, big, each line in its own style (only after bieruur, when it has synced lyrics) | Spotify, lrclib.net | `providers/lyric_video.py` |
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

## Setting it up on a new PC

On Ubuntu/Debian:

```sh
git clone https://github.com/bdkcspronk/slideshow ~/slideshow
~/slideshow/deploy/setup.sh
```

[deploy/setup.sh](deploy/setup.sh) installs the packages (`apt`), makes the Python environment (`.venv`, from
`requirements.txt`), sets up the Spotify speaker and starts the services. The files that are not in git (posters,
personal data, logins in `~/.config/slideshow/`) are not included: copy them by hand. `--no-services` only installs
packages and the environment (for a
laptop: then use `./start.sh`). Every step by hand, and what each account needs: [docs/06-tv-pc.md](docs/06-tv-pc.md) and
[docs/02-accounts-and-secrets.md](docs/02-accounts-and-secrets.md).

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
- `python3 tools/slides_gallery.py` puts every slide on one self-contained page, `data/slides_gallery.html`:
  today's public data, made-up private data (posters, people, Spotify, ...), no server needed.
- `python3 tools/emulator.py --serve` builds the whole slideshow as a website (`data/emulator/`) and shows it at
  http://127.0.0.1:8090: the real player, the menu (Esc) with its settings and the puzzles, all working without
  the TV PC, with the same made-up private data. Python runs inside the browser, so any web server can show
  the folder on any device (`--host 0.0.0.0` for other devices on the network); the data is from when it was built.
  What a build downloads is kept for 6 hours in `data/cache/emulator_http/`, so rebuilding is quick; `--fresh` fetches it all again.
- Keys in the slideshow: →/↓ next, ←/↑ previous, space pause (it goes on by itself after 4 minutes,
  unless "Pause until unpaused" is on in the settings), `m` mute/unmute all sound,
  `1` Daily puzzles, `2` Spotify, `3` today's activity chart, `4`-`7` news, weather, buses, timetable, `8` the Francken pet (change these under `[shortcuts]` in
  `config/config.toml`).
- **Esc** opens the menu. A row of tabs on top holds every slide type in groups (What's on, Today, The room,
  Puzzles, Music, ... the same groups as the buttons of the emulator, `GROUPS` in `francken_tv/menu.py`): ←/→ choose
  a group and show its slides, ↓ goes into them and Enter opens one (↑ goes back to the tabs; slides with nothing to
  show right now are greyed out). The first tab, **Quick**, is the slide types under `[shortcuts]` with their number
  keys (the number keys work in every tab). On Fridays the **Fun** group also has the vrijmibo GIF. The menu opens
  on the group it was last on. Below the tabs:
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
