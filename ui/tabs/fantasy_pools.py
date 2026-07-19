"""
Fantasy & Pools tab: custom scoring calculator against real season stats,
live via CollegeBasketballData.com. College basketball's fantasy angle
leans toward bracket pools and DFS rather than a season-long draft league,
so this is a standalone scoring calculator - set your rules, see real
fantasy points computed from a player's actual season.
"""
import streamlit as st

from config import AVAILABLE_SEASONS
from data.loaders import current_cbb_season, load_teams, load_team_roster, get_player_season_stats
from ui.components import render_coming_soon

_DEFAULT_SCORING = {
    'points': 1.0, 'rebounds': 1.2, 'assists': 1.5, 'steals': 3.0, 'blocks': 3.0, 'turnovers': -1.0,
}
_SCORING_LABELS = {
    'points': 'Point', 'rebounds': 'Rebound', 'assists': 'Assist',
    'steals': 'Steal', 'blocks': 'Block', 'turnovers': 'Turnover',
}


def render():
    st.markdown("<div class='custom-section-header'>FANTASY &amp; POOLS</div>", unsafe_allow_html=True)
    st.caption(
        "College basketball's fantasy angle leans toward bracket pools and DFS rather than "
        "a season-long draft league, so this tab is a standalone scoring calculator: set "
        "your rules, see real fantasy points computed from a player's actual season."
    )

    default_season = current_cbb_season()
    seasons = AVAILABLE_SEASONS if default_season in AVAILABLE_SEASONS else [default_season] + AVAILABLE_SEASONS
    season = st.selectbox("Season", seasons, index=seasons.index(default_season), format_func=lambda y: f"{y - 1}-{str(y)[2:]}", key="fp_season")

    with st.expander("Scoring settings", expanded=False):
        weights = {}
        cols = st.columns(3)
        for i, (key, label) in enumerate(_SCORING_LABELS.items()):
            with cols[i % 3]:
                weights[key] = st.number_input(f"{label} (pts)", value=_DEFAULT_SCORING[key], step=0.1, key=f"fp_w_{key}")

    teams_df = load_teams(season)
    if teams_df.empty:
        render_coming_soon(
            eyebrow="NEEDS SETUP",
            blurb="No CollegeBasketballData.com API key is configured yet (or the request failed).",
            data_sources=["CollegeBasketballData.com API"],
        )
        return

    team_names = sorted(teams_df['Team'].dropna().unique().tolist())
    c1, c2 = st.columns(2)
    with c1:
        team = st.selectbox("Team", team_names, index=team_names.index('Duke') if 'Duke' in team_names else 0, key="fp_team")
    roster_df = load_team_roster(team, season)
    if roster_df.empty:
        st.info(f"No roster data found for {team} in {season}.")
        return
    with c2:
        labels = [f"{r['name']} ({r['position'] or '?'})" for _, r in roster_df.iterrows()]
        sel_label = st.selectbox("Player", labels, key="fp_player_select")
    sel_row = roster_df.iloc[labels.index(sel_label)]

    stats = get_player_season_stats(team, season, sel_row['id'])
    if not stats:
        st.info("No season stats found for this player yet.")
        return

    reb = stats.get('rebounds') or {}
    stat_values = {
        'points': stats.get('points'), 'rebounds': reb.get('total'), 'assists': stats.get('assists'),
        'steals': stats.get('steals'), 'blocks': stats.get('blocks'), 'turnovers': stats.get('turnovers'),
    }
    games = stats.get('games') or 1

    total = 0.0
    breakdown = []
    for key, weight in weights.items():
        val = stat_values.get(key)
        if val is None:
            continue
        pts = float(val) * weight
        total += pts
        if pts != 0:
            breakdown.append((_SCORING_LABELS[key], val, weight, pts))

    st.markdown(f"<div class='custom-section-header'>{sel_row['name']} — {season - 1}-{str(season)[2:]} FANTASY POINTS</div>", unsafe_allow_html=True)
    m1, m2 = st.columns(2)
    m1.metric("Total Season Fantasy Points", f"{total:.1f}")
    m2.metric("Per-Game Average", f"{total / games:.1f}")

    if breakdown:
        st.markdown("**Breakdown (season totals)**")
        for label, val, weight, pts in breakdown:
            st.caption(f"{label}: {val} × {weight:+.2f} = {pts:+.1f} pts")
    st.caption("Season-total scoring — per-game/DFS-style scoring and bracket-pool tooling land in a later pass.")
