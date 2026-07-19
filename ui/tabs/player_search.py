"""
Player Search tab: flagship player lookup - bio and season stats, live via
CollegeBasketballData.com. Team-first UX (pick a team, then a player) since
CBBD has no global name-search endpoint the way CFBD does (confirmed live -
there's a /teams/roster and a /stats/player/season, both team-scoped, no
/player/search equivalent). Scoped down from NFL Scholar's 660-line version
on purpose - see CFB Scholar's player_search.py docstring for the same
reasoning (percentile ranking needs a full-league pull this pass doesn't
do; game-by-game logs are a later pass).
"""
import pandas as pd
import streamlit as st

from config import AVAILABLE_SEASONS
from data.loaders import (
    current_cbb_season, load_teams, load_team_roster, load_team_player_stats,
    get_player_season_stats, team_color_map, load_player_game_logs, get_league_player_stats,
)
from data.transforms import (
    breakout_flags, last_n_form, player_rate_profile, classify_player_role_best_available,
    league_rate_profiles,
)
from ui.components import render_coming_soon, render_team_banner, render_bio_strip, render_stat_tiles
from ui.charts import render_game_log_bars, render_role_badges, render_trend_line


def _fmt_height(inches):
    try:
        inches = int(inches)
        return f"{inches // 12}' {inches % 12}\""
    except (TypeError, ValueError):
        return '--'


def _pct(v):
    return f"{v:.1f}%" if isinstance(v, (int, float)) else '--'


def _per_game(total, games):
    try:
        return f"{float(total) / float(games):.1f}"
    except (TypeError, ValueError, ZeroDivisionError):
        return '--'


def render():
    st.markdown("<div class='custom-section-header'>PLAYER SEARCH</div>", unsafe_allow_html=True)

    default_season = current_cbb_season()
    seasons = AVAILABLE_SEASONS if default_season in AVAILABLE_SEASONS else [default_season] + AVAILABLE_SEASONS
    c1, c2 = st.columns([1, 2])
    with c1:
        season = st.selectbox("Season", seasons, index=seasons.index(default_season), format_func=lambda y: f"{y - 1}-{str(y)[2:]}", key="ps_season")

    teams_df = load_teams(season)
    if teams_df.empty:
        render_coming_soon(
            eyebrow="NEEDS SETUP",
            blurb="No CollegeBasketballData.com API key is configured yet (or the request failed). Add cbbd_api_key to .streamlit/secrets.toml — see DATA_SOURCES.md.",
            data_sources=["CollegeBasketballData.com API"],
        )
        return

    with c2:
        team_names = sorted(teams_df['Team'].dropna().unique().tolist())
        default_team_idx = team_names.index('Duke') if 'Duke' in team_names else 0
        team = st.selectbox("Team", team_names, index=default_team_idx, key="ps_team")

    with st.spinner("Loading roster..."):
        roster_df = load_team_roster(team, season)

    if roster_df.empty:
        st.info(f"No roster data found for {team} in {season}.")
        return

    labels = [f"{r['name']} ({r['position'] or '?'})" for _, r in roster_df.iterrows()]
    sel_label = st.selectbox("Select player", labels, key="ps_player_select")
    sel_row = roster_df.iloc[labels.index(sel_label)]

    with st.spinner("Loading stats..."):
        stats = get_player_season_stats(team, season, sel_row['id'])

    colors = team_color_map(season)
    render_team_banner(team, subtitle=f"{sel_row['position'] or '?'} #{sel_row['jersey'] or '?'}", team_color=colors.get(team))

    hometown = f"{sel_row.get('city', '')}, {sel_row.get('state', '')}".strip(', ') if sel_row.get('city') else '--'
    render_bio_strip([
        ('Height', _fmt_height(sel_row.get('height'))),
        ('Weight', f"{sel_row.get('weight')} lbs" if sel_row.get('weight') else '--'),
        ('Hometown', hometown or '--'),
    ])

    st.markdown(f"<div class='custom-section-header'>{season - 1}-{str(season)[2:]} SEASON STATS</div>", unsafe_allow_html=True)
    if not stats:
        st.info(f"No {season} season stats found for this player yet.")
        return

    games = stats.get('games') or 0
    fg = stats.get('fieldGoals') or {}
    three = stats.get('threePointFieldGoals') or {}
    ft = stats.get('freeThrows') or {}
    reb = stats.get('rebounds') or {}

    entries = [
        {'label': 'PPG', 'value_str': _per_game(stats.get('points'), games)},
        {'label': 'RPG', 'value_str': _per_game(reb.get('total'), games)},
        {'label': 'APG', 'value_str': _per_game(stats.get('assists'), games)},
        {'label': 'SPG', 'value_str': _per_game(stats.get('steals'), games)},
        {'label': 'BPG', 'value_str': _per_game(stats.get('blocks'), games)},
        {'label': 'MPG', 'value_str': _per_game(stats.get('minutes'), games)},
        {'label': 'FG%', 'value_str': _pct(fg.get('pct'))},
        {'label': '3P%', 'value_str': _pct(three.get('pct'))},
        {'label': 'FT%', 'value_str': _pct(ft.get('pct'))},
        {'label': 'eFG%', 'value_str': _pct(stats.get('effectiveFieldGoalPct'))},
        {'label': 'TS%', 'value_str': _pct((stats.get('trueShootingPct') or 0) * 100) if stats.get('trueShootingPct') is not None else '--'},
        {'label': 'Net Rating', 'value_str': str(stats.get('netRating', '--'))},
        {'label': 'Usage %', 'value_str': _pct(stats.get('usage'))},
        {'label': 'Games', 'value_str': str(games)},
    ]
    render_stat_tiles(entries)
    st.caption("Season stats via CollegeBasketballData.com.")

    league_rates = league_rate_profiles(get_league_player_stats(season))
    _render_tendencies_section(stats, team, colors, league_rates)
    _render_game_log_section(team, season, sel_row)


def _render_tendencies_section(stats, team, colors, league_rates=None):
    """Rate-basis role read - shooter/rebounder/passer/post, not raw
    totals, so a bench player and a starter with the same TENDENCY read
    the same. See data.transforms.player_rate_profile/
    classify_player_role_best_available for the underlying rates: a REAL
    D-I percentile rank when a league player database has been built (Team
    Efficiency tab), else a fixed-threshold heuristic fallback."""
    profile = player_rate_profile(stats)
    role, badges, mode = classify_player_role_best_available(profile, league_rates)
    st.markdown("<div class='custom-section-header'>TENDENCIES</div>", unsafe_allow_html=True)
    if mode == 'percentile':
        st.caption(
            "Rate-basis role read — ranked against REAL D-I player percentiles (see Team Efficiency's "
            "League Player Database). Controls for minutes/shot volume, so it reflects TYPE of player."
        )
    else:
        st.caption(
            "Rate-basis role read (fixed-threshold heuristic — build the League Player Database on the "
            "Team Efficiency tab for real D-I percentiles instead). Controls for minutes/shot volume."
        )
    render_role_badges(role, badges, primary_color=colors.get(team))
    if profile:
        tendency_entries = [
            {'label': 'Usage %', 'value_str': _pct(profile.get('usage'))},
            {'label': '3PA Rate', 'value_str': _pct(profile.get('three_pa_rate'))},
            {'label': 'FT Rate', 'value_str': _pct(profile.get('ft_rate'))},
            {'label': 'AST/40', 'value_str': f"{profile['ast_per40']:.1f}" if profile.get('ast_per40') is not None else '--'},
            {'label': 'REB/40', 'value_str': f"{profile['reb_per40']:.1f}" if profile.get('reb_per40') is not None else '--'},
            {'label': 'AST/TOV', 'value_str': f"{profile['ast_to_ratio']:.1f}" if profile.get('ast_to_ratio') is not None else '--'},
            {'label': 'BLK/40', 'value_str': f"{profile['blk_per40']:.1f}" if profile.get('blk_per40') is not None else '--'},
            {'label': 'STL/40', 'value_str': f"{profile['stl_per40']:.1f}" if profile.get('stl_per40') is not None else '--'},
        ]
        render_stat_tiles(tendency_entries)


def _render_role_trend(mine):
    """Rolling-average trend of Usage% and 3PT Rate across the season, from
    the same per-game rows already loaded for the breakout chart above -
    both are already present per-game in /games/players (Usage directly;
    3PT Rate computed from 3PA/FGA), so this costs nothing extra. This is
    the "beat the market" view: a real role/scheme change (more shots, a
    bigger shot-creation burden) shows up here as the rolling line pulling
    away from the season-average dashes well before it moves the season
    number itself."""
    st.markdown("**Role Trend (rolling 5-game average)**")
    trend_stat = st.selectbox("Trend stat", ["Usage %", "3PT Rate"], key="ps_trend_stat")
    labels = [f"{g['Home/Away']} {g['Opponent']} ({g['Date']})" for _, g in mine.iterrows()]
    if trend_stat == "Usage %":
        values = pd.to_numeric(mine['Usage'], errors='coerce').tolist()
        unit = '%'
    else:
        fga = pd.to_numeric(mine['FGA'], errors='coerce')
        three_pa = pd.to_numeric(mine['3PA'], errors='coerce')
        values = (three_pa / fga.replace(0, pd.NA) * 100).tolist()
        unit = '%'
    render_trend_line(labels, values, window=5, unit=unit)
    st.caption(
        "Violet line = trailing 5-game average; dashed = season average. A widening gap between "
        "them is the earliest signal of a real role or usage change, before it shows up in box scores."
    )


_GAME_LOG_STATS = [('Points', 'Points'), ('Rebounds', 'Rebounds'), ('Assists', 'Assists'),
                   ('Game Score', 'Game Score'), ('Minutes', 'Minutes')]


def _render_game_log_section(team, season, sel_row):
    """Game-by-game bars with season-average line, breakout flags (games
    >= 1.5 standard deviations above the player's own season mean), and a
    last-5-vs-season form readout."""
    st.markdown("<div class='custom-section-header'>GAME LOG &amp; BREAKOUT GAMES</div>", unsafe_allow_html=True)
    with st.spinner("Loading game log..."):
        logs = load_player_game_logs(team, season)
    if logs.empty:
        st.info("No per-game data available for this team yet.")
        return
    # Join on the ESPN-side sourceId, NOT the roster id - the game-log
    # endpoint's athleteId is a different id namespace from the roster's id
    # (confirmed live, see load_team_roster). Name match as a fallback for
    # any roster row missing a sourceId.
    mine = logs[logs['athleteSourceId'].astype(str) == str(sel_row.get('sourceId'))]
    if mine.empty:
        mine = logs[logs['name'] == sel_row['name']]
    mine = mine.reset_index(drop=True)
    if mine.empty:
        st.info("No per-game data for this player yet this season.")
        return

    labels = [label for _, label in _GAME_LOG_STATS]
    sel = st.selectbox("Stat", labels, key="ps_gamelog_stat")
    col = _GAME_LOG_STATS[labels.index(sel)][0]

    series = mine.dropna(subset=[col]).reset_index(drop=True)
    values = pd.to_numeric(series[col], errors='coerce').fillna(0).tolist()
    if not values:
        st.info("No per-game data for this stat.")
        return
    flags = breakout_flags(values)
    tooltips = [
        f"{sel}: {v:.0f} — {g['Home/Away']} {g['Opponent']} ({g['Date']})" + (" ★ breakout" if flags[i] else "")
        for i, (v, (_, g)) in enumerate(zip(values, series.iterrows()))
    ]
    avg = sum(values) / len(values)
    render_game_log_bars(values, tooltips, flags, avg=avg)

    n_breakouts = sum(flags)
    if n_breakouts:
        star_games = [f"{g['Home/Away']} {g['Opponent']} ({v:.0f})" for v, f, (_, g) in zip(values, flags, series.iterrows()) if f]
        st.caption(f"★ Breakout game(s) — at least 1.5σ above their own season average: {', '.join(star_games)}.")
    else:
        st.caption("No breakout games yet by the 1.5σ-above-season-average threshold.")

    _render_role_trend(mine)

    # Last-5 form vs season average - the heating-up/cooling-off readout.
    form = last_n_form(mine)
    if form:
        st.markdown("**Last 5 games vs season average**")
        cols = st.columns(len(form))
        for c, (stat, (recent, season_avg)) in zip(cols, form.items()):
            c.metric(stat, f"{recent:.1f}", f"{recent - season_avg:+.1f} vs season", delta_color="normal")

    with st.expander("Full game log table"):
        show_cols = ['Date', 'Home/Away', 'Opponent', 'Minutes', 'Points', 'Rebounds', 'Assists',
                     'Steals', 'Blocks', 'Turnovers', 'FGM', 'FGA', '3PM', '3PA', 'Game Score', 'Usage']
        st.dataframe(mine[[c for c in show_cols if c in mine.columns]], width="stretch", hide_index=True)
