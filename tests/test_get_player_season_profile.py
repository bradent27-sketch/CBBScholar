"""
Unit tests for data.loaders.get_player_season_profile - specifically the
fix for the review-flagged bug where this function gated on
load_espn_roster (ESPN's live-roster-only endpoint, no season parameter)
before ever checking the season box file. A player who left the program
since `season` (draft/transfer/graduation) demonstrably played that
season - real box-score rows exist for them - but used to fall back to
CBBD anyway because they weren't on TODAY's live roster. The fix removes
that gate entirely: the box-file match is the real, season-correct
existence check.

Run with: python3 -m unittest discover -s tests -v
"""
import unittest
from unittest.mock import patch

import pandas as pd

import data.loaders as loaders


def _espn_teams_df():
    return pd.DataFrame([
        {'Team': 'Duke', 'DisplayName': 'Duke Blue Devils', 'EspnId': '150', 'Conference': 'ACC', 'Color': None, 'AltColor': None},
    ])


def _box_row(**overrides):
    row = {
        'GameId': 1, 'Date': '2026-01-15', 'Team': 'Duke', 'Opponent': 'North Carolina',
        'Home/Away': 'vs', 'athleteSourceId': 's1', 'name': 'Departed Player', 'Position': 'F',
        'Minutes': 30, 'Points': 18, 'Rebounds': 6, 'OREB': 2, 'DREB': 4, 'Assists': 2,
        'Steals': 1, 'Blocks': 1, 'Turnovers': 2, 'FGM': 7, 'FGA': 14, '3PM': 1, '3PA': 3,
        'FTM': 3, 'FTA': 4,
    }
    row.update(overrides)
    return pd.DataFrame([row])


class GetPlayerSeasonProfileTests(unittest.TestCase):
    def test_departed_player_resolves_via_espn_without_needing_live_roster(self):
        """The core fix: a player who is NOT on today's live ESPN roster
        (load_espn_roster) but DOES have real box-file rows for `season`
        must resolve via ESPN, not silently fall back to CBBD."""
        box_df = _box_row()
        with patch.object(loaders, 'load_espn_teams', return_value=_espn_teams_df()), \
             patch.object(loaders, 'load_espn_season_player_box_native', return_value=box_df), \
             patch.object(loaders, 'load_espn_roster') as mock_roster, \
             patch.object(loaders, 'get_player_season_stats') as mock_cbbd_fallback:
            mock_roster.return_value = pd.DataFrame()  # today's live roster: empty/irrelevant
            stats, include_net_rating, source, returned_box_df, athlete_source_id = loaders.get_player_season_profile(
                'Duke', 2026, 'Departed Player', cbbd_athlete_id=999,
            )

        self.assertEqual(source, 'espn')
        self.assertFalse(include_net_rating)
        self.assertEqual(stats['games'], 1)
        self.assertEqual(stats['points'], 18.0)
        self.assertEqual(athlete_source_id, 's1')
        # The live-roster endpoint must never even be consulted anymore -
        # gating on it was the exact bug being fixed.
        mock_roster.assert_not_called()
        mock_cbbd_fallback.assert_not_called()

    def test_falls_back_to_cbbd_when_team_does_not_resolve(self):
        with patch.object(loaders, 'load_espn_teams', return_value=_espn_teams_df()), \
             patch.object(loaders, 'get_player_season_stats', return_value={'games': 5, 'points': 60}) as mock_cbbd:
            stats, include_net_rating, source, box_df, athlete_source_id = loaders.get_player_season_profile(
                'Some Unresolvable School', 2026, 'Anyone', cbbd_athlete_id=42,
            )

        self.assertEqual(source, 'cbbd')
        self.assertTrue(include_net_rating)
        self.assertIsNone(box_df)
        self.assertIsNone(athlete_source_id)
        mock_cbbd.assert_called_once_with('Some Unresolvable School', 2026, 42)
        self.assertEqual(stats, {'games': 5, 'points': 60})

    def test_falls_back_to_cbbd_when_player_not_in_box_file(self):
        box_df = _box_row()  # only has 'Departed Player'
        with patch.object(loaders, 'load_espn_teams', return_value=_espn_teams_df()), \
             patch.object(loaders, 'load_espn_season_player_box_native', return_value=box_df), \
             patch.object(loaders, 'get_player_season_stats', return_value={}) as mock_cbbd:
            stats, include_net_rating, source, returned_box_df, athlete_source_id = loaders.get_player_season_profile(
                'Duke', 2026, 'Nobody On This Team', cbbd_athlete_id=7,
            )

        self.assertEqual(source, 'cbbd')
        mock_cbbd.assert_called_once_with('Duke', 2026, 7)


if __name__ == "__main__":
    unittest.main()
