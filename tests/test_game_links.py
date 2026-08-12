"""
Unit tests for the cross-tab game links - the "this stat came from a real
game, open its box score" plumbing that connects Player Search's game log
and the Matchup Analyzer's trend charts to the Game Slate.

The failure mode worth testing for here is a link that navigates to the
WRONG game. That's strictly worse than no link at all, and it's silent:
the destination renders a perfectly good box score for a game the visitor
didn't ask about. Hence the emphasis below on the two id namespaces and on
unresolvable rows being dropped rather than emitted with a null id.

Run with: python3 -m unittest discover -s tests -v
"""
import unittest

import pandas as pd

from data.transforms import game_link_rows, game_link_rows_for_dates
import ui.components as components


def _slate(*rows):
    base = {
        'GameId': '1', 'Date': '2026-01-17', 'Date Display': '01/17/2026',
        'Away': 'UConn', 'Home': 'Michigan', 'Away Abbr': 'CONN', 'Home Abbr': 'MICH',
        'Away Pts': 63.0, 'Home Pts': 69.0, 'Winner': 'Michigan', 'Neutral Site': False,
    }
    return pd.DataFrame([{**base, **r} for r in rows])


class GameLinkRowsTests(unittest.TestCase):
    def test_resolves_by_espn_game_id(self):
        slate = _slate({'GameId': '401856600'})
        log = pd.DataFrame([{'GameId': 401856600, 'Date': '2026-01-17'}])   # int, as the file types it
        links = game_link_rows(log, slate, team='Michigan')
        self.assertEqual(len(links), 1)
        self.assertEqual(links[0]['game_id'], '401856600')

    def test_falls_back_to_date_and_team_for_a_foreign_id_namespace(self):
        """CBBD's gameId has nothing to do with ESPN's. Matching on it
        would either miss or, worse, collide with an unrelated game."""
        slate = _slate({'GameId': '401856600'})
        log = pd.DataFrame([{'GameId': 55512345, 'Date': '2026-01-17'}])
        links = game_link_rows(log, slate, team='Michigan')
        self.assertEqual(len(links), 1)
        self.assertEqual(links[0]['game_id'], '401856600')

    def test_date_fallback_requires_the_team_to_scope_it(self):
        """A date alone matches ~150 games in college basketball."""
        slate = _slate({'GameId': '401856600'})
        log = pd.DataFrame([{'GameId': 55512345, 'Date': '2026-01-17'}])
        self.assertEqual(game_link_rows(log, slate), [])

    def test_team_spelling_from_another_source_still_resolves(self):
        """The slate speaks ESPN ('UConn'); the Matchup Analyzer speaks
        CBBD ('Connecticut')."""
        slate = _slate({'GameId': '9'})
        log = pd.DataFrame([{'GameId': 'cbbd-1', 'Date': '2026-01-17'}])
        links = game_link_rows(log, slate, team='Connecticut')
        self.assertEqual(len(links), 1)
        self.assertEqual(links[0]['opponent'], 'Michigan')

    def test_unresolvable_rows_are_dropped_not_emitted_with_a_null_id(self):
        slate = _slate({'GameId': '1'})
        log = pd.DataFrame([{'GameId': 'nope', 'Date': '1999-01-01'}])
        self.assertEqual(game_link_rows(log, slate, team='Michigan'), [])

    def test_duplicate_rows_for_one_game_yield_one_link(self):
        slate = _slate({'GameId': '1'})
        log = pd.DataFrame([
            {'GameId': 1, 'Date': '2026-01-17'},
            {'GameId': 1, 'Date': '2026-01-17'},
        ])
        self.assertEqual(len(game_link_rows(log, slate, team='Michigan')), 1)

    def test_limit_keeps_the_most_recent_games(self):
        slate = _slate(
            {'GameId': '1', 'Date': '2026-01-01'},
            {'GameId': '2', 'Date': '2026-01-02'},
            {'GameId': '3', 'Date': '2026-01-03'},
        )
        log = pd.DataFrame([{'GameId': i, 'Date': f'2026-01-0{i}'} for i in (1, 2, 3)])
        links = game_link_rows(log, slate, team='Michigan', limit=2)
        self.assertEqual([e['game_id'] for e in links], ['2', '3'])

    def test_empty_inputs_are_safe(self):
        self.assertEqual(game_link_rows(pd.DataFrame(), _slate({}), team='Michigan'), [])
        self.assertEqual(game_link_rows(pd.DataFrame([{'GameId': 1}]), pd.DataFrame()), [])
        self.assertEqual(game_link_rows(None, None), [])


class LinkLabelTests(unittest.TestCase):
    def _link(self, team, **slate_over):
        slate = _slate(slate_over)
        log = pd.DataFrame([{'GameId': slate.iloc[0]['GameId'], 'Date': slate.iloc[0]['Date']}])
        return game_link_rows(log, slate, team=team)[0]

    def test_away_game_uses_an_at_sign_and_the_opponents_abbreviation(self):
        self.assertEqual(self._link('UConn')['label'], '1/17 @MICH')

    def test_home_game_uses_vs_with_a_space(self):
        # 'vsMICH' is unreadable; '@MICH' closed up is fine.
        self.assertEqual(self._link('Michigan')['label'], '1/17 vs CONN')

    def test_neutral_site_is_never_an_away_game(self):
        self.assertEqual(self._link('UConn', **{'Neutral Site': True})['label'], '1/17 vs MICH')

    def test_win_loss_is_from_the_subject_teams_point_of_view(self):
        self.assertTrue(self._link('Michigan')['won'])
        self.assertFalse(self._link('UConn')['won'])

    def test_unplayed_game_has_no_win_flag_and_no_score_in_the_tooltip(self):
        link = self._link('Michigan', Winner=None, **{'Away Pts': float('nan'), 'Home Pts': float('nan')})
        self.assertIsNone(link['won'])
        self.assertNotIn('(', link['help'])

    def test_tooltip_carries_the_full_matchup_and_score(self):
        self.assertIn('UConn @ Michigan (63-69)', self._link('Michigan')['help'])

    def test_missing_abbreviation_falls_back_to_the_school_name(self):
        link = self._link('Michigan', **{'Away Abbr': None})
        self.assertEqual(link['label'], '1/17 vs UCON')

    def test_label_never_contains_nan(self):
        link = self._link('Michigan', **{'Away Abbr': float('nan')})
        self.assertNotIn('nan', link['label'].lower())


class GameLinksForDatesTests(unittest.TestCase):
    def test_resolves_a_date_series_scoped_to_one_team(self):
        slate = _slate(
            {'GameId': '1', 'Date': '2026-01-17'},
            {'GameId': '2', 'Date': '2026-01-20', 'Away': 'Duke', 'Home': 'Michigan'},
        )
        links = game_link_rows_for_dates(['2026-01-17', '2026-01-20'], slate, 'Michigan')
        self.assertEqual([e['game_id'] for e in links], ['1', '2'])

    def test_a_date_the_team_did_not_play_is_skipped(self):
        slate = _slate({'GameId': '1', 'Date': '2026-01-17'})
        self.assertEqual(game_link_rows_for_dates(['2026-02-01'], slate, 'Michigan'), [])

    def test_requires_a_team(self):
        self.assertEqual(game_link_rows_for_dates(['2026-01-17'], _slate({}), None), [])

    def test_unknown_team_resolves_to_nothing_rather_than_a_wrong_game(self):
        self.assertEqual(game_link_rows_for_dates(['2026-01-17'], _slate({}), 'Nowhere State'), [])


class _FakeState(dict):
    """st.session_state stands in as a dict - the callbacks under test only
    ever assign, read and pop."""


class NavigationCallbackTests(unittest.TestCase):
    def _run(self, fn, *args, initial=None):
        state = _FakeState(initial or {})
        original = components.st
        components.st = type('S', (), {'session_state': state})()
        try:
            fn(*args)
        finally:
            components.st = original
        return state

    def test_open_box_score_lands_on_the_slate_with_the_game_and_date(self):
        state = self._run(components.open_box_score, 2026, '401856600', '2026-04-06')
        self.assertEqual(state['active_tab'], 'GAME SLATE')
        self.assertEqual(state['gs_box_game'], '401856600')
        self.assertEqual(state['_sticky__gs_season'], 2026)
        self.assertEqual(str(state['_sticky__gs_date']), '2026-04-06')

    def test_open_box_score_clears_filters_that_could_hide_the_day(self):
        """Arriving here names ONE game; a conference filter left over from
        earlier would show the box above an empty, baffling slate."""
        state = self._run(
            components.open_box_score, 2026, '1', '2026-04-06',
            initial={'_sticky__gs_conferences': ['Big Ten'], '_sticky__gs_ranked_only': True,
                     '_sticky__gs_page': '25-48 of 155'},
        )
        self.assertEqual(state['_sticky__gs_conferences'], [])
        self.assertFalse(state['_sticky__gs_ranked_only'])
        self.assertNotIn('_sticky__gs_page', state)

    def test_open_box_score_survives_a_malformed_date(self):
        state = self._run(components.open_box_score, 2026, '1', 'not-a-date')
        self.assertEqual(state['gs_box_game'], '1')
        self.assertNotIn('_sticky__gs_date', state)

    def test_open_slate_date_navigates_without_opening_a_box(self):
        state = self._run(
            components.open_slate_date, 2026, '2026-02-07',
            initial={'gs_box_game': '999'},
        )
        self.assertEqual(state['active_tab'], 'GAME SLATE')
        self.assertNotIn('gs_box_game', state)
        self.assertEqual(str(state['_sticky__gs_date']), '2026-02-07')


class NavHistoryTests(unittest.TestCase):
    """Back has to restore the exact state a jump overwrote, not just the
    tab. A jump seeds the destination's pickers and clears the origin's
    filters; returning to a tab whose controls have silently moved is worse
    than not offering Back at all."""

    def _state(self, initial=None):
        state = _FakeState(initial or {})
        components.st = type('S', (), {'session_state': state})()
        return state

    def setUp(self):
        self._original_st = components.st

    def tearDown(self):
        components.st = self._original_st

    def test_back_restores_the_tab_and_the_overwritten_values(self):
        state = self._state({
            'active_tab': 'PLAYER SEARCH',
            '_sticky__ma_player_team': 'Duke',
        })
        components.switch_tab('MATCHUP ANALYZER', ma_player_team='Kansas')
        self.assertEqual(state['active_tab'], 'MATCHUP ANALYZER')
        self.assertEqual(state['_sticky__ma_player_team'], 'Kansas')

        components.go_back()
        self.assertEqual(state['active_tab'], 'PLAYER SEARCH')
        self.assertEqual(state['_sticky__ma_player_team'], 'Duke')

    def test_a_key_that_did_not_exist_is_deleted_again_not_set_to_none(self):
        """A None left behind would read as a real remembered value to the
        sticky wrappers, which check membership rather than nullness."""
        state = self._state({'active_tab': 'PLAYER SEARCH'})
        components.switch_tab('MATCHUP ANALYZER', ma_def_team='Kansas')
        self.assertIn('_sticky__ma_def_team', state)
        components.go_back()
        self.assertNotIn('_sticky__ma_def_team', state)

    def test_back_through_a_box_score_jump_clears_the_open_box(self):
        state = self._state({'active_tab': 'PLAYER SEARCH'})
        components.open_box_score(2026, '401856600', '2026-04-06')
        self.assertEqual(state['gs_box_game'], '401856600')
        components.go_back()
        self.assertEqual(state['active_tab'], 'PLAYER SEARCH')
        self.assertNotIn('gs_box_game', state)

    def test_a_box_jump_records_exactly_one_entry_not_two(self):
        """open_box_score delegates to switch_tab; only one of them may
        push, or a single click would need two Backs to undo."""
        state = self._state({'active_tab': 'PLAYER SEARCH'})
        components.open_box_score(2026, '1', '2026-04-06')
        self.assertEqual(len(state['_nav_stack']), 1)

    def test_history_nests(self):
        state = self._state({'active_tab': 'MATCHUP ANALYZER'})
        components.open_box_score(2026, '1', '2026-04-06')
        components.switch_tab('PLAYER SEARCH', ps_team='Michigan')
        self.assertEqual(len(state['_nav_stack']), 2)
        components.go_back()
        self.assertEqual(state['active_tab'], 'GAME SLATE')
        components.go_back()
        self.assertEqual(state['active_tab'], 'MATCHUP ANALYZER')
        self.assertEqual(state['_nav_stack'], [])

    def test_back_on_an_empty_stack_is_a_no_op(self):
        state = self._state({'active_tab': 'PLAYER SEARCH'})
        components.go_back()
        self.assertEqual(state['active_tab'], 'PLAYER SEARCH')

    def test_history_is_depth_capped(self):
        state = self._state({'active_tab': 'PLAYER SEARCH'})
        for i in range(components._NAV_MAX_DEPTH + 5):
            components.switch_tab('MATCHUP ANALYZER', ma_season=i)
        self.assertEqual(len(state['_nav_stack']), components._NAV_MAX_DEPTH)

    def test_a_manual_tab_change_drops_the_history(self):
        """Otherwise Back lingers after hand navigation and sends someone
        somewhere they never asked to go."""
        state = self._state({'active_tab': 'PLAYER SEARCH'})
        components.switch_tab('MATCHUP ANALYZER', ma_season=2026)
        components.sync_nav_history()             # the run right after the jump
        self.assertEqual(len(state['_nav_stack']), 1)

        state['active_tab'] = 'LIVE ODDS'         # user clicks a tab by hand
        components.sync_nav_history()
        self.assertEqual(state['_nav_stack'], [])

    def test_a_rerun_on_the_same_tab_keeps_the_history(self):
        state = self._state({'active_tab': 'PLAYER SEARCH'})
        components.switch_tab('MATCHUP ANALYZER', ma_season=2026)
        components.sync_nav_history()
        components.sync_nav_history()             # an ordinary widget rerun
        self.assertEqual(len(state['_nav_stack']), 1)


class ChartPointLinkTests(unittest.TestCase):
    """The invisible hit strips laid over a trend chart's data points."""

    def _capture(self, entries):
        calls = []
        markdown = []

        class _Ctx:
            def __enter__(self_inner):
                return self_inner

            def __exit__(self_inner, *a):
                return False

        st_mod = components.st
        originals = (st_mod.container, st_mod.columns, st_mod.button, st_mod.markdown)
        st_mod.container = lambda *a, **k: _Ctx()
        st_mod.columns = lambda n, **k: [_Ctx() for _ in range(n)]
        st_mod.button = lambda *a, **k: calls.append((a, k))
        st_mod.markdown = lambda *a, **k: markdown.append(a[0] if a else '')
        drawn = []
        try:
            components.render_trend_with_point_links(
                lambda: drawn.append(True), entries, 2026, 'plr_Points', 150,
            )
        finally:
            st_mod.container, st_mod.columns, st_mod.button, st_mod.markdown = originals
        return calls, markdown, drawn

    def _entry(self, i):
        return {'game_id': f"g{i}", 'date': f"2026-01-{i + 1:02d}", 'help': f"Box {i}"}

    def test_one_strip_per_resolvable_point_opening_its_own_game(self):
        calls, _, _ = self._capture([self._entry(0), self._entry(1)])
        self.assertEqual([k['args'] for _, k in calls], [
            (2026, 'g0', '2026-01-01'), (2026, 'g1', '2026-01-02'),
        ])
        self.assertTrue(all(k['on_click'] is components.open_box_score for _, k in calls))

    def test_an_unresolvable_point_still_consumes_its_column(self):
        """Skipping the column entirely would slide every later strip onto
        the wrong dot - the alignment depends on column index matching
        point index exactly."""
        calls, _, _ = self._capture([self._entry(0), None, self._entry(2)])
        self.assertEqual(len(calls), 2)
        self.assertEqual([k['args'][1] for _, k in calls], ['g0', 'g2'])

    def test_the_chart_still_renders_when_no_point_resolves(self):
        calls, _, drawn = self._capture([None, None])
        self.assertEqual(calls, [])
        self.assertEqual(drawn, [True])

    def test_the_chart_is_drawn_before_the_overlay(self):
        _, _, drawn = self._capture([self._entry(0)])
        self.assertEqual(drawn, [True])

    def test_height_is_emitted_as_a_percentage_of_the_viewbox_width(self):
        """The chart is width:100%/height:auto over a fixed viewBox, so the
        overlay's height can only be expressed relative to width."""
        _, markdown, _ = self._capture([self._entry(0)])
        style = [m for m in markdown if 'padding-bottom' in str(m)]
        self.assertEqual(len(style), 1)
        self.assertIn(f"{150 / 860 * 100:.4f}%", style[0])
        self.assertIn('.st-key-cpl_row_plr_Points', style[0])


class GameLinkButtonTests(unittest.TestCase):
    def _capture(self, entries):
        calls = []

        class _Ctx:
            def __enter__(self_inner):
                return self_inner

            def __exit__(self_inner, *a):
                return False

        st_mod = components.st
        originals = (st_mod.container, st_mod.columns, st_mod.button, st_mod.caption)
        st_mod.container = lambda *a, **k: _Ctx()
        st_mod.columns = lambda n, **k: [_Ctx() for _ in range(n)]
        st_mod.caption = lambda *a, **k: None
        st_mod.button = lambda *a, **k: calls.append((a, k))
        try:
            components.render_game_links(entries, 2026, 'ps_boxlink')
        finally:
            st_mod.container, st_mod.columns, st_mod.button, st_mod.caption = originals
        return calls

    def test_key_carries_the_win_loss_tone_the_stylesheet_targets(self):
        """The tint is applied via `st-key-gl_<tone>_` substring selectors -
        verified in a real browser, since per-widget key classes are not
        documented API. If this token changes, the tint silently dies."""
        calls = self._capture([
            {'game_id': '1', 'label': '1/17 vs A', 'won': True, 'date': '2026-01-17'},
            {'game_id': '2', 'label': '1/20 @B', 'won': False, 'date': '2026-01-20'},
            {'game_id': '3', 'label': '1/22 vs C', 'won': None, 'date': '2026-01-22'},
        ])
        self.assertEqual([k['key'] for _, k in calls], [
            'gl_w_ps_boxlink_1', 'gl_l_ps_boxlink_2', 'gl_n_ps_boxlink_3',
        ])

    def test_each_button_opens_its_own_game(self):
        calls = self._capture([{'game_id': '77', 'label': 'x', 'won': True, 'date': '2026-01-17'}])
        (_, kw), = calls
        self.assertIs(kw['on_click'], components.open_box_score)
        self.assertEqual(kw['args'], (2026, '77', '2026-01-17'))

    def test_no_entries_renders_nothing_at_all(self):
        self.assertEqual(self._capture([]), [])


if __name__ == '__main__':
    unittest.main()
