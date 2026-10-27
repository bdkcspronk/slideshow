# 3. When something breaks

Start at the top and work down. Most problems are solved in the first two steps.

## Step 1: look at /status

Open <http://127.0.0.1:8080/status> in a browser on the TV PC (press `Alt+Tab` out of the full-screen
slideshow, or use your laptop's own copy). It lists every slide type with the time of its last
successful refresh and its **last error**. `/health` is the same in one line per problem.

- A slide type with an **error** → find it in step 3 below.
- Everything fine but the slide isn't on the TV → "A slide isn't shown", below.
- `/status` doesn't load at all → "The TV is black or frozen", below.

## Step 2: look at the log

```sh
journalctl --user -u francken-tv -f          # the slideshow (Ctrl+C to stop following)
journalctl --user -u francken-tv --since "1 hour ago"
journalctl --user -u francken-tv-sniffer -f  # the presence sniffer
```

(If you run the slideshow in a terminal instead of as a service, the log is in that terminal.)
A problem with one slide type shows up as `Refreshing <name> failed: ...`. The rest of the
slideshow keeps going, so one broken slide never takes the TV down.

## Step 3: find your symptom

### The TV is black or frozen

1. Is the PC on, and is the full-screen browser open? If you closed it (Alt+F4) it stays closed:
   `systemctl --user start francken-tv-kiosk`.
2. Is the slideshow running? `systemctl --user status francken-tv`. If not:
   `systemctl --user restart francken-tv`.
3. Still black? Wrong resolution after a reboot: `deploy/fix_tv_resolution.sh`.
4. Last resort: restart the TV PC (menu: `Esc` → Power, or just switch it off and on). Everything
   starts by itself.

### A slide isn't shown

Work through, in order:

1. **Is its type in the rotation?** `rotation.order` in `config/config.toml`. Also `Esc` → Settings:
   the choices made there are saved in `data/settings.json` and **win over config.toml**. Delete
   that file to go back to the config.
2. **Is it a slide that hides itself when there is nothing to show?** Practice sessions (none in the
   next two weeks), Spotify (nothing playing and show_when_idle off), daily puzzles (all done today),
   confidential and extern (their JSON file is missing), news/weather/buses/timetable (daytime
   only, and they take turns). `/preview/<name>` shows it anyway, or says why it can't.
3. **Is it broken?** `/status` shows the error. See the rest of this page.

### The slideshow is on an old version / doesn't pick up my change

`/status` → "Updates from GitHub". It checks every 10 minutes, then runs the tests; **if the tests
fail it keeps the old version and says so there.** Fix the failing test (run
`python3 -m unittest` yourself and read the failure), push, and it will pick the new commit up. It
also won't update while the TV PC has uncommitted changes of its own: `git status` in the project
folder on the TV PC.

### A website changed (activities, books, puzzles, timetable, ...)

The slideshow reads some websites the way a person would, and a redesign can break that. Symptom:
that slide is gone or empty, and `/status` shows an error or "no events found".

1. Open the website and check it works and that the address in `config.toml` is still right.
2. The code that reads it is in `francken_tv/providers/<name>.py`; the test is
   `tests/test_<name>.py`, with a saved copy of the old page in `tests/fixtures/`.
3. Save the new page over the fixture, run the test, and adjust the reading code until it passes.
   The tests show exactly what the code expects to find.

If the site isn't ours (NYT, catfishing, timeguessr) and it's hard to fix, remove that puzzle from
`puzzles.order` in `config.toml` rather than leave it broken.

### Instagram shows only our account name and a QR code

The token has expired or been revoked: [generate a new one](setup/instagram.md), step 3.

### No Spotify slide, or its buttons don't work

1. `systemctl --user status francken-tv-spotifyd`: it is the "Francken TV" speaker. Restart it if needed.
2. Log in again at `http://127.0.0.1:8080/spotify/login` (on the TV PC).
3. The buttons need Spotify **Premium**.
4. [Spotify setup](setup/spotify.md) has the full walkthrough.

### No sound / sound from the wrong place

Sound goes to the line-out (the speakers), not HDMI, and the slideshow forces that every 30 seconds
(`[sound]` in `config.toml`). Is `Esc` → Settings → mute on? Is the speakers' plug in? Check with
`wpctl status` (or `pactl list sinks short`).

### The presence chart is empty, or the leaderboard is

The chart is fed by the small ESP32 board with a USB cable.

1. `ls /dev/ttyUSB0`: not there? Reseat the USB cable; try another port.
2. `systemctl --user status francken-tv-sniffer`; its log: `journalctl --user -u francken-tv-sniffer -f`.
3. "Permission denied" on the port: `sudo usermod -aG dialout $USER`, then log in again.
4. If the board is dead, the firmware in `firmware/` (PlatformIO) can be flashed to a new ESP32.

### Nothing is read aloud (quotes, greetings)

1. Is sound muted, or "Read quotes aloud" off? `Esc` → Settings.
2. `/health` says "nothing can be spoken: the voice model ... is missing": the model is downloaded by itself;
   see [the text-to-speech voice](06-tv-pc.md#the-text-to-speech-voice) for why that might fail (no internet, the
   address changed) and how to copy it by hand.
3. "piper not found" in the log: `.venv/bin/pip install piper-tts`.

### "Temporary failure in name resolution" in the log

The PC's IPv6 DNS is unreliable: `deploy/fix_dns.sh` (`--undo` to reverse it). The slideshow
waits at boot for the network and recovers by itself when it comes back; this only matters if it
keeps happening.

### A change I made to config.toml does nothing

Restart: `systemctl --user restart francken-tv` (or `Ctrl+R` in the terminal). Then check that
`data/settings.json` isn't overriding it (see "A slide isn't shown").

### /status says there is no backup, or the last one is old

- **"no backup is set up on this PC"**: run `python -m francken_tv.backup setup` in the project folder (use
  `.venv/bin/python`), choose a passphrase, give it to the board for their KeePass. Then enable the timer:
  `systemctl --user enable --now francken-tv-backup.timer`, and run one by hand to see it work:
  `systemctl --user start francken-tv-backup`.
- **"the last backup was N days ago"**: `journalctl --user -u francken-tv-backup` says why. Usually the
  Nextcloud password changed (put the new one in `~/.config/slideshow/nextcloud.credentials.json`) or the
  PC was off for weeks. `systemctl --user list-timers` shows when the next one runs.
- **"gpg failed"**: `gpg` isn't installed (`sudo apt install gnupg`).
- Try it by hand: `.venv/bin/python -m francken_tv.backup backup` prints what it did.

### Phone votes in the weekly dilemma don't count

TV votes work but phone votes don't: the Google Sheet is no longer public by link, or the form
changed its answers. [Weekly dilemma](setup/weekly-dilemma.md).

## Step 4: if all else fails

- Restarting is safe: `systemctl --user restart francken-tv`.
- Going back to a known-good version: on the TV PC, `git log --oneline`, then
  `git checkout <commit>` and restart. (Auto-update won't move it while it has uncommitted
  changes; go back to the latest with `git checkout main`.)
- A new TV PC from scratch: [6. The TV PC](06-tv-pc.md), after
  [restoring the files that aren't in git](01-handover.md#not-everything-is-in-git).
- **Write down what happened and what fixed it, here.** The next person will have the same problem.
