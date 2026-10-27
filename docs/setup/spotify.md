# Spotify

[Manual](../README.md) · [Accounts and secrets](../02-accounts-and-secrets.md)

The Spotify slide shows what's playing and the next song. When nothing plays, it shows the last
played song paused where it stopped (▶ continues it); before anything has played, there is no slide.
Its buttons skip songs, pause and change the volume; **Playlists** shows the account's playlists and
their songs, and **Search** finds songs, albums, playlists and people by typing. Tapping a song plays
it. The buttons need Spotify Premium, and music already playing on some device. One-time setup:

1. At https://developer.spotify.com/dashboard, log in and **Create app**. Any name and description;
   **Redirect URI**: `http://127.0.0.1:8080/spotify/callback` (exactly this; `127.0.0.1`, not
   `localhost`); tick **Web API**.
2. Open the app's **Settings** and put its **Client ID** and **Client secret** in
   `~/.config/slideshow/spotify.json` on the TV PC:
   `{"client_id": "...", "client_secret": "..."}`
3. Start the slideshow and open http://127.0.0.1:8080/spotify/login **on the TV PC**; log in with
   the Spotify account whose music should be shown. The slideshow adds a refresh token to that
   file (no password is stored). It keeps working after restarts. Connected before changing
   playlists or showing the last played song was possible? Log in once more, so Spotify allows it.
   Spotify doesn't let the app search people or see their profiles: **People** finds the makers of
   the account's playlists by name. A playlist's page has **+ Add to library** (its maker then
   shows up under People) and **Remove** (not for the account's own playlists).
4. So music plays from the PC itself (not from a Spotify tab somewhere): `deploy/install_spotifyd.sh`
   installs [spotifyd](https://github.com/Spotifyd/spotifyd) as `~/.local/bin/spotifyd` and logs it
   in once (open the link it prints on that PC; `--login` logs in again). The TV PC runs it with
   `francken-tv-spotifyd.service` (see [the TV PC](../06-tv-pc.md)); elsewhere `start.sh` starts it (log:
   `data/spotifyd.log`). The PC is then a Spotify speaker called "Francken TV"; when nothing plays,
   the slide starts music there, and "Play on TV" moves music playing elsewhere to it. Without it,
   songs only play when a Spotify app somewhere is already playing.
