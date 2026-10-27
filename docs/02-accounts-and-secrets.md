# 2. Accounts and secrets

Every outside service the slideshow depends on, in one place. When a slide goes missing, the cause
is very often a row in this table.

`/status` shows a warning for the logins that can expire (see "Expiry warnings" below).

## The table

| Service | What it's used for | Where the login is kept | Expires? | Symptom when it fails | Fix |
|---|---|---|---|---|---|
| **Instagram** (Meta developer app, owned by the board's Instagram account `tfvprofessorfrancken`) | the Instagram slide | `~/.config/slideshow/instagram.json` (TV PC) | The token lasts 60 days, but the slideshow renews it weekly by itself. It only expires if the TV PC was off or disconnected for about two months, or the Instagram password changed. | The slide shows our account and a QR code instead of posts; `/status` shows an Instagram error. | [Generate a new token](setup/instagram.md), step 3 |
| **Spotify** (developer app and Premium account, owned by the board: `bestuur@professorfrancken.nl`) | the Spotify slide and the "Francken TV" speaker | `~/.config/slideshow/spotify.json`, and spotifyd's own login | The refresh token does not expire, but a password change, or removing the app's access in the Spotify account, ends it. | No Spotify slide; its buttons do nothing. | Log in again at `http://127.0.0.1:8080/spotify/login` on the TV PC; [Spotify setup](setup/spotify.md) |
| **Nextcloud** (`nextcloud.professorfrancken.nl`, owned by the board) | the event photos slide, and the weekly backup (the login needs write access for that) | `~/.config/slideshow/nextcloud.credentials.json` | If the account's password is changed. | No event photos, and no backup; `/status` shows an error for `event_photos` and, after 10 days, a backup warning. | Put the new password in that file; restart `francken-tv` |
| **Backup passphrase** | encrypts the weekly backup on Nextcloud | `~/.config/slideshow/backup.passphrase` (TV PC) and the board's KeePass | Never, but without it the backups can't be opened. | `/health`: "no backup is set up" (file missing). A backup that can't be opened is only found out when restoring: test a restore once. | `python -m francken_tv.backup setup` chooses a new one; the old backups then can't be opened, so make a new backup straight away. Give the new passphrase to the board. |
| **Google Form and Sheet** (weekly dilemma) | phone votes via the QR code | `[poll]` in `config/config.toml` (`form_url`, `sheet_id`), no login: the sheet is public by link | If someone makes the sheet private or deletes it. | TV votes still count; phone votes don't. | [Weekly dilemma](setup/weekly-dilemma.md) |
| **Google Sheet of quotes** | the quote slide | `[quote] sheet_id` in `config/config.toml`, no login | If the sheet stops being shared by link. | No quote slide. | Share the sheet as "anyone with the link can view" |
| **professorfrancken.nl** | activities, practice sessions, books | none (public pages) | If the website's layout changes, the slideshow can't read it any more. | The slide disappears; `/status` shows an error or an empty list. | [3. When something breaks](03-when-something-breaks.md), "A website changed" |
| **NYT, catfishing.net, timeguessr.com** | the daily puzzles | none | Layout changes (as above). Those sites aren't ours and may change without notice. | That puzzle is missing from the Daily puzzles slide. | [3. When something breaks](03-when-something-breaks.md), "A website changed" |
| **open-meteo.com, Buienradar, OVapi, rooster.rug.nl, RSS feeds** | weather, rain, buses, timetable, news | none | Rarely. The bus stop codes and the timetable programme names in `config.toml` can change. | That slide is missing. | Check `/status`; compare with the website |
| **GitHub** (repository `bdkcspronk/slideshow`, on a **private account of the current maintainer**: the association has no GitHub account) | the code; the TV PC downloads updates from it | none on the TV PC if the repository is public; otherwise a deploy key | If the owner deletes the repository, makes it private, renames it or leaves it. | `/status` shows "Updates from GitHub: failed". The slideshow keeps running its current version, but no new change reaches it. | The TV PC's `git remote -v` must point at the repository. **To fix the single point of failure:** make a GitHub account or organisation for the association (e.g. under `bestuur@professorfrancken.nl`), transfer the repository to it (GitHub: Settings → Transfer), then on the TV PC run `git remote set-url origin <new address>`. Add each new maintainer as a collaborator. |
| **Spotify and Meta developer apps** | (they hold the two logins above) | the developer dashboards, under the board's accounts (Spotify: `bestuur@professorfrancken.nl`; Meta: the `tfvprofessorfrancken` Instagram account) | They belong to the board, not to a person, so a new maintainer needs no personal account. They do need the board to give them access to those accounts, and each board handover must pass the logins on. | If the board loses access: no Spotify slide, no Instagram posts. | **At every board handover, make sure the new board gets these logins (they're the only way to reach the developer dashboards), and that the recovery email/phone of both accounts isn't a former board member's.** |

Spotify, Instagram/Meta and Nextcloud are held by the board (above). *Still to fill in: who holds the
Google Form and Sheets. Personal names don't belong in this file if the repository is public: put "see the
association's password manager, entry X" instead.*

## Where secrets live

Passwords and tokens are **never** in git. They are files in `~/.config/slideshow/` on the TV PC,
readable only by its user. To move the slideshow to a new PC, copy that folder (see
[6. The TV PC](06-tv-pc.md)).

## Expiry warnings

The Instagram token records its own expiry date. `/status` (and `/health`) warns when it is less than
two weeks away, which only happens if the weekly renewal has stopped working. Nothing else
carries an expiry date; for those, the table above says what to watch.
