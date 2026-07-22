"""
NET & Resume tab: real NET rank + Quad 1-4 records, via a manual (never
automatic) fetch from ncaa.com's official rankings page. No free API
exposes this data - checked CollegeBasketballData.com's full API spec
directly (no "/net"/"/quad"/"/resume" path exists anywhere in it) and
ESPN's hidden API directly (their rankings endpoint ignores a `type=net`
param and just returns the same AP/Coaches poll data; their own NET page
404s; no NET/Quad field appears anywhere in their standings response
either) before concluding this. ncaa.com's own page IS the real data, but
it's server-rendered HTML with no JSON API behind it, and NCAA.org's terms
of service prohibit automated access - see data.loaders.fetch_net_rankings_manual
for why this is a deliberate, explicitly user-authorized exception to this
app's normal "prefer free APIs over scraping" policy, and why it's wired
as a manual button click rather than anything automatic.

AP/Coaches poll tracking (CBBD, fully automatic/live) stays as a secondary
section below - it's real, free, complementary data, not a substitute
anymore now that real NET/Quad data is available.
"""
import streamlit as st

from config import AVAILABLE_SEASONS
from data.loaders import (
    current_cbb_season, fetch_net_rankings_manual, list_cbb_poll_types, load_latest_poll,
    _fetch_rankings_raw, team_color_map,
)
from data.transforms import poll_trajectory
from ui.components import render_coming_soon
from ui.charts import render_rank_trajectory
from ui.styling import style_plain_dataframe, df_auto_height, build_column_help_config

_NET_DISPLAY_COLS = ['Rank', 'Team', 'Conference', 'Record', 'Prev', 'Quad 1', 'Quad 2', 'Quad 3', 'Quad 4']


def render():
    st.markdown("**NET Rankings &amp; Quad Records**")

    if st.button("Fetch latest NET rankings from NCAA.com"):
        st.session_state['net_data_fetched'] = True

    if st.session_state.get('net_data_fetched'):
        with st.spinner("Fetching NCAA.com..."):
            net_df = fetch_net_rankings_manual()
        if net_df.empty:
            st.warning("Couldn't fetch or parse NCAA.com's NET rankings page right now — try again in a moment.")
        else:
            filter_text = st.text_input("Filter by team name", key="nr_net_filter")
            shown = net_df
            if filter_text:
                shown = net_df[net_df['Team'].str.contains(filter_text, case=False, na=False)]
            cols = [c for c in _NET_DISPLAY_COLS if c in shown.columns]
            # 'Team' stays a real COLUMN here (not the index) - Streamlit's
            # dataframe grid doesn't render Styler colors on index/row-
            # header cells at all (confirmed live), only on data columns,
            # so a `.set_index('Team')` here would silently render every
            # row with no team color - see style_plain_dataframe's
            # docstring. hide_index=True + a plain sequential index instead.
            display_df = shown[cols].reset_index(drop=True)
            net_colors = team_color_map()
            st.dataframe(
                style_plain_dataframe(display_df, team_color_map=net_colors),
                width="stretch", height=df_auto_height(min(len(display_df), 30)), hide_index=True,
            )
            st.caption(f"{len(shown)} of {len(net_df)} teams shown. Source: ncaa.com.")
    else:
        st.info("Click above to fetch real NET rank and Quad 1-4 records.")

    st.markdown("---")
    st.markdown("**Polls (AP / Coaches)**")

    default_season = current_cbb_season()
    seasons = AVAILABLE_SEASONS if default_season in AVAILABLE_SEASONS else [default_season] + AVAILABLE_SEASONS
    c1, c2 = st.columns([1, 2])
    with c1:
        season = st.selectbox("Season", seasons, index=seasons.index(default_season), format_func=lambda y: f"{y - 1}-{str(y)[2:]}", key="nr_season")

    poll_types = list_cbb_poll_types(season)
    if not poll_types:
        render_coming_soon(
            eyebrow="NEEDS SETUP",
            blurb="No CollegeBasketballData.com API key is configured yet (or the request failed).",
            data_sources=["CollegeBasketballData.com API — /rankings"],
        )
        return

    with c2:
        default_idx = poll_types.index('AP Top 25') if 'AP Top 25' in poll_types else 0
        poll_type = st.selectbox("Poll", poll_types, index=default_idx, key="nr_poll")

    df, week = load_latest_poll(season, poll_type)
    if df.empty:
        st.info("No poll data available for this selection.")
        return

    st.caption(f"Week {week}, {season - 1}-{str(season)[2:]} season")
    # 'Team' stays a real column - see the NET table's comment above on why
    # `.set_index('Team')` would silently defeat the team coloring below.
    display_df = df.reset_index(drop=True)
    column_config = build_column_help_config(display_df, pinned_cols=['Rank'])
    poll_colors = team_color_map(season)
    st.dataframe(
        style_plain_dataframe(display_df, team_color_map=poll_colors),
        width="stretch", height=df_auto_height(len(display_df)),
        column_config=column_config, hide_index=True,
    )
    st.caption("Source: CollegeBasketballData.com.")

    # --- Season-long rank trajectories --------------------------------------
    # The raw /rankings payload above is already the FULL season history
    # (every week, every poll) - the table shows only the latest week, so
    # the trajectory chart below is pure re-use of the same cached call.
    st.markdown("<div class='custom-section-header'>RANK TRAJECTORY</div>", unsafe_allow_html=True)
    raw = _fetch_rankings_raw(season)
    all_teams = sorted({r.get('team') for r in raw if r.get('pollType') == poll_type and r.get('team')})
    picked = st.multiselect(
        "Teams (default: current top 10)", all_teams, key="nr_traj_teams",
        help="Every team that appeared in this poll at any point this season is selectable.",
    )
    pivot, labels = poll_trajectory(raw, poll_type, teams=picked or None, top_n=10)
    if pivot.empty:
        st.info("No trajectory data for this poll.")
        return
    render_rank_trajectory(pivot, labels, team_color_map(season))
