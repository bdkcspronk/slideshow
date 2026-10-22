"""Keeping the sound on the line-out (line_out.py)."""

import json
import unittest
from pathlib import Path

from francken_tv.line_out import Card, Port, Sink, Sound, parse_pactl, parse_pw_dump, plan

FIXTURE = Path(__file__).parent / "fixtures" / "pw-dump.json"   # a real PipeWire setup: one card, analog output

ANALOG = "alsa_output.pci-0000_00_1f.3.analog-stereo"
HDMI = "alsa_output.pci-0000_00_1f.3.hdmi-stereo"


def card(active):
	profiles = {"output:hdmi-stereo": True, "output:analog-stereo+input:analog-stereo": True, "output:analog-stereo": True, "off": True}
	return Card("48", profiles, active, {name: i for i, name in enumerate(profiles)})


def analog_sink(active_port="analog-output-headphones", line_out_available=True):
	ports = [Port("analog-output-lineout", line_out_available, 3), Port("analog-output-headphones", True, 4)]
	return Sink("55", ANALOG, "48", ports, active_port)


class PlanTest(unittest.TestCase):
	def test_a_real_pipewire_setup_on_analog_needs_nothing(self):
		sound = parse_pw_dump(json.loads(FIXTURE.read_text()))
		self.assertEqual([sink.name for sink in sound.sinks], ["alsa_output.pci-0000_00_05.0.analog-stereo"])
		self.assertEqual(sound.default_sink, "alsa_output.pci-0000_00_05.0.analog-stereo")
		self.assertEqual(plan(sound), [])

	def test_card_on_hdmi_switches_to_analog(self):
		sound = Sound([card("output:hdmi-stereo")], [Sink("60", HDMI, "48", [], None)], HDMI)
		[(kind, target, profile)] = plan(sound)
		self.assertEqual((kind, target.id, profile, target.profile_index[profile]), ("profile", "48", "output:analog-stereo+input:analog-stereo", 1))

	def test_then_the_line_out_port_and_the_default(self):
		sound = Sound([card("output:analog-stereo+input:analog-stereo")], [analog_sink()], HDMI)
		steps = plan(sound)
		self.assertEqual([(step[0], step[-1].name) for step in steps], [("port", "analog-output-lineout"), ("default", ANALOG)])
		self.assertEqual(steps[0][2].index, 3)   # PipeWire's route index

	def test_unplugged_line_out_keeps_the_port(self):
		sound = Sound([card("output:analog-stereo")], [analog_sink(line_out_available=False)], ANALOG)
		self.assertEqual(plan(sound), [])   # nothing in the line-out: the PC's own choice stays

	def test_already_right(self):
		sound = Sound([card("output:analog-stereo")], [analog_sink(active_port="analog-output-lineout")], ANALOG)
		self.assertEqual(plan(sound), [])

	def test_no_analog_output_at_all(self):
		sound = Sound([Card("1", {"output:hdmi-stereo": True}, "output:hdmi-stereo")], [Sink("60", HDMI, "1", [], None)], HDMI)
		self.assertEqual(plan(sound), [])   # e.g. a PC without a line-out: leave it


PACTL_CARDS = """Card #0
	Name: alsa_card.pci-0000_00_1f.3
	Driver: module-alsa-card.c
	Profiles:
		input:analog-stereo: Analog Stereo Input (sinks: 0, sources: 1, priority: 65, available: yes)
		output:analog-stereo: Analog Stereo Output (sinks: 1, sources: 0, priority: 6500, available: yes)
		output:analog-stereo+input:analog-stereo: Analog Stereo Duplex (sinks: 1, sources: 1, priority: 6565, available: yes)
		output:hdmi-stereo: Digital Stereo (HDMI) Output (sinks: 1, sources: 0, priority: 5900, available: yes)
		off: Off (sinks: 0, sources: 0, priority: 0, available: yes)
	Active Profile: output:hdmi-stereo
	Ports:
		analog-output-lineout: Line Out (type: Line, priority: 9000, latency offset: 0 usec, availability unknown)
			Part of profile(s): output:analog-stereo, output:analog-stereo+input:analog-stereo
"""
PACTL_SINKS = """Sink #1
	State: RUNNING
	Name: alsa_output.pci-0000_00_1f.3.hdmi-stereo
	Description: Built-in Audio Digital Stereo (HDMI)
	Ports:
		hdmi-output-0: HDMI / DisplayPort (type: HDMI, priority: 5900, available)
	Active Port: hdmi-output-0
"""


class PactlTest(unittest.TestCase):
	def test_pulseaudio_on_hdmi_switches_the_card_to_analog(self):
		sound = parse_pactl(PACTL_CARDS, PACTL_SINKS, "alsa_output.pci-0000_00_1f.3.hdmi-stereo\n")
		self.assertEqual(sound.cards[0].active_profile, "output:hdmi-stereo")
		self.assertEqual(sound.sinks[0].ports[0].available, True)
		[(kind, target, profile)] = plan(sound)
		self.assertEqual((kind, target.id, profile), ("profile", "alsa_card.pci-0000_00_1f.3", "output:analog-stereo+input:analog-stereo"))

	def test_pulseaudio_ports_and_availability(self):
		sinks = PACTL_SINKS.replace("hdmi-stereo", "analog-stereo").replace(
			"		hdmi-output-0: HDMI / DisplayPort (type: HDMI, priority: 5900, available)\n",
			"		analog-output-lineout: Line Out (type: Line, priority: 9000, not available)\n"
			"		analog-output-headphones: Headphones (type: Headphones, priority: 9900, available)\n"
		).replace("Active Port: hdmi-output-0", "Active Port: analog-output-headphones")
		sound = parse_pactl(PACTL_CARDS.replace("Active Profile: output:hdmi-stereo", "Active Profile: output:analog-stereo"), sinks,
			"alsa_output.pci-0000_00_1f.3.analog-stereo")
		self.assertEqual([(p.name, p.available) for p in sound.sinks[0].ports],
			[("analog-output-lineout", False), ("analog-output-headphones", True)])
		self.assertEqual(plan(sound), [])   # the line-out is unplugged: headphones stay


if __name__ == "__main__":
	unittest.main()
