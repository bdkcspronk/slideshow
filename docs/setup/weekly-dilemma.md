# Weekly dilemma

[Manual](../README.md) · [Accounts and secrets](../02-accounts-and-secrets.md)

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
