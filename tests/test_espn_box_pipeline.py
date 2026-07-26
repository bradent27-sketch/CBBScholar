"""
Unit tests for the ESPN/SportsDataverse season box-score pipeline in
data/loaders.py - specifically the two real, review-flagged risks fixed in
this pass:

1. DNP rows (0/missing Minutes) must not count as "games played"
   (_resolve_espn_box_team_names' DNP filter - a real, live-confirmed bug,
   see HANDOFF.md).
2. Positional matchup defense's CBBD-name-resolved box file
   (_load_espn_season_player_box_cached) must not silently drop an entire
   opponent's rows just because that opponent's ESPN-spelled name doesn't
   happen to match CBBD's independently-formatted team list - the two-step
   ESPN-canonical-first, then CBBD-bridge fix.

Run with: python3 -m unittest discover -s tests -v
"""
import unittest

import pandas as pd

import data.loaders as loaders


def _raw_box_row(**overrides):
    row = {
        'GameId': 1, 'Date': '2026-01-15', 'TeamRaw': 'Duke', 'OpponentRaw': 'North Carolina',
        'Home/Away': 'vs', 'athleteSourceId': 's1', 'name': 'Player One', 'Position': 'G',
        'Minutes': 30, 'Points': 20, 'Rebounds': 5, 'OREB': 1, 'DREB': 4, 'Assists': 3,
        'Steals': 1, 'Blocks': 0, 'Turnovers': 2, 'FGM': 7, 'FGA': 15, '3PM': 2, '3PA': 6,
        'FTM': 4, 'FTA': 5,
    }
    row.update(overrides)
    return row


class ResolveEspnBoxTeamNamesTests(unittest.TestCase):
    def test_dnp_row_dropped(self):
        raw = pd.DataFrame([
            _raw_box_row(GameId=1, Minutes=30),   # played
            _raw_box_row(GameId=2, Minutes=0),    # DNP - available but didn't play
            _raw_box_row(GameId=3, Minutes=None), # DNP - missing minutes entirely
        ])
        out = loaders._resolve_espn_box_team_names(raw, ['Duke', 'North Carolina'])
        self.assertEqual(len(out), 1)
        self.assertEqual(out.iloc[0]['GameId'], 1)

    def test_dnp_filter_fixes_games_played_count(self):
        # Reproduces the real, live-confirmed bug (HANDOFF.md): a DNP row
        # counted as a "game played" deflated season averages ~44% for an
        # injured player. games = len(g) must equal only the PLAYED games.
        from data.transforms import espn_player_season_stats_for_teams
        raw = pd.DataFrame([
            _raw_box_row(GameId=1, Minutes=30, Points=20),
            _raw_box_row(GameId=2, Minutes=28, Points=18),
            _raw_box_row(GameId=3, Minutes=0, Points=0),  # DNP, shouldn't count
        ])
        resolved = loaders._resolve_espn_box_team_names(raw, ['Duke', 'North Carolina'])
        stats = espn_player_season_stats_for_teams(resolved, 'Duke')
        self.assertEqual(len(stats), 1)
        self.assertEqual(stats.iloc[0]['games'], 2)
        self.assertEqual(stats.iloc[0]['points'], 38.0)

    def test_unresolvable_team_name_dropped(self):
        raw = pd.DataFrame([_raw_box_row(TeamRaw='Totally Unknown School')])
        out = loaders._resolve_espn_box_team_names(raw, ['Duke', 'North Carolina'])
        self.assertTrue(out.empty)


class BridgeEspnBoxToCbbdNamesTests(unittest.TestCase):
    """
    _bridge_espn_box_to_cbbd_names (the two-step resolution
    _load_espn_season_player_box_cached delegates to, factored out as a
    pure function specifically so it's testable without touching that
    function's persist="disk" cache) resolves raw team names against
    ESPN's own team list FIRST, then bridges to CBBD's list - a row whose
    CBBD bridge fails keeps its ESPN-spelled name instead of being dropped
    outright. This directly fixes the "undercounts opponents" risk: an
    opponent whose CBBD spelling diverges from ESPN's (a real possibility
    for mid-majors, per TEAM_NAME_ALIASES' own "not exhaustive" disclaimer)
    no longer vanishes from the file entirely.
    """

    def setUp(self):
        self.raw_box = pd.DataFrame([
            _raw_box_row(GameId=1, TeamRaw='Duke', OpponentRaw='Alpha State'),
        ])
        self.espn_canonical = ['Duke', 'Alpha State']
        # CBBD spells the opponent differently, with no alias registered
        # for it - the exact divergence this fix targets.
        self.cbbd_canonical = ['Duke', 'Alpha St.']

    def test_opponent_survives_when_cbbd_bridge_fails(self):
        out = loaders._bridge_espn_box_to_cbbd_names(self.raw_box, self.espn_canonical, self.cbbd_canonical)
        self.assertFalse(out.empty, "row should survive via the ESPN-name fallback, not be dropped")
        self.assertEqual(out.iloc[0]['Team'], 'Duke')
        # CBBD bridge failed for the opponent - kept its ESPN-spelled name
        # rather than being silently dropped (the old single-hop behavior).
        self.assertEqual(out.iloc[0]['Opponent'], 'Alpha State')

    def test_single_hop_against_cbbd_only_would_have_dropped_the_row(self):
        """Contrast case proving the bug this fix addresses: resolving the
        SAME raw names directly against CBBD's list alone (the old,
        single-hop approach) drops the row entirely."""
        out = loaders._resolve_espn_box_team_names(self.raw_box, self.cbbd_canonical)
        self.assertTrue(out.empty)

    def test_bridge_succeeds_when_cbbd_name_matches(self):
        out = loaders._bridge_espn_box_to_cbbd_names(self.raw_box, self.espn_canonical, ['Duke', 'Alpha State'])
        self.assertEqual(out.iloc[0]['Opponent'], 'Alpha State')


if __name__ == "__main__":
    unittest.main()
