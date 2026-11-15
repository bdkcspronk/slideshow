"""When and how often a slide type (or a group of them) comes round: the menu's Settings -> "Rotation settings of slides".

A rule says how often (every round, every 5th round, once an hour, ...), in which months, on which days of the week and at
what time of day. Every slide type has one; slide types without a saved rule get the default, which is "every round, all
year, all day", or "daytime only" for the ones in rotation.daytime_only (config.toml).

A group is a set of slide types that take turns: they share one place in the round, the next of them each round
(rotation.take_turns in config.toml). A group has a rule of its own for that shared place, on top of its slides' rules.

The rules and groups changed on the TV are saved with the other settings (settings.py: `rules`, `groups`; on/off is
`hidden`). The scheduler (scheduler.py) follows them; the menu (menu.py, player.js) shows and edits them through edit().
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta

# How often, as (value, label). A number: every so many rounds; the others by the clock.
FREQUENCIES = [("1", "Every round"), ("2", "Every 2nd round"), ("3", "Every 3rd round"), ("5", "Every 5th round"),
	("10", "Every 10th round"), ("hour", "Once an hour"), ("3hours", "Once every 3 hours"), ("day", "Once a day")]
CLOCK = {"hour": timedelta(hours=1), "3hours": timedelta(hours=3)}
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
ALL_MONTHS = tuple(range(1, 13))
ALL_DAYS = tuple(range(7))
RULE_FIELDS = ("every", "months", "days", "hours")


@dataclass(frozen=True)
class Rule:
	every: str = "1"                        # one of FREQUENCIES
	months: tuple[int, ...] = ALL_MONTHS    # 1-12
	days: tuple[int, ...] = ALL_DAYS        # 0 = Monday
	hours: str | tuple[int, int] = "any"    # "any", "daytime" (rotation.daytime_from until daytime_until), "nighttime" (the rest) or (from, until) in whole hours

	@classmethod
	def from_dict(cls, data: dict | None, default: Rule | None = None) -> Rule:
		base = default or cls()
		data = clean_rule(data or {})
		hours = data.get("hours", base.hours)
		return cls(every=data.get("every", base.every), months=tuple(data.get("months", base.months)),
			days=tuple(data.get("days", base.days)), hours=tuple(hours) if isinstance(hours, list) else hours)

	def to_dict(self) -> dict:
		return {"every": self.every, "months": list(self.months), "days": list(self.days),
			"hours": list(self.hours) if isinstance(self.hours, tuple) else self.hours}

	def on_this_day(self, now: datetime) -> bool:
		return now.month in self.months and now.weekday() in self.days

	def in_hours(self, now: datetime, daytime: tuple[time, time]) -> bool:
		if self.hours == "any":
			return True
		if self.hours == "daytime":
			return daytime[0] <= now.time() < daytime[1]
		if self.hours == "nighttime":   # the rest of the day: from the end of the daytime until it starts again
			return not daytime[0] <= now.time() < daytime[1]
		start, until = self.hours
		if start == until:
			return True   # from 08:00 until 08:00: the whole day
		if start < until:
			return start <= now.hour < until
		return now.hour >= start or now.hour < until   # over midnight, e.g. 20:00 until 02:00

	def due(self, last: tuple[int, datetime] | None, round_number: int, now: datetime) -> bool:
		"""Whether it may come round again, `last` being (the round, the time) it was last shown."""
		if last is None or self.every == "1":
			return True
		last_round, last_time = last
		if self.every in CLOCK:
			return now - last_time >= CLOCK[self.every]
		if self.every == "day":
			return now.date() != last_time.date()
		return round_number - last_round >= int(self.every)


@dataclass(frozen=True)
class Group:
	slides: tuple[str, ...]
	on: bool = True
	rule: Rule = field(default_factory=Rule)
	color: str = ""   # one of COLORS, to see in the menu which slides are in it; "": the next one free (with_colors())

	@property
	def key(self) -> str:   # what the scheduler remembers its last showing by
		return "group:" + ",".join(sorted(self.slides))

	@classmethod
	def from_dict(cls, data: dict) -> Group:
		data = clean_group(data)
		return cls(tuple(data["slides"]), data.get("on", True), Rule.from_dict({k: data[k] for k in RULE_FIELDS if k in data}),
			data.get("color", ""))

	def to_dict(self) -> dict:
		return {"slides": list(self.slides), "on": self.on, **self.rule.to_dict(), **({"color": self.color} if self.color else {})}


# The groups' colours in the menu: bright enough on its dark blue, and none of them the red that means "chosen" there.
COLORS = ["#f2b134", "#4fc3a1", "#e86f9a", "#8c9eff", "#ff8a5c", "#9ccc65", "#4dd0e1", "#ce93d8"]


def with_colors(groups: list[dict]) -> list[dict]:
	"""Every group with a colour: the ones without get the first that no other group has (in order, so the groups of
	config.toml always get the same ones)."""
	used = {group.get("color") for group in groups}
	free = [color for color in COLORS if color not in used] or COLORS
	result = []
	for group in groups:
		if not group.get("color"):
			group = {**group, "color": free.pop(0) if free else COLORS[len(result) % len(COLORS)]}
		result.append(group)
	return result


def random_color(groups: list[dict]) -> str:
	"""A colour for a new group: any that no other group has, picked at random."""
	used = {group.get("color") for group in groups}
	return random.choice([color for color in COLORS if color not in used] or COLORS)


def clean_rule(data) -> dict:
	"""The fields of a rule from the menu or settings.json, checked; raises ValueError for a wrong one."""
	if not isinstance(data, dict):
		raise ValueError("a rule must be an object")
	clean = {}
	for name, value in data.items():
		if name == "every":
			if value not in dict(FREQUENCIES):
				raise ValueError(f"every must be one of {[f for f, _ in FREQUENCIES]}")
		elif name in ("months", "days"):
			allowed = ALL_MONTHS if name == "months" else ALL_DAYS
			if not isinstance(value, (list, tuple)) or not value or any(type(item) is not int or item not in allowed for item in value):
				raise ValueError(f"{name} must be a list with at least one of {list(allowed)}")
			value = sorted(set(value))
		elif name == "hours":
			if isinstance(value, (list, tuple)):
				if len(value) != 2 or any(type(item) is not int or not 0 <= item <= 23 for item in value):
					raise ValueError("hours must be two whole hours from 0 to 23")
				value = list(value)
			elif value not in ("any", "daytime", "nighttime"):
				raise ValueError('hours must be "any", "daytime", "nighttime" or [from, until]')
		else:
			raise ValueError(f"unknown field {name!r} in a rule")
		clean[name] = value
	return clean


def clean_group(data) -> dict:
	if not isinstance(data, dict) or not isinstance(data.get("slides"), list) or not all(isinstance(s, str) for s in data["slides"]):
		raise ValueError("a group needs a list of slide types")
	if not isinstance(data.get("on", True), bool):
		raise ValueError("a group's on must be true or false")
	if not isinstance(data.get("color", ""), str):
		raise ValueError("a group's color must be text")
	rule = clean_rule({k: v for k, v in data.items() if k not in ("slides", "on", "color")})
	color = {"color": data["color"]} if data.get("color") else {}
	return {"slides": list(dict.fromkeys(data["slides"])), "on": data.get("on", True), **rule, **color}


def clean_rules(value) -> dict:
	if not isinstance(value, dict) or not all(isinstance(name, str) for name in value):
		raise ValueError("rules must be an object of slide types")
	return {name: clean_rule(rule) for name, rule in value.items()}


def clean_groups(value) -> list | None:
	if value is None:
		return None   # the groups of config.toml
	if not isinstance(value, list):
		raise ValueError("groups must be a list")
	groups = [clean_group(group) for group in value]
	seen: set[str] = set()
	for group in groups:
		if seen & set(group["slides"]):
			raise ValueError(f"a slide type can only be in one group: {sorted(seen & set(group['slides']))}")
		seen |= set(group["slides"])
	return groups


# ---- The menu -----------------------------------------------------------------------------------

def runs(values: tuple[int, ...], names: list[str]) -> str:
	"""(3, 4, 5, 12) -> "Mar–May, Dec"; runs wrap round the end (Nov–Feb), as months and weekdays do."""
	count = len(names)
	chosen = set(values)
	start = next((i for i in range(count) if i in chosen and (i - 1) % count not in chosen), None)
	if start is None:
		return ""   # all of them
	parts, i = [], start
	for _ in range(count):
		if i in chosen and (i - 1) % count not in chosen:
			end = i
			while (end + 1) % count in chosen:
				end = (end + 1) % count
			parts.append(names[i] if end == i else f"{names[i]}–{names[end]}" if (end - i) % count > 1 else f"{names[i]}, {names[end]}")
		i = (i + 1) % count
	return ", ".join(parts)


def hours_text(hours, daytime: tuple[time, time]) -> str:
	if hours == "any":
		return "All day"
	if hours == "daytime":
		return f"Daytime ({daytime[0]:%H:%M}–{daytime[1]:%H:%M})"
	if hours == "nighttime":
		return f"Nighttime ({daytime[1]:%H:%M}–{daytime[0]:%H:%M})"
	return f"{hours[0]:02d}:00–{hours[1]:02d}:00"


def summary(rule: Rule, on: bool, daytime: tuple[time, time]) -> str:
	"""A short line for the list: "Every 5th round · Dec · Mon–Fri · Daytime"."""
	if not on:
		return "Off"
	parts = [dict(FREQUENCIES)[rule.every]]
	if rule.months != ALL_MONTHS:
		parts.append(runs(tuple(m - 1 for m in rule.months), MONTHS))
	if rule.days == (5, 6):
		parts.append("Weekends")
	elif rule.days != ALL_DAYS:
		parts.append(runs(rule.days, DAYS))
	if rule.hours in ("daytime", "nighttime"):
		parts.append(rule.hours.capitalize())
	elif rule.hours != "any":
		parts.append(hours_text(rule.hours, daytime))
	return " · ".join(parts)


def group_title(group: Group, titles: dict[str, str]) -> str:
	return " · ".join(titles.get(name, name) for name in group.slides) or "Empty group"


def menu_data(scheduler, settings, titles: dict[str, str]) -> dict:
	"""Everything the Rotation pages of the menu show. `titles`: slide type -> its name in the menu, in rotation order."""
	daytime = getattr(scheduler, "daytime", (time(8, 0), time(18, 0)))
	groups = current_groups(scheduler, settings)
	in_group = {name: number for number, group in enumerate(groups) for name in group.slides}
	slides = []
	for name, title in titles.items():
		rule = rule_of(scheduler, settings, name)
		on = name not in settings.hidden
		slides.append({"name": name, "title": title, "on": on, "rule": rule.to_dict(), "summary": summary(rule, on, daytime),
			"group": in_group.get(name)})
	return {
		"slides": slides,
		"groups": [{"title": group_title(group, titles), "slides": list(group.slides), "on": group.on, "rule": group.rule.to_dict(),
			"summary": summary(group.rule, group.on, daytime), "color": colored["color"]}
			for group, colored in zip(groups, with_colors([group.to_dict() for group in groups]))],
		"frequencies": [{"value": value, "label": label} for value, label in FREQUENCIES],
		"months": MONTHS,
		"days": DAYS,
		"daytime": hours_text("daytime", daytime),
		"nighttime": hours_text("nighttime", daytime),
		"daytime_hours": [daytime[0].hour, daytime[1].hour],   # what "Custom" starts from
		"changed": bool(settings.rules or settings.groups is not None or settings.hidden),
	}


def default_rule(scheduler, name: str) -> Rule:
	return Rule(hours="daytime") if name in getattr(scheduler, "daytime_only", set()) else Rule()


def rule_of(scheduler, settings, name: str) -> Rule:
	return Rule.from_dict(settings.rules.get(name), default_rule(scheduler, name))


def current_groups(scheduler, settings) -> list[Group]:
	if settings.groups is not None:
		return [Group.from_dict(group) for group in settings.groups]
	return list(getattr(scheduler, "config_groups", []))


def edit(scheduler, settings, value: dict) -> tuple[dict, str | None]:
	"""A change from the Rotation pages -> (the settings to change, a message for the screen or None).

	{"slide": name, "set": {"on" or a rule field: value}}   one slide type
	{"group": number, "set": {...}}                         a group's own rule, or switching it on or off
	{"group": number, "toggle": name}                       a slide type into this group (out of any other) or out of it
	{"new_group": true}, {"delete_group": number}, {"reset": true} (back to config.toml)
	Raises ValueError for anything else."""
	if not isinstance(value, dict):
		raise ValueError("rotation needs an object")
	if value.get("reset"):
		return {"rules": {}, "groups": None, "hidden": []}, "Rotation reset to default"
	# With their colours written down from the first change on, so deleting a group doesn't recolour the others.
	groups = with_colors([group.to_dict() for group in current_groups(scheduler, settings)])
	if value.get("new_group"):
		return {"groups": groups + [{"slides": [], "on": True, "color": random_color(groups)}]}, None
	if "delete_group" in value:
		groups.pop(group_number(value["delete_group"], groups))
		return {"groups": groups}, "Group deleted"
	if "slide" in value:
		name = value["slide"]
		changes = value.get("set")
		if not isinstance(name, str) or not isinstance(changes, dict) or not changes:
			raise ValueError("slide needs a name and set")
		changes = dict(changes)
		result = {}
		if "on" in changes:
			if not isinstance(changes["on"], bool):
				raise ValueError("on must be true or false")
			result["hidden"] = [n for n in settings.hidden if n != name] + ([] if changes.pop("on") else [name])
		if changes:
			rule = {**rule_of(scheduler, settings, name).to_dict(), **clean_rule(changes)}
			result["rules"] = {**settings.rules, name: rule}
		return result, None
	if "group" in value:
		number = group_number(value["group"], groups)
		if "toggle" in value:
			name = value["toggle"]
			if not isinstance(name, str):
				raise ValueError("toggle needs a slide type")
			joining = name not in groups[number]["slides"]
			for group in groups:
				group["slides"] = [n for n in group["slides"] if n != name]
			if joining:
				groups[number]["slides"].append(name)
			return {"groups": groups}, None
		changes = value.get("set")
		if not isinstance(changes, dict) or not changes:
			raise ValueError("group needs set or toggle")
		changes = dict(changes)
		if "on" in changes:
			if not isinstance(changes["on"], bool):
				raise ValueError("on must be true or false")
			groups[number]["on"] = changes.pop("on")
		groups[number].update(clean_rule(changes))
		return {"groups": groups}, None
	raise ValueError("unknown rotation change")


def group_number(number, groups: list) -> int:
	if type(number) is not int or not 0 <= number < len(groups):
		raise ValueError(f"no group {number!r}")
	return number
