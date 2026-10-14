import unittest
from datetime import date, datetime

from francken_tv.providers.connections import ConnectionsProvider, parse_puzzle


def fake_puzzle(day: str, number: int) -> dict:
	"""Same shape as the NYT JSON: four categories, easiest first, each card with a grid position."""
	categories = []
	for group in range(4):
		cards = [{"content": f"W{group}{i}", "position": (i * 4 + group)} for i in range(4)]
		categories.append({"title": f"GROUP {group}", "cards": cards})
	return {"status": "OK", "id": number, "print_date": day, "categories": categories}


class ConnectionsTest(unittest.TestCase):
	def test_parse_puts_words_in_grid_order(self):
		puzzle = parse_puzzle(fake_puzzle("2026-10-14", 1330))
		self.assertEqual(puzzle.day, date(2026, 10, 14))
		self.assertEqual(puzzle.words[:5], ["W00", "W10", "W20", "W30", "W01"])
		self.assertEqual(puzzle.groups[0], ("GROUP 0", ["W00", "W01", "W02", "W03"]))

	def test_downloads_today_and_yesterday_once(self):
		provider = ConnectionsProvider({}, 8)
		fetched = []
		provider.fetch = lambda day: fetched.append(day) or parse_puzzle(fake_puzzle(day.isoformat(), 1))
		now = datetime(2026, 10, 14, 12, 0)
		provider.refresh(now)
		provider.refresh(now)
		self.assertEqual(fetched, [date(2026, 10, 14), date(2026, 10, 13)])
		[slide] = provider.slides(now)
		self.assertEqual((slide.data["today"].day, slide.data["yesterday"].day), (date(2026, 10, 14), date(2026, 10, 13)))

	def test_no_slide_without_todays_puzzle(self):
		self.assertEqual(ConnectionsProvider({}, 8).slides(datetime(2026, 10, 14)), [])


if __name__ == "__main__":
	unittest.main()
