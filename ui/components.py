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


def render_header():
    st.markdown(
        f"<div style='display:flex; align-items:center; gap:12px; margin-top:0;'>"
        f"<div style='font-size:30px; line-height:1;'>🏀</div>"
        f"<div>"
        f"<div style='font-family:{F['display']}; font-size:21px; font-weight:800; letter-spacing:-0.02em; line-height:1.05; color:#ffffff;'>"
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
        cbbd_key = _get_secret("cbbd_api_key")
        odds_key = _get_secret("odds_api_key")

        def _line(ok, label, ok_detail, missing_detail):
            icon = "✅" if ok else "⚠️"
            detail = ok_detail if ok else missing_detail
            st.markdown(f"{icon} **{label}**  \n{detail}")

        _line(bool(cbbd_key), "CollegeBasketballData.com API key", "Configured", "Not set — see DATA_SOURCES.md")
        _line(bool(odds_key), "Odds API key", "Configured", "Not set — needed for Live Odds")

        st.caption("This pass ships navigation and theme only — tabs go live as each source above is wired in during the follow-up data pass.")

        st.markdown("---")
        st.markdown("**League-wide data**")
        st.caption(
            "Percentiles, D-I rankings, and matchup defense profiles are cached ~weekly "
            "(not re-fetched every visit) — a team/player's own stats stay fresh on their "
            "usual short cache. Click below for a fresh league-wide pull on demand."
        )
        if st.button("🔄 Refresh league-wide data", key="sb_refresh_league"):
            from data.loaders import clear_league_wide_caches
            clear_league_wide_caches()
            st.success("Cleared — next tab visit re-pulls current league-wide data.")


def render_team_banner(team_name, subtitle="", team_color=None):
    """Team identity banner (Player Search etc): name over a team-color
    gradient that fades into the app surface. Ported from CFB Scholar's
    identical function."""
    color = team_color or C['surface_container_high']
    sub_html = f"<div class='tb-sub'>{subtitle}</div>" if subtitle else ""
    st.markdown(
        f"<div class='team-banner' style='background: linear-gradient(90deg, {color}D9 0%, {color}66 40%, {C['surface_container']} 100%);'>"
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
            f"<div style='font-family:{F['mono']}; font-size:18px; font-weight:600; color:#ffffff; margin-top:2px;'>{value}</div>"
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
            f"<div style='font-family:{F['mono']}; font-size:11px; font-weight:700; color:{color}; margin-top:4px;'>{delta}</div>"
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
