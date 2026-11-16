import unittest

from toolhub import theme
from toolhub.gui import german_date, megabytes
from toolhub.widgets import initials_of


class Helpers(unittest.TestCase):
    def test_initials(self):
        self.assertEqual(initials_of("Music Renamer"), "MR")
        self.assertEqual(initials_of("OpenRisk"), "OR")
        self.assertEqual(initials_of("OCRDMS"), "OC")
        self.assertEqual(initials_of("Canio"), "Ca")

    def test_date(self):
        self.assertEqual(german_date("2026-10-07"), "7. Okt. 2026")
        self.assertEqual(german_date("2026-03-01"), "1. März 2026")
        self.assertEqual(german_date(""), "")

    def test_megabytes(self):
        self.assertEqual(megabytes(131 * 1048576), "131 MB")
        self.assertEqual(megabytes(int(2.5 * 1048576)), "2,5 MB")

    def test_tool_color_is_stable(self):
        self.assertEqual(theme.tool_color("Canio"), theme.tool_color("canio"))
        self.assertIn(theme.tool_color("x"), theme.TOOL_COLORS)

    def test_palettes_have_same_keys(self):
        self.assertEqual(set(theme.LIGHT), set(theme.DARK))


if __name__ == "__main__":
    unittest.main()
