"""Team/Player Compare tab: head-to-head player comparison, live via
CollegeBasketballData.com. Reuses Player Search's team-first loaders."""
import streamlit as st

from config import AVAILABLE_SEASONS
from data.loaders import (
    current_cbb_season, load_teams, load_team_roster, get_player_season_stats, team_color_map,
)
from ui.components import render_coming_soon, render_team_banner, render_bio_strip, render_stat_tiles
from ui.charts import render_radar
from ui.tabs.player_search import _fmt_height, _pct, _per_game


def _player_picker(col, label_prefix, season, teams_list, key_prefix, default_team=None):
    with col:
        default_idx = teams_list.index(default_team) if default_team in teams_list else 0
        team = st.selectbox(f"{label_prefix} — team", teams_list, index=default_idx, key=f"{key_prefix}_team")
        roster_df = load_team_roster(team, season)
        if roster_df.empty:
            st.info("No roster data.")
            return None, None
        labels = [f"{r['name']} ({r['position'] or '?'})" for _, r in roster_df.iterrows()]
        sel_label = st.selectbox(f"{label_prefix} — player", labels, key=f"{key_prefix}_player")
        return team, roster_df.iloc[labels.index(sel_label)]


def _render_player_column(col, team, row, season, colors):
    stats = get_player_season_stats(team, season, row['id'])
    with col:
        render_team_banner(team, subtitle=f"{row['position'] or '?'} #{row['jersey'] or '?'}", team_color=colors.get(team))
        render_bio_strip([
            ('Height', _fmt_height(row.get('height'))),
            ('Weight', f"{row.get('weight')} lbs" if row.get('weight') else '--'),
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
            {'label': 'Net Rating', 'value_str': str(stats.get('netRating', '--'))},
        ]
        render_stat_tiles(entries)


def render():
    st.markdown("<div class='custom-section-header'>TEAM / PLAYER COMPARE</div>", unsafe_allow_html=True)

    default_season = current_cbb_season()
    seasons = AVAILABLE_SEASONS if default_season in AVAILABLE_SEASONS else [default_season] + AVAILABLE_SEASONS
    season = st.selectbox("Season", seasons, index=seasons.index(default_season), format_func=lambda y: f"{y - 1}-{str(y)[2:]}", key="cmp_season")

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

    colors = team_color_map(season)
    st.markdown(f"<div class='custom-section-header'>{row_a['name']} vs {row_b['name']}</div>", unsafe_allow_html=True)
    col_a2, col_b2 = st.columns(2)
    _render_player_column(col_a2, team_a, row_a, season, colors)
    _render_player_column(col_b2, team_b, row_b, season, colors)

    _render_delta_table(team_a, row_a, team_b, row_b, season)
    _render_radar_section(team_a, row_a, team_b, row_b, season, colors)
    st.caption("Season stats via CollegeBasketballData.com.")


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
    direct('Net Rating', stats.get('netRating'))
    return out


def _render_delta_table(team_a, row_a, team_b, row_b, season):
    """The head-to-head delta table (formerly parked): every stat both
    players share, with a diverging-color relative-edge column (green =
    Player A leads)."""
    stats_a = _numeric_stat_map(get_player_season_stats(team_a, season, row_a['id']))
    stats_b = _numeric_stat_map(get_player_season_stats(team_b, season, row_b['id']))
    common = [k for k in stats_a if k in stats_b]
    if not common:
        return
    st.markdown("<div class='custom-section-header'>HEAD-TO-HEAD DELTA</div>", unsafe_allow_html=True)
    rows = []
    for k in common:
        va, vb = stats_a[k], stats_b[k]
        edge = va - vb
        # Relative edge (% of the pair's mean) so the shared color scale
        # isn't dominated by whichever stat has the biggest raw numbers.
        denom = (abs(va) + abs(vb)) / 2
        rel = (edge / denom * 100) if denom else 0.0
        rows.append({
            'Stat': k,
            row_a['name']: round(va, 1),
            row_b['name']: round(vb, 1),
            'Edge %': round(rel, 1),
        })
    import pandas as pd
    from ui.styling import style_plain_dataframe, df_auto_height
    df = pd.DataFrame(rows).set_index('Stat')
    max_abs = df['Edge %'].abs().max() or 1
    st.dataframe(
        style_plain_dataframe(df, diverging_cols={'Edge %': max_abs}),
        width="stretch", height=df_auto_height(len(df)),
    )
    st.caption(f"Edge %: relative difference — green = {row_a['name']} leads, red = {row_b['name']} leads.")


_RADAR_AXES = ['PPG', 'RPG', 'APG', 'FG%', '3P%', 'Usage %']


def _render_radar_section(team_a, row_a, team_b, row_b, season, colors):
    """Shape-comparison radar - a visual complement to the delta table
    above, not a replacement: axes are scaled to just these two players
    (see ui.charts.render_radar's docstring for why - no league-wide
    player percentile source exists yet)."""
    stats_a = _numeric_stat_map(get_player_season_stats(team_a, season, row_a['id']))
    stats_b = _numeric_stat_map(get_player_season_stats(team_b, season, row_b['id']))
    axes = [ax for ax in _RADAR_AXES if ax in stats_a and ax in stats_b]
    if len(axes) < 3:
        return
    st.markdown("<div class='custom-section-header'>SHAPE COMPARISON</div>", unsafe_allow_html=True)
    render_radar(
        axes, stats_a, stats_b, row_a['name'], row_b['name'],
        color_a=colors.get(team_a), color_b=colors.get(team_b),
    )
    st.caption(
        "Each axis is scaled to these two players only (not a league percentile) — the shape shows relative "
        "strengths between them, not where either player ranks nationally."
    )
