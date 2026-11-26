# Voice commands ("Hey Katinka")

[Manual](../README.md). With a USB microphone plugged into the TV PC (Katinka), people can say:

| Say | It does |
|---|---|
| "Hey Katinka, pause" (or "stop", "pause the music") | pause the music on Spotify (not the slideshow) |
| "Hey Katinka, play" ("resume", "continue", "play the music") | play it again; with nothing played yet, the account's last music on the TV PC's speaker |
| "Hey Katinka, pause the slideshow" ("pause the slides", "stop the slideshow") | pause the slideshow, like space |
| "Hey Katinka, play the slideshow" ("play the slides", "resume / continue / start the slideshow") | go on with the slides |
| "Hey Katinka, skip" ("next song", "skip the song") | the next song on Spotify |
| "Hey Katinka, next" ("next slide") / "back" ("previous") | the next slide / the one before, like → and ← |
| "Hey Katinka, mute" ("sound off") / "sound on" | all sound off / on, like `m` |
| "Hey Katinka, menu" / "close" | open / close the menu, like Esc |
| "Hey Katinka, help" ("what can I say", "what can you do") | a card with examples of what to say; for 20 seconds one works without "Hey Katinka" ("close" closes it) |
| "Hey Katinka, go to the weather" ("show me ...", "open ...") | that slide now: posters, activities, news, weather, rain, buses, timetable, photos, presence, leaderboard, puzzles, connections, world (= Wordle), cat fishing, time guesser, spotify (or music), lyrics, books, quote, commandments, poll, pet, xkcd, digger, membership, socks, socials, instagram, countdown (or beer hour), ... (all of them: `SLIDE_NAMES` in `francken_tv/voice.py`) |

"Katinka" alone works too: the speech model is English and knows "Katinka", and hears a Dutch "Kathinka" as
it, but often misses a Dutch "Hé" (the commands are English). For 8 seconds after a command the next one works
without "Hey Katinka" ("next" ... "next" ... "pause"), and several at once work too ("Hey Katinka, next, next").

The bottom centre of the screen shows what it is doing. As soon as it hears "Katinka": a red microphone and
"Listening". Then how it ended, for a few seconds:

| Shows | Means |
|---|---|
| a green tick and the command ("Pause the music", "Next", "Go to Weather") | done |
| an amber ? and "Sorry, I didn't catch that" | it heard the name, but not a command it knows, or wasn't sure enough |
| a grey microphone and "Didn't hear anything" | "Hey Katinka" alone, and no command within 8 seconds |
| an amber ? and "Weather: not shown right now" | a slide that isn't on now (membership out of season) |
| an amber ? and why ("Spotify isn't connected", "Spotify can't be reached right now") | pause or play didn't work |

The speech recognition is [Vosk](https://alphacephei.com/vosk/), offline: the sound never leaves the TV PC,
nothing is recorded or kept. It only listens for the phrases above, so other talk in the room is ignored.

## Setting it up

1. Plug in the microphone. `arecord -l` lists it; `arecord -d 3 -f S16_LE -r 16000 test.wav && aplay test.wav`
   records and plays three seconds.
2. `.venv/bin/pip install vosk`
3. The speech model (about 40 MB, not in git): download `vosk-model-small-en-us-0.15.zip` from
   [alphacephei.com/vosk/models](https://alphacephei.com/vosk/models) and unzip it into `media/voice-model/`,
   so that `media/voice-model/vosk-model-small-en-us-0.15/am/` exists.
4. Try it without the slideshow: `.venv/bin/python tools/voice_test.py` shows what it hears and the command it
   makes of it. Say "Hey Katinka, go to the weather"; then talk normally, with music on, and check that nothing
   turns into a command. `--say "hey katinka pause"` tests it without a microphone (the TV's own voice says it).
5. `enabled = true` under `[voice]` in `config/config.toml`, and restart the slideshow
   (`systemctl --user restart francken-tv`). The log says `Listening for "hey katinka"`.

Another microphone than the default one: `arecord -L` lists the names; add `"-D", "<name>"` to `record` under `[voice]`.

## When it doesn't work

- `/health` says what's wrong: vosk not installed, the model missing, or the recorder stopped (the microphone
  unplugged: it tries again every 30 seconds by itself).
- Commands not heard, or heard wrongly: run `tools/voice_test.py` and look at the numbers after each word (how
  sure it was, 0-1). Below `min_confidence` (0.75) the sentence is ignored: lower it a little if real commands
  score just under it, raise it if talk turns into commands. The name has its own, lower `wake_confidence`
(0.5): a Dutch "Kathinka" scores lower than the English one the model knows.
- Only `hey(1.00)` and nothing after it: the sound after "hey" didn't arrive (a misheard name would show as
  `[unk]` or a low number). The microphone cuts out or is too quiet: `arecord -d 5 -f S16_LE -r 16000 -c 1 test.wav`,
  then `aplay test.wav` to hear what it records. Moving the microphone away from the speakers
  helps most: music from the TV makes it hard to hear people.
- A new slide type to go to: add its spoken names to `SLIDE_NAMES` in `francken_tv/voice.py`. Only words the
  model knows work (a made-up name like "wordle" or "compucie" doesn't: pick a word that sounds the same, as
  "world" for Wordle); check with `tools/voice_test.py --say "hey katinka go to ..."`.
