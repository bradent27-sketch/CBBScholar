"""
Matchup Analyzer tab: player-vs-team-defense prep, live via
CollegeBasketballData.com - built for individual matchup research (props,
"how does this player fare against this defense") rather than a team-vs-team
score projection. Two independent columns: PLAYER (any player's own tendency
percentiles plus a last-10-games-vs-season-average trend, the same vocabulary
Player Search uses) on the left, TEAM DEFENSE (any one team's defensive shape
vs D-I, plus the positional matchup defense breakdown - what opposing
Guards/Forwards/Centers have actually done against that team) on the right.
Deliberately not team-vs-team anymore: no venue/win-probability/projected-
score/Four-Factors-matchup/style-profile/recent-form content, all of which
lived here in an earlier "Team A vs Team B" version of this tab - removed
per explicit request (player-vs-team prep matters here, not head-to-head
team projection). See HANDOFF.md for the positional-defense architecture
writeup (still unchanged) and the position-granularity caveat that couldn't
be verified live against a real payload.
"""
import pandas as pd
import streamlit as st

from config import AVAILABLE_SEASONS
from data.loaders import (
    current_cbb_season, load_all_team_season_stats, load_team_roster, load_positional_matchup_data,
    get_player_season_stats, load_player_game_logs, load_conference_player_season_stats,
    load_all_player_season_stats, load_teams,
)
from data.transforms import (
    position_bucket, positional_defense_summary, positional_defense_trend,
    player_percentile_rows, player_trend_series, team_defense_profile_rows,
)
from ui.components import render_coming_soon
from ui.charts import render_trend_line, render_relative_bars
from ui.styling import style_plain_dataframe, df_auto_height

_PLAYER_TREND_STATS = [('Points', ''), ('Assists', ''), ('Rebounds', ''), ('Minutes', ''), ('3P%', '%')]

_PLAYER_STAT_HELP = {
    'eFG%': "Effective field goal % - field goal % with made threes counted as 1.5 makes.",
    'TS%': "True shooting % - scoring efficiency including free throws, the most complete shooting number.",
    'Net Rating': "Team point differential per 100 possessions while this player is on the floor.",
    'Usage %': "Share of the team's possessions this player uses while on the floor.",
    '3PT Rate': "Share of this player's own field goal attempts that are three-pointers.",
    '2PT Rate': "Share of this player's own field goal attempts from two-point range.",
    'FT Rate': "Free throw attempts relative to field goal attempts - how often this player gets to the line.",
    'ORB/G': "Offensive rebounds per game.",
    'DRB/G': "Defensive rebounds per game.",
}


def _safe_max_abs(series):
    m = series.abs().max()
    return float(m) if pd.notna(m) and m else 1.0


def render():
    st.markdown("<div class='custom-section-header'>MATCHUP ANALYZER</div>", unsafe_allow_html=True)
    st.caption(
        "Pull up any player's stat profile next to any team's defense — built for individual matchup prep "
        "(player props, \"how does this guy do against this defense\") rather than a team-vs-team projection."
    )

    default_season = current_cbb_season()
    seasons = AVAILABLE_SEASONS if default_season in AVAILABLE_SEASONS else [default_season] + AVAILABLE_SEASONS
    season = st.selectbox("Season", seasons, index=seasons.index(default_season), format_func=lambda y: f"{y - 1}-{str(y)[2:]}", key="ma_season")

    teams_df = load_teams(season)
    if teams_df.empty:
        render_coming_soon(
            eyebrow="NEEDS SETUP",
            blurb="No CollegeBasketballData.com API key is configured yet (or the request failed). Add cbbd_api_key to .streamlit/secrets.toml — see DATA_SOURCES.md.",
            data_sources=["CollegeBasketballData.com API"],
        )
        return

    col_player, col_defense = st.columns(2)
    with col_player:
        st.markdown("<div class='custom-section-header'>PLAYER</div>", unsafe_allow_html=True)
        _render_player_panel(season, teams_df)
    with col_defense:
        st.markdown("<div class='custom-section-header'>TEAM DEFENSE</div>", unsafe_allow_html=True)
        _render_team_defense_panel(season, teams_df)


def _render_player_panel(season, teams_df):
    team_names = sorted(teams_df['Team'].dropna().unique().tolist())
    if not team_names:
        st.info("No team data available.")
        return
    default_team = 'Duke' if 'Duke' in team_names else team_names[0]
    team_choice = st.selectbox("Team", team_names, index=team_names.index(default_team), key="ma_player_team")

    with st.spinner("Loading roster..."):
        roster_df = load_team_roster(team_choice, season)
    if roster_df.empty:
        st.info(f"No roster data for {team_choice}.")
        return
    labels = [f"{r['name']} ({r['position'] or '?'})" for _, r in roster_df.iterrows()]
    sel_label = st.selectbox("Player", labels, key="ma_player_select")
    sel_row = roster_df.iloc[labels.index(sel_label)]

    with st.spinner("Loading stats..."):
        stats = get_player_season_stats(team_choice, season, sel_row['id'])
    if not stats:
        st.info("No season stats for this player yet.")
        return

    conf_series = teams_df.loc[teams_df['Team'] == team_choice, 'Conference']
    conf = conf_series.iloc[0] if not conf_series.empty else None

    compare_all = st.checkbox(
        "Compare against all of Division I instead of just this conference (cached ~weekly)",
        key="ma_player_compare_all",
    )
    if compare_all:
        with st.spinner("Loading Division I player stats..."):
            group_df = load_all_player_season_stats(season)
        group_label = "D-I"
    elif conf:
        with st.spinner(f"Loading {conf} player stats..."):
            group_df = load_conference_player_season_stats(conf, season)
        group_label = conf
    else:
        group_df = pd.DataFrame()
        group_label = "conference"

    st.markdown(f"**{sel_row['name']} — tendency profile**")
    rows = player_percentile_rows(stats, group_df, _PLAYER_STAT_HELP)
    render_relative_bars(rows)
    if not group_df.empty:
        st.caption(f"Percentile vs. {group_label} (≥5 games played). Tick mark = the group's average.")
    else:
        st.caption("No comparison group available right now — showing raw values only.")

    st.markdown(f"**{sel_row['name']} — last 10 games vs season average**")
    with st.spinner("Loading game log..."):
        logs = load_player_game_logs(team_choice, season)
    mine = logs[logs['athleteSourceId'].astype(str) == str(sel_row.get('sourceId'))] if not logs.empty else logs
    if mine.empty and not logs.empty:
        mine = logs[logs['name'] == sel_row['name']]
    if mine.empty:
        st.info("No per-game data for this player yet this season.")
        return
    mine = mine.sort_values('Date').reset_index(drop=True)
    # 3P% isn't a column load_player_game_logs returns directly (it has
    # 3PM/3PA, makes and attempts, not a precomputed percentage) - derived
    # here per game. `.where(attempts > 0)` (same divide-by-zero guard
    # data.transforms.player_rate_stats already uses for 3PT/2PT/FT rate)
    # turns a 0-attempt game into NaN instead of a raw ZeroDivisionError/inf,
    # which player_trend_series already drops via its own dropna(subset=[col]).
    if {'3PM', '3PA'}.issubset(mine.columns):
        attempts = pd.to_numeric(mine['3PA'], errors='coerce')
        makes = pd.to_numeric(mine['3PM'], errors='coerce')
        mine['3P%'] = (makes / attempts.where(attempts > 0)) * 100

    # Stacked one-per-row, not the 2-per-row grid an earlier team-vs-team
    # version used - this panel is now a half-width column, so a 2-across
    # grid would cramp each chart to a quarter of the page's width.
    shown_any = False
    for stat, suffix in _PLAYER_TREND_STATS:
        if stat not in mine.columns:
            continue
        dates, values, avg = player_trend_series(mine, stat, n=10)
        st.markdown(f"_{stat} — last {len(values)} games_")
        if len(values) >= 2:
            render_trend_line(dates, values, avg=avg, avg_label='season avg', y_suffix=suffix, height=150)
            shown_any = True
        else:
            st.caption("Not enough games yet for a trend.")
    if shown_any:
        st.caption("Green points are above the season average, red are below — a run of green is a player heating up.")


def _position_map_for_matchup(matchup_df, season):
    """{athleteSourceId(str): position_bucket} for every opposing player in
    `matchup_df` (data.loaders.load_positional_matchup_data output).

    Prefers the 'Position' column directly on `matchup_df` when present -
    the ESPN/SportsDataverse source (see data.loaders.load_positional_
    matchup_data) carries athlete_position_name on every row, so no extra
    lookup is needed at all for those rows: zero CBBD roster calls. Only
    rows without a usable Position (the CBBD-fallback path, which doesn't
    carry position) fall back to pulling that opponent's roster - already
    independently cached per-team, so this reuses whatever's already been
    fetched elsewhere this session/week rather than adding new API
    surface."""
    if matchup_df is None or matchup_df.empty:
        return {}
    pos_map = {}
    has_position_col = 'Position' in matchup_df.columns
    if has_position_col:
        with_pos = matchup_df.dropna(subset=['Position', 'athleteSourceId'])
        for _, r in with_pos.iterrows():
            pos_map[str(r['athleteSourceId'])] = position_bucket(r['Position'])
    missing_position = matchup_df[~matchup_df['athleteSourceId'].astype(str).isin(pos_map)] if has_position_col else matchup_df
    for opp in missing_position['Opponent Team'].dropna().unique():
        roster = load_team_roster(opp, season)
        if roster.empty:
            continue
        for _, r in roster.iterrows():
            sid = r.get('sourceId')
            if sid is not None and str(sid) not in pos_map:
                pos_map[str(sid)] = position_bucket(r.get('position'))
    return pos_map


def _render_team_defense_panel(season, teams_df):
    team_names = sorted(teams_df['Team'].dropna().unique().tolist())
    if not team_names:
        st.info("No team data available.")
        return
    default_team = 'Duke' if 'Duke' in team_names else team_names[0]
    team = st.selectbox("Team", team_names, index=team_names.index(default_team), key="ma_def_team")

    team_stats = load_all_team_season_stats(season)
    if team_stats.empty:
        st.info("Team defense profile needs /stats/team/season data, which isn't available right now.")
        return

    # Pace: already pulled by load_all_team_season_stats (t.get('pace') off
    # /stats/team/season - no new API call needed), just not previously
    # surfaced on this panel. Shown as a plain st.metric, NOT folded into
    # the percentile bars below - pace isn't itself "good" or "bad" defense
    # the way an allowed-rate stat is, so running it through the same
    # green/red percentile-bar treatment would misleadingly imply a fast
    # pace is a defensive strength or weakness. It's context for reading
    # the rate stats instead: a fast-paced team allows more RAW points/
    # rebounds/assists per game than its per-possession rates alone would
    # suggest, just because the game has more possessions in it.
    pace_row = team_stats[team_stats['Team'] == team]
    pace = pace_row.iloc[0]['Pace'] if not pace_row.empty else None
    if pace is not None and pd.notna(pace):
        st.metric(
            "Pace", f"{float(pace):.1f} poss/40",
            help="Possessions per 40 minutes — tempo, not quality. Context for the rate stats below: a "
                 "fast-paced team gives up more RAW points/rebounds/assists per game even with identical "
                 "per-possession defensive rates, just because there are more possessions to defend.",
        )

    profile_rows = team_defense_profile_rows(team_stats, team)
    if profile_rows:
        st.markdown(f"**{team} — defensive profile (vs D-I)**")
        render_relative_bars(profile_rows)
        st.caption(
            "Percentile vs all of D-I, correct direction per column baked in — an ALLOWED rate/percentage is "
            "colored good when it's LOW; this team's own DREB% and TO ratio forced are colored good when HIGH."
        )
    else:
        st.info(f"No defensive profile available for {team} yet.")

    st.markdown("---")
    st.markdown(f"**{team} — positional matchup defense**")
    st.caption(
        f"What opposing Guards/Forwards/Centers have actually done against {team} this season, relative to "
        "those same players' own season averages — the 'is this defense good against guards or against bigs' "
        "question. Built from this team's own recent games, preferring a free ESPN season file (zero CBBD-quota "
        "cost) and falling back to CBBD's API (~1 call per opponent already faced) only where that free file "
        "isn't available or fresh yet — see HANDOFF.md for the full architecture and caveats."
    )
    recent_games_cap = st.slider(
        "Games to include (most recent)", min_value=5, max_value=30, value=20, step=5,
        key="ma_pos_defense_window",
        help="Lower = fewer CBBD calls (only matters on the fallback) and a more current read; higher = more complete.",
    )
    trigger_key = f"ma_pos_defense_loaded_{season}_{team}_{recent_games_cap}"
    triggered = st.session_state.get(trigger_key, False)
    if not triggered:
        if st.button("Load positional matchup defense", key="ma_load_pos_defense"):
            st.session_state[trigger_key] = True
            triggered = True
        else:
            st.info(f"Click above to pull it — free where possible, up to ~{recent_games_cap} CBBD calls otherwise.")
            return

    with st.spinner(f"Loading {team}'s opponent game logs..."):
        matchup_df = load_positional_matchup_data(team, season, max_recent_games=recent_games_cap)
    if matchup_df.empty:
        st.info(f"No opponent game log data available for {team} yet.")
        return
    pos_map = _position_map_for_matchup(matchup_df, season)
    summary = positional_defense_summary(matchup_df, pos_map)
    if summary.empty:
        st.info(
            f"No position-bucketed data for {team} yet — either not enough opponent games loaded, or the "
            "roster position field didn't match a recognized Guard/Forward/Center pattern (see HANDOFF.md)."
        )
        return
    display = summary.set_index('Bucket')
    st.dataframe(
        style_plain_dataframe(display, diverging_cols={
            'Points Delta': _safe_max_abs(display['Points Delta']),
            'Rebounds Delta': _safe_max_abs(display['Rebounds Delta']),
            'Assists Delta': _safe_max_abs(display['Assists Delta']),
        }),
        width="stretch", height=df_auto_height(len(display)),
    )
    st.caption(
        "Allowed = mean stat line in games against this team. Delta = allowed minus that player's OWN "
        "season average (green = outperforming their normal production against this team; red = held below it)."
    )

    # Position-group picker + all three stats for whichever bucket is
    # selected, rather than every bucket's Points-only trend stacked at
    # once (3 buckets x 3 stats = 9 charts was too long a page) - Rebounds/
    # Assists trend data was already available from load_positional_
    # matchup_data (positional_defense_trend takes any stat column present
    # on matchup_df), it just wasn't wired into the UI before. Key
    # incorporates team/season/games-cap so switching teams can't leave a
    # stale bucket selection that isn't in the new options list.
    bucket_options = summary['Bucket'].tolist()
    selected_bucket = st.selectbox(
        "Position group", bucket_options, key=f"ma_pos_defense_bucket_{team}_{season}_{recent_games_cap}",
    )
    for stat in ('Points', 'Rebounds', 'Assists'):
        dates, values = positional_defense_trend(matchup_df, pos_map, selected_bucket, stat)
        st.markdown(f"_{selected_bucket}s — {stat.lower()} allowed, over time_")
        if len(values) >= 2:
            render_trend_line(dates, values, avg=sum(values) / len(values), avg_label='avg', height=150)
        else:
            st.caption("Not enough games yet for a trend.")
