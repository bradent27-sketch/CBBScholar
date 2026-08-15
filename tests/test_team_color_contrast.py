"""
Unit tests for the team-color contrast correction in ui/styling.py, and for
the Game Slate row markup that consumes it.

The reported bug: a winner's score is printed in that team's brand color,
and a large share of D-I brand colors are near-black or deep navy - on the
dark card those scores landed at ~1.05:1 against their own background.

The fix has to satisfy two things at once, which is what these tests pin:
legibility (clears a real contrast threshold on the surface it's actually
drawn on), and IDENTITY (still recognizably the team's color - snapping
every winner to white would pass a contrast check while destroying the only
reason to color a score).

Run with: python3 -m unittest discover -s tests -v
"""
import colorsys
import unittest

from ui.styling import (
    contrast_ratio, ink_on, readable_on, _card_backdrop_rgb, _safe_hex_to_rgb,
)

# Real published brand colors, spanning the range that matters: the
# near-black/navy cluster that caused the bug, and bright colors that must
# be left alone in dark mode.
DARK_BRANDS = {'Duke': '#001a57', 'UConn': '#000e2f', 'Michigan': '#00274c',
               'Butler': '#13294b', 'Oregon': '#154733'}
BRIGHT_BRANDS = {'Iowa': '#ffcd00', 'Syracuse': '#f76900', 'North Carolina': '#7bafd4'}


class ContrastRatioTests(unittest.TestCase):
    def test_known_anchor_values(self):
        self.assertAlmostEqual(contrast_ratio((0, 0, 0), (255, 255, 255)), 21.0, places=2)
        self.assertAlmostEqual(contrast_ratio((0, 0, 0), (0, 0, 0)), 1.0, places=2)

    def test_symmetric(self):
        a, b = (0, 26, 87), (240, 240, 240)
        self.assertAlmostEqual(contrast_ratio(a, b), contrast_ratio(b, a), places=6)


class ReadableOnTests(unittest.TestCase):
    def setUp(self):
        self.dark = _card_backdrop_rgb(True)
        self.light = _card_backdrop_rgb(False)

    def test_dark_brand_colors_become_legible_on_the_dark_card(self):
        """The actual reported bug, on the actual colors that caused it."""
        for name, brand in DARK_BRANDS.items():
            with self.subTest(team=name):
                self.assertLess(
                    contrast_ratio(_safe_hex_to_rgb(brand), self.dark), 2.0,
                    "test's premise: this brand color is genuinely illegible raw")
                fixed = readable_on(brand, self.dark)
                self.assertGreaterEqual(contrast_ratio(_safe_hex_to_rgb(fixed), self.dark), 4.4)

    def test_bright_brand_colors_pass_light_mode(self):
        for name, brand in BRIGHT_BRANDS.items():
            with self.subTest(team=name):
                fixed = readable_on(brand, self.light)
                self.assertGreaterEqual(contrast_ratio(_safe_hex_to_rgb(fixed), self.light), 4.4)

    def test_hue_is_preserved_so_the_team_stays_identifiable(self):
        """The point of the whole exercise. Duke navy must come out a Duke
        BLUE, not white and not some other hue - a legible score that no
        longer says whose score it is has lost the information it existed to
        carry."""
        for brand in DARK_BRANDS.values():
            with self.subTest(brand=brand):
                before = colorsys.rgb_to_hls(*(c / 255 for c in _safe_hex_to_rgb(brand)))
                after = colorsys.rgb_to_hls(*(c / 255 for c in _safe_hex_to_rgb(readable_on(brand, self.dark))))
                self.assertAlmostEqual(before[0], after[0], places=2, msg="hue drifted")

    def test_result_is_not_white_or_black(self):
        for brand in DARK_BRANDS.values():
            fixed = readable_on(brand, self.dark).lower()
            self.assertNotIn(fixed, ('#ffffff', '#000000'))

    def test_already_legible_color_is_returned_untouched(self):
        """A color that already clears the bar must not be nudged at all -
        otherwise every card drifts away from its real brand color for no
        reason."""
        self.assertEqual(readable_on('#ffcd00', self.dark).lower(), '#ffcd00')

    def test_corrections_go_the_right_direction_per_theme(self):
        """Lighter on the dark card, darker on the light one."""
        duke = _safe_hex_to_rgb('#001a57')
        on_dark = _safe_hex_to_rgb(readable_on('#001a57', self.dark))
        self.assertGreater(sum(on_dark), sum(duke))

        gold = _safe_hex_to_rgb('#ffcd00')
        on_light = _safe_hex_to_rgb(readable_on('#ffcd00', self.light))
        self.assertLess(sum(on_light), sum(gold))

    def test_pure_black_still_becomes_visible(self):
        """An achromatic brand (Army) has no hue to preserve, so it can only
        move along the gray axis - it must still end up legible."""
        fixed = readable_on('#000000', self.dark)
        self.assertGreaterEqual(contrast_ratio(_safe_hex_to_rgb(fixed), self.dark), 4.4)

    def test_accepts_bare_hex_without_a_hash(self):
        self.assertEqual(readable_on('ffcd00', self.dark).lower(), '#ffcd00')

    def test_malformed_color_returns_none_not_a_broken_css_value(self):
        for junk in (None, '', 'not-a-color', '#12345', '#zzzzzz', 'rgb(1,2,3)'):
            with self.subTest(value=junk):
                self.assertIsNone(readable_on(junk, self.dark))


class InkOnTests(unittest.TestCase):
    def test_light_chip_gets_dark_text_and_vice_versa(self):
        self.assertEqual(ink_on('#ffcd00'), '#0b0f24')
        self.assertEqual(ink_on('#001a57'), '#ffffff')

    def test_chosen_ink_always_beats_the_alternative(self):
        for brand in list(DARK_BRANDS.values()) + list(BRIGHT_BRANDS.values()):
            with self.subTest(brand=brand):
                chip = _safe_hex_to_rgb(brand)
                chosen = _safe_hex_to_rgb(ink_on(brand))
                other = _safe_hex_to_rgb('#0b0f24' if ink_on(brand) == '#ffffff' else '#ffffff')
                self.assertGreaterEqual(contrast_ratio(chosen, chip), contrast_ratio(other, chip))

    def test_malformed_color_returns_none(self):
        self.assertIsNone(ink_on('nope'))


class TeamRowMarkupTests(unittest.TestCase):
    """The row must publish BOTH properties: the raw brand color (identity)
    and the corrected ink (legibility). The stylesheet reads --gs-ink for
    everything that has to be read and falls back to --gs-color."""

    def _row(self, color='#001a57', dark=True, winner=True):
        import pandas as pd
        from ui.tabs.game_slate import _team_row_html
        row = pd.Series({'Home': 'Duke', 'Home Color': color, 'Home Pts': 78,
                         'Home Conf': 'ACC', 'Home Rank': 1, 'Home Logo': None})
        return _team_row_html(row, 'Home', winner, True, dark)

    def test_publishes_both_the_brand_color_and_the_corrected_ink(self):
        html_ = self._row()
        self.assertIn('--gs-color:#001a57;', html_)
        self.assertIn('--gs-ink:', html_)
        self.assertIn('--gs-on-ink:', html_)
        self.assertNotIn('--gs-ink:#001a57', html_, "navy must not survive uncorrected on a dark card")

    def test_ink_clears_the_threshold_for_the_theme_it_was_built_for(self):
        import re
        for dark in (True, False):
            html_ = self._row(dark=dark)
            ink = re.search(r'--gs-ink:(#[0-9a-f]{6})', html_).group(1)
            self.assertGreaterEqual(
                contrast_ratio(_safe_hex_to_rgb(ink), _card_backdrop_rgb(dark)), 4.4)

    def test_missing_color_emits_no_style_attribute_at_all(self):
        """Rather than an empty or malformed one - the stylesheet's own
        fallback then supplies the neutral outline color."""
        html_ = self._row(color=None)
        self.assertNotIn('--gs-', html_)
        self.assertIn("class='gs-team gs-won'", html_)

    def test_malformed_color_still_publishes_brand_but_no_ink(self):
        html_ = self._row(color='bogus')
        self.assertIn('--gs-color:bogus;', html_)
        self.assertNotIn('--gs-ink:', html_)


if __name__ == "__main__":
    unittest.main()
