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
"""
import math

import pandas as pd
import streamlit as st

from config import AVAILABLE_SEASONS
from data.loaders import (
    current_cbb_season, load_efficiency_ratings, load_all_team_season_stats, load_team_games,
    load_positional_defense_report, load_team_roster, load_player_game_logs, get_player_season_stats,
    load_conference_player_season_stats,
)
from data.transforms import (
    four_factors_matchup, style_profile, defense_profile, project_score, recent_form, pct_rank,
    player_rate_stats, last_n_form,
)
from ui.components import render_coming_soon, render_hero_tiles
from ui.charts import render_mirror_bars, render_form_strip, render_trend_line
from ui.charts import render_relative_bars

# Standard CBB home-court advantage in points (~3 historically, all venues
# pooled) - a flat constant, not a per-arena model.
HOME_COURT_POINTS = 3.0


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

    st.markdown(f"<div class='custom-section-header'>{team_a} vs {team_b}</div>", unsafe_allow_html=True)

    hca = HOME_COURT_POINTS if venue == f"At {team_a}" else (-HOME_COURT_POINTS if venue == f"At {team_b}" else 0.0)
    margin = float(row_a['Net Rating']) - float(row_b['Net Rating']) + hca

    # Headline hero callout - the "who wins and by how much" story up front,
    # before the supporting per-team metrics below.
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

    m1, m2, m3 = st.columns(3)
    m1.metric(f"{team_a} Net Rating", f"{row_a['Net Rating']:.1f}", f"Rank #{int(row_a['Rank'])}" if row_a['Rank'] == row_a['Rank'] else None)
    m2.metric(f"{team_b} Net Rating", f"{row_b['Net Rating']:.1f}", f"Rank #{int(row_b['Rank'])}" if row_b['Rank'] == row_b['Rank'] else None)
    m3.metric("Projected Edge (per 100 poss)", f"{team_a if margin >= 0 else team_b} by {abs(margin):.1f}",
              f"incl. {HOME_COURT_POINTS:+.1f} home court" if hca else "neutral court")

    win_prob_a = _margin_to_win_prob(margin) * 100
    st.progress(win_prob_a / 100, text=f"{team_a} win probability: {win_prob_a:.0f}%")

    team_stats = load_all_team_season_stats(season)

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

        # --- Defense profile (vs league) ------------------------------------
        def_rows = defense_profile(team_stats, team_a, team_b)
        if def_rows:
            st.markdown("<div class='custom-section-header'>DEFENSIVE PROFILE (VS D-I)</div>", unsafe_allow_html=True)
            st.caption(
                "What each defense allows, D-I percentile-ranked (color always reads 'better defense this way', "
                "regardless of whether the raw number is meant to be high or low)."
            )
            render_mirror_bars(
                team_a, team_b,
                [{'label': r['label'], 'help': r['help'],
                  'left_val_str': _fmt(r['left_val']), 'left_pct': r['left_pct'],
                  'right_val_str': _fmt(r['right_val']), 'right_pct': r['right_pct']} for r in def_rows],
            )

    # --- Defense vs position -------------------------------------------------
    st.markdown("<div class='custom-section-header'>DEFENSE VS POSITION</div>", unsafe_allow_html=True)
    st.caption(
        "For every completed game, pulls the opponent's own box score for that game and compares what their "
        "Guards/Wings/Bigs scored/rebounded to their OWN season averages — 'this team lets guards outscore their "
        "average' is a defensive tell no single team-wide stat captures. Built from CollegeBasketballData.com's "
        "existing per-team data (no second source needed); first load per team this session is slow (one pull per "
        "opponent faced), cached 6h after that. Approximate: position buckets come from CBBD's own roster "
        "position field, and back-to-back trades/injuries aren't accounted for."
    )
    with st.spinner("Building defense-vs-position report (first time this session, cached after)..."):
        pos_report_a = load_positional_defense_report(team_a, season)
        pos_report_b = load_positional_defense_report(team_b, season)
    tab_pos_a, tab_pos_b = st.tabs([f"{team_a} defense", f"{team_b} defense"])
    for tab, team_name, report in ((tab_pos_a, team_a, pos_report_a), (tab_pos_b, team_b, pos_report_b)):
        with tab:
            _render_positional_defense(team_name, report)

    # --- Player lens ----------------------------------------------------------
    st.markdown("<div class='custom-section-header'>PLAYER LENS</div>", unsafe_allow_html=True)
    st.caption(
        "Pick one player from either roster: shot-diet/usage percentiles vs their own conference, plus a "
        "last-10-games trend for points, 3PA and assists so you can see who's heating up (or cooling off) right "
        "before this matchup."
    )
    pl1, pl2 = st.columns(2)
    with pl1:
        team_for_player = st.selectbox("Team", [team_a, team_b], key="ma_pl_team")
    roster_df = load_team_roster(team_for_player, season)
    if not roster_df.empty:
        with pl2:
            labels = [f"{r['name']} ({r['position'] or '?'})" for _, r in roster_df.iterrows()]
            sel_label = st.selectbox("Player", labels, key="ma_pl_player")
        sel_row = roster_df.iloc[labels.index(sel_label)]
        _render_player_lens(team_for_player, sel_row, season, ratings)

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


_BUCKET_ORDER = ('Guards', 'Wings', 'Bigs')


def _render_positional_defense(team_name, report):
    """One team's Defense vs Position sub-tab: a summary tile per bucket
    (points/rebounds allowed vs what those opponents normally produce) plus
    a trend line of the points differential game-by-game, so a recent
    upward/downward swing is visible at a glance."""
    if not report or not report.get('season'):
        st.info(f"Not enough per-game opponent data available yet for {team_name}.")
        return
    season_summary = report['season']
    games = report['games']

    cols = st.columns(len(_BUCKET_ORDER))
    for col, bucket in zip(cols, _BUCKET_ORDER):
        s = season_summary.get(bucket)
        with col:
            if not s:
                st.metric(bucket, "--")
                continue
            st.metric(
                f"{bucket} — Pts Allowed", f"{s['avg_pts_allowed']:.1f}",
                f"{s['pts_diff']:+.1f} vs their {s['avg_pts_expected']:.1f} avg",
                delta_color="inverse",
            )
            st.caption(f"Reb: {s['avg_reb_allowed']:.1f} allowed ({s['reb_diff']:+.1f} vs avg) · {s['games']} games")

    bucket_pick = st.selectbox("Trend for", [b for b in _BUCKET_ORDER if b in season_summary],
                                key=f"ma_pos_trend_{team_name}")
    if not bucket_pick:
        return
    trend_games = [g for g in games if bucket_pick in g['buckets']]
    if len(trend_games) < 2:
        st.caption("Not enough games with this position group faced yet for a trend line.")
        return
    diffs = [g['buckets'][bucket_pick]['pts_allowed'] - g['buckets'][bucket_pick]['pts_expected'] for g in trend_games]
    tooltips = [
        f"{g['Date']} vs {g['Opponent']}: {g['buckets'][bucket_pick]['pts_allowed']:.0f} allowed "
        f"({g['buckets'][bucket_pick]['pts_allowed'] - g['buckets'][bucket_pick]['pts_expected']:+.1f} vs their avg)"
        for g in trend_games
    ]
    render_trend_line(diffs, tooltips, zero_line=True, y_label="Pts vs avg")
    st.caption(
        f"Points {bucket_pick.lower()} scored above/below their own season average, game by game (oldest → newest). "
        "Green = this defense held them below their normal production; red = let them outscore it. "
        "Dashed line = 0 (exactly their average)."
    )


def _render_player_lens(team, sel_row, season, ratings):
    stats = get_player_season_stats(team, season, sel_row['id'])
    if not stats:
        st.info("No season stats recorded yet for this player.")
        return
    games = stats.get('games') or 0
    fg = stats.get('fieldGoals') or {}
    three = stats.get('threePointFieldGoals') or {}
    ft = stats.get('freeThrows') or {}
    reb = stats.get('rebounds') or {}
    fga, three_a, fta = fg.get('attempted'), three.get('attempted'), ft.get('attempted')

    def rate(part, whole):
        try:
            return float(part) / float(whole) * 100 if whole else None
        except (TypeError, ValueError, ZeroDivisionError):
            return None

    def per_g(total):
        try:
            return float(total) / games if games else None
        except (TypeError, ValueError):
            return None

    player_values = {
        'PPG': per_g(stats.get('points')), 'RPG': per_g(reb.get('total')), 'APG': per_g(stats.get('assists')),
        'Usage %': stats.get('usage'),
        '3PA Rate': rate(three_a, fga),
        '2PA Rate': rate((fga - three_a) if fga is not None and three_a is not None else None, fga),
        'FT Rate': rate(fta, fga),
    }

    conf_row = ratings[ratings['Team'] == team]
    conference = conf_row.iloc[0]['Conference'] if not conf_row.empty else None
    group_df = load_conference_player_season_stats(conference, season) if conference else pd.DataFrame()
    rates = player_rate_stats(group_df)

    rows = []
    for label, value in player_values.items():
        if value is None:
            continue
        value_str = f"{value:.1f}%" if (label.endswith('%') or label.endswith('Rate')) else f"{value:.1f}"
        pct = avg_pct = None
        if not rates.empty and label in rates.columns:
            dist = rates[label].dropna()
            if not dist.empty:
                pct = pct_rank(dist, value)
                avg_pct = pct_rank(dist, dist.mean())
        rows.append({'label': label, 'value_str': value_str, 'pct': pct, 'avg_pct': avg_pct})
    if rows:
        render_relative_bars(rows)
        st.caption(f"Percentile vs {conference or 'conference'} this season. {games} games played.")

    with st.spinner("Loading recent games..."):
        logs = load_player_game_logs(team, season)
    if logs.empty:
        return
    mine = logs[logs['athleteSourceId'].astype(str) == str(sel_row.get('sourceId'))]
    if mine.empty:
        mine = logs[logs['name'] == sel_row['name']]
    mine = mine.reset_index(drop=True)
    if mine.empty:
        return
    form = last_n_form(mine, cols=('Points', '3PA', 'Assists'), n=10)
    if form:
        cols = st.columns(len(form))
        for c, (stat, (recent, season_avg)) in zip(cols, form.items()):
            c.metric(f"{stat} (L10 vs season)", f"{season_avg:.1f}", f"L10: {recent:.1f} ({recent - season_avg:+.1f})", delta_color="off")
    metric_pick = st.selectbox("Trend for", [c for c in ('Points', 'Rebounds', 'Assists', '3PA') if c in mine.columns],
                                key=f"ma_player_trend_{team}_{sel_row['name']}")
    series = pd.to_numeric(mine[metric_pick], errors='coerce')
    if series.notna().sum() >= 2:
        render_trend_line(series.tolist(), [f"{d} vs {o}: {v:g}" for d, o, v in zip(mine['Date'], mine['Opponent'], series)],
                          zero_line=False, y_label=metric_pick)
        st.caption(f"{metric_pick} per game this season (oldest → newest). Dashed line = this player's own season average.")
