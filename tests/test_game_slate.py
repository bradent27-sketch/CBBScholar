"""
Unit tests for the Game Slate (data.loaders' slate section + the card
renderer in ui/tabs/game_slate.py).

These assert on RENDERED HTML, which is unusual for this codebase and is
deliberate: the card's requirements are visual, and the important ones all
fail SILENTLY. A card printing "nan" where a score goes still renders fine
and raises nothing; a tie that dims both teams looks like a normal game;
a mixed-content logo URL just never appears, with no error anywhere. None
of those are catchable by a test that only checks the function returns.

Fixtures build score columns as FLOAT WITH NaN, matching what pandas
actually hands the renderer (an int column holding any missing value is
promoted to float64 and None becomes NaN) - not None, which would let the
`NaN is not None` trap regress undetected.

Run with: python3 -m unittest discover -s tests -v
"""
import unittest

import pandas as pd

import data.loaders as loaders
from ui.tabs import game_slate


def _raw_game(**overrides):
    """A row shaped like hoopR's published schedule file - the input
    _normalize_slate_frame actually consumes."""
    row = {
        'game_id': 401856600, 'id': 401856600,
        'date': '2026-04-07T00:50Z', 'start_date': '2026-04-07T00:50Z',
        'time_valid': True, 'neutral_site': True,
        'venue_full_name': 'Lucas Oil Stadium',
        'status_type_name': 'STATUS_FINAL', 'status_type_state': 'post',
        'status_type_completed': True, 'status_type_short_detail': 'Final',
        'season_type': 3, 'notes_headline': None, 'broadcast': 'TBS',
        'groups_id': 7.0, 'groups_short_name': 'Big Ten', 'groups_is_conference': True,
        'home_location': 'Michigan', 'home_display_name': 'Michigan Wolverines',
        'home_abbreviation': 'MICH', 'home_color': '00274c',
        'home_logo': 'https://a.espncdn.com/i/teamlogos/ncaa/500/130.png',
        'home_conference_id': 7.0, 'home_score': 69.0, 'home_winner': True,
        'home_current_rank': 1.0,
        'away_location': 'UConn', 'away_display_name': 'UConn Huskies',
        'away_abbreviation': 'CONN', 'away_color': '0c2340',
        'away_logo': 'https://a.espncdn.com/i/teamlogos/ncaa/500/41.png',
        'away_conference_id': 4.0, 'away_score': 63.0, 'away_winner': False,
        'away_current_rank': 2.0,
    }
    row.update(overrides)
    return row


def _normalize(*rows, conf_map=None):
    return loaders._normalize_slate_frame(pd.DataFrame(list(rows)), conf_map=conf_map or {})


def _card(row, idx=0, dark_mode=True):
    return game_slate._card_html(idx, row, dark_mode)


class NormalizeSlateFrameTests(unittest.TestCase):
    def test_played_game_scores_and_winner(self):
        df = _normalize(_raw_game())
        r = df.iloc[0]
        self.assertTrue(r['Played'])
        self.assertEqual(r['Home Pts'], 69)
        self.assertEqual(r['Away Pts'], 63)
        self.assertEqual(r['Winner'], 'Michigan')
        # 00:50Z is the evening of the 6th in Central - see
        # test_date_is_the_local_day_not_the_UTC_slice.
        self.assertEqual(r['Date'], '2026-04-06')
        self.assertEqual(r['Date Display'], '04/06/2026')

    def test_scheduled_game_has_no_score_despite_espn_sending_zero(self):
        """ESPN sends score "0" for a game that hasn't tipped, not null -
        so the loader must gate on STATUS, never on score presence."""
        df = _normalize(_raw_game(
            status_type_name='STATUS_SCHEDULED', status_type_state='pre',
            status_type_completed=False, status_type_short_detail='7:00 PM CT',
            home_score=0, away_score=0, home_winner=None, away_winner=None,
        ))
        r = df.iloc[0]
        self.assertFalse(r['Played'])
        self.assertTrue(pd.isna(r['Home Pts']))
        self.assertTrue(pd.isna(r['Away Pts']))
        self.assertIsNone(r['Winner'])

    def test_postponed_game_is_not_a_zero_zero_final(self):
        """A postponed game reaches a 'post' state carrying 0-0 (18 such
        rows in the real 2026 file) and must not render as a real final."""
        df = _normalize(_raw_game(
            status_type_name='STATUS_POSTPONED', status_type_state='post',
            home_score=0, away_score=0, home_winner=None, away_winner=None,
        ))
        r = df.iloc[0]
        self.assertFalse(r['Played'])
        self.assertTrue(pd.isna(r['Home Pts']))
        self.assertIsNone(r['Winner'])

    def test_live_game_shows_running_score_but_no_winner(self):
        df = _normalize(_raw_game(
            status_type_name='STATUS_IN_PROGRESS', status_type_state='in',
            status_type_short_detail='2nd Half 4:21',
            home_score=41, away_score=38, home_winner=None, away_winner=None,
        ))
        r = df.iloc[0]
        self.assertTrue(r['Live'])
        self.assertFalse(r['Played'])
        self.assertEqual(r['Home Pts'], 41)
        self.assertIsNone(r['Winner'])

    def test_unranked_sentinel_99_becomes_missing(self):
        """ESPN publishes rank 99 for an unranked team rather than omitting
        the field - 5,744 of the real 2026 file's 6,318 rows carry it."""
        df = _normalize(_raw_game(home_current_rank=99.0, away_current_rank=3.0))
        r = df.iloc[0]
        self.assertTrue(pd.isna(r['Home Rank']))
        self.assertEqual(r['Away Rank'], 3)

    def test_date_is_the_local_day_not_the_UTC_slice(self):
        """A night game is already the NEXT day in UTC. Slicing the raw
        timestamp gave the 2026 national championship (00:50Z) a date of
        04/07 while its own tip line read "Monday at 7:50 PM CDT" - and
        04/07 was a Tuesday. Caught on real data, not in review."""
        df = _normalize(_raw_game(start_date='2026-04-07T00:50Z'))
        r = df.iloc[0]
        self.assertEqual(r['Date'], '2026-04-06')
        self.assertEqual(r['Date Display'], '04/06/2026')
        self.assertTrue(r['Tipoff Long'].startswith('Monday'))

    def test_tbd_game_keeps_the_raw_date_rather_than_shifting_back_a_day(self):
        """The inverse trap: a TBD game's midnight-UTC placeholder converts
        to the PREVIOUS evening in Central (six hours back, so it lands at
        6pm the day before), which would move a Saturday game to Friday."""
        df = _normalize(_raw_game(start_date='2026-01-17T00:00Z', time_valid=False))
        r = df.iloc[0]
        self.assertEqual(r['Date'], '2026-01-17')
        self.assertTrue(r['Time TBD'])
        self.assertIn('TBD', r['Tipoff Long'])

    def test_games_order_by_real_time_not_the_display_string(self):
        """"Mon 9:00 AM" sorts AFTER "Mon 10:00 AM" as text ('9' > '1')."""
        df = _normalize(
            _raw_game(game_id=1, start_date='2026-01-17T22:00Z'),   # 4:00 PM CST
            _raw_game(game_id=2, start_date='2026-01-17T14:00Z'),   # 8:00 AM CST
            _raw_game(game_id=3, start_date='2026-01-17T16:00Z'),   # 10:00 AM CST
        )
        self.assertEqual(list(df['GameId']), ['2', '3', '1'])

    def test_di_matchup_flag_needs_both_conference_ids(self):
        df = _normalize(
            _raw_game(game_id=1),
            _raw_game(game_id=2, away_location='Fairleigh Dickinson', away_conference_id=None),
        )
        self.assertTrue(bool(df.loc[df['GameId'] == '1', 'D-I Matchup'].iloc[0]))
        self.assertFalse(bool(df.loc[df['GameId'] == '2', 'D-I Matchup'].iloc[0]))

    def test_conference_labels_resolve_through_the_id_map(self):
        df = _normalize(_raw_game(), conf_map={7: 'Big Ten', 4: 'Big East'})
        r = df.iloc[0]
        self.assertEqual(r['Home Conf'], 'Big Ten')
        self.assertEqual(r['Away Conf'], 'Big East')

    def test_missing_columns_do_not_crash(self):
        """The published file's schema genuinely drifts between seasons -
        broadcast/highlights only exist in 2025-26, venue_capacity only in
        2023, away_non_div1_team only in 2025."""
        row = _raw_game()
        for gone in ('broadcast', 'notes_headline', 'home_current_rank', 'away_current_rank'):
            row.pop(gone)
        df = _normalize(row)
        self.assertEqual(len(df), 1)
        self.assertTrue(pd.isna(df.iloc[0]['Home Rank']))

    def test_malformed_color_is_rejected_not_interpolated(self):
        df = _normalize(_raw_game(home_color='red; } body { display:none', away_color=None))
        r = df.iloc[0]
        self.assertIsNone(r['Home Color'])
        self.assertIsNone(r['Away Color'])

    def test_matchup_string_uses_vs_for_neutral_site(self):
        neutral = _normalize(_raw_game(neutral_site=True)).iloc[0]
        home = _normalize(_raw_game(neutral_site=False)).iloc[0]
        self.assertEqual(neutral['Matchup'], 'UConn vs Michigan')
        self.assertEqual(home['Matchup'], 'UConn @ Michigan')

    def test_logo_variants_and_https(self):
        df = _normalize(_raw_game(home_logo='http://a.espncdn.com/i/teamlogos/ncaa/500/130.png'))
        r = df.iloc[0]
        self.assertTrue(r['Home Logo'].startswith('https://'))
        self.assertIn('/500-dark/', r['Home Logo Dark'])
        self.assertIn('/500/', r['Home Logo'])

    def test_dark_variant_is_none_when_pattern_absent(self):
        self.assertIsNone(loaders.dark_logo_variant('https://example.com/logo.png'))
        self.assertIsNone(loaders.dark_logo_variant(None))


class TipoffFormattingTests(unittest.TestCase):
    def test_long_form_names_the_weekday_in_et(self):
        # 2026-04-07T00:50Z is Monday evening in Eastern, not Tuesday.
        self.assertEqual(loaders.format_tipoff('2026-04-07T00:50Z', long=True), 'Monday at 7:50 PM CDT')

    def test_leading_zero_stripped(self):
        self.assertIn(' 7:50 PM', loaders.format_tipoff('2026-04-07T00:50Z'))
        self.assertNotIn('07:50', loaders.format_tipoff('2026-04-07T00:50Z'))

    def test_tbd_never_prints_its_placeholder_timestamp(self):
        out = loaders.format_tipoff('2026-01-17T00:00Z', tbd=True, long=True)
        self.assertIn('TBD', out)
        self.assertNotIn(':', out.replace('·', ''))

    def test_tbd_weekday_comes_from_the_raw_date_not_a_tz_conversion(self):
        """Midnight UTC converts to the PREVIOUS EVENING in Eastern, so a
        Saturday game would otherwise read 'Friday'."""
        self.assertTrue(loaders.format_tipoff('2026-01-17T00:00Z', tbd=True, long=True).startswith('Saturday'))

    def test_times_are_central_and_labelled_with_the_zone_in_force(self):
        """A basketball season straddles the DST boundary, so one hardcoded
        label would be wrong for part of every season: November tips are
        CST, March/April tournament games are CDT."""
        november = loaders.format_tipoff('2025-11-04T01:00Z')      # 7:00 PM CST
        april = loaders.format_tipoff('2026-04-07T00:50Z')         # 7:50 PM CDT
        self.assertEqual(november, 'Mon 7:00 PM CST')
        self.assertEqual(april, 'Mon 7:50 PM CDT')

    def test_display_tz_is_central_not_eastern(self):
        local, label = loaders._to_display_tz(
            __import__('datetime').datetime.fromisoformat('2026-04-07T00:50+00:00'))
        self.assertEqual(label, 'CDT')
        self.assertEqual(local.hour, 19)     # 7pm, not 8pm

    def test_unparseable_input_degrades_quietly(self):
        self.assertEqual(loaders.format_tipoff('not a date'), '')
        self.assertEqual(loaders._format_slate_date('not a date'), 'not a date')


class CardMarkupTests(unittest.TestCase):
    def test_played_game_marks_one_winner_and_one_loser(self):
        row = _normalize(_raw_game()).iloc[0]
        out = _card(row)
        self.assertEqual(out.count('gs-won'), 1)
        self.assertEqual(out.count('gs-lost'), 1)
        self.assertEqual(out.count('gs-win-flag'), 1)
        self.assertIn(">69<", out)
        self.assertIn(">63<", out)
        # The date and the weekday must agree: 04/06/2026 IS the Monday.
        self.assertIn('04/06/2026', out)
        self.assertIn('Monday at 7:50 PM CDT', out)

    def test_keyed_style_binds_both_team_colors(self):
        row = _normalize(_raw_game()).iloc[0]
        out = _card(row, idx=3)
        self.assertIn('.st-key-gs_card_3{--gs-a:#0c2340;--gs-b:#00274c;}', out)

    def test_unplayed_game_emits_no_score_node_and_never_the_string_nan(self):
        row = _normalize(_raw_game(
            status_type_name='STATUS_SCHEDULED', status_type_state='pre',
            home_score=0, away_score=0, home_winner=None, away_winner=None,
        )).iloc[0]
        out = _card(row)
        self.assertNotIn('gs-score', out)
        self.assertNotIn('nan', out.lower())
        self.assertNotIn('gs-won', out)
        self.assertNotIn('gs-lost', out)

    def test_tie_dims_neither_team(self):
        row = _normalize(_raw_game(
            home_score=70, away_score=70, home_winner=False, away_winner=False,
        )).iloc[0]
        out = _card(row)
        self.assertNotIn('gs-won', out)
        self.assertNotIn('gs-lost', out)
        self.assertEqual(out.count('gs-score'), 2)

    def test_postponed_game_says_so_instead_of_a_tip_time(self):
        row = _normalize(_raw_game(
            status_type_name='STATUS_POSTPONED', status_type_state='post',
            status_type_short_detail='Postponed',
            home_score=0, away_score=0, home_winner=None, away_winner=None,
        )).iloc[0]
        out = _card(row)
        self.assertIn('Postponed', out)
        self.assertNotIn('gs-score', out)

    def test_ampersands_in_team_and_venue_names_are_escaped(self):
        row = _normalize(_raw_game(
            home_location='Texas A&M', venue_full_name='M&T Bank Stadium',
        )).iloc[0]
        out = _card(row)
        self.assertIn('Texas A&amp;M', out)
        self.assertIn('M&amp;T Bank Stadium', out)
        self.assertNotIn('A&M', out)

    def test_missing_color_falls_back_to_the_neutral_outline(self):
        row = _normalize(_raw_game(home_color=None, away_color=None)).iloc[0]
        out = _card(row)
        self.assertNotIn('<style>', out)
        self.assertNotIn('--gs-color', out)

    def test_missing_venue_is_omitted_not_printed_as_nan(self):
        row = _normalize(_raw_game(venue_full_name=None)).iloc[0]
        out = _card(row)
        self.assertNotIn('nan', out.lower())
        self.assertNotIn('Lucas Oil', out)

    def test_neutral_site_venue_is_labelled(self):
        row = _normalize(_raw_game(neutral_site=True)).iloc[0]
        self.assertIn('Lucas Oil Stadium (neutral)', _card(row))

    def test_logos_render_and_the_color_stripe_survives_alongside_them(self):
        row = _normalize(_raw_game()).iloc[0]
        out = _card(row)
        self.assertEqual(out.count('gs-logo'), 2)
        self.assertEqual(out.count('--gs-color'), 2)

    def test_card_with_no_logos_renders_text_only(self):
        row = _normalize(_raw_game(home_logo=None, away_logo=None)).iloc[0]
        out = _card(row)
        self.assertNotIn('<img', out)
        self.assertIn('Michigan', out)

    def test_map_missing_one_logo_drops_only_that_one(self):
        row = _normalize(_raw_game(away_logo=None)).iloc[0]
        self.assertEqual(_card(row).count('gs-logo'), 1)

    def test_light_mode_uses_the_standard_mark_dark_mode_the_dark_one(self):
        row = _normalize(_raw_game()).iloc[0]
        self.assertIn('/500-dark/', _card(row, dark_mode=True))
        self.assertNotIn('/500-dark/', _card(row, dark_mode=False))

    def test_unranked_team_shows_no_rank_badge(self):
        row = _normalize(_raw_game(home_current_rank=99.0, away_current_rank=99.0)).iloc[0]
        out = _card(row)
        self.assertNotIn('gs-rank', out)
        self.assertNotIn('99', out)


class ButtonLabelTests(unittest.TestCase):
    def test_abbreviation_used_when_available(self):
        row = _normalize(_raw_game()).iloc[0]
        self.assertEqual(game_slate._abbrev(row, 'Home'), 'MICH')
        self.assertEqual(game_slate._abbrev(row, 'Away'), 'CONN')

    def test_long_name_truncates_at_a_word_boundary(self):
        row = _normalize(_raw_game(home_location='Delaware State', home_abbreviation=None)).iloc[0]
        # Never "Delaware Sta" - a hard character slice reads as a typo.
        self.assertEqual(game_slate._abbrev(row, 'Home'), 'Delaware')

    def test_short_name_untouched(self):
        row = _normalize(_raw_game(home_location='Duke', home_abbreviation=None)).iloc[0]
        self.assertEqual(game_slate._abbrev(row, 'Home'), 'Duke')


class ScoreboardParserTests(unittest.TestCase):
    """The live ESPN path must land in the SAME normalized shape as the
    published file, so nothing downstream branches on source."""

    PAYLOAD = {'events': [{
        'id': '401856600', 'date': '2026-04-07T00:50Z',
        'season': {'year': 2026, 'type': 3},
        'competitions': [{
            'date': '2026-04-07T00:50Z', 'timeValid': True, 'neutralSite': True,
            'venue': {'fullName': 'Lucas Oil Stadium'},
            'notes': [{'headline': 'National Championship'}],
            'broadcasts': [{'names': ['TBS', 'truTV']}],
            'groups': {'id': '7', 'shortName': 'Big Ten', 'isConference': True},
            'status': {'type': {
                'name': 'STATUS_FINAL', 'state': 'post', 'completed': True, 'shortDetail': 'Final',
            }},
            'competitors': [
                {'homeAway': 'home', 'score': '69', 'winner': True,
                 'curatedRank': {'current': 1},
                 'team': {'id': '130', 'location': 'Michigan', 'displayName': 'Michigan Wolverines',
                          'abbreviation': 'MICH', 'color': '00274c', 'conferenceId': '7',
                          'logo': 'https://a.espncdn.com/i/teamlogos/ncaa/500/130.png'}},
                {'homeAway': 'away', 'score': '63', 'winner': False,
                 'curatedRank': {'current': 99},
                 'team': {'id': '41', 'location': 'UConn', 'displayName': 'UConn Huskies',
                          'abbreviation': 'CONN', 'color': '0c2340', 'conferenceId': '4',
                          'logo': 'https://a.espncdn.com/i/teamlogos/ncaa/500/41.png'}},
            ],
        }],
    }]}

    def test_scoreboard_normalizes_to_the_same_contract(self):
        raw = loaders._scoreboard_raw_rows(self.PAYLOAD)
        df = loaders._normalize_slate_frame(raw, conf_map={7: 'Big Ten', 4: 'Big East'}, source='espn')
        r = df.iloc[0]
        self.assertEqual(r['Home'], 'Michigan')
        self.assertEqual(r['Away'], 'UConn')
        self.assertEqual(r['Home Pts'], 69)          # string "69" coerced
        self.assertEqual(r['Winner'], 'Michigan')
        self.assertEqual(r['Home Rank'], 1)
        self.assertTrue(pd.isna(r['Away Rank']))     # 99 sentinel
        self.assertEqual(r['Broadcast'], 'TBS/truTV')
        self.assertEqual(r['Home Conf'], 'Big Ten')
        self.assertTrue(r['Neutral Site'])
        self.assertTrue(r['D-I Matchup'])
        self.assertEqual(r['_source'], 'espn')

    def test_column_sets_match_between_the_two_sources(self):
        espn = loaders._normalize_slate_frame(
            loaders._scoreboard_raw_rows(self.PAYLOAD), source='espn')
        local = _normalize(_raw_game())
        self.assertEqual(set(espn.columns), set(local.columns))

    def test_event_missing_a_side_is_skipped_not_half_rendered(self):
        payload = {'events': [{'id': '1', 'competitions': [{
            'status': {'type': {'name': 'STATUS_SCHEDULED', 'state': 'pre'}},
            'competitors': [{'homeAway': 'home', 'team': {'location': 'Duke'}}],
        }]}]}
        self.assertTrue(loaders._scoreboard_raw_rows(payload).empty)

    def test_empty_payload_is_an_empty_frame(self):
        self.assertTrue(loaders._scoreboard_raw_rows({}).empty)
        self.assertTrue(loaders._normalize_slate_frame(pd.DataFrame()).empty)


class ConferenceIdMapTests(unittest.TestCase):
    def test_map_built_from_conference_games_only(self):
        raw = pd.DataFrame([
            _raw_game(groups_id=7.0, groups_short_name='Big Ten', groups_is_conference=True),
            _raw_game(groups_id=2.0, groups_short_name='ACC', groups_is_conference=True),
            # A non-conference game's group must not pollute the map.
            _raw_game(groups_id=50.0, groups_short_name='Division I', groups_is_conference=None),
        ])
        self.assertEqual(loaders._conference_id_name_map(raw), {7: 'Big Ten', 2: 'ACC'})

    def test_missing_group_columns_degrade_to_empty(self):
        self.assertEqual(loaders._conference_id_name_map(pd.DataFrame([{'a': 1}])), {})
        self.assertEqual(loaders._conference_id_name_map(pd.DataFrame()), {})


class TeamBridgeTests(unittest.TestCase):
    def test_unresolvable_team_is_omitted_never_mapped_to_none(self):
        """Every call site does .get(name) and disables the button on a
        miss - a None VALUE would sail through that check and seed a null
        into the destination's team picker."""
        games = _normalize(_raw_game(away_location='Not A Real School'))
        original = loaders.load_teams
        loaders.load_teams = lambda season=None: pd.DataFrame({'Team': ['Michigan', 'Duke']})
        try:
            bridge = loaders.slate_team_bridge(games, 2026)
        finally:
            loaders.load_teams = original
        self.assertEqual(bridge.get('Michigan'), 'Michigan')
        self.assertNotIn('Not A Real School', bridge)

    def test_no_cbbd_team_list_yields_an_empty_bridge(self):
        games = _normalize(_raw_game())
        original = loaders.load_teams
        loaders.load_teams = lambda season=None: pd.DataFrame()
        try:
            self.assertEqual(loaders.slate_team_bridge(games, 2026), {})
        finally:
            loaders.load_teams = original


class DefaultDateTests(unittest.TestCase):
    def test_off_season_prefers_the_last_date_with_di_games(self):
        dates = [
            {'date': '2026-04-04', 'games': 20, 'di_games': 20},
            {'date': '2026-04-06', 'games': 8, 'di_games': 0},   # all non-D-I
        ]
        self.assertEqual(
            loaders.default_slate_date(2024, dates), __import__('datetime').date(2026, 4, 4),
        )

    def test_falls_back_to_any_games_when_no_date_has_di_games(self):
        dates = [{'date': '2026-04-06', 'games': 8, 'di_games': 0}]
        self.assertEqual(
            loaders.default_slate_date(2024, dates), __import__('datetime').date(2026, 4, 6),
        )

    def test_no_published_dates_at_all_does_not_crash(self):
        self.assertIsNotNone(loaders.default_slate_date(2024, []))


def _player_buttons(calls):
    """Only the two '<TEAM> players' buttons - a completed card also
    renders a 'Box score' button, which these tests aren't about."""
    return [c for c in calls if 'players' in str(c[0][0])]


class BoxScoreButtonTests(unittest.TestCase):
    def test_completed_game_offers_a_box_score_button(self):
        calls = SwitchTabSeedingTests()._capture({}, row=_normalize(_raw_game()).iloc[0])
        labels = [str(c[0][0]) for c in calls]
        self.assertIn('Box score', labels)

    def test_unplayed_game_offers_no_box_score_button(self):
        row = _normalize(_raw_game(
            status_type_name='STATUS_SCHEDULED', status_type_state='pre',
            home_score=0, away_score=0, home_winner=None, away_winner=None,
        )).iloc[0]
        labels = [str(c[0][0]) for c in SwitchTabSeedingTests()._capture({}, row=row)]
        self.assertNotIn('Box score', labels)

    def test_game_the_source_says_has_no_box_offers_no_button(self):
        """The schedule file stamps this per row - False for exactly the
        postponed/canceled games. A button opening an empty panel is worse
        than no button."""
        row = _normalize(_raw_game(player_box=False)).iloc[0]
        self.assertFalse(row['Has Box'])
        labels = [str(c[0][0]) for c in SwitchTabSeedingTests()._capture({}, row=row)]
        self.assertNotIn('Box score', labels)

    def test_box_button_opens_the_right_game(self):
        calls = SwitchTabSeedingTests()._capture({}, row=_normalize(_raw_game()).iloc[0])
        box = [c for c in calls if str(c[0][0]) == 'Box score'][0]
        self.assertIs(box[1]['on_click'], game_slate._open_box)
        self.assertEqual(box[1]['args'], ('401856600',))


class SwitchTabSeedingTests(unittest.TestCase):
    """Verifies the button wiring by calling the card renderer directly
    with st.button monkeypatched to capture its arguments.

    Deliberately NOT an AppTest interaction: AppTest cannot reliably
    simulate a tab switch followed by another widget interaction with this
    app's key="active_tab"-bound tabs pattern - a subsequent
    .set_value().run() silently resets active_tab to index 0. That's a
    harness limitation, not a real-user bug, so the wiring is asserted at
    the call-argument level instead.
    """

    def _capture(self, bridge, row=None):
        calls = []

        class _FakeCol:
            def __enter__(self_inner):
                return self_inner

            def __exit__(self_inner, *a):
                return False

        class _FakeCtx(_FakeCol):
            pass

        st_mod = game_slate.st
        originals = (st_mod.container, st_mod.markdown, st_mod.columns, st_mod.button)
        st_mod.container = lambda *a, **k: _FakeCtx()
        st_mod.markdown = lambda *a, **k: None
        st_mod.columns = lambda n, **k: [_FakeCol() for _ in range(n if isinstance(n, int) else len(n))]
        st_mod.button = lambda *a, **k: calls.append((a, k))
        try:
            row = _normalize(_raw_game()).iloc[0] if row is None else row
            game_slate._render_card(0, row, 2026, bridge, True)
        finally:
            st_mod.container, st_mod.markdown, st_mod.columns, st_mod.button = originals
        return calls

    def test_each_button_seeds_its_own_team_and_the_opponents_defense(self):
        calls = _player_buttons(self._capture({'Michigan': 'Michigan', 'UConn': 'Connecticut'}))
        self.assertEqual(len(calls), 2)

        (away_args, away_kw), (home_args, home_kw) = calls
        self.assertEqual(away_args[0], 'CONN players')
        self.assertIs(away_kw['on_click'], game_slate.switch_tab)
        self.assertEqual(away_kw['args'], (game_slate.TAB_MATCHUP,))
        self.assertEqual(away_kw['kwargs'], {
            'ma_season': 2026, 'ma_player_team': 'Connecticut', 'ma_def_team': 'Michigan',
        })

        self.assertEqual(home_args[0], 'MICH players')
        self.assertEqual(home_kw['kwargs'], {
            'ma_season': 2026, 'ma_player_team': 'Michigan', 'ma_def_team': 'Connecticut',
        })

    def test_unbridged_team_disables_both_buttons_rather_than_seeding_a_null(self):
        calls = _player_buttons(self._capture({'Michigan': 'Michigan'}))   # UConn missing
        for _, kw in calls:
            self.assertTrue(kw['disabled'])
            self.assertIsNone(kw['on_click'])
            self.assertIsNone(kw['kwargs'])

    def test_seeded_team_names_are_the_cbbd_spelling_not_espn(self):
        """The destination's pickers are keyed on CBBD's school names; a
        mismatch here is silent - the seeded value just isn't a valid
        option and the tab quietly opens on its default."""
        calls = _player_buttons(self._capture({'Michigan': 'Michigan', 'UConn': 'Connecticut'}))
        seeded = {c[1]['kwargs']['ma_player_team'] for c in calls}
        self.assertEqual(seeded, {'Michigan', 'Connecticut'})
        self.assertNotIn('UConn', seeded)


class BoxScoreRenderTests(unittest.TestCase):
    """The box panel's markup, same reasoning as the card tests: these
    requirements are visual and fail silently."""

    def _teams(self):
        away = pd.Series({'Team': 'UConn', 'Score': 63, 'FGM': 21, 'FGA': 68, 'FG%': 30.88,
                          '3PM': 9, '3PA': 33, '3P%': 27.27, 'FTM': 12, 'FTA': 16, 'FT%': 75.0,
                          'REB': 46, 'AST': 9, 'TOV': 11, 'PIP': 22, 'Fast Break': 4,
                          'Off TO': 8, 'Largest Lead': 3, 'Lead Changes': 6})
        home = pd.Series({'Team': 'Michigan', 'Score': 69, 'FGM': 21, 'FGA': 55, 'FG%': 38.18,
                          '3PM': 2, '3PA': 15, '3P%': 13.33, 'FTM': 25, 'FTA': 28, 'FT%': 89.29,
                          'REB': 39, 'AST': 7, 'TOV': 10, 'PIP': 36, 'Fast Break': 2,
                          'Off TO': 4, 'Largest Lead': 11, 'Lead Changes': 6})
        return away, home

    def test_comparison_bars_compare_shooting_by_percentage_not_makes(self):
        """21-68 and 21-55 are the same makes and very different games."""
        a, h = self._teams()
        out = game_slate._comparison_html(a, h, '#0c2340', '#00274c')
        # Michigan shot better, so its bar leads despite equal makes.
        fg_block = out.split("3PT")[0]
        self.assertIn('bs-lead', fg_block.split('bs-cmp-track')[1])
        self.assertIn('21-68', out)
        self.assertIn('21-55', out)

    def test_equal_values_split_the_track_evenly(self):
        bar = game_slate._split_bar(10, 10, '#111111', '#222222')
        self.assertIn('width:50.0%', bar)
        self.assertNotIn('bs-lead', bar)

    def test_zero_zero_does_not_collapse_the_track(self):
        bar = game_slate._split_bar(0, 0, '#111111', '#222222')
        self.assertIn('width:50.0%', bar)

    def test_missing_stat_renders_a_dash_never_nan(self):
        a, h = self._teams()
        a['PIP'] = float('nan'); h['PIP'] = float('nan')
        out = game_slate._comparison_html(a, h, '#0c2340', '#00274c') + \
              game_slate._chips_html(a, h, 'CONN', 'MICH')
        self.assertNotIn('nan', out.lower())
        self.assertNotIn('Paint', out)      # chip skipped entirely, not blank

    def test_player_strip_never_prints_nan_for_a_dnp_row(self):
        p = pd.Series({'PosAbbr': 'F', 'Minutes': float('nan'), 'Points': float('nan'),
                       'Rebounds': float('nan'), 'Assists': float('nan'), 'Steals': float('nan'),
                       'Blocks': float('nan'), 'Turnovers': float('nan'), 'Fouls': float('nan'),
                       'FGM': float('nan'), 'FGA': float('nan'), '3PM': float('nan'),
                       '3PA': float('nan'), 'FTM': float('nan'), 'FTA': float('nan')})
        out = game_slate._player_strip_html(p, 20.0, '#00274c')
        self.assertNotIn('nan', out.lower())
        self.assertNotIn('linear-gradient', out)   # no heat bar for no points

    def test_points_heat_bar_scales_to_the_games_top_scorer(self):
        p = pd.Series({'PosAbbr': 'G', 'Points': 10.0, 'Minutes': 30.0})
        self.assertIn('50%', game_slate._player_strip_html(p, 20.0, '#00274c'))

    def test_header_escapes_and_marks_the_winner(self):
        row = _normalize(_raw_game(home_location='Texas A&M', home_winner=True)).iloc[0]
        out = game_slate._box_header_html(row, None, True)
        self.assertIn('Texas A&amp;M', out)
        self.assertEqual(out.count('bs-pts bs-w'), 1)

    def test_malformed_color_cannot_reach_the_bar_style(self):
        bar = game_slate._split_bar(1, 1, "red;}</style><script>", None)
        self.assertNotIn('<script>', bar)
        self.assertIn('&lt;', bar)


class PlayerLinkSeedingTests(unittest.TestCase):
    def _capture_seed(self, pos):
        captured = {}
        st_mod = game_slate.st
        original = st_mod.button
        st_mod.button = lambda *a, **k: captured.update(k)
        try:
            row = _normalize(_raw_game()).iloc[0]
            p = pd.Series({'name': 'Elliot Cadeau', 'PosAbbr': pos})
            game_slate._player_button('Elliot Cadeau', 'Elliot Cadeau', p, row, 'Home', 2026, 'k')
        finally:
            st_mod.button = original
        return captured

    def test_seeds_all_three_layers(self):
        """Player Search resolves a player through two different widget
        paths, and an exact label match is not guaranteed - so the team +
        name query must be able to land the player on their own."""
        kw = self._capture_seed('G')
        self.assertIs(kw['on_click'], game_slate.switch_tab)
        self.assertEqual(kw['args'], (game_slate.TAB_PLAYER_SEARCH,))
        self.assertEqual(kw['kwargs'], {
            'ps_season': 2026,
            'ps_team': 'Michigan',                      # ESPN spelling, matches the slate
            'ps_player_query_team': 'Elliot Cadeau',    # layer 1: narrows the roster
            'ps_player_select': 'Elliot Cadeau (G)',    # layer 2: exact label
            'ps_player_query': 'Elliot Cadeau',         # layer 3: All-Teams fallback
        })

    def test_label_uses_the_abbreviation_not_the_full_position_name(self):
        """load_espn_roster emits position ABBREVIATIONS, which is what
        Player Search's labels are built from - 'Guard' would never match."""
        self.assertEqual(self._capture_seed('G')['kwargs']['ps_player_select'], 'Elliot Cadeau (G)')

    def test_missing_position_still_seeds_a_usable_label(self):
        kw = self._capture_seed(None)
        self.assertEqual(kw['kwargs']['ps_player_select'], 'Elliot Cadeau (?)')
        # Layers 1 and 3 are unaffected, so the player is still reachable.
        self.assertEqual(kw['kwargs']['ps_player_query_team'], 'Elliot Cadeau')


class SwitchTabCallbackTests(unittest.TestCase):
    def test_seeds_the_mirror_and_clears_the_widget_key(self):
        """Cross-tab seeding must write the sticky MIRROR, not the raw
        widget key: the mirror is guarded by an `in options` check, so a
        team that doesn't exist in the destination's list degrades to its
        default instead of raising on the next run."""
        import ui.components as components

        state = {'ma_player_team': 'Stale Team'}
        original = components.st
        components.st = type('S', (), {'session_state': state})()
        try:
            components.switch_tab('MATCHUP ANALYZER', ma_player_team='Duke', ma_def_team='Kansas')
        finally:
            components.st = original

        self.assertEqual(state['active_tab'], 'MATCHUP ANALYZER')
        self.assertEqual(state['_sticky__ma_player_team'], 'Duke')
        self.assertEqual(state['_sticky__ma_def_team'], 'Kansas')
        self.assertNotIn('ma_player_team', state)


if __name__ == '__main__':
    unittest.main()
