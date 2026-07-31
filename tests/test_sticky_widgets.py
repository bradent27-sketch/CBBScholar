"""
Regression tests for the sticky_* widget wrappers in ui/components.py - a
real, live-confirmed bug (Playwright against a real running app, then
pinned down precisely via streamlit.testing.v1.AppTest - not just reasoned
from reading the code): a plain `st.selectbox(..., index=I, key=K)` (same
for multiselect/slider/checkbox/text_input) living inside a tab gated by
`if tab.open:` (this app's own tab-switching perf optimization - see
app.py's `_render_guarded` and its docstring) silently resets to its
hardcoded default the instant a user switches to a DIFFERENT top-level tab
and back. Root cause: Streamlit prunes a widget-scoped session_state entry
whenever that widget isn't instantiated during a script run (confirmed
directly - `st.session_state['ma_def_team']` disappeared entirely while
Matchup Analyzer's own tab wasn't open, not just the rendered value), so a
freshly re-instantiated widget has nothing to inherit and falls back to
its hardcoded index/value/default.

Each test below drives a real streamlit.testing.v1.AppTest script (not a
plain unittest against pure-Python logic alone) specifically because this
bug is about STREAMLIT'S OWN widget/session_state lifecycle, which only a
real (if headless) script run can actually exercise - a pure-function test
of the wrapper's internals would not have caught the original bug, since
the original bug was never in this module's own arithmetic to begin with.
"""
import unittest

from streamlit.testing.v1 import AppTest

_TWO_TAB_SCRIPT = """
import streamlit as st
from ui.components import sticky_selectbox, sticky_multiselect, sticky_slider, sticky_checkbox, sticky_text_input

tab_a, tab_b = st.tabs(["A", "B"], key="active_tab", on_change="rerun")
if tab_a.open:
    with tab_a:
        sticky_selectbox("Pick", ["Alpha", "Bravo", "Charlie"], key="pick", default_index=0)
        sticky_multiselect("Pick many", ["Alpha", "Bravo", "Charlie"], key="pick_many")
        sticky_slider("Slide", key="slide", default_value=10, min_value=0, max_value=100)
        sticky_checkbox("Check", key="check", default_value=False)
        sticky_text_input("Type", key="type_in", default_value="")
if tab_b.open:
    with tab_b:
        st.write("tab b")
"""


def _roundtrip_through_tab_b(at):
    """Switches active_tab away to B and back to A - the exact interaction
    that triggers the bug for anything that isn't sticky (tab A's own
    render body, and every widget inside it, doesn't execute at all while
    active_tab == 'B')."""
    at.session_state["active_tab"] = "B"
    at.run()
    at.session_state["active_tab"] = "A"
    at.run()
    return at


class StickySelectboxSurvivesTabRoundTripTests(unittest.TestCase):
    def test_changed_value_survives_switching_tabs_away_and_back(self):
        at = AppTest.from_string(_TWO_TAB_SCRIPT)
        at.run()
        self.assertEqual(at.selectbox(key="pick").value, "Alpha")

        at.selectbox(key="pick").set_value("Charlie").run()
        self.assertEqual(at.selectbox(key="pick").value, "Charlie")

        _roundtrip_through_tab_b(at)
        self.assertEqual(
            at.selectbox(key="pick").value, "Charlie",
            "sticky_selectbox must reopen on the last real selection, not silently "
            "reset to its hardcoded default_index the moment its tab round-trips.",
        )
        self.assertEqual(at.exception, [])

    def test_unchanged_value_is_unaffected(self):
        """Sanity check: a selectbox never touched by the user still shows
        its real default after a round-trip (not a false "always shows
        default_index" pass hiding behind this - the value above test
        deliberately changes AWAY from index 0 first)."""
        at = AppTest.from_string(_TWO_TAB_SCRIPT)
        at.run()
        _roundtrip_through_tab_b(at)
        self.assertEqual(at.selectbox(key="pick").value, "Alpha")


class StickyMultiselectSurvivesTabRoundTripTests(unittest.TestCase):
    def test_changed_selection_survives_roundtrip(self):
        at = AppTest.from_string(_TWO_TAB_SCRIPT)
        at.run()
        at.multiselect(key="pick_many").set_value(["Bravo", "Charlie"]).run()
        self.assertEqual(at.multiselect(key="pick_many").value, ["Bravo", "Charlie"])

        _roundtrip_through_tab_b(at)
        self.assertEqual(at.multiselect(key="pick_many").value, ["Bravo", "Charlie"])


class StickySliderSurvivesTabRoundTripTests(unittest.TestCase):
    def test_changed_value_survives_roundtrip(self):
        at = AppTest.from_string(_TWO_TAB_SCRIPT)
        at.run()
        self.assertEqual(at.slider(key="slide").value, 10)
        at.slider(key="slide").set_value(75).run()
        self.assertEqual(at.slider(key="slide").value, 75)

        _roundtrip_through_tab_b(at)
        self.assertEqual(at.slider(key="slide").value, 75)


class StickyCheckboxSurvivesTabRoundTripTests(unittest.TestCase):
    def test_checked_state_survives_roundtrip(self):
        at = AppTest.from_string(_TWO_TAB_SCRIPT)
        at.run()
        self.assertFalse(at.checkbox(key="check").value)
        at.checkbox(key="check").set_value(True).run()
        self.assertTrue(at.checkbox(key="check").value)

        _roundtrip_through_tab_b(at)
        self.assertTrue(at.checkbox(key="check").value)


class StickyTextInputSurvivesTabRoundTripTests(unittest.TestCase):
    def test_typed_text_survives_roundtrip(self):
        at = AppTest.from_string(_TWO_TAB_SCRIPT)
        at.run()
        at.text_input(key="type_in").set_value("Cooper Flagg").run()
        self.assertEqual(at.text_input(key="type_in").value, "Cooper Flagg")

        _roundtrip_through_tab_b(at)
        self.assertEqual(at.text_input(key="type_in").value, "Cooper Flagg")


if __name__ == "__main__":
    unittest.main()
