"""
CBB Scholar - entrypoint. Page config, theme injection, sidebar diagnostics,
and tab wiring only; all data/UI logic lives in data/ and ui/. Structure
ported directly from NFL Scholar (C:\\FantasyF\\app.py) / CFB Scholar.
"""
import traceback

import streamlit as st

from config import TAB_LABELS
from ui.styling import inject_theme
from ui.components import render_setup_status_sidebar, render_header
from ui.tabs import (
    player_search, team_efficiency, rankings, transfer_portal, matchup_analyzer, live_odds, compare,
)


def _render_guarded(tab_module, tab_label):
    """One tab blowing up degrades to an error message inside THAT tab,
    never a full-page traceback taking the whole app down - see NFL
    Scholar's app.py for the same pattern and rationale."""
    try:
        tab_module.render()
    except Exception:
        st.error(
            f"The {tab_label} tab hit an error and couldn't finish rendering. "
            "The other tabs are unaffected."
        )
        with st.expander("Technical details (for debugging)"):
            st.code(traceback.format_exc())


st.set_page_config(page_title="CBB Scholar", layout="wide", page_icon="🏀")
inject_theme()

render_setup_status_sidebar()
render_header()

# key= + on_change="rerun" (Streamlit >=1.59) makes each tab's .open property
# real (True only for the active tab), so only the visible tab's render()
# actually runs on any given rerun - see NFL Scholar's app.py for why this
# matters for perceived performance as more tabs go from placeholder to
# real (potentially expensive) data pipelines.
tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs(TAB_LABELS, key="active_tab", on_change="rerun")

_tab_modules = [
    player_search, team_efficiency, rankings, transfer_portal, matchup_analyzer, live_odds, compare,
]
_tabs = [tab1, tab2, tab3, tab4, tab5, tab6, tab7]
for _tab, _module, _label in zip(_tabs, _tab_modules, TAB_LABELS):
    if _tab.open:
        with _tab:
            _render_guarded(_module, _label)
