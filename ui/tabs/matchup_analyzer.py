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

Grown well past a single flat scroll (Projected Score, Unit vs Unit, Four
Factors, Style Profile, Matchup Edges, Recent Form, Season Margin Trend all
stacked) - user feedback was "feels like three different pages at once."
Team/venue selection and the headline metrics stay visible above
everything (that context should never scroll out of view), but the rest is
split into sub-tabs by QUESTION being answered: how do the raw numbers
compare (Overview), how does each team actually generate/allow production
(Efficiency & Style), which specific opposing player types exploit this
matchup (Matchup Edges), and how has each team performed recently /
game-to-game (Form & Trends). Same st.tabs() pattern the Four Factors
section already used internally, just applied one level up.
"""
import math

import streamlit as st

from config import AVAILABLE_SEASONS
from data.loaders import (
    current_cbb_season, load_efficiency_ratings, load_all_team_season_stats, load_team_games,
    load_team_roster, load_team_player_stats, load_defense_allowed_by_role, team_color_map,
    get_league_player_stats,
)
from data.transforms import (
    four_factors_matchup, style_profile, project_score, recent_form, pct_rank, margin_volatility,
    player_rate_profile, classify_player_role_best_available, aggregate_defense_by_role,
    defense_role_game_series, league_rate_profiles, ROLE_ORDER,
)
from ui.components import render_coming_soon
from ui.charts import render_mirror_bars, render_form_strip, render_margin_chart, render_role_badges, render_trend_line
from ui.styling import style_plain_dataframe, df_auto_height

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

    m1, m2, m3 = st.columns(3)
    m1.metric(f"{team_a} Net Rating", f"{row_a['Net Rating']:.1f}", f"Rank #{int(row_a['Rank'])}" if row_a['Rank'] == row_a['Rank'] else None)
    m2.metric(f"{team_b} Net Rating", f"{row_b['Net Rating']:.1f}", f"Rank #{int(row_b['Rank'])}" if row_b['Rank'] == row_b['Rank'] else None)
    m3.metric("Projected Edge (per 100 poss)", f"{team_a if margin >= 0 else team_b} by {abs(margin):.1f}",
              f"incl. {HOME_COURT_POINTS:+.1f} home court" if hca else "neutral court")

    win_prob_a = _margin_to_win_prob(margin) * 100
    st.progress(win_prob_a / 100, text=f"{team_a} win probability: {win_prob_a:.0f}%")

    team_stats = load_all_team_season_stats(season)

    tab_overview, tab_style, tab_edges, tab_form = st.tabs([
        "Overview", "Efficiency & Style", "Matchup Edges", "Form & Trends",
    ])
    with tab_overview:
        _render_overview(ratings, team_stats, team_a, team_b, row_a, row_b, hca)
    with tab_style:
        _render_efficiency_style(ratings, team_stats, team_a, team_b, row_a, row_b)
    with tab_edges:
        _render_matchup_edges(team_stats, team_a, team_b, season)
    with tab_form:
        _render_form_and_trends(team_a, team_b, season)

    st.caption(
        "Projected edge, score, and win probability are estimates from adjusted ratings plus a flat "
        f"{HOME_COURT_POINTS}-point home-court constant when a venue is chosen — injuries, matchup-specific "
        "lineups, and shot-variance aren't modeled."
    )


def _render_overview(ratings, team_stats, team_a, team_b, row_a, row_b, hca):
    """Quick numeric snapshot: tempo-adjusted projected score, and the raw
    offense-vs-defense efficiency matchup - the "what do the top-line
    numbers say" answer, no digging required."""
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


def _render_efficiency_style(ratings, team_stats, team_a, team_b, row_a, row_b):
    """How each team actually generates/allows production: Dean Oliver's
    Four Factors matched unit-vs-unit, then a descriptive style contrast
    (tempo, shot selection, transition share)."""
    if team_stats.empty:
        st.info("Four Factors and style data need the CollegeBasketballData.com key configured.")
        return

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


def _render_matchup_edges(team_stats, team_a, team_b, season):
    """The real matchup question: which opposing player TYPES does each
    defense struggle with, and does the other team have that type? Direct
    shooting/rebounding-allowed numbers are free; the full points-by-role
    breakdown is a heavier on-demand pull (see load_defense_allowed_by_role)."""
    colors = team_color_map(season)
    st.caption(
        "No free CBB source publishes 'defense vs. role' directly (checked — see HANDOFF), so the full "
        "breakdown below is built by cross-referencing every opponent's own game log. Shooting/rebounding-"
        "allowed numbers are free (same cached pull as the Efficiency & Style tab); the full points-by-role "
        "breakdown is a heavier on-demand pull."
    )

    if not team_stats.empty:
        da_rows = team_stats[team_stats['Team'] == team_a]
        db_rows = team_stats[team_stats['Team'] == team_b]
        if not da_rows.empty and not db_rows.empty:
            da, db = da_rows.iloc[0], db_rows.iloc[0]
            allowed_rows = []
            for label, col, help_text in (
                ('3PA Rate Allowed', 'Def 3PA Rate', "Share of opponent field goal attempts from three, allowed."),
                ('3P% Allowed', 'Def 3P%', "Opponent three-point percentage, allowed."),
                ('ORB% Allowed', 'Def ORB%', "Opponent offensive rebound rate, allowed."),
            ):
                if col not in team_stats.columns:
                    continue
                allowed_rows.append({
                    'label': label, 'help': help_text,
                    'left_val_str': _fmt(da[col]), 'left_pct': pct_rank(team_stats[col], da[col], higher_is_better=False),
                    'right_val_str': _fmt(db[col]), 'right_pct': pct_rank(team_stats[col], db[col], higher_is_better=False),
                })
            if allowed_rows:
                st.markdown("<div class='custom-section-header'>SHOOTING &amp; REBOUNDING ALLOWED</div>", unsafe_allow_html=True)
                render_mirror_bars(f"{team_a} allows", f"{team_b} allows", allowed_rows)
                st.caption("D-I percentile — longer/greener bar = allows LESS of that shot type (i.e. defends it better).")

    league_rates = league_rate_profiles(get_league_player_stats(season))
    st.markdown("<div class='custom-section-header'>ROSTER TENDENCIES</div>", unsafe_allow_html=True)
    st.caption(
        ("Every rostered player's primary role, ranked against REAL D-I percentiles" if not league_rates.empty else
         "Every rostered player's primary role from a fixed-threshold heuristic (build the League Player "
         "Database on Team Efficiency for real D-I percentiles instead)")
        + " — see Player Search for a single player's full breakdown."
    )
    rc_a, rc_b = st.columns(2)
    for col, team_name in ((rc_a, team_a), (rc_b, team_b)):
        with col:
            st.markdown(f"**{team_name}**")
            roster = load_team_roster(team_name, season)
            player_stats_df = load_team_player_stats(team_name, season)
            if roster.empty or player_stats_df.empty:
                st.caption("No roster/stat data.")
                continue
            merged = player_stats_df.merge(roster[['id', 'name']], left_on='athleteId', right_on='id', how='inner')
            role_groups = {}
            for _, p in merged.iterrows():
                profile = player_rate_profile(p.to_dict())
                role, _, _ = classify_player_role_best_available(profile, league_rates)
                if role:
                    role_groups.setdefault(role, []).append(p['name'])
            if not role_groups:
                st.caption("Not enough minutes logged yet to classify this roster.")
            for role in ROLE_ORDER:
                if role not in role_groups:
                    continue
                pill_color = colors.get(team_name)
                render_role_badges(role, [], primary_color=pill_color)
                st.caption(", ".join(role_groups[role]))

    st.markdown("<div class='custom-section-header'>DEFENSE VS. ROLE — FULL BREAKDOWN</div>", unsafe_allow_html=True)
    st.caption(
        "Up to ~60-90 extra API calls for a full schedule (roster + season-stats + game-log pull per "
        "opponent, less once a League Player Database exists — see Team Efficiency) — not run "
        "automatically. Cached once run, and opponents already viewed elsewhere this session are free."
    )
    edge_a, edge_b = st.columns(2)
    for col, team_name in ((edge_a, team_a), (edge_b, team_b)):
        with col:
            state_key = f"ma_role_data_{team_name}"
            if st.button(f"Analyze {team_name}'s Defense", key=f"ma_analyze_{team_name}"):
                st.session_state[state_key] = True
            if st.session_state.get(state_key):
                with st.spinner(f"Cross-referencing {team_name}'s opponents — this can take a while..."):
                    role_games = load_defense_allowed_by_role(team_name, season)
                if role_games.empty:
                    st.info("Not enough data to compute this yet (schedule or opponent stats unavailable).")
                else:
                    summary = aggregate_defense_by_role(role_games)
                    st.dataframe(style_plain_dataframe(summary), width="stretch", height=df_auto_height(len(summary)))
                    role_pick = st.selectbox("Trend for role", summary.index.tolist(), key=f"ma_role_trend_{team_name}")
                    trend = defense_role_game_series(role_games, role_pick)
                    if not trend.empty and len(trend) >= 2:
                        render_trend_line(trend['Date'].tolist(), trend['Points'].tolist(), window=5, unit=' pts')
                        st.caption(f"Points allowed to {role_pick} per game — rolling 5-game average (violet) vs. season average (dashed). A rising line with the game log still showing the same opponents is the earliest sign of a scheme or personnel change.")


def _render_form_and_trends(team_a, team_b, season):
    """Recent results (last-5 chips + Elo trend) and the full-season
    margin/consistency picture - "how has each team actually been playing,"
    as opposed to the season-long averages everything else on this tab
    uses."""
    st.markdown("<div class='custom-section-header'>RECENT FORM (LAST 5)</div>", unsafe_allow_html=True)
    with st.spinner("Loading results..."):
        games_a = load_team_games(team_a, season)
        games_b = load_team_games(team_b, season)
    chips_a, elo_a = recent_form(games_a)
    chips_b, elo_b = recent_form(games_b)
    render_form_strip(team_a, chips_a, elo_a)
    render_form_strip(team_b, chips_b, elo_b)
    st.caption("Hover a chip for the score and opponent. Elo trend spans the shown window (Elo via CollegeBasketballData.com).")

    st.markdown("<div class='custom-section-header'>SEASON MARGIN TREND &amp; CONSISTENCY</div>", unsafe_allow_html=True)
    st.caption(
        "Every completed game this season, bar height = scoring margin (green = win, red = loss, "
        "split at zero) — same game logs already pulled for Recent Form above, no extra API cost. "
        "A steady team hugs a consistent band; a streaky one swings wide game to game."
    )
    for team, games in ((team_a, games_a), (team_b, games_b)):
        if games is None or games.empty:
            continue
        game_dicts = [{
            'margin': int(g['Margin']),
            'tooltip': f"{g['Result']} {g['PF']}-{g['PA']} {g['Home/Away']} {g['Opponent']} ({g['Date']})",
        } for _, g in games.iterrows()]
        st.markdown(f"**{team}**")
        render_margin_chart(game_dicts)
        vol = margin_volatility(games)
        if vol:
            v1, v2, v3, v4 = st.columns(4)
            v1.metric("Volatility (σ margin)", f"{vol['std']:.1f} pts", help="Population std. dev. of scoring margin — lower means steadier night-to-night performance.")
            v2.metric("Best Margin", f"+{vol['best_margin']}")
            v3.metric("Worst Margin", f"{vol['worst_margin']}")
            v4.metric("Close-Game Record", f"{vol['close_wins']}-{vol['close_losses']}", help="Games decided by 5 points or fewer.")
