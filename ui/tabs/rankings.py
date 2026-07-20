"""Rankings tab: a thin grouping shell around NET & Resume and Conference
Standings - these two get looked at together (team's overall standing) far
more often than as standalone destinations, so they're sub-tabs of one
parent instead of two separate top-level tabs. Bracketology was dropped
from this group entirely per explicit instruction, not merged in here."""
import streamlit as st

from ui.tabs import net_resume, conference_standings


def render():
    st.markdown("<div class='custom-section-header'>RANKINGS</div>", unsafe_allow_html=True)

    sub_net, sub_standings = st.tabs(
        ["NET & RESUME", "CONFERENCE STANDINGS"], key="rk_subtab", on_change="rerun"
    )
    if sub_net.open:
        with sub_net:
            net_resume.render()
    if sub_standings.open:
        with sub_standings:
            conference_standings.render()
