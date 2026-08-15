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

    def test_no_canonical_list_keeps_the_box_files_own_names(self):
        """An ABSENT canonical list must not be treated as "every name is
        unresolvable".

        This is the whole historical-season bug: `load_espn_teams` was
        standings-only, the standings payload is empty for a season that
        isn't the current one, and mapping every row through an empty list
        turned a fully-downloaded 196,589-row box file into an empty
        DataFrame - which Player Search then reported as "no box-score data
        available for this season yet".

        Distinct from test_unresolvable_team_name_dropped above: a name
        that fails against a REAL list is genuinely unresolvable and still
        gets dropped. This case has no list to fail against.
        """
        raw = pd.DataFrame([_raw_box_row(TeamRaw='Duke', OpponentRaw='North Carolina')])
        out = loaders._resolve_espn_box_team_names(raw, [])
        self.assertEqual(len(out), 1, "an empty canonical list must not empty the box file")
        self.assertEqual(out.iloc[0]['Team'], 'Duke')
        self.assertEqual(out.iloc[0]['Opponent'], 'North Carolina')

    def test_no_canonical_list_still_drops_dnp_rows(self):
        """The fallback path above must not skip the rest of the cleanup."""
        raw = pd.DataFrame([_raw_box_row(GameId=1, Minutes=30), _raw_box_row(GameId=2, Minutes=0)])
        out = loaders._resolve_espn_box_team_names(raw, [])
        self.assertEqual(len(out), 1)
        self.assertEqual(out.iloc[0]['GameId'], 1)


def _sched_row(**overrides):
    """One schedule-parquet row, in the file's own column naming."""
    row = {
        'home_location': 'Duke', 'home_display_name': 'Duke Blue Devils', 'home_id': 150,
        'home_conference_id': 2, 'home_color': '001a57', 'home_alternate_color': 'ffffff',
        'away_location': 'North Carolina', 'away_display_name': 'North Carolina Tar Heels',
        'away_id': 153, 'away_conference_id': 2, 'away_color': '7bafd4',
        'away_alternate_color': '13294b',
        'groups_is_conference': True, 'groups_id': 2, 'groups_short_name': 'ACC',
    }
    row.update(overrides)
    return row


class EspnTeamsFromScheduleTests(unittest.TestCase):
    """
    The standings-free team list that makes historical seasons work.
    Patches _season_schedule rather than hitting the network, the same way
    the rest of this file stays offline.
    """

    def _teams(self, rows):
        original = loaders._season_schedule
        loaders._season_schedule = lambda season: pd.DataFrame(rows)
        try:
            return loaders._espn_teams_from_schedule(2023)
        finally:
            loaders._season_schedule = original

    def test_builds_the_team_list_off_both_sides_of_the_schedule(self):
        out = self._teams([_sched_row()])
        self.assertEqual(sorted(out['Team']), ['Duke', 'North Carolina'])
        self.assertEqual(
            list(out.columns), ['Team', 'DisplayName', 'EspnId', 'Conference', 'Color', 'AltColor'])

    def test_team_name_is_location_never_display_name(self):
        """The exact bug HANDOFF.md records: a displayName-keyed list
        ("Duke Blue Devils") resolves NOTHING against the box file's
        location-keyed team_location column."""
        out = self._teams([_sched_row()])
        self.assertIn('Duke', set(out['Team']))
        self.assertNotIn('Duke Blue Devils', set(out['Team']))
        self.assertEqual(out[out['Team'] == 'Duke'].iloc[0]['DisplayName'], 'Duke Blue Devils')

    def test_non_di_opponent_excluded(self):
        """Carrying no ESPN conference id is what makes a team non-D-I -
        the same test _normalize_slate already uses for 'D-I Matchup'.
        Without it, every exhibition opponent lands in the team picker."""
        out = self._teams([
            _sched_row(),
            _sched_row(away_location='Tiny Bible College', away_conference_id=None,
                       away_display_name='Tiny Bible College Saints', away_id=99999),
        ])
        self.assertNotIn('Tiny Bible College', set(out['Team']))

    def test_one_row_per_school_with_colors_normalized(self):
        out = self._teams([_sched_row(), _sched_row(), _sched_row()])
        self.assertEqual(len(out), 2)
        self.assertEqual(out[out['Team'] == 'Duke'].iloc[0]['Color'], '#001a57')

    def test_conference_names_come_from_the_schedule_file_itself(self):
        out = self._teams([_sched_row()])
        self.assertEqual(set(out['Conference']), {'ACC'})

    def test_empty_schedule_returns_empty_rather_than_raising(self):
        original = loaders._season_schedule
        loaders._season_schedule = lambda season: pd.DataFrame()
        try:
            self.assertTrue(loaders._espn_teams_from_schedule(2023).empty)
        finally:
            loaders._season_schedule = original


class LoadEspnTeamsFallbackTests(unittest.TestCase):
    """load_espn_teams prefers the live standings payload and falls back to
    the schedule file only when that payload has nothing - so the current
    season's behavior is untouched."""

    def _load(self, standings, sched_rows):
        orig_standings, orig_sched = loaders._safe_standings, loaders._season_schedule
        loaders._safe_standings = lambda season: standings
        loaders._season_schedule = lambda season: pd.DataFrame(sched_rows)
        # load_espn_teams is @st.cache_data(ttl=86400)-memoized ON SEASON,
        # so without this every case after the first would be served the
        # first one's result for season 2023 and pass or fail for the
        # wrong reason.
        loaders.load_espn_teams.clear()
        try:
            return loaders.load_espn_teams(2023)
        finally:
            loaders._safe_standings, loaders._season_schedule = orig_standings, orig_sched
            loaders.load_espn_teams.clear()

    _STANDINGS = {'children': [{
        'isConference': True, 'name': 'Atlantic Coast Conference',
        'standings': {'entries': [
            {'team': {'location': 'Duke', 'displayName': 'Duke Blue Devils',
                      'id': '150', 'color': '001a57', 'alternateColor': 'ffffff'}}]},
    }]}

    def test_standings_payload_wins_when_present(self):
        out = self._load(self._STANDINGS, [_sched_row()])
        self.assertEqual(list(out['Team']), ['Duke'])
        self.assertEqual(out.iloc[0]['Conference'], 'Atlantic Coast Conference')

    def test_falls_back_to_the_schedule_when_standings_is_empty(self):
        out = self._load({}, [_sched_row()])
        self.assertEqual(sorted(out['Team']), ['Duke', 'North Carolina'])

    def test_both_sources_empty_returns_empty(self):
        self.assertTrue(self._load({}, []).empty)


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
