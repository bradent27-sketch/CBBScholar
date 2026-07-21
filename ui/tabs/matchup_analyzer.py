"""
Matchup Analyzer tab: head-to-head projection from each team's adjusted net
rating, live via CollegeBasketballData.com, upgraded with four analytical
layers: a venue adjustment (~3-point home-court constant), a tempo-based
projected FINAL SCORE (net ratings are per-100-possessions; combining both
teams' pace from /stats/team/season turns the per-possession edge into an
actual score and total), Dean Oliver's Four Factors matched unit-vs-unit
(each side's factor percentile-ranked against all of D-I), and last-5 form
strips with Elo trend from /games. Still explicitly labeled an estimate,
not a possession-by-possession simulation.

Three sub-tabs (lazily rendered, same tab.open + key/on_change="rerun"
pattern used elsewhere in this app so an unopened sub-tab costs nothing):
OVERVIEW (the original projection/efficiency/four-factors/style/form
content), TEAM DEFENSE (general defensive shape vs D-I plus the positional
matchup defense breakdown - what opposing guards/forwards/centers have
actually done against this team, relative to their own season averages),
and PLAYER TRENDS (pick any player from either roster - tendency
percentiles plus a last-10-games-vs-season-average trend line). See
HANDOFF.md for the full data-architecture writeup behind Team Defense and
Player Trends, including the position-granularity caveat that could not be
verified live in this pass (this sandbox's network policy blocked reaching
the API directly).
"""
import math

import pandas as pd
import streamlit as st

from config import AVAILABLE_SEASONS
from data.loaders import (
    current_cbb_season, load_efficiency_ratings, load_all_team_season_stats, load_team_games,
    load_team_roster, load_positional_matchup_data, get_player_season_stats, load_player_game_logs,
    load_conference_player_season_stats, load_all_player_season_stats, load_teams,
)
from data.transforms import (
    four_factors_matchup, style_profile, project_score, recent_form, pct_rank,
    team_defense_profile, position_bucket, positional_defense_summary, positional_defense_trend,
    player_percentile_rows, player_trend_series,
)
from ui.components import render_coming_soon, render_hero_tiles, render_stat_tiles
from ui.charts import render_mirror_bars, render_form_strip, render_trend_line, render_relative_bars
from ui.styling import style_plain_dataframe, df_auto_height

# Standard CBB home-court advantage in points (~3 historically, all venues
# pooled) - a flat constant, not a per-arena model.
HOME_COURT_POINTS = 3.0

_PLAYER_TREND_STATS = [('Points', ''), ('3PA', ' att'), ('Assists', ''), ('Usage', '%')]

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


def _margin_to_win_prob(margin, scale=11.0):
    """Logistic approximation calibrated loosely to typical CBB game-margin
    variance - a single-number translation of the net-rating differential,
    not a full simulation."""
    return 1 / (1 + math.exp(-margin / scale))


def _fmt(v, decimals=1, suffix=''):
    try:
        return f"{float(v):.{decimals}f}{suffix}"
    except (TypeError, ValueError):
        return '--'


def _safe_max_abs(series):
    m = series.abs().max()
    return float(m) if pd.notna(m) and m else 1.0


def render():
    st.markdown("<div class='custom-section-header'>MATCHUP ANALYZER</div>", unsafe_allow_html=True)

    default_season = current_cbb_season()
    seasons = AVAILABLE_SEASONS if default_season in AVAILABLE_SEASONS else [default_season] + AVAILABLE_SEASONS
    season = st.selectbox("Season", seasons, index=seasons.index(default_season), format_func=lambda y: f"{y - 1}-{str(y)[2:]}", key="ma_season")

    ratings = load_efficiency_ratings(season)
    if ratings.empty:
        render_coming_soon(
            eyebrow="NEEDS SETUP",
            blurb="No CollegeBasketballData.com API key is configured yet (or the request failed). Add cbbd_api_key to .streamlit/secrets.toml — see DATA_SOURCES.md.",
            data_sources=["CollegeBasketballData.com API — /ratings/adjusted"],
        )
        return

    teams = sorted(ratings['Team'].dropna().unique().tolist())
    c1, c2, c3 = st.columns([2, 2, 1.4])
    with c1:
        team_a = st.selectbox("Team A", teams, index=teams.index('Duke') if 'Duke' in teams else 0, key="ma_team_a")
    with c2:
        default_b = next((t for t in teams if t != team_a), teams[0])
        team_b = st.selectbox("Team B", teams, index=teams.index(default_b), key="ma_team_b")
    with c3:
        venue = st.selectbox("Venue", ["Neutral court", f"At {team_a}", f"At {team_b}"], key="ma_venue")

    row_a = ratings[ratings['Team'] == team_a].iloc[0]
    row_b = ratings[ratings['Team'] == team_b].iloc[0]
    team_stats = load_all_team_season_stats(season)

    st.markdown(f"<div class='custom-section-header'>{team_a} vs {team_b}</div>", unsafe_allow_html=True)

    hca = HOME_COURT_POINTS if venue == f"At {team_a}" else (-HOME_COURT_POINTS if venue == f"At {team_b}" else 0.0)
    margin = float(row_a['Net Rating']) - float(row_b['Net Rating']) + hca

    # Headline hero callout - kept, but intentionally not the main event
    # anymore: pace/ratings/style below are what this tab gets used for
    # most, per how this app actually gets used day to day.
    hero_win_prob_a = _margin_to_win_prob(margin) * 100
    if margin >= 0:
        leader, leader_prob = team_a, hero_win_prob_a
    else:
        leader, leader_prob = team_b, 100 - hero_win_prob_a
    hca_sub = f"per 100 poss, incl. {HOME_COURT_POINTS:+.1f} HCA" if hca else "per 100 poss (neutral court)"
    render_hero_tiles([
        {'label': 'Projected Winner', 'value_str': leader, 'sub': f"{leader_prob:.0f}% win probability"},
        {'label': 'Projected Edge', 'value_str': f"{abs(margin):.1f}", 'sub': hca_sub},
    ])
    win_prob_a = _margin_to_win_prob(margin) * 100
    st.progress(win_prob_a / 100, text=f"{team_a} win probability: {win_prob_a:.0f}%")

    # --- Team snapshot: pace/off/def up front, before anything else -------
    st.markdown("<div class='custom-section-header'>TEAM SNAPSHOT</div>", unsafe_allow_html=True)
    snap_a, snap_b = st.columns(2)
    pace_a = pace_b = None
    if not team_stats.empty:
        ts_a = team_stats[team_stats['Team'] == team_a]
        ts_b = team_stats[team_stats['Team'] == team_b]
        pace_a = float(ts_a.iloc[0]['Pace']) if not ts_a.empty and pd.notna(ts_a.iloc[0]['Pace']) else None
        pace_b = float(ts_b.iloc[0]['Pace']) if not ts_b.empty and pd.notna(ts_b.iloc[0]['Pace']) else None
    for col, team, row, pace in ((snap_a, team_a, row_a, pace_a), (snap_b, team_b, row_b, pace_b)):
        with col:
            st.markdown(f"**{team}**")
            entries = [
                {'label': 'Net Rating', 'value_str': _fmt(row['Net Rating'])},
                {'label': 'Off Rating', 'value_str': _fmt(row['Off Rating'])},
                {'label': 'Def Rating', 'value_str': _fmt(row['Def Rating'])},
                {'label': 'Pace', 'value_str': _fmt(pace) if pace is not None else '--'},
            ]
            render_stat_tiles(entries)
    st.caption("Pace: possessions per 40 minutes (tempo, not quality). Off/Def Rating: adjusted points per 100 possessions (Def: lower = better).")

    sub_overview, sub_defense, sub_players = st.tabs(
        ["OVERVIEW", "TEAM DEFENSE", "PLAYER TRENDS"], key="ma_subtab", on_change="rerun",
    )
    if sub_overview.open:
        with sub_overview:
            _render_overview(season, team_a, team_b, row_a, row_b, ratings, team_stats, margin, hca)
    if sub_defense.open:
        with sub_defense:
            _render_team_defense(season, team_a, team_b, team_stats)
    if sub_players.open:
        with sub_players:
            _render_player_trends(season, team_a, team_b)


def _render_overview(season, team_a, team_b, row_a, row_b, ratings, team_stats, margin, hca):
    m1, m2, m3 = st.columns(3)
    m1.metric(f"{team_a} Net Rating", f"{row_a['Net Rating']:.1f}", f"Rank #{int(row_a['Rank'])}" if row_a['Rank'] == row_a['Rank'] else None)
    m2.metric(f"{team_b} Net Rating", f"{row_b['Net Rating']:.1f}", f"Rank #{int(row_b['Rank'])}" if row_b['Rank'] == row_b['Rank'] else None)
    m3.metric("Projected Edge (per 100 poss)", f"{team_a if margin >= 0 else team_b} by {abs(margin):.1f}",
              f"incl. {HOME_COURT_POINTS:+.1f} home court" if hca else "neutral court")

    # --- Projected score (tempo x efficiency) ------------------------------
    if not team_stats.empty:
        proj = project_score(ratings, team_stats, team_a, team_b, hfa_margin=hca)
        if proj:
            st.markdown("<div class='custom-section-header'>PROJECTED SCORE</div>", unsafe_allow_html=True)
            s1, s2, s3, s4 = st.columns(4)
            s1.metric(team_a, f"{proj['score_a']:.0f}")
            s2.metric(team_b, f"{proj['score_b']:.0f}")
            s3.metric("Projected Total", f"{proj['total']:.0f}")
            s4.metric("Tempo (poss)", f"{proj['possessions']:.0f}")
            st.caption(
                "Adjusted offensive/defensive ratings (points per 100 possessions vs the D-I average) scaled "
                "by the two teams' average pace — an estimate of how the per-possession edge cashes out at "
                "this game's likely tempo, not a simulation."
            )

    # --- Unit vs unit: adjusted efficiency ---------------------------------
    st.markdown("<div class='custom-section-header'>UNIT VS UNIT (ADJUSTED EFFICIENCY)</div>", unsafe_allow_html=True)
    unit_rows = []
    for off_team, off_row, def_team, def_row in ((team_a, row_a, team_b, row_b), (team_b, row_b, team_a, row_a)):
        unit_rows.append({
            'label': f"{off_team} O vs {def_team} D",
            'help': f"{off_team}'s adjusted offensive rating against {def_team}'s adjusted defensive rating (defense: lower = better, percentile already inverted).",
            'left_val_str': _fmt(off_row['Off Rating']),
            'left_pct': pct_rank(ratings['Off Rating'], off_row['Off Rating'], higher_is_better=True),
            'right_val_str': _fmt(def_row['Def Rating']),
            'right_pct': pct_rank(ratings['Def Rating'], def_row['Def Rating'], higher_is_better=False),
        })
    render_mirror_bars("Offense", "Defense", unit_rows)

    # --- Four Factors -------------------------------------------------------
    if not team_stats.empty:
        rows_ab, rows_ba = four_factors_matchup(team_stats, team_a, team_b)
        if rows_ab:
            st.markdown("<div class='custom-section-header'>FOUR FACTORS — WHERE GAMES ARE WON</div>", unsafe_allow_html=True)
            st.caption(
                "Dean Oliver's four factors, matched unit against unit. Bar length and color = D-I percentile "
                "with the correct 'better' direction per side, so on BOTH sides a long bar means that team is "
                "winning this specific battle. Hover any bar for the raw value."
            )
            tab_ab, tab_ba = st.tabs([f"{team_a} offense vs {team_b} defense", f"{team_b} offense vs {team_a} defense"])
            for tab, rows, off_t, def_t in ((tab_ab, rows_ab, team_a, team_b), (tab_ba, rows_ba, team_b, team_a)):
                with tab:
                    render_mirror_bars(
                        f"{off_t} offense", f"{def_t} defense",
                        [{**r,
                          'left_val_str': _fmt(r['off_val'], 2 if 'TO' in r['label'] else 1),
                          'left_pct': r['off_pct'],
                          'right_val_str': _fmt(r['def_val'], 2 if 'TO' in r['label'] else 1),
                          'right_pct': r['def_pct']} for r in rows],
                    )

        # --- Style profile --------------------------------------------------
        style_rows = style_profile(team_stats, team_a, team_b)
        if style_rows:
            st.markdown("<div class='custom-section-header'>STYLE PROFILE</div>", unsafe_allow_html=True)
            st.caption(
                "How each offense generates its points (tempo, three-point volume, paint share, transition share). "
                "Descriptive contrast — percentile shows where each team sits across D-I, not who is better."
            )
            render_mirror_bars(
                team_a, team_b,
                [{'label': r['label'], 'help': r['help'],
                  'left_val_str': _fmt(r['left_val']), 'left_pct': r['left_pct'],
                  'right_val_str': _fmt(r['right_val']), 'right_pct': r['right_pct']} for r in style_rows],
            )

    # --- Recent form --------------------------------------------------------
    st.markdown("<div class='custom-section-header'>RECENT FORM (LAST 5)</div>", unsafe_allow_html=True)
    with st.spinner("Loading results..."):
        games_a = load_team_games(team_a, season)
        games_b = load_team_games(team_b, season)
    chips_a, elo_a = recent_form(games_a)
    chips_b, elo_b = recent_form(games_b)
    render_form_strip(team_a, chips_a, elo_a)
    render_form_strip(team_b, chips_b, elo_b)
    st.caption("Hover a chip for the score and opponent. Elo trend spans the shown window (Elo via CollegeBasketballData.com).")

    st.caption(
        "Projected edge, score, and win probability are estimates from adjusted ratings plus a flat "
        f"{HOME_COURT_POINTS}-point home-court constant when a venue is chosen — injuries, matchup-specific "
        "lineups, and shot-variance aren't modeled."
    )


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


def _render_team_defense(season, team_a, team_b, team_stats):
    st.caption(
        "General defensive shape vs D-I, plus what opposing Guards/Forwards/Centers have actually done against "
        "each team this season relative to those same players' own season averages — the 'is this defense good "
        "against guards or against bigs' question."
    )
    if team_stats.empty:
        st.info("Team defense profile needs /stats/team/season data, which isn't available right now.")
        return

    profile_rows = team_defense_profile(team_stats, team_a, team_b)
    if profile_rows:
        st.markdown("**General Defensive Profile (vs D-I)**")
        render_mirror_bars(
            team_a, team_b,
            [{'label': r['label'], 'help': r['help'],
              'left_val_str': _fmt(r['left_val']), 'left_pct': r['left_pct'],
              'right_val_str': _fmt(r['right_val']), 'right_pct': r['right_pct']} for r in profile_rows],
        )
        st.caption(
            "Percentile vs all of D-I, correct direction per column baked in — an ALLOWED rate/percentage is "
            "colored good when it's LOW; this team's own DREB% and TO ratio forced are colored good when HIGH."
        )

    st.markdown("---")
    st.markdown("**Positional Matchup Defense**")
    st.caption(
        f"Built from {team_a} and {team_b}'s own recent games, preferring a free ESPN season file (zero "
        "CBBD-quota cost, whole D-I already in one place) and falling back to CBBD's API — roughly one call per "
        "opponent already faced — only where that free file isn't available yet or is stale (most likely early in "
        "a brand-new season). CBBD's free tier caps out at 1,000 calls/month, so this stays capped to each team's "
        "most recent games either way. See HANDOFF.md for the full architecture and the caveats (position-field "
        "granularity and the ESPN source's freshness couldn't be verified live against a real payload)."
    )
    recent_games_cap = st.slider(
        "Games per team to include (most recent)", min_value=5, max_value=30, value=20, step=5,
        key="ma_pos_defense_window",
        help="Lower = fewer CBBD calls (only matters if the free ESPN source isn't available/fresh for this team) "
             "and a more CURRENT read on each defense; higher = more complete but costs more quota on the fallback.",
    )
    trigger_key = f"ma_pos_defense_loaded_{season}_{recent_games_cap}"
    triggered = st.session_state.get(trigger_key, False)
    if not triggered:
        if st.button("Load positional matchup defense", key="ma_load_pos_defense"):
            st.session_state[trigger_key] = True
            triggered = True
        else:
            st.info(f"Click above to pull it — free where possible, up to ~{recent_games_cap} CBBD calls per team otherwise.")
            return

    for team in (team_a, team_b):
        with st.spinner(f"Loading {team}'s opponent game logs..."):
            matchup_df = load_positional_matchup_data(team, season, max_recent_games=recent_games_cap)
        st.markdown(f"**{team} — defense by position**")
        if matchup_df.empty:
            st.info(f"No opponent game log data available for {team} yet.")
            continue
        pos_map = _position_map_for_matchup(matchup_df, season)
        summary = positional_defense_summary(matchup_df, pos_map)
        if summary.empty:
            st.info(
                f"No position-bucketed data for {team} yet — either not enough opponent games loaded, or the "
                "roster position field didn't match a recognized Guard/Forward/Center pattern (see HANDOFF.md)."
            )
            continue
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
        trend_cols = st.columns(max(len(summary), 1))
        for col, bucket in zip(trend_cols, summary['Bucket']):
            dates, values = positional_defense_trend(matchup_df, pos_map, bucket, 'Points')
            with col:
                st.markdown(f"_{bucket}s — points allowed, over time_")
                if len(values) >= 2:
                    render_trend_line(dates, values, avg=sum(values) / len(values), avg_label='avg', height=150)
                else:
                    st.caption("Not enough games yet for a trend.")


def _render_player_trends(season, team_a, team_b):
    st.caption(
        "Pick any player from either roster: shot-selection/rebounding/passing tendency percentiles vs D-I or "
        "conference, plus their last 10 games vs their own season average — peaking, cooling off, shooting more "
        "or passing less than usual. This is where an edge shows up before it's obvious in the box score."
    )
    team_choice = st.radio("Team", [team_a, team_b], horizontal=True, key="ma_pt_team")
    roster_df = load_team_roster(team_choice, season)
    if roster_df.empty:
        st.info(f"No roster data for {team_choice}.")
        return
    labels = [f"{r['name']} ({r['position'] or '?'})" for _, r in roster_df.iterrows()]
    sel_label = st.selectbox("Player", labels, key="ma_pt_player")
    sel_row = roster_df.iloc[labels.index(sel_label)]

    with st.spinner("Loading stats..."):
        stats = get_player_season_stats(team_choice, season, sel_row['id'])
    if not stats:
        st.info("No season stats for this player yet.")
        return

    teams_df = load_teams(season)
    conf_series = teams_df.loc[teams_df['Team'] == team_choice, 'Conference'] if not teams_df.empty else pd.Series(dtype=object)
    conf = conf_series.iloc[0] if not conf_series.empty else None

    compare_all = st.checkbox(
        "Compare against all of Division I instead of just this conference (cached ~weekly)",
        key="ma_pt_compare_all",
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

    trend_cols = st.columns(2)
    shown_any = False
    for i, (stat, suffix) in enumerate(_PLAYER_TREND_STATS):
        if stat not in mine.columns:
            continue
        dates, values, avg = player_trend_series(mine, stat, n=10)
        with trend_cols[i % 2]:
            st.markdown(f"_{stat} — last {len(values)} games_")
            if len(values) >= 2:
                render_trend_line(dates, values, avg=avg, avg_label='season avg', y_suffix=suffix, height=150)
                shown_any = True
            else:
                st.caption("Not enough games yet for a trend.")
    if shown_any:
        st.caption("Green points are above the season average, red are below — a run of green is a player heating up.")
