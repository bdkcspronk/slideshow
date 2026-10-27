# 5. Architecture

For reading the code. You can run and look after the slideshow without this page.

## The flow

```
 ESP32 ──serial──> sniffer.py ──> data/presence.sqlite3 ──┐
                                                          │
                     python -m francken_tv                ▼
   providers/*  ──slides──>  scheduler.py  ──>  server.py  ──HTTP──>  browser (kiosk)
   (refresh in background)   (+ takeovers)      (renders templates)
                                    announcer.py: greetings, quotes, bieruur song (ffplay)
```

Everything runs in one Python process (`python -m francken_tv`), plus the sniffer as a second
process and the browser. The browser asks the server which slide is next and draws it.

## The three plug-in kinds

All defined in [`francken_tv/slides.py`](../francken_tv/slides.py), which has a docstring for each.

| Kind | Job | Examples |
|---|---|---|
| **Provider** | contributes slides to each round | `providers/activities.py`, `providers/news.py` |
| **Takeover** | grabs the screen at certain moments | `providers/bieruur.py`, `providers/vrijmibo.py` |
| **Job** | does something at certain moments, without a slide | the bieruur song, greetings (`announcer.py`) |

A provider does its slow work (downloading, drawing) in `refresh()`, which runs in a background
thread (`background.py`). Its `slides()` method must be fast: it only hands out what `refresh()`
prepared. That is why one slow or broken website never freezes the TV.

## The files, in the order you'd want to read them

| File | What it does |
|---|---|
| `__main__.py` | starts everything; Ctrl+R restarts |
| `app.py` | `build_app()`: creates every provider. **The list of all slide types is here.** |
| `config.py` | loads `config/config.toml` |
| `slides.py` | the Slide, Provider, Takeover and Job classes |
| `scheduler.py` | decides what's next: takeovers first, otherwise the round |
| `background.py` | runs `refresh()` and jobs in threads; records errors for `/status`; waits for the network |
| `server.py` | the web server: `/`, `/status`, `/preview/<name>`, the actions of interactive slides |
| `updater.py` | pulls new commits from GitHub, runs the tests, restarts |
| `settings.py` | the choices made on the TV (Esc → Settings), saved in `data/settings.json` |
| `menu.py` | the Esc menu |
| `announcer.py`, `line_out.py`, `system_volume.py` | sound: text-to-speech, line-out, volume |
| `sniffer.py`, `presence_store.py`, `devices.py` | presence: serial from the ESP32, the database, who is who |
| `static/player.js` | the browser side; you shouldn't need to touch it |
| `templates/slides/*.html` | one small template per slide type |
| `providers/*.py` | the slide types |

## Where data lives

| Where | What |
|---|---|
| `config/` | settings and the text files (in git; except the personal data files) |
| `media/` | posters, songs, voice (not in git) |
| `data/` | everything the slideshow creates: database, caches, saved games, `settings.json`. Safe to delete (you lose the history, see the handover) |
| `~/.config/slideshow/` | logins and tokens (not in git) |

## Decisions worth knowing

- **The browser is dumb on purpose.** All logic is in Python so it can be tested; the tests don't
  need a browser.
- **Updates need passing tests.** The TV PC pulls from GitHub and runs the test suite before it
  restarts. It is the only safety net there is, so keep the tests green.
- **Failures stay local.** An error in one provider is caught, recorded for `/status` and retried
  after a minute. Nothing in a provider should be able to take the whole slideshow down.
- **Personal data is never in git.** See the handover for the list.
