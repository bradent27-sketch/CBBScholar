"""Conference Standings tab: live via ESPN's public standings endpoint - the
one tab in this shell wired to real data, since it needs zero setup (no API
key) to work right now."""
import streamlit as st

from config import AVAILABLE_SEASONS_WITH_UPCOMING
from data.loaders import current_cbb_season, list_conferences, load_conference_standings
from ui.styling import style_plain_dataframe, df_auto_height, build_column_help_config


def render():
    st.markdown("<div class='custom-section-header'>CONFERENCE STANDINGS</div>", unsafe_allow_html=True)

    default_season = current_cbb_season()
    seasons = AVAILABLE_SEASONS_WITH_UPCOMING if default_season in AVAILABLE_SEASONS_WITH_UPCOMING else [default_season] + AVAILABLE_SEASONS_WITH_UPCOMING
    col_season, col_conf = st.columns([1, 2])
    with col_season:
        season = st.selectbox("Season", seasons, index=seasons.index(default_season), format_func=lambda y: f"{y - 1}-{str(y)[2:]}")

    conferences = list_conferences(season)
    if not conferences:
        st.warning(
            "Couldn't reach ESPN's standings endpoint just now. This is a live network call, "
            "not local data, so a transient outage or connectivity hiccup shows up here - "
            "try reloading in a moment."
        )
        return

    with col_conf:
        labels = [name for name, _ in conferences]
        abbr_by_label = dict(conferences)
        default_conf_idx = next((i for i, (n, _) in enumerate(conferences) if n == 'Big Ten Conference'), 0)
        selected_label = st.selectbox("Conference", labels, index=default_conf_idx)
    conf_abbr = abbr_by_label[selected_label]

    df = load_conference_standings(season, conf_abbr)
    if df.empty:
        st.info("No standings data available for this conference/season yet.")
        return

    indexed = df.reset_index(drop=True)
    indexed.index = indexed.index + 1
    indexed.index.name = 'Rank'
    column_config = build_column_help_config(indexed)
    st.dataframe(
        style_plain_dataframe(indexed),
        width="stretch", height=df_auto_height(len(indexed)),
        column_config=column_config,
    )
    st.caption(
        "Source: ESPN (public, no key required). Sorted by ESPN's own conference "
        "ordering (playoff seed). Tiebreaker detail, NET-adjusted views, and "
        "non-conference (overall) standings land in the data-wiring pass."
    )
