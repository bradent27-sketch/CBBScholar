"""Player Compare tab: head-to-head player comparison. Reuses Player
Search's team-first loaders. (Named "Player Compare", not "Team/Player
Compare" - it only ever compared two players, never two teams, so the old
label overpromised.)

Season stats prefer ESPN's own live endpoints + the ESPN-native
SportsDataverse season box file over CollegeBasketballData.com, via
data.loaders.get_player_season_profile - the SAME architecture Player
Search uses (name-matched, not id-matched - see that function's docstring
for why an id-based join between ESPN's roster endpoint and the box file
doesn't work), falling back to CBBD only when ESPN's own roster/box-file
lookups genuinely come up empty for that player. This tab wasn't included
when Player Search's CBBD-free pipeline was first built (see HANDOFF.md's
"Player Search ONLY" scope note from that pass) - this is that follow-up.
Both players' profiles are resolved ONCE in render() and threaded into
every section below (column tiles, delta table, radar) instead of each
section independently re-fetching, which the CBBD-only version used to do."""
import pandas as pd
import streamlit as st

from config import AVAILABLE_SEASONS
from data.loaders import (
    current_cbb_season, load_teams, load_team_roster, get_player_season_profile, team_color_map,
    load_espn_teams, load_espn_season_player_box_native,
)
from data.utils import match_player_name, resolve_team_name
from ui.components import (
    render_coming_soon, render_team_banner, render_bio_strip, render_stat_tiles,
    sticky_selectbox,
)
from ui.charts import render_radar
from ui.tabs.player_search import _fmt_height, _display_weight, _pct, _per_game


def _player_picker(col, label_prefix, season, teams_list, key_prefix, default_team=None):
    """Team + player selectors. The player dropdown is CBBD's own season-
    scoped `/teams/roster` UNIONED with this season's own ESPN box-file
    players for the team - same fix Player Search already applies (see
    ui/tabs/player_search.py): CBBD's roster endpoint IS season-aware
    (unlike ESPN's live-only roster endpoint), but can still desync from
    box-score reality, hiding a player who otherwise has real stats this
    tab could show. Box-only rows are bare pd.Series with every field
    _render_player_column/render() can access set to None except
    name/position, so bracket access on 'jersey'/'id' elsewhere never
    KeyErrors."""
    with col:
        default_idx = teams_list.index(default_team) if default_team in teams_list else 0
        team = sticky_selectbox(f"{label_prefix} — team", teams_list, key=f"{key_prefix}_team", default_index=default_idx)
        roster_df = load_team_roster(team, season)

        box_only_rows = []
        espn_teams_season = load_espn_teams(season)
        if not espn_teams_season.empty:
            espn_team = resolve_team_name(team, espn_teams_season['Team'].dropna().tolist())
            if espn_team:
                box_df_for_picker = load_espn_season_player_box_native(season)
                if not box_df_for_picker.empty and 'Team' in box_df_for_picker.columns:
                    box_team_players = box_df_for_picker[box_df_for_picker['Team'] == espn_team][['name', 'Position']].drop_duplicates(subset=['name'])
                    existing_names = roster_df['name'] if not roster_df.empty else pd.Series([], dtype=str)
                    box_only = box_team_players[
                        box_team_players['name'].apply(lambda n: match_player_name(n, existing_names) is None)
                    ]
                    box_only_rows = [
                        pd.Series({'name': r['name'], 'position': r['Position'], 'jersey': None, 'height': None, 'weight': None, 'id': None})
                        for _, r in box_only.iterrows()
                    ]

        roster_rows = [roster_df.iloc[i] for i in range(len(roster_df))]
        combined_rows = roster_rows + box_only_rows
        if not combined_rows:
            st.info("No roster data.")
            return None, None
        labels = [f"{r['name']} ({r.get('position') or '?'})" for r in combined_rows]
        sel_label = sticky_selectbox(f"{label_prefix} — player", labels, key=f"{key_prefix}_player")
        return team, combined_rows[labels.index(sel_label)]


def _render_player_column(col, team, row, colors, stats):
    with col:
        render_team_banner(team, subtitle=f"{row['position'] or '?'} #{row['jersey'] or '?'}", team_color=colors.get(team))
        render_bio_strip([
            ('Height', _fmt_height(row.get('height'))),
            ('Weight', _display_weight(row)),
        ])
        if not stats:
            st.info("No stats recorded yet this season.")
            return
        games = stats.get('games') or 0
        fg = stats.get('fieldGoals') or {}
        three = stats.get('threePointFieldGoals') or {}
        reb = stats.get('rebounds') or {}
        entries = [
            {'label': 'PPG', 'value_str': _per_game(stats.get('points'), games)},
            {'label': 'RPG', 'value_str': _per_game(reb.get('total'), games)},
            {'label': 'APG', 'value_str': _per_game(stats.get('assists'), games)},
            {'label': 'FG%', 'value_str': _pct(fg.get('pct'))},
            {'label': '3P%', 'value_str': _pct(three.get('pct'))},
        ]
        render_stat_tiles(entries)


def render():
    st.markdown("<div class='custom-section-header'>PLAYER COMPARE</div>", unsafe_allow_html=True)

    default_season = current_cbb_season()
    seasons = AVAILABLE_SEASONS if default_season in AVAILABLE_SEASONS else [default_season] + AVAILABLE_SEASONS
    season = sticky_selectbox(
        "Season", seasons, key="cmp_season", default_index=seasons.index(default_season),
        format_func=lambda y: f"{y - 1}-{str(y)[2:]}",
    )

    teams_df = load_teams(season)
    if teams_df.empty:
        render_coming_soon(
            eyebrow="NEEDS SETUP",
            blurb="No CollegeBasketballData.com API key is configured yet (or the request failed).",
            data_sources=["CollegeBasketballData.com API"],
        )
        return
    team_names = sorted(teams_df['Team'].dropna().unique().tolist())

    col_a, col_b = st.columns(2)
    default_a = 'Duke' if 'Duke' in team_names else team_names[0]
    default_b = next((t for t in team_names if t != default_a), team_names[0])
    team_a, row_a = _player_picker(col_a, "Player A", season, team_names, "cmp_a", default_team=default_a)
    team_b, row_b = _player_picker(col_b, "Player B", season, team_names, "cmp_b", default_team=default_b)

    if row_a is None or row_b is None:
        return

    with st.spinner("Loading season stats..."):
        stats_a, _net_a, source_a, _box_a, _sid_a = get_player_season_profile(team_a, season, row_a['name'], row_a.get('id'))
        stats_b, _net_b, source_b, _box_b, _sid_b = get_player_season_profile(team_b, season, row_b['name'], row_b.get('id'))

    colors = team_color_map(season)
    st.markdown(f"<div class='custom-section-header'>{row_a['name']} vs {row_b['name']}</div>", unsafe_allow_html=True)
    col_a2, col_b2 = st.columns(2)
    _render_player_column(col_a2, team_a, row_a, colors, stats_a)
    _render_player_column(col_b2, team_b, row_b, colors, stats_b)

    _render_delta_table(team_a, team_b, row_a, row_b, colors, stats_a, stats_b)
    _render_radar_section(team_a, team_b, row_a, row_b, colors, stats_a, stats_b)
    sources = {source_a, source_b}
    if sources == {'espn'}:
        st.caption("Season stats: free ESPN/SportsDataverse box file (refreshes twice weekly, zero CBBD-quota cost).")
    elif sources == {'cbbd'}:
        st.caption("Season stats via CollegeBasketballData.com.")
    else:
        st.caption(
            "Season stats: the free ESPN/SportsDataverse box file for one player, CollegeBasketballData.com for "
            "the other — couldn't match the other player against ESPN's own roster/box-score data yet."
        )


def _numeric_stat_map(stats):
    """Flat {label: float} of the comparable per-game/percentage numbers
    from one player's season stat dict - same vocabulary both compare
    columns already display."""
    if not stats:
        return {}
    games = stats.get('games') or 0
    if not games:
        return {}
    fg = stats.get('fieldGoals') or {}
    three = stats.get('threePointFieldGoals') or {}
    ft = stats.get('freeThrows') or {}
    reb = stats.get('rebounds') or {}
    out = {}

    def per_game(label, total):
        try:
            out[label] = float(total) / games
        except (TypeError, ValueError, ZeroDivisionError):
            pass

    def direct(label, v):
        try:
            if v is not None:
                out[label] = float(v)
        except (TypeError, ValueError):
            pass

    per_game('PPG', stats.get('points'))
    per_game('RPG', reb.get('total'))
    per_game('APG', stats.get('assists'))
    per_game('SPG', stats.get('steals'))
    per_game('BPG', stats.get('blocks'))
    direct('FG%', fg.get('pct'))
    direct('3P%', three.get('pct'))
    direct('FT%', ft.get('pct'))
    direct('eFG%', stats.get('effectiveFieldGoalPct'))
    direct('Usage %', stats.get('usage'))
    return out


_PCT_STAT_LABELS = {'FG%', '3P%', 'FT%', 'eFG%', 'Usage %'}


def _render_delta_table(team_a, team_b, row_a, row_b, colors, stats_a, stats_b):
    """The head-to-head delta section: every stat both players share, as a
    dumbbell/gap chart (ui.charts.render_dumbbell_chart) instead of a plain
    table - one number-line per stat with each player's own true value
    marked by a team-colored dot, the connecting line's length reading as
    the size of the gap at a glance. `stats_a`/`stats_b` are the raw
    profile dicts render() already resolved via get_player_season_profile -
    if one source is missing a stat the other has, that stat simply won't
    be in `common` below."""
    stats_a = _numeric_stat_map(stats_a)
    stats_b = _numeric_stat_map(stats_b)
    common = [k for k in stats_a if k in stats_b]
    if not common:
        return
    st.markdown("<div class='custom-section-header'>HEAD-TO-HEAD DELTA</div>", unsafe_allow_html=True)
    from ui.charts import render_dumbbell_chart
    rows = []
    for k in common:
        va, vb = stats_a[k], stats_b[k]
        suffix = '%' if k in _PCT_STAT_LABELS else ''
        rows.append({
            'label': k,
            'value_a': va,
            'value_b': vb,
            'value_str_a': f"{va:.1f}{suffix}",
            'value_str_b': f"{vb:.1f}{suffix}",
        })
    render_dumbbell_chart(rows, row_a['name'], row_b['name'], color_a=colors.get(team_a), color_b=colors.get(team_b))


_RADAR_AXES = ['PPG', 'RPG', 'APG', 'FG%', '3P%', 'Usage %']


def _render_radar_section(team_a, team_b, row_a, row_b, colors, stats_a, stats_b):
    """Shape-comparison radar - a visual complement to the delta table
    above, not a replacement: axes are scaled to just these two players
    (see ui.charts.render_radar's docstring for why - no league-wide
    player percentile source exists yet). `stats_a`/`stats_b` are the raw
    profile dicts render() already resolved via get_player_season_profile."""
    stats_a = _numeric_stat_map(stats_a)
    stats_b = _numeric_stat_map(stats_b)
    axes = [ax for ax in _RADAR_AXES if ax in stats_a and ax in stats_b]
    if len(axes) < 3:
        return
    st.markdown("<div class='custom-section-header'>SHAPE COMPARISON</div>", unsafe_allow_html=True)
    render_radar(
        axes, stats_a, stats_b, row_a['name'], row_b['name'],
        color_a=colors.get(team_a), color_b=colors.get(team_b),
    )
