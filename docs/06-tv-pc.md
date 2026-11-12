# 6. The TV PC

[Manual](README.md). Before this, restore [the files that aren't in git](01-handover.md#not-everything-is-in-git); afterwards, copy `~/.config/slideshow/` from the old PC or follow [the account setup guides](02-accounts-and-secrets.md).

The slideshow updates itself: every 10 minutes it checks GitHub for new commits, pulls them (only
when the TV PC has no changes of its own), runs the tests and restarts, never during bieruur. A
commit whose tests fail is not taken; the log says why. A commit made on the TV PC itself is picked
up the same way (once nothing is left uncommitted). Switch it off with `[update] auto = false`.

```sh
sudo apt install python3-jinja2 python3-requests python3-bs4 python3-pil python3-serial python3-venv ffmpeg firefox poppler-utils
sudo usermod -aG dialout $USER                      # serial port access for the sniffer; log in again after
git clone <this repo> ~/slideshow && cd ~/slideshow
python3 -m venv --system-site-packages .venv        # uses the apt packages above
.venv/bin/pip install piper-tts tomli               # text-to-speech; tomli is only needed on Python 3.10
deploy/install_spotifyd.sh                          # the "Francken TV" Spotify speaker; open the login link it prints
mkdir -p ~/.config/systemd/user && cp deploy/*.service deploy/*.timer ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now francken-tv francken-tv-sniffer francken-tv-kiosk francken-tv-spotifyd
sudo loginctl enable-linger $USER                   # keep running without anyone logged in
```

Logs: `journalctl --user -u francken-tv -f` (or `-u francken-tv-sniffer`).
After changing `config.toml`: `systemctl --user restart francken-tv`.
Closed the full-screen slideshow with Alt+F4? It stays closed; bring it back with `systemctl --user start francken-tv-kiosk`
(`stop` to close it from a terminal). Starting `francken-tv` also opens it, and starts the Spotify speaker
(`francken-tv-spotifyd`); stopping `francken-tv` stops the speaker too.
The internet gone for minutes at a time ("Temporary failure in name resolution" in the log)?
`deploy/fix_dns.sh` makes the PC skip its unreliable IPv6 DNS server (`--undo` to switch back).

## In a terminal instead (Ctrl+C, Ctrl+M and Ctrl+R at hand)

Set up as above, then run `deploy/install_autostart.sh` once. From then on, logging in on the TV PC
opens a terminal running `./start.sh --fullscreen`: the full-screen slideshow is on top, Alt+Tab
gets to the terminal. If the slideshow stops, the terminal stays and Enter starts it again. This
needs the TV PC to log in by itself (Settings -> Users -> Automatic login). The script switches the
`francken-tv`, `francken-tv-sniffer` and `francken-tv-kiosk` services off (they'd run a second
slideshow); `deploy/install_autostart.sh --undo` switches them back on.

The sniffer firmware lives in `firmware/` (PlatformIO).

### The files that aren't in git

Media, personal data and logins are not in git and are not backed up: copy them by hand from the old PC
(see [the list](01-handover.md#not-everything-is-in-git)) into the project folder and `~/.config/slideshow/`.

### The text-to-speech voice

The voice for reading quotes and greetings aloud is a piper voice model (`media/voices/en_US-ryan-high.onnx`
and its `.json`, about 100 MB or more), the largest file there is. It is not in git, but the
slideshow **downloads it by itself** when it is missing: at startup, from
[piper's voices](https://huggingface.co/rhasspy/piper-voices) (`en/en_US/ryan/high/`), so on a
new PC the PC only needs internet access. If a download fails, it is tried again every ten minutes (when
something is to be spoken). Until the voice is there, nothing is spoken; the slideshow itself is not affected.

- `/health` says "nothing can be spoken: the voice model ... is missing" while it isn't there.
- The log (`journalctl --user -u francken-tv`) shows "Downloading ..." and then "Downloaded the voice", or
  "Could not download the voice ...: <why>".
- To switch the downloading off: `download_voice = false` under `[announcer]` in `config/config.toml`.
- To do it by hand (no internet on the TV PC): download the `.onnx` and `.onnx.json` files from the address above
  on another PC and copy them to `media/voices/`.
- Another voice: change `voice` under `[announcer]`; it is downloaded the same way (voice names are
  `<language>-<name>-<quality>`, e.g. `en_US-ryan-high`, as listed on the page above).
