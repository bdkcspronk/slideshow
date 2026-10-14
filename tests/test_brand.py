import unittest
from datetime import datetime

from francken_tv.providers.brand import BrandProvider
from francken_tv.server import make_templates


class BrandTest(unittest.TestCase):
	def test_slide_has_the_logo_and_name(self):
		[slide] = BrandProvider({"seconds": 10}, 8).slides(datetime(2026, 10, 14))
		self.assertEqual(slide.seconds, 10)
		html = make_templates().get_template(f"slides/{slide.template}").render(**slide.data)
		self.assertIn("<svg", html)                 # the logo, inline so CSS can colour it
		self.assertIn("T.F.V.", html)
		self.assertIn(">F</span>", html)            # the name is split into letters that rise one by one


if __name__ == "__main__":
	unittest.main()
