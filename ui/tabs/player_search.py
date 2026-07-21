"""
Player Search tab: flagship player lookup - bio and season stats, live via
CollegeBasketballData.com. Team-first UX by default (pick a team, then a
player) since CBBD has no global name-search endpoint the way CFBD does
(confirmed live - there's a /teams/roster and a /stats/player/season, both
team-scoped, no /player/search equivalent) - but an "All Teams" option on
the team picker plus a fuzzy-matched search box let a player be found by
name alone, without knowing their team first (data.loaders.load_all_rosters
fans that same team-scoped roster call out across all of D-I, weekly-cached
like this app's other full-league pulls). Scoped down from NFL Scholar's
660-line version on purpose - see CFB Scholar's player_search.py docstring
for the same reasoning (percentile ranking needs a full-league pull this
pass doesn't do; game-by-game logs are a later pass).
"""
import pandas as pd
import streamlit as st

from config import AVAILABLE_SEASONS
from data.loaders import (
    current_cbb_season, load_teams, load_team_roster, load_all_rosters,
    get_player_season_stats, team_color_map, load_player_game_logs,
    load_conference_player_season_stats, load_all_player_season_stats,
    load_team_games,
)
from data.transforms import last_n_form, player_percentile_rows
from data.utils import fuzzy_filter_names
from ui.components import render_coming_soon, render_team_banner, render_bio_strip, render_metric_tiles
from ui.charts import render_relative_bars
from ui.styling import render_sticky_footer_table

_STAT_HELP = {
    'eFG%': "Effective field goal % - field goal % with made threes counted as 1.5 makes.",
    'TS%': "True shooting % - scoring efficiency including free throws, the most complete shooting number.",
    'Net Rating': "Team point differential per 100 possessions while this player is on the floor.",
    'Usage %': "Share of the team's possessions this player uses while on the floor.",
    '3PT Rate': "Share of this player's own field goal attempts that are three-pointers - a high number means a volume three-point shooter, independent of playing time.",
    '2PT Rate': "Share of this player's own field goal attempts from two-point range.",
    'FT Rate': "Free throw attempts relative to field goal attempts - how often this player gets to the line.",
}

_ALL_TEAMS_OPTION = "All Teams (search any player)"


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
        team_options = [_ALL_TEAMS_OPTION] + team_names
        default_team_idx = team_options.index('Duke') if 'Duke' in team_options else 0
        team_choice = st.selectbox("Team", team_options, index=default_team_idx, key="ps_team")

    all_teams_mode = team_choice == _ALL_TEAMS_OPTION

    if all_teams_mode:
        with st.spinner("Loading all Division I rosters (cached ~weekly - first pull each week takes a bit)..."):
            roster_df = load_all_rosters(season)
    else:
        with st.spinner("Loading roster..."):
            roster_df = load_team_roster(team_choice, season)

    if roster_df.empty:
        st.info(f"No roster data found for {'Division I' if all_teams_mode else team_choice} in {season}.")
        return

    labels = [
        f"{r['name']} ({r['position'] or '?'})" + (f" — {r['Team']}" if all_teams_mode else '')
        for _, r in roster_df.iterrows()
    ]

    if all_teams_mode:
        query = st.text_input(
            "Search player name", key="ps_player_query",
            placeholder="Start typing any player's name — partial or slightly misspelled is fine",
        )
        if not query:
            st.info("Type a player's name above to search across all of Division I.")
            return
        matched_labels = fuzzy_filter_names(query, labels, limit=25)
        if not matched_labels:
            st.info("No players matched that spelling — try a shorter or different fragment.")
            return
    else:
        query = st.text_input(
            "Filter roster (optional)", key="ps_player_query_team",
            placeholder="Start typing to narrow the roster below…",
        )
        matched_labels = fuzzy_filter_names(query, labels, limit=len(labels)) if query else labels

    sel_label = st.selectbox("Select player", matched_labels, key="ps_player_select")
    sel_row = roster_df.iloc[labels.index(sel_label)]
    team = sel_row['Team'] if all_teams_mode else team_choice

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

    player_conf_series = teams_df.loc[teams_df['Team'] == team, 'Conference']
    player_conf = player_conf_series.iloc[0] if not player_conf_series.empty else None

    compare_all = st.checkbox(
        "Compare against all of Division I instead of just this conference "
        "(cached ~weekly — first pull each week takes a bit, instant after that)",
        key="ps_compare_all",
    )
    if compare_all:
        with st.spinner("Loading Division I player stats..."):
            group_df = load_all_player_season_stats(season)
        group_label = "D-I"
    elif player_conf:
        with st.spinner(f"Loading {player_conf} player stats..."):
            group_df = load_conference_player_season_stats(player_conf, season)
        group_label = player_conf
    else:
        group_df = pd.DataFrame()
        group_label = "conference"

    rows = player_percentile_rows(stats, group_df, _STAT_HELP)

    render_relative_bars(rows)
    if not group_df.empty:
        st.caption(
            f"Bar position + color: this season's percentile vs. {group_label} (≥5 games played, to keep the "
            f"comparison group clean). Tick mark = the group's average. {games} games played."
        )
    else:
        st.caption(f"No comparison group available right now — showing raw values only. {games} games played.")

    _render_game_log_section(team, season, sel_row, colors)


_GAME_LOG_COLS = ['Date', 'Result', 'Home/Away', 'Opponent', 'Minutes', 'Points', 'Rebounds', 'Assists',
                  'Steals', 'Blocks', 'Turnovers', 'FGM', 'FGA', '3PM', '3PA', 'Usage', 'Net Rating']
_GAME_LOG_NON_NUMERIC = ('Date', 'Result', 'Home/Away', 'Opponent')


def _join_team_result(mine, team, season):
    """Adds a 'Result' (W/L) column to a player's game log by joining the
    team's own schedule (load_team_games) - GameId is the primary join key
    (both /games and /games/players are keyed to the same underlying CBBD
    game object), Date+Opponent is a fallback in case that id namespace
    ever diverges between the two endpoints. Returns `mine` unchanged (no
    'Result' column) if the join finds nothing, rather than a column of
    blanks."""
    team_games = load_team_games(team, season)
    if team_games.empty:
        return mine
    mine = mine.copy()
    if 'GameId' in mine.columns and 'GameId' in team_games.columns and mine['GameId'].notna().any():
        result_map = dict(zip(team_games['GameId'], team_games['Result']))
        mine['Result'] = mine['GameId'].map(result_map)
    else:
        result_map = {(r['Date'], r['Opponent']): r['Result'] for _, r in team_games.iterrows()}
        mine['Result'] = mine.apply(lambda r: result_map.get((r['Date'], r['Opponent'])), axis=1)
    if mine['Result'].isna().all():
        return mine.drop(columns=['Result'])
    return mine


def _render_game_log_section(team, season, sel_row, colors):
    """Full game log table (every completed game, every core box-score
    column except Game Score) with a season-averages row rendered as a
    real, pinned FOOTER of the same table (ui.styling.render_sticky_footer_table
    - see its docstring for why this is a hand-rolled table rather than
    st.dataframe: no row-pinning API exists in this Streamlit version, and
    two separate st.dataframe widgets never actually shared scroll state
    even when CSS-seamed to look connected) - the average row stays visible
    at the bottom of the scroll area no matter how far down the game list
    you've scrolled, and it's the same table now, not a second one. Plus a
    last-5-vs-season form readout, colored green when recent form beats the
    season average and red when it's below. Opponent cells tint with that
    team's color, Result (W/L) tints green/red, matching the color language
    used elsewhere."""
    st.markdown("<div class='custom-section-header'>GAME LOG</div>", unsafe_allow_html=True)
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
    mine = _join_team_result(mine, team, season)

    # Last-5 form vs season average - season average listed first/primary,
    # last-5 called out below it (this order, and this section staying,
    # was requested explicitly - keep it even though the chart above it
    # went away). Delta text is exactly the same as before; only the color
    # is new (green = last 5 ahead of season average, red = behind).
    form = last_n_form(mine)
    if form:
        st.markdown("**Season average — last 5 games below**")
        entries = []
        for stat, (recent, season_avg) in form.items():
            delta = recent - season_avg
            better = None if abs(delta) < 1e-9 else delta > 0
            entries.append({
                'label': stat,
                'value_str': f"{season_avg:.1f}",
                'delta_str': f"last 5: {recent:.1f} ({delta:+.1f})",
                'better': better,
            })
        render_metric_tiles(entries)

    table_cols = [c for c in _GAME_LOG_COLS if c in mine.columns]
    numeric_cols = [c for c in table_cols if c not in _GAME_LOG_NON_NUMERIC]
    avg_row = {c: round(float(pd.to_numeric(mine[c], errors='coerce').mean()), 1) for c in numeric_cols}
    for c in _GAME_LOG_NON_NUMERIC:
        if c in table_cols:
            avg_row[c] = ''
    if 'Opponent' in table_cols:
        avg_row['Opponent'] = f"SEASON AVG ({len(mine)} games)"

    render_sticky_footer_table(
        mine[table_cols], avg_row, numeric_cols=numeric_cols, team_color_map=colors,
        opponent_col='Opponent', win_loss_col='Result', height=360,
    )
    st.caption(
        "Season averages stay pinned to the bottom of the table no matter where you've scrolled within it. "
        "Opponent tinted by that team's color; Result (W/L) tinted green/red."
    )
