"""
Reusable UI pieces shared across tabs: the branded header, the sidebar setup
status panel, and the "coming soon" placeholder card every not-yet-wired tab
uses. Pattern ported from NFL Scholar / CFB Scholar, trimmed to what this
shell pass actually has callers for. No PFF-related helpers here at all
(unlike CFB Scholar) - there is no PFF product for college basketball.
"""
import datetime

import streamlit as st

from config import THEME

C = THEME['colors']
F = THEME['fonts']
# Sanitized (single quotes -> double quotes) font-family strings for
# embedding inside a single-quoted inline HTML `style='...'` attribute -
# THEME['fonts'] values are themselves single-quoted (e.g. "'Inter',
# sans-serif"), and splicing that raw into a `style='...'` attribute
# prematurely closes the attribute at the font name's own opening quote,
# silently dropping every declaration after it. Real, confirmed bug
# (Playwright): render_header's title and render_bio_strip/render_metric_
# tiles' value text had all been silently falling back to Streamlit's
# default font/size instead of this app's own display/mono styling, for
# their entire history - same fix ui.charts already established for its
# own inline SVG styles (_BODY_FONT/_MONO_FONT).
_DISPLAY_FONT_SAFE = F['display'].replace("'", '"')
_MONO_FONT_SAFE = F['mono'].replace("'", '"')


# ---------------------------------------------------------------------------
# "Sticky" widget wrappers - survive a top-level (or sub-)tab losing and
# regaining `.open` status, which every tab in this app is gated behind (see
# app.py's `if _tab.open:` / `_render_guarded` - the whole point of that
# gating is that an INACTIVE tab's render() doesn't execute AT ALL on a given
# rerun, so its expensive data pipelines don't re-fire on every click
# elsewhere in the app).
#
# REAL, LIVE-CONFIRMED BUG this fixes (Playwright, real Chromium - not just
# reasoned): a plain `st.selectbox(..., index=I, key=K)` (or multiselect/
# slider) living inside such a gated tab silently resets to its hardcoded
# I/default the instant a user switches to a DIFFERENT tab and back - proven
# with three independent, isolated round-trips (Player Search's team picker,
# Matchup Analyzer's PLAYER team picker, and - the decisive case, since it
# has no placeholder at all - Matchup Analyzer's TEAM DEFENSE picker
# explicitly changed away from its own hardcoded default 'Duke' to 'Kansas',
# which reverted to 'Duke' after a round-trip through an unrelated tab).
# Confirmed via AppTest at the session_state level too: `ma_def_team`
# disappears from `st.session_state` entirely while its tab isn't open, not
# just from the rendered widget - Streamlit prunes a WIDGET-scoped key's
# session_state entry whenever that widget isn't instantiated during a
# script run, and a fresh instantiation with no prior state to inherit falls
# back to whatever `index=`/`value=`/`default=` the call site hardcoded.
# This is invisible for a widget whose hardcoded default already matches
# what a user would pick anyway (e.g., TEAM DEFENSE defaulting to 'Duke' -
# looks "retained" if you never change it away from Duke) - which is likely
# why this survived every prior review pass in this doc; it only becomes
# obvious once you pick something ELSE and watch it snap back.
#
# Fix: mirror each widget's real value into a SECOND, plain session_state
# entry (not itself tied to any widget's auto-managed key) on every render -
# a plain dict assignment isn't part of Streamlit's widget-instantiation
# bookkeeping, so it survives exactly the round-trip a widget-scoped key
# doesn't. Each wrapper reads that mirror BEFORE instantiating the real
# widget to compute the index/default the widget itself should reopen with,
# so even a freshly (re-)instantiated widget reopens on the last real
# selection instead of snapping back to its hardcoded default.
# ---------------------------------------------------------------------------

def _sticky_mirror_key(widget_key):
    return f"_sticky__{widget_key}"


def sticky_selectbox(label, options, key, default_index=0, **kwargs):
    """Drop-in `st.selectbox` replacement that survives its containing tab
    losing/regaining focus - see this module's own section header comment
    for the bug this fixes. `options` must support `.index()` (a list, not
    a generator) since it's used both for the remembered-value lookup below
    and passed straight through to st.selectbox."""
    options = list(options)
    mirror_key = _sticky_mirror_key(key)
    remembered = st.session_state.get(mirror_key)
    idx = options.index(remembered) if remembered in options else default_index
    value = st.selectbox(label, options, index=idx, key=key, **kwargs)
    st.session_state[mirror_key] = value
    return value


def sticky_multiselect(label, options, key, default=None, **kwargs):
    """Drop-in `st.multiselect` replacement - see sticky_selectbox above.
    Remembered selections that are no longer valid options (e.g. a
    conference/season switch narrowed the choices) are dropped silently,
    same as st.multiselect's own behavior when `default` contains a stale
    value."""
    options = list(options)
    mirror_key = _sticky_mirror_key(key)
    remembered = st.session_state.get(mirror_key)
    default_value = [v for v in remembered if v in options] if remembered is not None else (default or [])
    value = st.multiselect(label, options, default=default_value, key=key, **kwargs)
    st.session_state[mirror_key] = value
    return value


def sticky_slider(label, key, default_value, **kwargs):
    """Drop-in `st.slider` replacement - see sticky_selectbox above."""
    mirror_key = _sticky_mirror_key(key)
    remembered = st.session_state.get(mirror_key, default_value)
    value = st.slider(label, value=remembered, key=key, **kwargs)
    st.session_state[mirror_key] = value
    return value


def sticky_checkbox(label, key, default_value=False, **kwargs):
    """Drop-in `st.checkbox` replacement - see sticky_selectbox above."""
    mirror_key = _sticky_mirror_key(key)
    remembered = st.session_state.get(mirror_key, default_value)
    value = st.checkbox(label, value=remembered, key=key, **kwargs)
    st.session_state[mirror_key] = value
    return value


def sticky_text_input(label, key, default_value="", **kwargs):
    """Drop-in `st.text_input` replacement - see sticky_selectbox above."""
    mirror_key = _sticky_mirror_key(key)
    remembered = st.session_state.get(mirror_key, default_value)
    value = st.text_input(label, value=remembered, key=key, **kwargs)
    st.session_state[mirror_key] = value
    return value


def sticky_date_input(label, key, default_value, **kwargs):
    """Drop-in `st.date_input` replacement - see sticky_selectbox above.

    `default_value` is only ever consulted when there's no remembered value
    at all (a genuinely first visit), same contract as every wrapper above:
    a caller passing "today" as its default must not have that default snap
    back over a date the visitor actually picked, just because they looked
    at another tab in between."""
    mirror_key = _sticky_mirror_key(key)
    remembered = st.session_state.get(mirror_key, default_value)
    value = st.date_input(label, value=remembered, key=key, **kwargs)
    st.session_state[mirror_key] = value
    return value


def set_sticky_value(key, value):
    """
    Drives a sticky widget that is ON THE CURRENTLY OPEN TAB from outside
    itself - built for the Game Slate's prev/next-day arrows moving its own
    date picker.

    Sets BOTH the mirror entry and the widget's own session_state key,
    because a widget on the open tab was instantiated on the previous run
    and its widget key therefore still exists - and Streamlit uses that
    stored value in preference to the `value=`/`index=` the sticky wrapper
    computes, so writing the mirror alone would appear to do nothing at all.

    Only safe for a value the target widget will definitely accept (any
    date, for a date_input). To seed a widget on a tab that ISN'T open, use
    seed_sticky_value below instead - it has the opposite failure mode.

    MUST run in a callback (`on_click`) or otherwise before the target
    widget is instantiated this run: Streamlit raises if a widget's
    session_state key is reassigned after that widget has already rendered.
    """
    st.session_state[_sticky_mirror_key(key)] = value
    st.session_state[key] = value


def seed_sticky_value(key, value):
    """
    Seeds a sticky widget that lives on a tab which is NOT currently open -
    the cross-tab hand-off behind switch_tab below.

    Writes ONLY the mirror, and clears any lingering widget key. That
    asymmetry with set_sticky_value above is the whole point, and it is a
    safety property rather than a stylistic choice:

    - Writing the raw widget key makes Streamlit RAISE on the next run
      whenever the seeded value isn't a member of the destination
      selectbox's options - which is not a rare case here. Seeding a
      matchup seeds a team, and the destination's option list is a
      different data source's spelling of the league (CBBD's `school`
      names against the slate's ESPN `location` names), on a season the
      visitor may then change out from under it.
    - The mirror has no such problem: every sticky wrapper above checks
      `remembered in options` before using it and falls back to its own
      default otherwise. A value that doesn't resolve degrades to "opened
      on the default" instead of a traceback.

    Safe to write because the destination's widget key has been pruned by
    Streamlit while its tab was closed (see this module's section header) -
    the pop is belt-and-braces for the case where it somehow hasn't been.
    """
    st.session_state[_sticky_mirror_key(key)] = value
    st.session_state.pop(key, None)


def switch_tab(tab_label, _record=True, **sticky_state):
    """
    Switches the app's active top-level tab AND pre-seeds the destination's
    own widgets, so the target opens already pointed at whatever the caller
    was looking at instead of asking the visitor to re-pick it.

    THE RULE THIS DEPENDS ON: this must run as an `on_click` CALLBACK. It
    cannot be called from a tab's render() body. app.py builds the top-level
    tabs as `st.tabs(TAB_LABELS, key="active_tab", on_change="rerun")`, and
    Streamlit raises StreamlitAPIException if `st.session_state['active_tab']`
    is reassigned during the same script run that already read it to render
    those tabs - which app.py did, long before any tab's render() was
    reached. A callback runs in the PRE-SCRIPT phase, before st.tabs()
    executes for the next run, so the assignment is legal there.

    That single constraint is why the Game Slate's cards are keyed
    `st.container`s styled with CSS rather than one block of raw HTML:
    raw HTML cannot fire a Python callback, and without the callback there
    is no pre-seeding - which is the entire point of the tab.

    `sticky_state` keys are the DESTINATION widgets' own `key=` values
    (e.g. ma_player_team='Duke'). Seeding goes through seed_sticky_value,
    NOT set_sticky_value - see that function for why writing the raw
    widget key across a tab boundary turns an unresolvable team name into
    a traceback instead of a harmless fallback.
    """
    if _record:
        # Both the mirror AND the raw widget key, since seed_sticky_value
        # writes one and pops the other - Back has to undo both.
        touched = [k for key in sticky_state for k in (key, _sticky_mirror_key(key))]
        push_nav_history(touched)
    st.session_state['active_tab'] = tab_label
    for key, value in sticky_state.items():
        seed_sticky_value(key, value)


# ---------------------------------------------------------------------------
# Navigation history - a single "Back" control for every cross-tab jump in
# the app, so following a link somewhere doesn't mean re-navigating by hand
# to get back to what you were reading.
#
# A history ENTRY is not just a tab name: a jump also seeds the destination's
# pickers and can clear the origin's filters, so going back has to restore
# the exact values it overwrote. Each navigation therefore snapshots the
# keys it is ABOUT to touch, and Back replays that snapshot - restoring a
# key that was absent by deleting it, not by writing a None that would then
# look like a real remembered value to the sticky wrappers.
# ---------------------------------------------------------------------------

_NAV_STACK_KEY = '_nav_stack'
_NAV_MARKER_KEY = '_nav_marker'
_NAV_LAST_TAB_KEY = '_nav_last_tab'
_NAV_MAX_DEPTH = 20


class _Absent:
    """Marks a key that did not exist when the snapshot was taken, so Back
    can delete it again rather than resurrect it as None."""


_ABSENT = _Absent()


def _snapshot(keys):
    return {k: (st.session_state[k] if k in st.session_state else _ABSENT) for k in keys}


def push_nav_history(keys):
    """Record where we are, and the prior value of every key the pending
    navigation will overwrite. Called by the navigation helpers themselves,
    never by a tab."""
    entry = {
        'tab': st.session_state.get('active_tab'),
        'state': _snapshot(list(keys) + ['active_tab']),
    }
    stack = st.session_state.get(_NAV_STACK_KEY) or []
    stack.append(entry)
    st.session_state[_NAV_STACK_KEY] = stack[-_NAV_MAX_DEPTH:]
    st.session_state[_NAV_MARKER_KEY] = True


def go_back():
    """Callback: undo the most recent in-app jump. Same on_click rule as
    switch_tab - it reassigns `active_tab`."""
    stack = st.session_state.get(_NAV_STACK_KEY) or []
    if not stack:
        return
    entry = stack.pop()
    st.session_state[_NAV_STACK_KEY] = stack
    for key, value in entry['state'].items():
        if isinstance(value, _Absent):
            st.session_state.pop(key, None)
        else:
            st.session_state[key] = value
    st.session_state[_NAV_MARKER_KEY] = True


def sync_nav_history():
    """
    Drops the history when the visitor changes tabs BY HAND.

    Without this, Back lingers after manual navigation and sends someone
    somewhere they have no memory of asking for. A jump sets a marker in
    its callback (which runs before the script), so a tab change with no
    marker is a manual one. MUST be called before `st.tabs()` renders, for
    the same reason switch_tab must be a callback.
    """
    current = st.session_state.get('active_tab')
    if st.session_state.pop(_NAV_MARKER_KEY, False):
        st.session_state[_NAV_LAST_TAB_KEY] = current
        return
    if st.session_state.get(_NAV_LAST_TAB_KEY) not in (None, current):
        st.session_state[_NAV_STACK_KEY] = []
    st.session_state[_NAV_LAST_TAB_KEY] = current


def render_back_button():
    """The one Back control, rendered above the tab bar so it sits in the
    same place no matter which jump got you here - a browser back button,
    not a per-tab one."""
    stack = st.session_state.get(_NAV_STACK_KEY) or []
    if not stack:
        return
    previous = stack[-1].get('tab') or 'where you were'
    st.button(
        f"\u2190 Back to {previous.title()}",
        key='nav_back',
        help="Return to whatever you followed the last link from.",
        on_click=go_back,
    )


_SLATE_NAV_KEYS = [
    'gs_box_game',
    'gs_season', '_sticky__gs_season',
    'gs_date', '_sticky__gs_date',
    'gs_conferences', '_sticky__gs_conferences',
    'gs_ranked_only', '_sticky__gs_ranked_only',
    'gs_page', '_sticky__gs_page',
]


def open_box_score(season, game_id, date_iso=None):
    """
    Callback: jump to the Game Slate with one game's full box score open.

    The cross-tab entry point for every "this stat came from a real game"
    link in the app - a player's game log row, a point on a trend chart, a
    defensive matchup. Same on_click-callback rule as switch_tab, which it
    delegates to.

    Seeds the slate's own season and date so the grid underneath the box
    lands on that game's day rather than wherever the visitor last left it,
    and clears the incidental filters (conference, ranked-only, paging).
    That clearing is deliberate: arriving here is a request to look at ONE
    named game, and leaving a stale conference filter on would show the
    box above an empty, confusing "no games match those filters" slate.
    `gs_di_only` is left alone - it's on by default and can't hide a game
    that this app had stats for in the first place.

    `gs_box_game` is plain session state, not a widget key, so it's set
    directly rather than through the sticky mirror.
    """
    from config import TAB_SLATE
    push_nav_history(_SLATE_NAV_KEYS)
    extra = {'gs_season': season}
    if date_iso:
        try:
            extra['gs_date'] = datetime.date.fromisoformat(str(date_iso)[:10])
        except (TypeError, ValueError):
            pass
    switch_tab(TAB_SLATE, _record=False, **extra)
    st.session_state['gs_box_game'] = str(game_id)
    for key, cleared in (('gs_conferences', []), ('gs_ranked_only', False)):
        seed_sticky_value(key, cleared)
    st.session_state.pop('_sticky__gs_page', None)
    st.session_state.pop('gs_page', None)


def open_slate_date(season, date_iso):
    """
    Callback: jump to the Game Slate on a given date, WITHOUT opening a box
    score. For games that haven't been played - an upcoming game on the
    odds board has no box to show, but "what else is on that night, and who
    are these two teams" is still a real question the slate answers.

    Same filter-clearing rationale as open_box_score: arriving here is a
    request to look at a specific day, so a stale conference filter left on
    would show an empty slate for no reason the visitor can see.
    """
    from config import TAB_SLATE
    push_nav_history(_SLATE_NAV_KEYS)
    extra = {'gs_season': season}
    try:
        extra['gs_date'] = datetime.date.fromisoformat(str(date_iso)[:10])
    except (TypeError, ValueError):
        pass
    switch_tab(TAB_SLATE, _record=False, **extra)
    st.session_state.pop('gs_box_game', None)
    for key, cleared in (('gs_conferences', []), ('gs_ranked_only', False)):
        seed_sticky_value(key, cleared)
    st.session_state.pop('_sticky__gs_page', None)
    st.session_state.pop('gs_page', None)


_CHART_VIEWBOX_W = 860


def render_trend_with_point_links(render_chart, entries, season, key_suffix, chart_height):
    """
    Renders a trend chart with its DATA POINTS clickable - click a dot, open
    that game's box score.

    `render_chart` is a zero-arg callable that draws the chart; `entries` is
    one item per plotted point in the chart's own order, each a game-link
    dict (see data.transforms.game_link_rows) or None for a point with no
    resolvable game.

    HOW: the chart and a row of transparent `st.button`s go into one
    relatively-positioned container; the button row is absolutely positioned
    over the chart, so each button is an invisible hit strip sitting on its
    own data point and a click fires a real Python callback.

    WHY NOT an <a> inside the SVG, which is the obvious approach: it works,
    but a query-string link is a real page navigation, and that starts a NEW
    Streamlit session - every picker, every sticky mirror and the back stack
    wiped. Confirmed in a browser rather than reasoned about: a session
    token printed before and after the click came back different.

    WHY NOT a Vega/Altair chart with on_select: native point selection, but
    only by replacing this app's hand-built SVG charts (reference line,
    per-point coloring, corner badges) with a different rendering stack.
    This leaves the chart untouched.

    WHY one wrapper rather than pulling the row up with a negative margin:
    the margin has to cancel Streamlit's own inter-element gap as well as
    the chart's height, and that gap is not a number this code can know -
    measured at 39px in a real browser, not the 16 you'd guess. Absolute
    positioning inside a shared parent has nothing to cancel.

    THE ALIGNMENT IS EXACT, not eyeballed: render_trend_line places point i
    at i/(n-1) of the plot width, and column i spans [i/n, (i+1)/n]. The
    point falls inside its own column for every i and every n, since
    i/(n-1) <= (i+1)/n reduces to i <= n-1. Column gaps are zeroed in CSS so
    the bands stay flush.

    The chart is `width:100%; height:auto` over a fixed viewBox, so its
    rendered height is width * H/860 - unknown in Python. The overlay's
    height therefore comes from `padding-bottom` as a PERCENTAGE, which CSS
    resolves against the container's width, emitted as a one-line <style>
    scoped to this row's key class (the technique the Game Slate's cards
    already use to get per-instance values onto a Streamlit-owned element).
    """
    usable = [e for e in entries if e]
    with st.container(key=f"cpl_wrap_{key_suffix}"):
        render_chart()
        if not usable:
            return
        row_key = f"cpl_row_{key_suffix}"
        st.markdown(
            f"<style>.st-key-{row_key}{{padding-bottom:{chart_height / _CHART_VIEWBOX_W * 100:.4f}%;}}</style>",
            unsafe_allow_html=True,
        )
        with st.container(key=row_key):
            cols = st.columns(len(entries))
            for col, entry in zip(cols, entries):
                with col:
                    if not entry:
                        # An unresolvable point still needs its column, or
                        # every point after it shifts onto the wrong dot.
                        st.markdown("<div class='cpl-gap'></div>", unsafe_allow_html=True)
                        continue
                    st.button(
                        "\u200b",  # zero-width space: a real button, no glyph
                        key=f"cpl_{key_suffix}_{entry['game_id']}",
                        width="stretch",
                        help=entry.get('help'),
                        on_click=open_box_score,
                        args=(season, entry['game_id'], entry.get('date')),
                    )


_GAME_LINKS_PER_ROW = 8


def render_game_links(entries, season, key_prefix, label="Open a game's full box score"):
    """
    A compact strip of one-click links, one per game, each opening that
    game's box score in the Game Slate.

    These have to be real `st.button`s: the tables and charts they sit
    under are hand-rolled HTML and inline SVG, and neither can fire the
    Python callback this navigation needs (see switch_tab). A strip below
    the visual is the honest way to get per-game clicks without rewriting
    every table in the app into widgets.

    Laid out with `st.columns` in fixed-width rows rather than a CSS
    flex-wrap on the container: columns are the predictable, supported way
    to get a horizontal run of buttons, and the wrap trick depends on
    Streamlit's internal DOM structure. NOTE the consequence - this spends
    one level of column nesting, and Streamlit allows exactly one, so this
    helper cannot be called from inside another `st.columns` block. Callers
    that live in a column (the Matchup Analyzer's panels) must render it
    outside theirs.

    Wins/losses tint via the `won` flag so the strip doubles as a
    season-shape readout: a run of losses is visible before anything is
    clicked.
    """
    if not entries:
        return
    st.caption(label)
    with st.container(key=f"gamelinks_{key_prefix}"):
        for start in range(0, len(entries), _GAME_LINKS_PER_ROW):
            chunk = entries[start:start + _GAME_LINKS_PER_ROW]
            cols = st.columns(_GAME_LINKS_PER_ROW)
            for col, entry in zip(cols, chunk):
                with col:
                    won = entry.get('won')
                    tone = 'n' if won is None else ('w' if won else 'l')
                    st.button(
                        entry['label'],
                        # The `gl_<tone>_` token is what the win/loss tint
                        # in ui/styling.py keys off: Streamlit puts
                        # `st-key-<button key>` on each button's own element
                        # container, so a substring selector on that class
                        # is the only handle for styling ONE button
                        # differently from its neighbours. Verified in a
                        # real browser with getComputedStyle, not assumed -
                        # per-widget key classes are not documented API.
                        key=f"gl_{tone}_{key_prefix}_{entry['game_id']}",
                        width="stretch",
                        help=entry.get('help'),
                        on_click=open_box_score,
                        args=(season, entry['game_id'], entry.get('date')),
                    )


def render_header():
    st.markdown(
        f"<div style='display:flex; align-items:center; gap:12px; margin-top:0;'>"
        f"<div style='font-size:30px; line-height:1;'>🏀</div>"
        f"<div>"
        f"<div style='font-family:{_DISPLAY_FONT_SAFE}; font-size:21px; font-weight:800; letter-spacing:-0.02em; line-height:1.05; color:{C['on_surface']};'>"
        f"CBB <span style='color:{C['primary']};'>SCHOLAR</span></div>"
        f"<div style='font-size:10px; font-weight:700; text-transform:uppercase; letter-spacing:0.14em; color:{C['on_surface_variant']}; margin-top:1px;'>"
        f"College Basketball Analytics &amp; Matchup Intelligence</div>"
        f"</div></div>", unsafe_allow_html=True,
    )


def render_coming_soon(blurb, data_sources, eyebrow="COMING SOON"):
    """
    Shared empty-state card for every tab that isn't wired to real data yet
    this pass - one component instead of a bespoke placeholder per tab.
    `data_sources`: list of short strings rendered as chips so it's clear
    at a glance what will eventually power this tab.
    """
    chips = "".join(f"<span class='cs-source-chip'>{s}</span>" for s in data_sources)
    st.markdown(
        f"<div class='coming-soon-card'>"
        f"<div class='cs-eyebrow'>{eyebrow}</div>"
        f"<div class='cs-blurb'>{blurb}</div>"
        f"<div class='cs-sources'>{chips}</div>"
        f"</div>",
        unsafe_allow_html=True,
    )


def _get_secret(key):
    try:
        return st.secrets.get(key, "")
    except Exception:
        return ""


def render_setup_status_sidebar():
    """Sidebar diagnostics - same spirit as NFL Scholar's "Local Data
    Health" panel / CFB Scholar's Setup Status: what's configured vs. what's
    left to do from DATA_SOURCES.md. No PFF check here - not applicable."""
    with st.sidebar:
        st.markdown("<div class='custom-section-header'>SETUP STATUS</div>", unsafe_allow_html=True)

        st.markdown("**Appearance**")
        # key='theme_mode' directly (no separate widget-state key to keep in
        # sync) - config.apply_theme_mode reads this exact
        # st.session_state key, called from the very top of
        # ui.styling.inject_theme() on every rerun, before anything else
        # reads a color. 'dark' stays the default so a first-ever visit
        # renders exactly what this app always has - opting into light mode
        # is something a visitor does, not something forced on them.
        st.radio(
            "Theme", options=['dark', 'light'], format_func=str.capitalize,
            key='theme_mode', horizontal=True, label_visibility='collapsed',
        )
        # key='text_scale' directly, same pattern as 'theme_mode' above -
        # ui.styling.inject_theme() reads this exact key to pick a zoom
        # multiplier on top of its own viewport-width baseline (a laptop
        # window reads meaningfully smaller than a large desktop monitor
        # at identical declared px sizes - this is the manual override on
        # top of that automatic baseline, not a replacement for it).
        # 'default' stays the default for the same reason 'dark' does -
        # a first-ever visit renders the automatic viewport baseline
        # untouched; sizing up or down is something a visitor opts into.
        st.radio(
            "Text size", options=['small', 'default', 'large'], format_func=str.capitalize,
            index=1, key='text_scale', horizontal=True, label_visibility='collapsed',
            help="Shifts this app's automatic per-device text size up or down.",
        )
        st.markdown("---")

        cbbd_key = _get_secret("cbbd_api_key")
        odds_key = _get_secret("odds_api_key")

        def _line(ok, label, ok_detail, missing_detail):
            icon = "✅" if ok else "⚠️"
            detail = ok_detail if ok else missing_detail
            st.markdown(f"{icon} **{label}**  \n{detail}")

        _line(bool(cbbd_key), "CollegeBasketballData.com API key", "Configured", "Not set — see DATA_SOURCES.md")
        _line(bool(odds_key), "Odds API key", "Configured", "Not set — needed for Live Odds")

        st.markdown("---")
        st.markdown("**League-wide data**")
        if st.button("🔄 Refresh league-wide data", key="sb_refresh_league"):
            from data.loaders import clear_league_wide_caches
            clear_league_wide_caches()
            st.success("Cleared — next tab visit re-pulls current league-wide data.")

        # Rough, session-local CBBD call counter - not a real quota readout
        # (CBBD's free tier is 1,000 calls/MONTH, this only counts calls
        # made THIS session, and cached calls from earlier sessions/disk
        # persistence don't show up here at all), but enough to make quota
        # risk visible at a glance for the most quota-sensitive feature
        # (Matchup Analyzer's positional matchup defense CBBD fallback can
        # cost ~1+2N calls per team - see DATA_SOURCES.md's API budget
        # section) - same spirit as Live Odds' "requests remaining"
        # caption, which reads a real header CBBD doesn't expose.
        cbbd_calls = st.session_state.get('cbbd_calls_this_session', 0)
        if cbbd_calls:
            st.caption(f"CBBD API calls made this session: {cbbd_calls} (free tier: 1,000/month — see DATA_SOURCES.md).")


def render_team_banner(team_name, subtitle="", team_color=None):
    """Team identity banner (Player Search etc): name over a team-color
    gradient that fades into the app surface. Ported from CFB Scholar's
    identical function.

    CORRECTION: used to gradient the RAW team color straight in (`{color}
    D9` -> `{color}66` -> surface) - a vivid school color (Duke blue,
    Syracuse orange, ...) at 85% opacity reads as a loud, "solid and
    oppressive" block rather than a design accent, per explicit request.
    Muted by blending the raw color toward a FIXED dark neutral first
    (ui.styling._blend_hex) rather than toward this app's own theme-
    dependent surface color - surface_container is a pale
    lavender in light mode, and blending toward it would have pushed a
    naturally light team color (e.g. UNC's powder blue, Purdue's tan)
    light enough to break this banner's own hardcoded white title text's
    contrast. Blending toward a fixed dark tone instead keeps the result
    reliably dark enough for white text in BOTH themes while still
    reading as "this team's color," just desaturated rather than neon -
    verified live (Playwright) against several real school colors
    spanning dark (Duke navy) to naturally light (UNC powder blue,
    Purdue tan) so this isn't just true for the safe/dark cases.
    """
    from ui.styling import _blend_hex
    raw = team_color or C['surface_container_high']
    color = _blend_hex(raw, '#0b1020', 0.52)
    sub_html = f"<div class='tb-sub'>{subtitle}</div>" if subtitle else ""
    st.markdown(
        f"<div class='team-banner' style='background: linear-gradient(90deg, {color}CC 0%, {color}55 45%, {C['surface_container']} 100%);'>"
        f"<div><div class='tb-name'>{team_name}</div>{sub_html}</div></div>",
        unsafe_allow_html=True,
    )


def render_bio_strip(fields):
    """Compact bio tiles in a single row - fields: list of (label, value)
    tuples. Ported from CFB Scholar's identical function."""
    cells = []
    for label, value in fields:
        cells.append(
            f"<div class='bio-cell' style='flex:1; background:{C['surface_container']}; text-align:center; padding:10px 6px;'>"
            f"<div style='font-size:10px; font-weight:700; text-transform:uppercase; letter-spacing:0.08em; color:{C['on_surface_variant']};'>{label}</div>"
            f"<div style='font-family:{_MONO_FONT_SAFE}; font-size:18px; font-weight:600; color:{C['on_surface']}; margin-top:2px;'>{value}</div>"
            f"</div>"
        )
    st.markdown(
        f"<div style='display:flex; gap:1px; margin-top:12px; background:{C['outline_variant']}; "
        f"border:1px solid {C['outline_variant']}; border-radius:4px; overflow:hidden;'>{''.join(cells)}</div>",
        unsafe_allow_html=True,
    )


def render_stat_tiles(entries):
    """Stat tile grid - each stat is its own card with the value in mono.
    Ported from CFB Scholar's identical function. `entries`: list of
    {'label', 'value_str', 'pct' (optional)} - when 'pct' (0-100) is
    present, a thin colored percentile meter renders along the tile's
    bottom edge, same treatment as CFB Scholar's PFF percentile tiles.
    Callers only pass 'pct' when the distribution was free to compute
    (an already-cached full-league pull or purely local data)."""
    from ui.styling import get_grade_color
    tiles = []
    for e in entries:
        label = str(e.get('label', ''))
        value = str(e.get('value_str', '--'))
        pct = e.get('pct')
        pct_html = ""
        if pct is not None:
            color = get_grade_color(pct)
            pct_html = (
                f"<div title='{pct:.0f}th percentile' style='position:absolute; left:0; bottom:0; height:3px; "
                f"width:{max(pct, 3):.0f}%; background:{color}; border-radius:0 2px 0 0;'></div>"
                f"<div style='position:absolute; right:5px; bottom:3px; font-size:9px; font-weight:700; "
                f"color:{C['on_surface_variant']};' title='{pct:.0f}th percentile'>{pct:.0f}</div>"
            )
        tiles.append(
            f"<div class='stat-tile'><div class='t-label' title='{label}'>{label}</div>"
            f"<div class='t-value'>{value}</div>{pct_html}</div>"
        )
    st.markdown(f"<div class='stat-tile-grid'>{''.join(tiles)}</div>", unsafe_allow_html=True)


def render_metric_tiles(entries):
    """Stat tiles with a colored secondary delta line - built for "recent
    form vs season average" readouts (Player Search's last-5 form) where
    the delta TEXT should stay exactly as computed by the caller, just
    colored green when it's an improvement and red when it's a decline.
    Deliberately not st.metric: st.metric's own delta-coloring only reads a
    plain leading +/- number, and this delta text is a full sentence
    ("last 5: 24.3 (+2.1)") - custom HTML gives direct control over the
    color instead of depending on how st.metric parses an arbitrary string.
    entries: list of {'label', 'value_str', 'delta_str', 'better'} where
    'better' is True (green) / False (red) / None (neutral, no signal)."""
    tiles = []
    for e in entries:
        label = str(e.get('label', ''))
        value = str(e.get('value_str', '--'))
        delta = str(e.get('delta_str', ''))
        better = e.get('better')
        color = C['positive'] if better is True else (C['negative'] if better is False else C['on_surface_variant'])
        tiles.append(
            f"<div class='stat-tile'><div class='t-label' title='{label}'>{label}</div>"
            f"<div class='t-value'>{value}</div>"
            f"<div style='font-family:{_MONO_FONT_SAFE}; font-size:11px; font-weight:700; color:{color}; margin-top:4px;'>{delta}</div>"
            f"</div>"
        )
    st.markdown(f"<div class='stat-tile-grid'>{''.join(tiles)}</div>", unsafe_allow_html=True)


def render_hero_tiles(entries):
    """Bigger-emphasis tile row for the 1-3 headline numbers on a tab (e.g.
    a league-leader net rating, or a matchup's win probability) - a step up
    in visual weight from render_stat_tiles' detail grid, for drawing the
    eye to whatever matters most on that page first. Wires up the
    .hero-tile/.hero-tile-grid CSS in ui/styling.py, which was ported over
    from the sibling apps but had no caller in this app until now. entries:
    list of {'label', 'value_str', 'sub' (optional secondary line)}."""
    tiles = []
    for e in entries:
        label = str(e.get('label', ''))
        value = str(e.get('value_str', '--'))
        sub = e.get('sub')
        sub_html = f"<div class='h-sub'>{sub}</div>" if sub else ""
        tiles.append(
            f"<div class='hero-tile'><div class='h-label' title='{label}'>{label}</div>"
            f"<div class='h-value'>{value}</div>{sub_html}</div>"
        )
    st.markdown(f"<div class='hero-tile-grid'>{''.join(tiles)}</div>", unsafe_allow_html=True)
