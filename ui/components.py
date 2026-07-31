"""
Reusable UI pieces shared across tabs: the branded header, the sidebar setup
status panel, and the "coming soon" placeholder card every not-yet-wired tab
uses. Pattern ported from NFL Scholar / CFB Scholar, trimmed to what this
shell pass actually has callers for. No PFF-related helpers here at all
(unlike CFB Scholar) - there is no PFF product for college basketball.
"""
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
