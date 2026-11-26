import io
import threading
import unittest
from types import SimpleNamespace

from francken_tv import voice
from francken_tv.voice import Commands, Listener, Settings, Understanding, grammar, phrases

SLIDES = {"weather": "Weather", "spotify": "Spotify", "wordle": "Wordle"}


def result(text: str, conf: float = 1.0) -> dict:
	"""A Vosk result for `text`, every word this sure."""
	return {"text": text, "result": [{"word": word, "conf": conf} for word in text.split()]}


class Clock:
	def __init__(self) -> None:
		self.now = 1000.0

	def __call__(self) -> float:
		return self.now


class UnderstandingTest(unittest.TestCase):
	def setUp(self):
		self.clock = Clock()
		self.understanding = Understanding(Settings(enabled=True), phrases(SLIDES), self.clock)

	def hear(self, text, conf=1.0):
		return [command["do"] for command in self.understanding.hear(result(text, conf))]

	def test_a_command_after_the_wake_words(self):
		self.assertEqual(self.hear("hey katinka pause"), ["pause"])
		self.assertEqual(self.understanding.hear(result("hey katinka go to the weather")),
			[{"do": "go", "slide": "weather", "said": "Go to Weather"}])

	def test_wordle_is_heard_as_world(self):
		self.assertEqual(self.understanding.hear(result("hey katinka go to world"))[0]["slide"], "wordle")

	def test_without_the_wake_words_nothing_happens(self):
		self.assertEqual(self.hear("pause"), [])
		self.assertEqual(self.hear("go to the weather"), [])

	def test_right_after_a_command_the_next_needs_no_wake_words(self):
		self.hear("hey katinka next")
		self.clock.now += 5
		self.assertEqual(self.hear("next"), ["next"])
		self.clock.now += 7   # each command keeps it listening for follow_up_seconds again
		self.assertEqual(self.hear("pause"), ["pause"])
		self.clock.now += 9
		self.assertEqual(self.hear("next"), [])

	def test_the_wake_words_alone_listen_for_a_command(self):
		self.assertEqual(self.hear("hey katinka"), ["listening"])
		self.clock.now += 3
		self.assertEqual(self.hear("go to spotify"), ["go"])

	def test_several_commands_at_once(self):
		self.assertEqual(self.hear("hey katinka mute next next"), ["mute", "next", "next"])
		self.assertEqual(self.hear("hey katinka go back"), ["previous"])   # the longest phrase, not "go" + "back"

	def test_talk_before_the_wake_words_is_left_out(self):
		self.assertEqual(self.hear("[unk] hey katinka sound on"), ["unmute"])

	def test_the_wake_words_and_something_else_is_unclear(self):
		self.assertEqual(self.hear("hey katinka [unk]"), ["unclear"])
		self.assertEqual(self.hear("hey katinka next [unk]"), ["unclear"])

	def test_talk_while_listening_for_a_next_command_is_ignored(self):
		self.hear("hey katinka next")
		self.assertEqual(self.hear("[unk] go to the [unk]"), [])
		self.assertEqual(self.hear("[unk]"), [])

	def test_unsure_words_are_ignored(self):
		self.assertEqual(self.hear("hey katinka pause", conf=0.6), [])   # "hey kathy" scores about that

	def test_katinka_alone_wakes_it(self):
		# A Dutch "Hé" or "Hee" is often missed, or heard as "he".
		self.assertEqual(self.hear("katinka go to spotify"), ["go"])
		self.clock.now += 100
		self.assertEqual(self.hear("he katinka pause"), ["pause"])

	def test_a_dutch_kathinka_may_score_lower_than_the_command(self):
		heard = {"text": "", "result": [{"word": "hey", "conf": 0.62}, {"word": "katinka", "conf": 0.55},
			{"word": "next", "conf": 1.0}]}
		self.assertEqual([c["do"] for c in self.understanding.hear(heard)], ["next"])
		heard["result"][1]["conf"] = 0.3
		self.assertEqual(self.understanding.hear(heard), [])


class GrammarTest(unittest.TestCase):
	def test_every_phrase_with_and_without_the_wake_words(self):
		commands = phrases(SLIDES)
		words = grammar(["hey katinka", "katinka"], commands)
		self.assertIn("hey katinka", words)
		self.assertIn("hey katinka show me the weather", words)
		self.assertIn("katinka show me the weather", words)
		self.assertIn("show me the weather", words)
		self.assertEqual(words[-1], "[unk]")

	def test_only_slide_types_that_exist(self):
		self.assertFalse(any(command.get("slide") == "news" for command in phrases(SLIDES).values()))

	def test_the_spoken_names_are_words_the_model_knows(self):
		# Vosk drops a word it doesn't know, which would leave "go to" as a command of its own. These were checked
		# with tools/voice_test.py; a slide type's own name often isn't a word (wordle, catfishing, timeguessr).
		unknown = {"wordle", "catfishing", "timeguessr", "unmute", "bieruur", "francken", "extern", "graafmachine"}
		names = {word for spoken in voice.SLIDE_NAMES.values() for name in spoken for word in name.split()}
		said = {word for phrases_ in voice.COMMANDS.values() for phrase in phrases_ for word in phrase.split()}
		self.assertEqual((names | said) & unknown, set())


class CommandsTest(unittest.TestCase):
	def test_the_browser_gets_what_was_heard_after_its_number(self):
		commands = Commands()
		commands.put({"do": "next"})
		commands.put({"do": "pause"})
		self.assertEqual(commands.after(0, wait=0), {"commands": [{"do": "next"}, {"do": "pause"}], "last": 2})
		self.assertEqual(commands.after(1, wait=0)["commands"], [{"do": "pause"}])

	def test_a_new_page_gets_nothing_old(self):
		commands = Commands()
		commands.put({"do": "next"})
		self.assertEqual(commands.after(-1, wait=0), {"commands": [], "last": 1})
		self.assertEqual(commands.after(7, wait=0), {"commands": [], "last": 1})   # from before a restart

	def test_waits_for_a_command(self):
		commands = Commands()
		threading.Timer(0.05, commands.put, [{"do": "menu"}]).start()
		self.assertEqual(commands.after(0, wait=5)["commands"], [{"do": "menu"}])

	def test_nothing_heard_answers_after_the_wait(self):
		self.assertEqual(Commands().after(0, wait=0.01), {"commands": [], "last": 0})


class FakeRecognizer:
	"""Vosk, as far as Listener.follow uses it: each chunk of "sound" is the text of a finished sentence."""

	def __init__(self) -> None:
		self.text = ""

	def AcceptWaveform(self, sound: bytes) -> bool:
		self.text = sound.decode().strip()
		return not self.text.startswith("~")   # "~...": the sentence so far, not finished

	def PartialResult(self) -> str:
		import json
		return json.dumps({"partial": self.text.removeprefix("~")})

	def Result(self) -> str:
		import json
		return json.dumps(result(self.text))

	def FinalResult(self) -> str:
		return '{"text": ""}'


class ListenerTest(unittest.TestCase):
	def test_the_sentences_heard_become_commands(self):
		heard = []
		settings = Settings(enabled=True)
		listener = Listener(settings, phrases(SLIDES), heard.append)
		sound = "".join(text.ljust(voice.CHUNK) for text in ["[unk]", "hey katinka mute", "next"]).encode()
		listener.follow(io.BytesIO(sound), FakeRecognizer(), Understanding(settings, phrases(SLIDES)))
		self.assertEqual([command["do"] for command in heard], ["mute", "next"])

	def follow(self, *texts: str) -> list[str]:
		heard = []
		settings = Settings(enabled=True)
		listener = Listener(settings, phrases(SLIDES), heard.append)
		sound = "".join(text.ljust(voice.CHUNK) for text in texts).encode()
		listener.follow(io.BytesIO(sound), FakeRecognizer(), Understanding(settings, phrases(SLIDES)))
		return [command["do"] for command in heard]

	def test_listening_always_gets_an_answer(self):
		self.assertEqual(self.follow("~hey katinka", "hey katinka pause"), ["listening", "pause"])
		self.assertEqual(self.follow("~hey katinka", "hey katinka [unk]"), ["listening", "unclear"])
		self.assertEqual(self.follow("~katinka", "cat in a"), ["listening", "unclear"])   # the name was another word after all
		self.assertEqual(self.follow("~hey katinka", "hey katinka"), ["listening", "listening"])   # the browser waits for the next

	def test_talk_without_the_name_gets_no_answer(self):
		self.assertEqual(self.follow("~nice weather", "[unk]"), [])

	def test_without_the_model_it_says_why(self):
		listener = Listener(Settings(enabled=True, model="media/no-such-model"), {}, lambda command: None)
		try:
			import vosk   # noqa: F401
		except ImportError:
			self.assertIsNone(listener.load())
			self.assertIn("vosk", listener.problem)
			return
		self.assertIsNone(listener.load())
		self.assertIn("no-such-model", listener.problem)


class VoiceTest(unittest.TestCase):
	def test_mute_and_sound_on_are_done_by_the_server(self):
		changes = []
		app = SimpleNamespace(providers={}, read_sound=lambda: None, change_settings=changes.append)
		sound = voice.Voice(app, Settings(enabled=True))
		sound.heard({"do": "mute", "said": "Sound off"})
		sound.heard({"do": "unmute", "said": "Sound on"})
		sound.heard({"do": "next", "said": "Next"})
		self.assertEqual(changes, [{"muted": True}, {"muted": False}])
		self.assertEqual([c["do"] for c in sound.commands.after(0, wait=0)["commands"]], ["mute", "unmute", "next"])   # shown in the browser

	def spotify(self, playing):
		actions = []
		spotify = SimpleNamespace(title="Spotify", connected=True, playing=playing, action=lambda name, values, now: actions.append(name) or (None, None))
		app = SimpleNamespace(providers={"spotify": spotify}, clock=SimpleNamespace(now=lambda: None))
		return voice.Voice(app, Settings(enabled=True)), actions

	def test_pause_and_play_are_for_the_music(self):
		sound, actions = self.spotify(SimpleNamespace(is_playing=True))
		sound.heard({"do": "pause", "said": "Pause the music"})
		sound.heard({"do": "resume", "said": "Play the music"})   # still playing as far as it knows: nothing to do
		self.assertEqual(actions, ["toggle"])
		said = [c["said"] for c in sound.commands.after(0, wait=0)["commands"]]
		self.assertEqual(said, ["Pause the music", "The music is already playing"])

	def test_play_with_nothing_played_yet_starts_the_music(self):
		sound, actions = self.spotify(None)
		sound.heard({"do": "resume", "said": "Play the music"})
		sound.heard({"do": "pause", "said": "Pause the music"})
		self.assertEqual(actions, ["toggle"])
		self.assertEqual(sound.commands.after(0, wait=0)["commands"][1]["said"], "No music is playing")

	def test_the_slideshow_has_its_own_pause(self):
		understanding = Understanding(Settings(enabled=True), phrases(SLIDES))
		hear = lambda text: [c["do"] for c in understanding.hear(result(text))]
		self.assertEqual(hear("hey katinka pause the slideshow"), ["pause_slides"])
		self.assertEqual(hear("hey katinka pause slides"), ["pause_slides"])
		self.assertEqual(hear("hey katinka continue the slide show"), ["resume_slides"])
		self.assertEqual(hear("hey katinka pause"), ["pause"])   # the music

	def test_without_spotify_it_says_so(self):
		sound = voice.Voice(SimpleNamespace(providers={}), Settings(enabled=True))
		sound.heard({"do": "pause", "said": "Pause the music"})
		self.assertEqual(sound.commands.after(0, wait=0)["commands"], [{"do": "failed", "said": "Spotify isn't connected"}])

	def test_one_wake_phrase_in_the_config_is_a_list_of_one(self):
		self.assertEqual(Settings.from_config({"wake": "hey katinka"}).wake, ["hey katinka"])

	def test_unknown_settings_are_refused(self):
		with self.assertRaises(SystemExit):
			Settings.from_config({"enabeld": True})


if __name__ == "__main__":
	unittest.main()
