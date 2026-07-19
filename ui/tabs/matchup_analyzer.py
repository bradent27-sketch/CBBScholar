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

import streamlit as st

from config import AVAILABLE_SEASONS
from data.loaders import (
    current_cbb_season, load_efficiency_ratings, load_all_team_season_stats, load_team_games,
)
from data.transforms import four_factors_matchup, style_profile, project_score, recent_form, pct_rank
from ui.components import render_coming_soon
from ui.charts import render_mirror_bars, render_form_strip

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
