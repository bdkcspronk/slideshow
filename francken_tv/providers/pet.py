"""The Francken pet: a tamagotchi on the TV. Tap to feed it, play with it and clean it, or it dies.

Its three needs (food, fun, clean) go down only while people are in the room, and faster the more
people there are (counted like the activity chart: known devices the sniffer saw in the last few
minutes). With nobody around it sleeps and nothing goes down, so it survives nights and weekends.
However many people there are, a need goes down at most MAX_DRAIN_PER_DAY a day: three visits a day
(one tap on each button) are always enough. A crowd only makes it needy sooner in the day.

When a need is empty, its health goes down; when health is empty, it dies, and the slide shows its
grave. The first time, and after it died, the slide asks for a name (typed on the screen's keyboard
or a real one); the pet hatches once someone gives it one. Below half health it cries now and then
on the speakers (PetCry, static/pet/cry.wav).

The state is in data/pet.json, so it survives a restart. refresh() moves it on every minute in the
background; while the slide is shown, the bars follow along (refresh_seconds, data-live).
"""

from __future__ import annotations

import json
import logging
import random
import re
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

from ..announcer import Announcer
from ..config import PROJECT_DIR
from ..presence_store import PresenceStore
from ..slides import Job, Provider, Slide

log = logging.getLogger(__name__)

NEEDS = ("food", "fun", "clean")
LABELS = {"food": "Food", "fun": "Fun", "clean": "Clean", "health": "Health"}
# With one person in the room, a full bar empties in this many hours; with ten people ten times as fast...
HOURS_PER_PERSON = {"food": 16, "fun": 12, "clean": 24}
# ...but never more than this a day (from 04:00 to 04:00). Three taps on a button fill 90 (clean: 120); feeding
# costs 5 clean and playing 5 food, so three visits a day, each tapping all three buttons, always keep up.
MAX_DRAIN_PER_DAY = 75
DAY_STARTS_AT = timedelta(hours=4)
# What each button does (the need it fills, and how much), and what the pet says.
ACTIONS = {
	"feed": ("food", 30, "Yum!"),
	"play": ("fun", 30, "Wheee!"),
	"clean": ("clean", 40, "So fresh!"),
}
FULL = 92                  # above this a need can't be filled more ("I'm full!")
NEGLECT_HOURS = 2          # one empty need takes all health in this long (two empty needs: twice as fast)
RECOVER_HOURS = 4          # with no empty need, health comes back in this long
CRY_BELOW = 50             # health below which it cries now and then
SHOW_BELOW = 50            # only in the slideshow once a bar (a need or health) is below this
MAX_STEP = timedelta(minutes=5)   # a longer gap between updates: the slideshow was off, nothing happened
TAP_COOLDOWN = timedelta(seconds=2)   # the same button tapped faster than this counts once
AWAKE_AFTER_TAP = timedelta(minutes=5)   # a tap wakes it up even if the sniffer sees nobody
SAY_SECONDS = timedelta(seconds=4)   # how long its answer to a tap stays in the speech bubble
CAUSES = {"food": "starved", "fun": "died of boredom", "clean": "died of filth"}
MAX_NAME = 16
# What a new pet can look like: its shape (the parts in templates/pet_creature.svg) and its colour (body, and the
# darker arms and feet). Picked on the slide before it's named.
SPECIES = {"blob": "Blob", "cat": "Cat", "bunny": "Bunny", "bear": "Bear", "dino": "Dino", "octopus": "Octopus"}
COLORS = {
	"crimson": ("#c8102e", "#9c0c24"), "blue": ("#2f7de1", "#1f5bb0"), "green": ("#3fae5a", "#2b7f40"),
	"yellow": ("#f2c230", "#c99a12"), "orange": ("#f07a2a", "#c2571a"), "purple": ("#8e5bd6", "#6a3fb0"),
	"pink": ("#f27ab0", "#c9548a"),
}
KEYBOARD = ["QWERTYUIOP", "ASDFGHJKL", "ZXCVBNM"]


def roman(number: int) -> str:
	"""2 -> "II": after a name that was used before (Bob, Bob II, Bob III, ...)."""
	numerals = [(1000, "M"), (900, "CM"), (500, "D"), (400, "CD"), (100, "C"), (90, "XC"), (50, "L"), (40, "XL"),
		(10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")]
	result = ""
	for value, numeral in numerals:
		while number >= value:
			result += numeral
			number -= value
	return result


ROMAN = re.compile(r"\s+[IVXLCDM]+$", re.IGNORECASE)


def base_name(name: str) -> str:
	"""The name without a numeral after it ("Bob II" -> "Bob"), for counting earlier pets with that name."""
	return ROMAN.sub("", name).strip() or name


def numbered_name(base: str, graves: list[dict]) -> str:
	"""The name with II, III, ... after it if earlier pets had it (in any case)."""
	earlier = sum(1 for grave in graves if base_name(grave.get("base") or grave["name"]).casefold() == base.casefold())
	return f"{base} {roman(earlier + 1)}" if earlier else base


def age_text(age: timedelta) -> str:
	minutes = int(age.total_seconds() // 60)
	if minutes < 60:
		return f"{minutes} min"
	if minutes < 48 * 60:
		return f"{minutes // 60} h {minutes % 60:02d} min" if minutes < 10 * 60 else f"{minutes // 60} hours"
	return f"{minutes // (24 * 60)} days"


def clean_name(typed: str) -> str:
	"""The typed name, tidied: letters, digits, spaces and a few marks, at most MAX_NAME long. Typed on the
	screen's keyboard it's in capitals ("BOB"): then "Bob"."""
	name = " ".join(re.sub(r"[^\w '\-.!]", "", typed).split())[:MAX_NAME].strip()
	return name.title() if name.isupper() else name


def day_of(now: datetime) -> str:
	return (now - DAY_STARTS_AT).date().isoformat()


def new_egg() -> dict:
	"""A pet still to be hatched: its look (a random one to start from) and where in picking it is ("choose": the
	shape and colour, "name": typing its name)."""
	return {"species": random.choice(list(SPECIES)), "color": random.choice(list(COLORS)), "step": "choose"}


def look(thing: dict) -> dict:
	"""The template's variables for how a pet or egg looks (an old pet without a look: the crimson blob)."""
	species = thing.get("species") if thing.get("species") in SPECIES else "blob"
	color = thing.get("color") if thing.get("color") in COLORS else "crimson"
	body, dark = COLORS[color]
	return {"species": species, "color": color, "body": body, "dark": dark}


def new_pet(name: str, generation: int, now: datetime, species: str = "blob", color: str = "crimson") -> dict:
	return {"name": name, "generation": generation, "species": species, "color": color, "hatched": now.isoformat(timespec="seconds"),
		"updated": now.isoformat(timespec="seconds"), "food": 80.0, "fun": 80.0, "clean": 80.0, "health": 100.0,
		"died": None, "cause": None, "drained": {"day": day_of(now)}}


def advance(pet: dict, now: datetime, people: int) -> None:
	"""Move the pet on from its last update to now, with `people` in the room all that time."""
	last = datetime.fromisoformat(pet["updated"])
	pet["updated"] = now.isoformat(timespec="seconds")
	if pet["died"] or now <= last:
		return
	hours = min(now - last, MAX_STEP).total_seconds() / 3600
	if people <= 0:
		return   # asleep: nothing changes
	drained = pet.setdefault("drained", {})
	if drained.get("day") != day_of(now):
		drained.clear()
		drained["day"] = day_of(now)
	for need in NEEDS:
		amount = min(100 / HOURS_PER_PERSON[need] * people * hours, MAX_DRAIN_PER_DAY - drained.get(need, 0))
		if amount > 0:
			pet[need] = max(0.0, pet[need] - amount)
			drained[need] = drained.get(need, 0) + amount
	empty = [need for need in NEEDS if pet[need] <= 0]
	if empty:
		if pet.get("first_empty") not in empty:
			pet["first_empty"] = empty[0]   # what it dies of, if it does
		pet["health"] = max(0.0, pet["health"] - 100 / NEGLECT_HOURS * len(empty) * hours)
		if pet["health"] <= 0:
			pet["died"] = now.isoformat(timespec="seconds")
			pet["cause"] = CAUSES[pet["first_empty"]]
	else:
		pet["first_empty"] = None
		pet["health"] = min(100.0, pet["health"] + 100 / RECOVER_HOURS * hours)


def done_for_today(pet: dict, now: datetime) -> bool:
	"""Whether every need has gone down as much as it can today."""
	drained = pet.get("drained", {})
	return drained.get("day") == day_of(now) and all(drained.get(need, 0) >= MAX_DRAIN_PER_DAY - 0.01 for need in NEEDS)


def mood(pet: dict) -> str:
	"""happy, okay, sad or sick: how it looks, from its emptiest need and its health."""
	lowest = min(pet[need] for need in NEEDS)
	if lowest <= 0 or pet["health"] < 50:
		return "sick"
	return "happy" if lowest > 60 else "okay" if lowest > 25 else "sad"


def complaint(pet: dict) -> str:
	"""What it says when nobody just tapped: about its emptiest need."""
	need = min(NEEDS, key=lambda need: pet[need])
	if pet[need] > 60:
		return "Life is good!"
	return {"food": "I'm hungry...", "fun": "I'm so bored...", "clean": "I'm getting stinky..."}[need] if pet[need] > 25 \
		else {"food": "FEED ME!", "fun": "Play with me!!", "clean": "I smell terrible!"}[need]


class PetProvider(Provider):
	name = "pet"
	title = "Francken pet"
	refresh_seconds = 60
	nothing_to_show = "Doing fine: it shows up once one of its bars is below half"

	def __init__(self, settings: dict, count_people: Callable[[datetime], int], state_path: Path | None = None) -> None:
		self.seconds = settings.get("seconds", 20)
		self.cry_minutes = settings.get("cry_minutes", 20)   # below half health, about this long between cries
		self.count_people = count_people
		self.state_path = state_path
		self.people = 0               # in the room at the last refresh()
		self.state: dict | None = None   # {"pet": {...} or None (being picked: "egg"), "egg": {...}, "graves": [...]}
		self.last_tap: dict[str, datetime] = {}
		self.last_any_tap: datetime | None = None
		self.said: tuple[str, datetime] | None = None   # its answer to the last tap, until when
		self.next_cry: datetime | None = None
		self.lock = threading.Lock()   # taps arrive from the web server's threads, refresh() from the background

	# ---- the state ------------------------------------------------------------------------------

	def load(self) -> dict:
		if self.state is None:
			self.state = {}
			if self.state_path and self.state_path.exists():
				try:
					self.state = json.loads(self.state_path.read_text(encoding="utf-8"))
				except (OSError, ValueError) as error:
					log.warning("Ignoring unreadable pet %s: %s", self.state_path, error)
			if not isinstance(self.state, dict) or not isinstance(self.state.get("pet"), (dict, type(None))):
				self.state = {}
			self.state.setdefault("pet", None)
			self.state.setdefault("graves", [])
			if not isinstance(self.state.get("egg"), dict):
				self.state["egg"] = new_egg()
		return self.state

	def save(self) -> None:
		if self.state_path is None or self.state is None:
			return
		self.state_path.parent.mkdir(parents=True, exist_ok=True)
		temporary = self.state_path.with_suffix(".tmp")
		temporary.write_text(json.dumps(self.state, indent=1, ensure_ascii=False), encoding="utf-8")
		temporary.replace(self.state_path)

	def awake_people(self, now: datetime) -> int:
		"""People in the room; at least one for a while after a tap (the sniffer doesn't know everyone)."""
		tapped = self.last_any_tap and now - self.last_any_tap < AWAKE_AFTER_TAP
		return max(self.people, 1 if tapped else 0)

	def step(self, now: datetime) -> dict | None:
		"""The pet moved on to now; None while it waits for a name."""
		state = self.load()
		pet = state["pet"]
		if pet is None:
			return None
		was_alive = not pet["died"]
		advance(pet, now, self.awake_people(now))
		if was_alive and pet["died"]:
			state["graves"].append({"name": pet["name"], "base": pet.get("base", pet["name"]), "species": pet.get("species"), "color": pet.get("color"),
				"hatched": pet["hatched"], "died": pet["died"], "cause": pet["cause"]})
			log.info("The pet %s %s", pet["name"], pet["cause"])
		return pet

	def refresh(self, now: datetime) -> None:
		people = self.count_people(now)
		with self.lock:
			self.step(now)   # up to now with the old count, then the new count from here on
			self.people = people
			self.save()

	def cry_due(self, now: datetime) -> bool:
		"""Whether it should cry now: below CRY_BELOW health, awake, and not too soon after the last cry.
		Right away when health drops below it, then every cry_minutes or so (a bit random, so it's no clock)."""
		with self.lock:
			pet = self.step(now)
			if pet is None or pet["died"] or pet["health"] >= CRY_BELOW or not self.awake_people(now):
				self.next_cry = None
				return False
			if self.next_cry is not None and now < self.next_cry:
				return False
			self.next_cry = now + timedelta(minutes=self.cry_minutes * random.uniform(0.7, 1.3))
			return True

	# ---- the slide ------------------------------------------------------------------------------

	def data(self, now: datetime, anim: str | None = None) -> dict:
		with self.lock:
			said = self.said[0] if self.said and now < self.said[1] else None
			pet = self.step(now)
			graves = list(self.state["graves"])
			egg = dict(self.state["egg"])
			people = self.awake_people(now)
		lives = [datetime.fromisoformat(g["died"]) - datetime.fromisoformat(g["hatched"]) for g in graves]
		data = {"people": people, "anim": anim, "graves": len(graves), "record": age_text(max(lives)) if lives else None}
		if pet is None:
			choices = {"species_list": [{"key": key, "label": label} | look({"species": key, "color": egg["color"]}) for key, label in SPECIES.items()],
				"colors": [{"key": key, "body": body} for key, (body, _) in COLORS.items()]}
			return data | look(egg) | choices | {"state": "naming" if egg["step"] == "name" else "choosing", "first": not graves,
				"said": said, "keyboard": KEYBOARD, "last": graves[-1]["name"] if graves else None, "species_name": SPECIES[look(egg)["species"]]}
		hatched = datetime.fromisoformat(pet["hatched"])
		data |= look(pet)
		data["name"] = pet["name"]
		if pet["died"]:
			died = datetime.fromisoformat(pet["died"])
			return data | {"state": "dead", "mood": "dead", "cause": pet["cause"], "age": age_text(died - hatched), "said": said}
		bars = [{"key": key, "label": LABELS[key], "value": round(pet[key]), "low": pet[key] <= 25} for key in (*NEEDS, "health")]
		return data | {
			"state": "awake" if people else "asleep",
			"mood": mood(pet) if people else "asleep",
			"age": age_text(now - hatched),
			"bars": bars,
			"said": said or (complaint(pet) if people else "Zzz..."),
			"done_today": done_for_today(pet, now),
		}

	def make_slide(self, now: datetime, anim: str | None = None) -> Slide:
		slide = Slide("pet.html", self.seconds, self.data(now, anim), refresh_seconds=2)
		slide.update = lambda later: self.data(later)   # the bars move while it's shown, without the tap's animation
		return slide

	def needs_attention(self, now: datetime) -> bool:
		"""Whether it belongs in the slideshow: waiting for a name, dead (its grave, and a new one), or one of its
		bars below SHOW_BELOW. A happy pet stays out of the way."""
		with self.lock:
			pet = self.step(now)
		return pet is None or bool(pet["died"]) or any(pet[key] < SHOW_BELOW for key in (*NEEDS, "health"))

	def slides(self, now: datetime) -> list[Slide]:
		return [self.make_slide(now)] if self.needs_attention(now) else []

	def shortcut_slide(self, now: datetime) -> Slide | None:
		return self.make_slide(now)   # the menu's preview: always

	def action(self, name: str, values: list[str], now: datetime) -> tuple[Slide | None, str | None]:
		"""'feed', 'play' or 'clean' a living pet; 'bury' a dead one (then the slide asks for a new one). Picking the
		new one: 'species' and 'color' with values = [its key], 'next' to the name and 'back' to the look; 'name' with
		values = [the typed name] hatches it."""
		with self.lock:
			pet = self.step(now)
			last = self.last_tap.get(name)
			if last and now - last < TAP_COOLDOWN and name in (*ACTIONS, "bury", "name"):
				return None, None   # a double tap
			self.last_tap[name] = now
			self.last_any_tap = now
			said, anim = None, None
			egg = self.state["egg"]
			if name == "name" and pet is None:
				typed = clean_name(values[0]) if values else ""
				if not typed:
					return None, "Type a name first"
				generation = len(self.state["graves"]) + 1
				chosen = look(egg)
				base = base_name(typed)
				typed = numbered_name(base, self.state["graves"])
				self.state["pet"] = new_pet(typed, generation, now, chosen["species"], chosen["color"]) | {"base": base}
				self.state["egg"] = new_egg()   # for the next one
				said, anim = f"Hi! I'm {typed}!", "hatch"
			elif pet is None and name in ("species", "color") and values and values[0] in (SPECIES if name == "species" else COLORS):
				egg[name] = values[0]
			elif pet is None and name in ("next", "back"):
				egg["step"] = "name" if name == "next" else "choose"
			elif name == "bury" and pet is not None and pet["died"]:
				self.state["pet"] = None
				self.state["egg"] = new_egg()
			elif name in ACTIONS and pet is not None and not pet["died"]:
				need, amount, said = ACTIONS[name]
				if pet[need] >= FULL:
					said, anim = {"food": "I'm full!", "fun": "I'm tired, later!", "clean": "I'm already clean!"}[need], "no"
				else:
					pet[need] = min(100.0, pet[need] + amount)
					anim = name
					if name == "feed":
						pet["clean"] = max(0.0, pet["clean"] - 5)   # eating is messy
					elif name == "play":
						pet["food"] = max(0.0, pet["food"] - 5)    # playing makes hungry
			else:
				return None, None
			self.said = (said, now + SAY_SECONDS) if said else None
			self.save()
		return self.make_slide(now, anim), None


class PetCry(Job):
	"""Plays the pet's cry on the speakers now and then while its health is low (PetProvider.cry_due)."""

	name = "pet_cry"
	check_every = timedelta(seconds=10)

	def __init__(self, pet: PetProvider, announcer: Announcer, sound: Path = PROJECT_DIR / "francken_tv/static/pet/cry.wav") -> None:
		self.pet = pet
		self.announcer = announcer
		self.sound = sound
		self.last_check: datetime | None = None

	def tick(self, now: datetime) -> None:
		if self.last_check is not None and now - self.last_check < self.check_every:
			return
		self.last_check = now
		if self.pet.cry_due(now):
			self.announcer.play_sound(self.sound)


def people_in_room(store: PresenceStore, minutes: float) -> Callable[[datetime], int]:
	"""How many known devices the sniffer saw in the last `minutes`."""
	def count(now: datetime) -> int:
		return len({sighting.name for sighting in store.known_sightings(now - timedelta(minutes=minutes), now + timedelta(seconds=1))})
	return count
