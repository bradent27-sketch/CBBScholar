"""
Unit tests for data.transforms' Predictive Analytics engine (Scheme
Fingerprint, Efficiency Elasticity Curve, Composite Matchup Advantage
Score, Rim-Pressure & Foul-Leverage Exploitation, Game-Script Sensitivity,
Positional Leverage, and the probability-band projection powering the new
Predictive Analytics tab). Every function under test is pure local compute
over plain DataFrames/dicts - no loaders, no Streamlit, no network - so
these are synthetic-data tests with hand-checkable expected values, same
style as the rest of this tests/ directory.

Run with: python3 -m unittest discover -s tests -v
"""
import unittest

import pandas as pd

import data.transforms as transforms


class SchemeFingerprintTests(unittest.TestCase):
    def _team_stats_df(self):
        return pd.DataFrame([
            {'Team': 'Weak D', 'Def 2P%': 58, 'Def FT Rate': 40, 'Opp Paint Pts %': 50, 'Def 3PA Rate': 45, 'Def 3P%': 38},
            {'Team': 'Mid D', 'Def 2P%': 50, 'Def FT Rate': 30, 'Opp Paint Pts %': 42, 'Def 3PA Rate': 38, 'Def 3P%': 33},
            {'Team': 'Strong D', 'Def 2P%': 42, 'Def FT Rate': 22, 'Opp Paint Pts %': 34, 'Def 3PA Rate': 30, 'Def 3P%': 28},
        ])

    def _positional_summary_df(self):
        return pd.DataFrame([
            {'Bucket': 'Guard', 'Games': 10, 'Points Allowed': 15.0, 'Points Delta': 3.0},
            {'Bucket': 'Forward', 'Games': 10, 'Points Allowed': 12.0, 'Points Delta': 0.0},
            {'Bucket': 'Center', 'Games': 10, 'Points Allowed': 10.0, 'Points Delta': -3.0},
        ])

    def test_unknown_team_returns_empty(self):
        self.assertEqual(transforms.scheme_fingerprint(self._team_stats_df(), 'Nobody', self._positional_summary_df()), {})

    def test_team_wide_percentiles_rank_correctly(self):
        weak = transforms.scheme_fingerprint(self._team_stats_df(), 'Weak D', self._positional_summary_df())
        strong = transforms.scheme_fingerprint(self._team_stats_df(), 'Strong D', self._positional_summary_df())
        self.assertGreater(weak['rim_pressure_pct'], strong['rim_pressure_pct'])
        self.assertGreater(weak['perimeter_openness_pct'], strong['perimeter_openness_pct'])

    def test_bucket_vulnerability_follows_points_delta(self):
        fp = transforms.scheme_fingerprint(self._team_stats_df(), 'Weak D', self._positional_summary_df())
        buckets = fp['buckets']
        self.assertGreater(buckets['Guard']['vulnerability'], buckets['Forward']['vulnerability'])
        self.assertGreater(buckets['Forward']['vulnerability'], buckets['Center']['vulnerability'])
        # Guard: delta_score = clip(50 + 3*4) = 62; Forward: 50; Center: 38.
        self.assertAlmostEqual(buckets['Guard']['delta_score'], 62.0)
        self.assertAlmostEqual(buckets['Forward']['delta_score'], 50.0)
        self.assertAlmostEqual(buckets['Center']['delta_score'], 38.0)

    def test_missing_positional_summary_still_returns_team_percentiles(self):
        fp = transforms.scheme_fingerprint(self._team_stats_df(), 'Weak D', pd.DataFrame())
        self.assertEqual(fp['buckets'], {})
        self.assertIsNotNone(fp['rim_pressure_pct'])


class PositionalLeverageTests(unittest.TestCase):
    def test_ranks_and_edge(self):
        fingerprint = {'buckets': {
            'Guard': {'vulnerability': 70}, 'Forward': {'vulnerability': 50}, 'Center': {'vulnerability': 30},
        }}
        guard = transforms.positional_leverage(fingerprint, 'Guard')
        self.assertEqual(guard['rank'], 1)
        self.assertEqual(guard['of'], 3)
        self.assertTrue(guard['is_weakest'])
        self.assertEqual(guard['weakest_bucket'], 'Guard')
        self.assertAlmostEqual(guard['edge_vs_avg'], 30.0)  # 70 - mean(50, 30)

        center = transforms.positional_leverage(fingerprint, 'Center')
        self.assertEqual(center['rank'], 3)
        self.assertFalse(center['is_weakest'])
        self.assertAlmostEqual(center['edge_vs_avg'], -30.0)  # 30 - mean(70, 50)

    def test_empty_fingerprint_returns_empty(self):
        self.assertEqual(transforms.positional_leverage({}, 'Guard'), {})
        self.assertEqual(transforms.positional_leverage({'buckets': {}}, 'Guard'), {})

    def test_unscored_bucket_returns_empty(self):
        fingerprint = {'buckets': {'Guard': {'vulnerability': 70}}}
        self.assertEqual(transforms.positional_leverage(fingerprint, 'Center'), {})


class UsageWeightedEfficiencyTests(unittest.TestCase):
    def test_edge_and_percentile(self):
        group_rate_df = pd.DataFrame({'TS%': [55, 60, 65, 70], 'Usage %': [20, 25, 20, 25]})
        player_values = {'TS%': 70, 'Usage %': 30}
        result = transforms.usage_weighted_efficiency(player_values, group_rate_df)
        self.assertAlmostEqual(result['edge'], 2.25)  # (70 - 62.5) * 0.30
        self.assertAlmostEqual(result['pct'], 100.0)  # highest edge in the group by a clear margin

    def test_missing_values_return_empty(self):
        group_rate_df = pd.DataFrame({'TS%': [55, 60], 'Usage %': [20, 25]})
        self.assertEqual(transforms.usage_weighted_efficiency({'TS%': None, 'Usage %': 30}, group_rate_df), {})
        self.assertEqual(transforms.usage_weighted_efficiency({'TS%': 60, 'Usage %': 30}, pd.DataFrame()), {})


class RimFoulLeverageScoreTests(unittest.TestCase):
    def test_full_weighted_score(self):
        group_rate_df = pd.DataFrame({'FT Rate': [20, 30, 40, 50], '2PT Rate': [40, 50, 60, 70]})
        team_stats_df = pd.DataFrame([{'Team': 'A', 'Def FT Rate': 25}, {'Team': 'B', 'Def FT Rate': 35}, {'Team': 'C', 'Def FT Rate': 45}])
        player_values = {'FT Rate': 45, '2PT Rate': 65}
        result = transforms.rim_foul_leverage_score(player_values, group_rate_df, team_stats_df, 'C')
        self.assertAlmostEqual(result['player_ft_rate_pct'], 75.0)
        self.assertAlmostEqual(result['player_2pt_rate_pct'], 75.0)
        self.assertAlmostEqual(result['opponent_def_ft_rate_pct'], 83.3, places=1)
        self.assertAlmostEqual(result['score'], 78.3, places=1)

    def test_renormalizes_over_missing_components(self):
        group_rate_df = pd.DataFrame({'FT Rate': [20, 30, 40, 50], '2PT Rate': [40, 50, 60, 70]})
        player_values = {'FT Rate': 45, '2PT Rate': 65}
        # No team_stats_df/opponent data at all - only the two player-side
        # components (weights 0.35 + 0.25) should renormalize to a clean 75.0.
        result = transforms.rim_foul_leverage_score(player_values, group_rate_df, pd.DataFrame(), 'C')
        self.assertAlmostEqual(result['score'], 75.0)
        self.assertNotIn('opponent_def_ft_rate_pct', result)

    def test_no_components_returns_empty(self):
        self.assertEqual(transforms.rim_foul_leverage_score({}, pd.DataFrame(), pd.DataFrame(), 'C'), {})


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
        # Efficiency deliberately drops as opponent defense gets tougher
        # (Weak D easiest -> highest TS%, Elite D toughest -> lowest TS%),
        # so slope_vs_defense should come back clearly negative.
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
        self.assertIn('vs Weaker Defenses', result['bucket_means'])
        self.assertIn('vs Top-Tier Defenses', result['bucket_means'])
        self.assertGreater(result['bucket_means']['vs Weaker Defenses']['mean'], result['bucket_means']['vs Top-Tier Defenses']['mean'])

    def test_efg_fallback_when_no_fta(self):
        games = self._player_games().drop(columns=['FTA'])
        games['FGM'] = [12, 11, 9, 10, 6, 7]
        games['3PM'] = [3, 2, 2, 3, 1, 1]
        result = transforms.efficiency_elasticity(games, self._eff_ratings_df(), self._team_stats_df(), 'Mid D')
        self.assertEqual(result['efficiency_label'], 'eFG%')

    def test_insufficient_games_returns_empty(self):
        games = self._player_games().head(3)
        result = transforms.efficiency_elasticity(games, self._eff_ratings_df(), self._team_stats_df(), 'Mid D', min_games=5)
        self.assertEqual(result, {})

    def test_empty_inputs_return_empty(self):
        self.assertEqual(transforms.efficiency_elasticity(pd.DataFrame(), self._eff_ratings_df(), self._team_stats_df(), 'Mid D'), {})


class GameScriptSensitivityTests(unittest.TestCase):
    def test_close_vs_decided_split(self):
        team_games = pd.DataFrame([
            {'Date': '2026-01-01', 'Margin': 20}, {'Date': '2026-01-05', 'Margin': -3},
            {'Date': '2026-01-08', 'Margin': 5}, {'Date': '2026-01-12', 'Margin': -25},
            {'Date': '2026-01-15', 'Margin': 2}, {'Date': '2026-01-19', 'Margin': 30},
        ])
        player_games = pd.DataFrame([
            {'Date': '2026-01-01', 'Points': 10}, {'Date': '2026-01-05', 'Points': 20},
            {'Date': '2026-01-08', 'Points': 22}, {'Date': '2026-01-12', 'Points': 8},
            {'Date': '2026-01-15', 'Points': 18}, {'Date': '2026-01-19', 'Points': 12},
        ])
        result = transforms.game_script_sensitivity(player_games, team_games, stat_col='Points')
        self.assertEqual(result['n_close'], 3)
        self.assertEqual(result['n_decided'], 3)
        self.assertAlmostEqual(result['close_mean'], 20.0)
        self.assertAlmostEqual(result['decided_mean'], 10.0)
        self.assertAlmostEqual(result['sensitivity_index'], 66.7, places=1)

    def test_insufficient_sample_flagged(self):
        team_games = pd.DataFrame([{'Date': '2026-01-01', 'Margin': 2}, {'Date': '2026-01-05', 'Margin': 20}])
        player_games = pd.DataFrame([{'Date': '2026-01-01', 'Points': 10}, {'Date': '2026-01-05', 'Points': 12}])
        result = transforms.game_script_sensitivity(player_games, team_games, stat_col='Points')
        self.assertTrue(result['insufficient_sample'])
        self.assertEqual(result['n_close'], 1)
        self.assertEqual(result['n_decided'], 1)

    def test_empty_inputs_return_empty(self):
        self.assertEqual(transforms.game_script_sensitivity(pd.DataFrame(), pd.DataFrame()), {})


class CompositeMatchupAdvantageTests(unittest.TestCase):
    def test_all_components_present(self):
        result = transforms.composite_matchup_advantage(80, 60, 40, 50)
        self.assertAlmostEqual(result['score'], 61.5)  # .35*80 + .30*60 + .20*40 + .15*50
        self.assertEqual(result['tier'], 'Slight Edge')

    def test_renormalizes_over_missing_component(self):
        result = transforms.composite_matchup_advantage(80, 60, 40, None)
        self.assertAlmostEqual(result['score'], 63.5, places=1)  # (28+18+8) / 0.85

    def test_all_missing_returns_empty(self):
        self.assertEqual(transforms.composite_matchup_advantage(None, None, None, None), {})

    def test_tier_labels_span_range(self):
        self.assertEqual(transforms.composite_matchup_advantage(100, 100, 100, 100)['tier'], 'Strong Edge')
        self.assertEqual(transforms.composite_matchup_advantage(0, 0, 0, 0)['tier'], 'Tough Matchup')


class MatchupProjectionBandTests(unittest.TestCase):
    def test_floor_median_ceiling_ordering_and_multiplier_direction(self):
        values = [10, 12, 14, 16, 18, 20, 22, 24, 26, 28]
        strong = transforms.matchup_projection_band(values, composite_score=100, pace_pctile=100)
        weak = transforms.matchup_projection_band(values, composite_score=0, pace_pctile=0)
        self.assertLess(strong['floor'], strong['median'])
        self.assertLess(strong['median'], strong['ceiling'])
        self.assertGreater(strong['multiplier'], 1.0)
        self.assertLess(weak['multiplier'], 1.0)
        self.assertGreater(strong['median'], weak['median'])
        self.assertEqual(strong['n_games'], 10)

    def test_insufficient_games_returns_empty(self):
        self.assertEqual(transforms.matchup_projection_band([10, 12], 50, 50), {})


class BuildMatchupAdvantageReportTests(unittest.TestCase):
    def test_end_to_end_assembly(self):
        team_stats_df = pd.DataFrame([
            {'Team': 'Weak D', 'Pace': 72, 'Def 2P%': 58, 'Def FT Rate': 40, 'Opp Paint Pts %': 50, 'Def 3PA Rate': 45, 'Def 3P%': 38},
            {'Team': 'Mid D', 'Pace': 68, 'Def 2P%': 50, 'Def FT Rate': 30, 'Opp Paint Pts %': 42, 'Def 3PA Rate': 38, 'Def 3P%': 33},
        ])
        eff_ratings_df = pd.DataFrame([{'Team': 'Weak D', 'Def Rating': 110}, {'Team': 'Mid D', 'Def Rating': 100}])
        positional_summary_df = pd.DataFrame([
            {'Bucket': 'Guard', 'Games': 8, 'Points Allowed': 15.0, 'Points Delta': 3.0},
            {'Bucket': 'Forward', 'Games': 8, 'Points Allowed': 12.0, 'Points Delta': 0.5},
            {'Bucket': 'Center', 'Games': 8, 'Points Allowed': 10.0, 'Points Delta': -2.0},
        ])
        group_rate_df = pd.DataFrame({
            'TS%': [50, 55, 60, 65], 'Usage %': [18, 22, 24, 28],
            'FT Rate': [20, 25, 30, 35], '2PT Rate': [45, 50, 55, 60],
        })
        player_values = {'TS%': 62, 'Usage %': 26, 'FT Rate': 32, '2PT Rate': 58}
        player_games = pd.DataFrame([
            {'Date': '2026-01-01', 'Opponent': 'Mid D', 'Points': 20, 'Rebounds': 5, 'Assists': 3, 'FGA': 18, 'FTA': 3},
            {'Date': '2026-01-04', 'Opponent': 'Weak D', 'Points': 24, 'Rebounds': 4, 'Assists': 2, 'FGA': 17, 'FTA': 5},
            {'Date': '2026-01-08', 'Opponent': 'Mid D', 'Points': 18, 'Rebounds': 6, 'Assists': 4, 'FGA': 16, 'FTA': 2},
            {'Date': '2026-01-11', 'Opponent': 'Weak D', 'Points': 26, 'Rebounds': 5, 'Assists': 3, 'FGA': 19, 'FTA': 4},
            {'Date': '2026-01-15', 'Opponent': 'Mid D', 'Points': 19, 'Rebounds': 7, 'Assists': 2, 'FGA': 17, 'FTA': 3},
            {'Date': '2026-01-18', 'Opponent': 'Weak D', 'Points': 22, 'Rebounds': 5, 'Assists': 5, 'FGA': 18, 'FTA': 4},
        ])
        team_games = pd.DataFrame([
            {'Date': '2026-01-01', 'Margin': 4}, {'Date': '2026-01-04', 'Margin': 18},
            {'Date': '2026-01-08', 'Margin': -6}, {'Date': '2026-01-11', 'Margin': 22},
            {'Date': '2026-01-15', 'Margin': 3}, {'Date': '2026-01-18', 'Margin': -19},
        ])

        report = transforms.build_matchup_advantage_report(
            player_bucket='Guard', player_values=player_values, group_rate_df=group_rate_df,
            player_games=player_games, team_games=team_games, opponent_team='Weak D',
            team_stats_df=team_stats_df, eff_ratings_df=eff_ratings_df,
            positional_summary_df=positional_summary_df, stat_col='Points',
        )

        self.assertIsNotNone(report['composite'].get('score'))
        self.assertIn(report['composite']['tier'], {'Strong Edge', 'Slight Edge', 'Neutral', 'Slight Disadvantage', 'Tough Matchup'})
        self.assertIn('Guard', report['scheme_fingerprint']['buckets'])
        self.assertEqual(report['positional_leverage']['player_bucket'], 'Guard')
        self.assertGreater(report['pace_pct'], 0)
        band = report['projection_band']
        self.assertLessEqual(band['floor'], band['median'])
        self.assertLessEqual(band['median'], band['ceiling'])
        self.assertEqual(report['opponent_team'], 'Weak D')
        self.assertEqual(report['stat_col'], 'Points')


if __name__ == '__main__':
    unittest.main()
