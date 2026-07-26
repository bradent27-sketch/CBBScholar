"""
Unit tests for data/utils.py's name-matching/team-name-resolution helpers -
the join logic behind several real, live-confirmed bugs this app has hit
(see HANDOFF.md): the ESPN roster/box-file id-namespace mismatch (fixed by
match_player_name), and the "Duke Blue Devils" vs "Duke" mascot-stripping
gap in resolve_team_name. Run with:

    python3 -m unittest discover -s tests -v
"""
import unittest

from data.utils import match_player_name, resolve_team_name


class MatchPlayerNameTests(unittest.TestCase):
    def test_exact_match(self):
        candidates = ["Cameron Boozer", "Isaiah Evans", "Caleb Foster"]
        self.assertEqual(match_player_name("Cameron Boozer", candidates), 0)
        self.assertEqual(match_player_name("Caleb Foster", candidates), 2)

    def test_case_and_punctuation_insensitive(self):
        candidates = ["Caleb Foster"]
        self.assertEqual(match_player_name("caleb  foster", candidates), 0)
        self.assertEqual(match_player_name("Caleb-Foster", candidates), 0)

    def test_suffix_inconsistency_falls_back_to_loose_match(self):
        # One source drops the suffix, the other keeps it - clean_name_exact
        # alone would miss this; clean_name_for_merge is the fallback tier.
        candidates = ["Michael Porter"]
        self.assertEqual(match_player_name("Michael Porter Jr.", candidates), 0)
        candidates2 = ["Michael Porter Jr."]
        self.assertEqual(match_player_name("Michael Porter", candidates2), 0)

    def test_no_match_returns_none(self):
        candidates = ["Cameron Boozer", "Isaiah Evans"]
        self.assertIsNone(match_player_name("Someone Else", candidates))

    def test_empty_candidates_returns_none(self):
        self.assertIsNone(match_player_name("Cameron Boozer", []))

    def test_ambiguous_names_resolve_to_first_occurrence(self):
        """
        Documents a known, real limitation (flagged in review, not yet
        fixed): two players sharing the exact same normalized name on the
        same team resolve to whichever one appears FIRST in `candidates`,
        with no warning. This test exists so a future disambiguation fix
        changes this assertion deliberately, not by accident.
        """
        candidates = ["John Smith", "John Smith"]
        self.assertEqual(match_player_name("John Smith", candidates), 0)


class ResolveTeamNameTests(unittest.TestCase):
    CANONICAL = [
        "Duke", "North Carolina", "North Carolina State", "Washington", "Washington State",
        "Miami (FL)", "Georgia", "Georgia State", "Georgia Tech", "Georgia Southern",
        "Virginia", "Virginia Commonwealth", "Virginia Tech", "Connecticut",
    ]

    def test_exact_match(self):
        self.assertEqual(resolve_team_name("Duke", self.CANONICAL), "Duke")

    def test_known_alias(self):
        # 'uconn' <-> 'connecticut' is a hardcoded TEAM_NAME_ALIASES entry.
        self.assertEqual(resolve_team_name("UConn", self.CANONICAL), "Connecticut")

    def test_mascot_stripping_simple(self):
        # The original live bug (HANDOFF.md): "Duke Blue Devils" never
        # resolved against a mascot-free canonical list before this fix.
        self.assertEqual(resolve_team_name("Duke Blue Devils", self.CANONICAL), "Duke")

    def test_mascot_stripping_prefers_longest_match(self):
        # "Washington" is ALSO a valid word-prefix of "Washington State
        # Cougars" - must not win over the more specific two-word match.
        self.assertEqual(resolve_team_name("Washington State Cougars", self.CANONICAL), "Washington State")
        self.assertEqual(resolve_team_name("Washington Huskies", self.CANONICAL), "Washington")

    def test_mascot_stripping_via_alias(self):
        # 'miami' isn't a canonical name on its own (canonical is
        # "Miami (FL)"), but the alias registers it - "Miami Hurricanes"
        # should resolve through the alias-expanded prefix match.
        self.assertEqual(resolve_team_name("Miami Hurricanes", self.CANONICAL), "Miami (FL)")

    def test_no_false_positive_across_similarly_prefixed_schools(self):
        self.assertEqual(resolve_team_name("Georgia Bulldogs", self.CANONICAL), "Georgia")
        self.assertEqual(resolve_team_name("Georgia State Panthers", self.CANONICAL), "Georgia State")
        self.assertEqual(resolve_team_name("Georgia Tech Yellow Jackets", self.CANONICAL), "Georgia Tech")
        self.assertEqual(resolve_team_name("Georgia Southern Eagles", self.CANONICAL), "Georgia Southern")

    def test_unresolvable_name_returns_none(self):
        self.assertIsNone(resolve_team_name("Nonexistent University Foobars", self.CANONICAL))


if __name__ == "__main__":
    unittest.main()
