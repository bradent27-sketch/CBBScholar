"""Transfer Portal tab: portal entry tracker plus recruiting class rankings,
live via CollegeBasketballData.com. CORRECTION vs. this app's original
DATA_SOURCES.md: that doc claimed no clean free composite recruiting API
exists for college basketball - checked CBBD's API spec directly while
building this and found /recruiting/players does exactly that, same as
CFBD does for football. Fixed here and in DATA_SOURCES.md."""
import streamlit as st

from config import AVAILABLE_SEASONS
from data.loaders import current_cbb_season, load_recruiting_rankings, load_transfer_portal
from ui.components import render_coming_soon
from ui.styling import style_plain_dataframe, df_auto_height


def render():
    st.markdown("<div class='custom-section-header'>TRANSFER PORTAL</div>", unsafe_allow_html=True)

    default_season = current_cbb_season()
    seasons = AVAILABLE_SEASONS if default_season in AVAILABLE_SEASONS else [default_season] + AVAILABLE_SEASONS
    season = st.selectbox("Season", seasons, index=seasons.index(default_season), format_func=lambda y: f"{y - 1}-{str(y)[2:]}", key="tp_season")

    st.markdown("**Recruiting Class Rankings**")
    recruits = load_recruiting_rankings(season)
    if recruits.empty:
        render_coming_soon(
            eyebrow="NEEDS SETUP",
            blurb="No CollegeBasketballData.com API key is configured yet (or the request failed).",
            data_sources=["CollegeBasketballData.com API — /recruiting/players"],
        )
        return

    # NOT indexed on Rank: recruiting ranks can repeat/be null (same
    # pandas Styler non-unique-index issue hit and fixed elsewhere in both
    # apps' ratings tables) - a clean sequential index sidesteps it
    # regardless of what the underlying data contains.
    display = recruits.reset_index(drop=True)
    display.index = display.index + 1
    st.dataframe(style_plain_dataframe(display), width="stretch", height=df_auto_height(min(len(display), 30)))

    st.markdown("**Transfer Portal**")
    portal = load_transfer_portal(season)
    if portal.empty:
        st.info(f"No transfer portal data found for {season}.")
        return

    filter_text = st.text_input("Filter by player or team name", key="tp_portal_filter")
    filtered = portal
    if filter_text:
        mask = (
            portal['Player'].str.contains(filter_text, case=False, na=False)
            | portal['From'].str.contains(filter_text, case=False, na=False)
            | portal['To'].str.contains(filter_text, case=False, na=False)
        )
        filtered = portal[mask]

    st.caption(f"{len(filtered):,} of {len(portal):,} entries shown")
    display = filtered.head(200).reset_index(drop=True)
    display.index = display.index + 1
    st.dataframe(style_plain_dataframe(display), width="stretch", height=df_auto_height(min(len(display), 30)))
    st.caption("Recruiting and portal data via CollegeBasketballData.com.")
