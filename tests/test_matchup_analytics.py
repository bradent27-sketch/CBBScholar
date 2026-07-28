"""
Unit tests for Matchup Analyzer's deeper predictive-layer functions in
data.transforms: positional_vulnerability_ranking, defensive_tendency_rows,
efficiency_elasticity, and the reworked (3-tier) game_script_sensitivity.
Every function under test is pure local compute over plain DataFrames -
no loaders, no Streamlit, no network - so these are synthetic-data tests
with hand-checkable expected values, same style as the rest of this
tests/ directory.

This supersedes the earlier tests/test_predictive_analytics.py, written
for the standalone Predictive Analytics tab (scheme_fingerprint,
rim_foul_leverage_score, composite_matchup_advantage,
matchup_projection_band) that was retired based on in-app usage feedback -
see HANDOFF.md.

Run with: python3 -m unittest discover -s tests -v
"""
import unittest

import pandas as pd

import data.transforms as transforms


class PositionalVulnerabilityRankingTests(unittest.TestCase):
    def _positional_summary_df(self):
        return pd.DataFrame([
            {'Bucket': 'Guard', 'Games': 10, 'Points Allowed': 15.0, 'Points Delta': 3.0},
            {'Bucket': 'Forward', 'Games': 10, 'Points Allowed': 12.0, 'Points Delta': 0.0},
            {'Bucket': 'Center', 'Games': 10, 'Points Allowed': 10.0, 'Points Delta': -3.0},
        ])

    def test_ranked_most_exploitable_first(self):
        rows = transforms.positional_vulnerability_ranking(self._positional_summary_df())
        self.assertEqual([r['label'] for r in rows], ['Guard', 'Forward', 'Center'])
        # score = clip(50 + delta*4): Guard 62, Forward 50, Center 38.
        self.assertAlmostEqual(rows[0]['pct'], 62.0)
        self.assertAlmostEqual(rows[1]['pct'], 50.0)
        self.assertAlmostEqual(rows[2]['pct'], 38.0)
        for r in rows:
            self.assertIn('label', r)
            self.assertIn('help', r)
            self.assertIn('value_str', r)

    def test_reordered_input_still_ranks_correctly(self):
        # Deliberately NOT in Guard/Forward/Center order - the ranking
        # should sort purely by score, not echo input order.
        df = pd.DataFrame([
            {'Bucket': 'Center', 'Games': 5, 'Points Delta': 5.0},
            {'Bucket': 'Guard', 'Games': 5, 'Points Delta': -1.0},
            {'Bucket': 'Forward', 'Games': 5, 'Points Delta': 2.0},
        ])
        rows = transforms.positional_vulnerability_ranking(df)
        self.assertEqual([r['label'] for r in rows], ['Center', 'Forward', 'Guard'])

    def test_empty_input_returns_empty_list(self):
        self.assertEqual(transforms.positional_vulnerability_ranking(pd.DataFrame()), [])

    def test_unrecognized_bucket_and_missing_delta_skipped(self):
        df = pd.DataFrame([
            {'Bucket': 'Unknown', 'Games': 3, 'Points Delta': 4.0},
            {'Bucket': 'Guard', 'Games': 3, 'Points Delta': None},
            {'Bucket': 'Forward', 'Games': 3, 'Points Delta': 1.5},
        ])
        rows = transforms.positional_vulnerability_ranking(df)
        self.assertEqual([r['label'] for r in rows], ['Forward'])


class DefensiveTendencyRowsTests(unittest.TestCase):
    def _team_stats_df(self):
        return pd.DataFrame([
            {'Team': 'Weak D', 'Def 2P%': 58, 'Def FT Rate': 40, 'Opp Paint Pts %': 50, 'Def 3PA Rate': 45, 'Def 3P%': 38},
            {'Team': 'Mid D', 'Def 2P%': 50, 'Def FT Rate': 30, 'Opp Paint Pts %': 42, 'Def 3PA Rate': 38, 'Def 3P%': 33},
            {'Team': 'Strong D', 'Def 2P%': 42, 'Def FT Rate': 22, 'Opp Paint Pts %': 34, 'Def 3PA Rate': 30, 'Def 3P%': 28},
        ])

    def test_rim_and_perimeter_rows_present_and_ranked(self):
        weak_rows = {r['label']: r for r in transforms.defensive_tendency_rows(self._team_stats_df(), 'Weak D')}
        strong_rows = {r['label']: r for r in transforms.defensive_tendency_rows(self._team_stats_df(), 'Strong D')}
        self.assertIn('Rim Pressure Allowed', weak_rows)
        self.assertIn('Perimeter Openness Allowed', weak_rows)
        self.assertGreater(weak_rows['Rim Pressure Allowed']['pct'], strong_rows['Rim Pressure Allowed']['pct'])
        self.assertGreater(weak_rows['Perimeter Openness Allowed']['pct'], strong_rows['Perimeter Openness Allowed']['pct'])

    def test_unknown_team_returns_empty(self):
        self.assertEqual(transforms.defensive_tendency_rows(self._team_stats_df(), 'Nobody'), [])

    def test_missing_columns_degrade_gracefully(self):
        df = pd.DataFrame([{'Team': 'A', 'Def 3PA Rate': 35, 'Def 3P%': 33}])
        rows = transforms.defensive_tendency_rows(df, 'A')
        labels = [r['label'] for r in rows]
        self.assertNotIn('Rim Pressure Allowed', labels)
        self.assertIn('Perimeter Openness Allowed', labels)


class EfficiencyElasticityTests(unittest.TestCase):
    def _eff_ratings_df(self):
        return pd.DataFrame([
            {'Team': 'Elite D', 'Def Rating': 90}, {'Team': 'Mid D', 'Def Rating': 100}, {'Team': 'Weak D', 'Def Rating': 110},
        ])

    def _team_stats_df(self):
        return pd.DataFrame([
            {'Team': 'Elite D', 'Pace': 65}, {'Team': 'Mid D', 'Pace': 68}, {'Team': 'Weak D', 'Pace': 72},
        ])

    def _player_games(self):
        rows = [
            {'Opponent': 'Weak D', 'Points': 30, 'FGA': 20, 'FTA': 4},
            {'Opponent': 'Weak D', 'Points': 28, 'FGA': 20, 'FTA': 2},
            {'Opponent': 'Mid D', 'Points': 22, 'FGA': 20, 'FTA': 3},
            {'Opponent': 'Mid D', 'Points': 24, 'FGA': 22, 'FTA': 2},
            {'Opponent': 'Elite D', 'Points': 16, 'FGA': 20, 'FTA': 2},
            {'Opponent': 'Elite D', 'Points': 18, 'FGA': 22, 'FTA': 1},
        ]
        return pd.DataFrame(rows)

    def test_negative_slope_against_tougher_defenses(self):
        result = transforms.efficiency_elasticity(self._player_games(), self._eff_ratings_df(), self._team_stats_df(), 'Mid D')
        self.assertEqual(result['efficiency_label'], 'TS%')
        self.assertEqual(result['n_games'], 6)
        self.assertLess(result['slope_vs_defense'], 0)
        self.assertGreater(result['bucket_means']['vs Weaker Defenses']['mean'], result['bucket_means']['vs Top-Tier Defenses']['mean'])

    def test_insufficient_games_returns_empty(self):
        games = self._player_games().head(3)
        self.assertEqual(transforms.efficiency_elasticity(games, self._eff_ratings_df(), self._team_stats_df(), 'Mid D', min_games=5), {})

    def test_empty_inputs_return_empty(self):
        self.assertEqual(transforms.efficiency_elasticity(pd.DataFrame(), self._eff_ratings_df(), self._team_stats_df(), 'Mid D'), {})


class GameScriptSensitivityTests(unittest.TestCase):
    def _team_games(self):
        return pd.DataFrame([
            {'Date': '2026-01-01', 'Margin': 3}, {'Date': '2026-01-04', 'Margin': -10},
            {'Date': '2026-01-08', 'Margin': 20}, {'Date': '2026-01-11', 'Margin': 5},
            {'Date': '2026-01-15', 'Margin': -16}, {'Date': '2026-01-18', 'Margin': 12},
        ])

    def _player_games(self):
        return pd.DataFrame([
            {'Date': '2026-01-01', 'Points': 25}, {'Date': '2026-01-04', 'Points': 18},
            {'Date': '2026-01-08', 'Points': 10}, {'Date': '2026-01-11', 'Points': 23},
            {'Date': '2026-01-15', 'Points': 8}, {'Date': '2026-01-18', 'Points': 16},
        ])

    def test_three_tier_split_in_order(self):
        result = transforms.game_script_sensitivity(self._player_games(), self._team_games(), stat_col='Points')
        self.assertEqual([t['label'] for t in result['tiers']], ['Close', 'Comfortable', 'Blowout'])
        close, comfortable, blowout = result['tiers']
        self.assertAlmostEqual(close['mean'], 24.0)
        self.assertEqual(close['games'], 2)
        self.assertAlmostEqual(comfortable['mean'], 17.0)
        self.assertEqual(comfortable['games'], 2)
        self.assertAlmostEqual(blowout['mean'], 9.0)
        self.assertEqual(blowout['games'], 2)
        self.assertAlmostEqual(result['season_mean'], 16.7, places=1)
        self.assertEqual(result['n_games'], 6)

    def test_missing_middle_tier_is_simply_omitted(self):
        team_games = pd.DataFrame([{'Date': '2026-01-01', 'Margin': 2}, {'Date': '2026-01-04', 'Margin': 25}, {'Date': '2026-01-08', 'Margin': -1}])
        player_games = pd.DataFrame([{'Date': '2026-01-01', 'Points': 20}, {'Date': '2026-01-04', 'Points': 8}, {'Date': '2026-01-08', 'Points': 22}])
        result = transforms.game_script_sensitivity(player_games, team_games, stat_col='Points')
        self.assertEqual([t['label'] for t in result['tiers']], ['Close', 'Blowout'])

    def test_insufficient_total_games_returns_empty(self):
        team_games = pd.DataFrame([{'Date': '2026-01-01', 'Margin': 3}, {'Date': '2026-01-04', 'Margin': 5}])
        player_games = pd.DataFrame([{'Date': '2026-01-01', 'Points': 20}, {'Date': '2026-01-04', 'Points': 18}])
        self.assertEqual(transforms.game_script_sensitivity(player_games, team_games, stat_col='Points'), {})

    def test_empty_inputs_return_empty(self):
        self.assertEqual(transforms.game_script_sensitivity(pd.DataFrame(), pd.DataFrame()), {})


if __name__ == '__main__':
    unittest.main()
