"""
Theme CSS injection + Styler-based table renderers. Structure and CSS ported
directly from NFL Scholar (C:\\FantasyF\\ui\\styling.py) / CFB Scholar -
only the color values differ (violet primary). Every place the cyan/amber
siblings hardcoded their accent as a literal rgba(...) for a glow/tint
effect, this version computes the same rgba string from config.THEME's
primary color instead, so the accent is driven entirely by config.py.
"""
import base64
import html
import os
import re

import pandas as pd
import streamlit as st

from config import THEME, TEAM_CONFIG, CONFERENCE_COLORS, apply_theme_mode
from data.utils import (
    normalize_team_name as _normalize_team_name,
    expand_team_name_aliases as _expand_with_aliases,
    CONFERENCE_NAME_ALIASES,
)

C = THEME['colors']
F = THEME['fonts']
R = THEME['radius']
S = THEME['spacing']

# Sanitized (single quotes -> double quotes) font-family string for
# embedding inside a single-quoted inline HTML `style='...'` attribute -
# THEME['fonts'] values are themselves single-quoted (e.g. "'JetBrains
# Mono', monospace"), and splicing that raw into a `style='...'` attribute
# prematurely closes the attribute at the font name's own opening quote,
# silently dropping every declaration after it in that same style string.
# Real, confirmed bug (Playwright): render_sticky_footer_table's <table>
# had been rendering in Streamlit's default 16px Source Sans instead of
# the intended 12px JetBrains Mono for this table's entire history, which
# also meant its own column-width math was sized for the wrong font. Same
# fix ui.charts already established for its inline SVG styles
# (_BODY_FONT/_MONO_FONT) - not shared cross-module since it's a one-line,
# self-contained sanitization.
_MONO_FONT_SAFE = F['mono'].replace("'", '"')

# Precomputed once (CONFERENCE_COLORS is static, not live/per-season data) -
# normalized + alias-expanded so 'ACC', 'Atlantic Coast Conference', and any
# other spelling a source emits all resolve to the same color. Same "exact
# match first, normalized fallback second" pattern style_plain_dataframe's
# own _lookup already uses for Team/Opponent - see _conference_color below.
_CONFERENCE_NORM_MAP = _expand_with_aliases(
    {_normalize_team_name(k): v for k, v in CONFERENCE_COLORS.items()}, aliases=CONFERENCE_NAME_ALIASES,
)


def _conference_color(name):
    """Resolves any spelling of a conference name to its config.
    CONFERENCE_COLORS hex value, or None if unrecognized - shared by
    style_plain_dataframe's Styler (desktop) and render_responsive_table's
    _mobile_cell_bg (mobile cards) so both color a 'Conference' column
    identically."""
    if name is None:
        return None
    return CONFERENCE_COLORS.get(str(name)) or _CONFERENCE_NORM_MAP.get(_normalize_team_name(str(name)))

_FONT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'assets', 'fonts')
_FONT_FACES = [
    ('Inter', 400, 'inter-400.woff2'),
    ('Inter', 500, 'inter-500.woff2'),
    ('Inter', 600, 'inter-600.woff2'),
    ('Inter', 700, 'inter-700.woff2'),
    ('Inter', 800, 'inter-800.woff2'),
    ('JetBrains Mono', 400, 'jbmono-400.woff2'),
    ('JetBrains Mono', 600, 'jbmono-600.woff2'),
]


def _hex_to_rgb_str(hex_color):
    """'#c084fc' -> '192, 132, 252', for building rgba(...) glow/tint
    strings from a THEME hex value instead of hand-transcribing triplets."""
    h = hex_color.lstrip('#')
    return f"{int(h[0:2], 16)}, {int(h[2:4], 16)}, {int(h[4:6], 16)}"


# NOT cached as module-level constants (unlike the rest of this file's
# ported-as-is structure) - C['primary']/C['secondary'] change contents
# in place when apply_theme_mode() switches modes (see config.py), and a
# frozen string computed once at import time would go stale on the very
# first light/dark toggle. _hex_to_rgb_str(C['primary']) is called fresh
# at every use site below instead.


@st.cache_data
def _font_face_css():
    """Self-hosted @font-face declarations, base64-embedded directly in the
    stylesheet - see NFL Scholar's identical function for why. Ported as-is
    since fonts are sport-agnostic."""
    rules = []
    for family, weight, fname in _FONT_FACES:
        with open(os.path.join(_FONT_DIR, fname), 'rb') as f:
            b64 = base64.b64encode(f.read()).decode('ascii')
        rules.append(
            f"@font-face {{ font-family: '{family}'; font-style: normal; font-weight: {weight}; "
            f"font-display: swap; src: url(data:font/woff2;base64,{b64}) format('woff2'); }}"
        )
    return '\n        '.join(rules)


# Hover-tooltip text for column headers, keyed by exact displayed column
# name. Populated as real stat columns get built during the data-wiring
# pass; starts small (just what the shell's one live tab uses).
COLUMN_HELP = {
    'PCT': "Win percentage",
    'Streak': "Current win/loss streak (e.g. W3, L2)",
    'Overall': "Overall season record",
    'Pace': "Adjusted possessions per 40 minutes — tempo, not a quality claim. A fast team just plays more possessions per game, for better or worse.",
}


def build_column_help_config(df, pinned_cols=None, meter_cols=None):
    """Returns the st.dataframe(column_config=...) dict for columns with a
    COLUMN_HELP entry or a pin/meter request. Ported as-is from NFL Scholar."""
    pinned_cols = pinned_cols or []
    meter_cols = meter_cols or {}
    config = {}
    for col in df.columns:
        help_text = COLUMN_HELP.get(col)
        is_pinned = col in pinned_cols
        if col in meter_cols:
            lo, hi = meter_cols[col]
            config[col] = st.column_config.ProgressColumn(help=help_text, pinned=is_pinned, min_value=lo, max_value=hi, format="%.1f")
        elif help_text or is_pinned:
            config[col] = st.column_config.Column(help=help_text, pinned=is_pinned)
    return config


def inject_theme():
    apply_theme_mode(st.session_state.get('theme_mode', 'dark'))
    is_light = st.session_state.get('theme_mode', 'dark') == 'light'
    # A handful of rules below were originally hand-tuned as literal rgba()
    # triplets rather than derived from C[...] (glow/tint effects where a
    # bare hex wouldn't give the right alpha blend) - those don't
    # automatically follow C's mutation the way every `{C['x']}` spot in
    # this file does, so each needs its own explicit light-mode value here.
    # Dark-mode strings are copied byte-for-byte from what was already
    # here before light mode existed, so toggling to 'dark' can never
    # change dark mode's actual output - only the light branch is new.
    _header_bg = 'rgba(247, 245, 251, 0.72)' if is_light else 'rgba(5, 9, 33, 0.72)'
    _header_border = 'rgba(207, 201, 221, 0.6)' if is_light else 'rgba(44, 50, 96, 0.6)'
    _tab_hover_tint = 'rgba(23, 20, 38, 0.05)' if is_light else 'rgba(255, 255, 255, 0.05)'
    _panel_tint = 'rgba(234, 230, 245, 0.85)' if is_light else 'rgba(19, 27, 56, 0.55)'
    _card_tint = 'rgba(234, 230, 245, 0.7)' if is_light else 'rgba(19, 27, 56, 0.4)'
    _input_bg = 'rgba(0, 0, 0, 0.04)' if is_light else 'rgba(0, 0, 0, 0.25)'
    # Streamlit's own unchecked-checkbox box has no stable testid of its
    # own to target (confirmed live: it's an unnamed emotion-hashed div,
    # a sibling of the real <input>, not a descendant of any [role] or
    # data-testid wrapper) - rgb(7, 12, 44) is its literal current dark-
    # mode fill, copied byte-for-byte so toggling to 'dark' can't change
    # it; only the light branch is new.
    _checkbox_box_bg = C['surface_container_high'] if is_light else 'rgb(7, 12, 44)'
    st.markdown(f"""
        <style>
        {_font_face_css()}

        .stApp {{
            background:
                radial-gradient(1100px 420px at 18% -8%, rgba({_hex_to_rgb_str(C['secondary'])}, 0.16) 0%, rgba({_hex_to_rgb_str(C['secondary'])}, 0) 60%),
                radial-gradient(900px 380px at 85% -12%, rgba({_hex_to_rgb_str(C['primary'])}, 0.07) 0%, rgba({_hex_to_rgb_str(C['primary'])}, 0) 55%),
                linear-gradient(180deg, {C['surface']} 0%, {C['surface_dim']} 100%) !important;
            color: {C['on_surface']} !important;
            font-family: {F['body']} !important;
            font-variant-numeric: tabular-nums;
        }}

        header[data-testid="stHeader"] {{
            background: {_header_bg} !important;
            backdrop-filter: blur(8px);
            border-bottom: 1px solid {_header_border};
        }}
        [data-testid="stAppDeployButton"], .stDeployButton, footer {{ display: none !important; }}

        .block-container {{
            padding-top: 4.5rem !important;
            padding-bottom: 2rem !important;
            padding-left: 2.5rem !important;
            padding-right: 2.5rem !important;
            max-width: none !important;
        }}

        h1, h2, h3, h4 {{
            font-family: {F['display']} !important;
            font-weight: 700 !important;
            color: {C['on_surface']};
            margin-bottom: 0.5rem;
            letter-spacing: -0.01em;
        }}

        .custom-section-header {{
            display: flex;
            align-items: center;
            gap: 10px;
            color: {C['on_surface']} !important;
            font-family: {F['display']};
            font-size: 12.5px !important;
            font-weight: 800 !important;
            text-transform: uppercase !important;
            letter-spacing: 0.1em !important;
            padding: 6px 0 8px 0 !important;
            margin-top: 26px !important;
            margin-bottom: 12px !important;
            border-bottom: 1px solid {C['outline_variant']};
        }}
        .custom-section-header::before {{
            content: "";
            display: inline-block;
            width: 4px;
            height: 14px;
            border-radius: 2px;
            background: {C['primary']};
            box-shadow: 0 0 8px rgba({_hex_to_rgb_str(C['primary'])}, 0.5);
            flex: 0 0 auto;
        }}

        div[data-testid="stTabs"] [role="tablist"] {{
            gap: 4px;
            border-bottom: 1px solid {C['outline_variant']};
            padding-bottom: 6px;
            flex-wrap: wrap;
        }}
        [data-testid="stTab"], div[data-testid="stTabs"] button[data-baseweb="tab"] {{
            border-radius: {R['full']} !important;
            padding: 6px 18px !important;
            transition: background-color 150ms ease-out;
            cursor: pointer;
        }}
        [data-testid="stTab"]:hover, div[data-testid="stTabs"] button[data-baseweb="tab"]:hover {{
            background-color: {_tab_hover_tint} !important;
        }}
        [data-testid="stTab"] p, button[data-baseweb="tab"] p {{
            color: {C['on_surface_variant']} !important;
            font-family: {F['display']};
            font-size: 12.5px !important;
            font-weight: 600 !important;
            letter-spacing: 0.02em;
        }}
        [data-testid="stTab"][aria-selected="true"], button[data-baseweb="tab"][aria-selected="true"] {{
            background-color: rgba({_hex_to_rgb_str(C['primary'])}, 0.10) !important;
        }}
        [data-testid="stTab"][aria-selected="true"] p, button[data-baseweb="tab"][aria-selected="true"] p {{
            color: {C['primary']} !important;
        }}
        div[data-baseweb="tab-highlight"] {{ background-color: {C['primary']} !important; }}

        div[data-testid="stMetric"] {{
            background: {C['surface_container']};
            border: 1px solid {C['outline_variant']};
            border-radius: {R['md']};
            padding: 10px 14px;
        }}
        div[data-testid="stMetric"] label, div[data-testid="stMetricLabel"] p {{
            color: {C['on_surface_variant']} !important;
            font-size: 11px !important;
            font-weight: 700 !important;
            text-transform: uppercase;
            letter-spacing: 0.07em;
        }}
        div[data-testid="stMetricValue"] {{
            font-family: {F['mono']} !important;
            font-size: 24px !important;
            font-weight: 600;
            color: {C['on_surface']} !important;
        }}

        div[data-testid="stAlert"] {{
            background: {_panel_tint} !important;
            border: 1px solid {C['outline_variant']} !important;
            border-radius: {R['md']} !important;
            backdrop-filter: blur(6px);
            color: {C['on_surface']} !important;
        }}
        div[data-testid="stAlert"] p {{ color: {C['on_surface']} !important; }}

        section[data-testid="stSidebar"] {{
            background: {C['surface_dim']} !important;
            border-right: 1px solid {C['outline_variant']};
            color: {C['on_surface']} !important;
        }}
        /* Two spots inside the sidebar re-assert Streamlit's own native
           text color on a wrapper BELOW the section-level override above
           (confirmed live via Chrome DevTools Protocol matched-styles, not
           guessed) instead of inheriting it: a radio/checkbox/select
           option's own inner wrapper, and the sidebar's collapse-icon
           button. Both needed their own explicit override - the section-
           level `color` above never reaches either. */
        [data-testid="stRadioOption"] p, [data-testid="stCheckbox"] p,
        [data-testid="stSelectbox"] p, [data-testid="stWidgetLabel"] p {{
            color: {C['on_surface']} !important;
        }}
        [data-testid="stSidebarCollapseButton"] svg, [data-testid="stSidebarCollapseButton"] span {{
            color: {C['on_surface_variant']} !important;
            fill: {C['on_surface_variant']} !important;
        }}

        ::-webkit-scrollbar {{ width: 10px; height: 10px; }}
        ::-webkit-scrollbar-track {{ background: transparent; }}
        ::-webkit-scrollbar-thumb {{ background: {C['surface_container_highest']}; border-radius: 8px; }}
        ::-webkit-scrollbar-thumb:hover {{ background: {C['outline']}; }}

        .stat-tile-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(108px, 1fr));
            gap: 8px;
            margin: 4px 0 8px 0;
        }}
        .stat-tile {{
            position: relative;
            background: {C['surface_container']};
            border: 1px solid {C['outline_variant']};
            border-radius: {R['default']};
            padding: 9px 34px 10px 11px;
            overflow: hidden;
        }}
        .stat-tile .t-label {{
            font-size: 10px;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.06em;
            color: {C['on_surface_variant']};
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }}
        .stat-tile .t-value {{
            font-family: {F['mono']};
            font-size: 16.5px;
            font-weight: 600;
            color: {C['on_surface']};
            margin-top: 3px;
            line-height: 1.15;
        }}

        .hero-tile-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
            gap: 10px;
            margin: 10px 0 4px 0;
        }}
        .hero-tile {{
            background: linear-gradient(180deg, {C['surface_container']} 0%, {C['surface_container_low']} 100%);
            border: 1px solid {C['outline_variant']};
            border-radius: {R['md']};
            padding: 12px 14px;
            text-align: center;
        }}
        .hero-tile .h-label {{
            font-size: 10.5px;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            color: {C['on_surface_variant']};
        }}
        .hero-tile .h-value {{
            font-family: {F['mono']};
            font-size: 26px;
            font-weight: 600;
            color: {C['on_surface']};
            line-height: 1.2;
            margin-top: 2px;
        }}
        .hero-tile .h-sub {{
            font-size: 10.5px;
            color: {C['on_surface_variant']};
            margin-top: 2px;
        }}

        .team-banner {{
            display: flex;
            align-items: center;
            gap: 16px;
            border-radius: {R['md']};
            padding: 14px 18px;
            margin: 6px 0 14px 0;
            border: 1px solid {C['outline_variant']};
        }}
        .team-banner img {{ height: 52px; width: 52px; object-fit: contain; filter: drop-shadow(0 2px 6px rgba(0,0,0,0.5)); }}
        .team-banner .tb-name {{
            font-family: {F['display']};
            font-size: 22px;
            font-weight: 800;
            letter-spacing: -0.01em;
            color: #ffffff;
            text-shadow: 0 2px 4px rgba(0,0,0,0.4);
            line-height: 1.1;
        }}
        .team-banner .tb-sub {{
            font-size: 11px;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            color: rgba(255,255,255,0.75);
            margin-top: 2px;
        }}

        /* "Coming soon" placeholder card (see ui.components.render_coming_soon) -
           one shared empty-state treatment for every not-yet-wired tab. */
        .coming-soon-card {{
            background: {_card_tint};
            border: 1px dashed {C['outline_variant']};
            border-radius: {R['lg']};
            padding: 28px 30px;
            margin: 10px 0;
        }}
        .coming-soon-card .cs-eyebrow {{
            font-size: 11px;
            font-weight: 800;
            text-transform: uppercase;
            letter-spacing: 0.1em;
            color: {C['primary']};
            margin-bottom: 8px;
        }}
        .coming-soon-card .cs-blurb {{
            font-size: 14px;
            color: {C['on_surface_variant']};
            line-height: 1.5;
            max-width: 720px;
            margin-bottom: 14px;
        }}
        .coming-soon-card .cs-sources {{
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
        }}
        .coming-soon-card .cs-source-chip {{
            background: {C['surface_container_high']};
            border: 1px solid {C['outline_variant']};
            border-radius: {R['full']};
            padding: 5px 14px;
            font-size: 11.5px;
            font-weight: 600;
            color: {C['on_surface']};
            font-family: {F['mono']};
        }}

        div[data-testid="stExpander"] {{
            background: {_card_tint} !important;
            border: 1px solid {C['outline_variant']} !important;
            border-radius: {R['md']} !important;
            backdrop-filter: blur(8px);
        }}
        div[data-testid="stExpander"] summary {{
            font-family: {F['display']};
            font-weight: 600 !important;
        }}

        .stButton button, .stDownloadButton button {{
            background-color: {C['surface_container']} !important;
            color: {C['on_surface']} !important;
            border-radius: {R['full']} !important;
            font-family: {F['display']};
            font-weight: 600 !important;
            border: 1px solid {C['outline_variant']} !important;
            transition: all 150ms ease-out;
        }}
        .stButton button:hover, .stDownloadButton button:hover {{
            border-color: {C['primary']} !important;
            color: {C['primary']} !important;
            background-color: rgba({_hex_to_rgb_str(C['primary'])}, 0.06) !important;
        }}
        .stButton button[kind="primary"] {{
            background-color: {C['primary']} !important;
            color: {C['on_primary']} !important;
            border: none !important;
        }}

        .stSelectbox [role="group"], .stMultiSelect [role="group"],
        .stNumberInput [role="group"], .stDateInput [role="group"],
        div[data-baseweb="select"] > div,
        [data-testid="stTextInputRootElement"], [data-testid="stTextAreaRootElement"],
        [data-testid="stNumberInputContainer"] {{
            background-color: {_input_bg} !important;
            border-radius: {R['default']} !important;
            border: 1px solid {C['outline_variant']} !important;
            color: {C['on_surface']} !important;
        }}
        .stSelectbox [role="group"] input, .stMultiSelect [role="group"] input, .stNumberInput [role="group"] input,
        .stTextInput input, .stTextArea textarea, .stNumberInput input {{
            background-color: transparent !important;
            border: none !important;
            color: {C['on_surface']} !important;
        }}
        /* The checkbox glyph box itself: a sibling of the real (visually
           hidden) <input type="checkbox">, not reachable by any stable
           testid/role - :has() lets this anchor off the one stable thing
           nearby (the [data-testid="stWidgetLabel"] that always follows
           it) instead of an emotion-hash class. */
        [data-testid="stCheckbox"] div:has(+ [data-testid="stWidgetLabel"]) {{
            background-color: {_checkbox_box_bg} !important;
        }}
        .stSelectbox [role="group"]:focus-within, .stMultiSelect [role="group"]:focus-within,
        .stNumberInput [role="group"]:focus-within, .stDateInput [role="group"]:focus-within,
        div[data-baseweb="select"] > div:focus-within, .stTextInput input:focus, .stTextArea textarea:focus {{
            border-color: {C['primary']} !important;
            box-shadow: 0 0 0 2px rgba({_hex_to_rgb_str(C['primary'])}, 0.15) !important;
        }}
        .stSelectbox [role="group"]:hover, .stMultiSelect [role="group"]:hover,
        .stNumberInput [role="group"]:hover, .stDateInput [role="group"]:hover,
        div[data-baseweb="select"] > div:hover, .stTextInput input:hover, .stTextArea textarea:hover {{
            border-color: {C['outline']} !important;
        }}

        div.stSelectbox {{ margin-bottom: -10px !important; }}

        div[data-testid="stFullScreenFrame"]:has(div[data-testid="stImage"]) button[data-testid="stBaseButton-elementToolbar"] {{
            display: none !important;
        }}

        div[data-testid="stDataFrame"], div[data-testid="stTable"], .stDataFrame {{
            background-color: {C['surface_container']} !important;
            border: 1px solid {C['outline_variant']} !important;
            border-radius: {R['sm']} !important;
            padding: 6px;
            font-family: {F['mono']} !important;
        }}
        div[data-testid="stDataFrame"] * {{
            color: {C['on_surface']} !important;
            font-family: {F['mono']} !important;
        }}

        /* --- Elevation & depth polish (additive - no rule above changes) --- */
        .stat-tile, .hero-tile, .team-banner, .coming-soon-card {{
            box-shadow: 0 1px 2px rgba(0, 0, 0, 0.35), 0 8px 20px -10px rgba(0, 0, 0, 0.55);
        }}
        div[data-testid="stMetric"], div[data-testid="stAlert"], div[data-testid="stExpander"],
        div[data-testid="stDataFrame"], div[data-testid="stTable"] {{
            box-shadow: 0 1px 2px rgba(0, 0, 0, 0.35), 0 8px 20px -10px rgba(0, 0, 0, 0.55) !important;
        }}
        .stat-tile, .hero-tile {{
            transition: transform 140ms ease-out, border-color 140ms ease-out, box-shadow 140ms ease-out;
        }}
        .stat-tile:hover, .hero-tile:hover {{
            border-color: rgba({_hex_to_rgb_str(C['primary'])}, 0.55);
            box-shadow: 0 1px 2px rgba(0, 0, 0, 0.35), 0 10px 22px -10px rgba({_hex_to_rgb_str(C['primary'])}, 0.3) !important;
            transform: translateY(-1px);
        }}

        /* --- Chart hover affordances (additive) ---------------------------
           Every custom inline-SVG chart (ui/charts.py) marks its data
           shapes with one of these classes so hovering ANY bar/cell/dot
           throughout the app gives a visible response, not just the
           native <title> tooltip (which has no visual change and a
           noticeable delay before it appears) - this was asked for
           explicitly: hover feedback on individual stats, not just
           headers/buttons. transform-box:fill-box makes scale() pivot
           around each shape's own center instead of the whole SVG's
           origin corner, which is what "grow in place" needs.

           NOTE: st.dataframe's grid (Player Search's game log, NET/Polls/
           Standings tables, Transfer Portal, etc.) is canvas-rendered
           (glide-data-grid), not real DOM - confirmed live that it has NO
           native row/cell hover highlight in this Streamlit version, and
           CSS cannot reach into a canvas to add one. Every OTHER stat
           display in this app (percentile bars, mirror bars, the Four
           Factors heatmap, scatter/trend/radar/trajectory charts, stat
           tiles above) is real DOM and gets real hover feedback below. */
        svg .hz-bar, svg .hz-cell {{
            transition: filter 110ms ease-out, stroke-width 110ms ease-out;
            cursor: pointer;
        }}
        svg .hz-bar:hover, svg .hz-cell:hover {{
            filter: brightness(1.3);
            stroke: rgba(255, 255, 255, 0.6);
            stroke-width: 1.5px;
        }}
        svg .hz-dot {{
            transition: filter 110ms ease-out, transform 110ms ease-out;
            transform-box: fill-box;
            transform-origin: center;
            cursor: pointer;
        }}
        svg .hz-dot:hover {{
            filter: brightness(1.35) drop-shadow(0 0 5px rgba({_hex_to_rgb_str(C['primary'])}, 0.75));
            transform: scale(1.45);
        }}
        svg .hz-line {{
            transition: filter 110ms ease-out, stroke-width 110ms ease-out;
        }}
        svg:has(.hz-line:hover) .hz-line {{
            filter: brightness(1.2);
        }}

        /* Bio strip cells (ui.components.render_bio_strip) and W/L form
           chips (ui.charts.render_form_strip) - small hover lift so these
           read as individually-hoverable stats too, matching the tile/
           chart treatment above. */
        .bio-cell {{
            transition: background-color 110ms ease-out;
        }}
        .bio-cell:hover {{
            background-color: {C['surface_container_high']};
            cursor: default;
        }}
        .form-chip {{
            transition: transform 110ms ease-out, filter 110ms ease-out;
        }}
        .form-chip:hover {{
            transform: translateY(-2px);
            filter: brightness(1.2);
            cursor: pointer;
        }}

        /* Dataframe toolbar icons (sort/search/download/fullscreen overlays)
           default to a light-mode gray - retint to the dark theme + accent
           hover so they don't read as a foreign widget. Selector confirmed
           live elsewhere in this file (stFullScreenFrame image-toolbar rule
           above uses the same testid). */
        button[data-testid="stBaseButton-elementToolbar"] {{
            color: {C['on_surface_variant']} !important;
            transition: color 120ms ease-out;
        }}
        button[data-testid="stBaseButton-elementToolbar"]:hover {{
            color: {C['primary']} !important;
        }}

        /* ===================================================================
           MOBILE RESPONSIVENESS (<=767px only) - every rule in this block is
           scoped to this one media query, so nothing here touches >=768px.
           Two different patterns depending on what a given table actually IS:
           1. Hand-rolled HTML tables (render_sticky_footer_table's
              `.sft-table`) are real DOM - a genuine table-row -> card CSS
              transform is possible and lives here.
           2. st.dataframe tables are canvas-rendered (glide-data-grid) - CSS
              cannot restyle individual cells/rows in them at all (see the
              chart-hover-affordance comment above, confirmed live). Those get
              a SEPARATE hand-rolled mobile card component instead
              (ui.styling.render_responsive_table), toggled by the .st-key-*
              classes st.container(key=...) emits - a media query choosing
              WHICH of two whole components to show, not a query reaching
              inside the dataframe itself.
           =================================================================== */
        @media (max-width: 767px) {{
            /* --- render_sticky_footer_table: row -> card. Header hidden (each
               cell shows its own label instead, via the data-label attribute
               that function now emits); every column stays present, just
               reflowed into a labeled grid.

               Desktop scrolls `<tbody>` alone (`overflow-y:auto` set inline,
               with `<thead>`/`<tfoot>` as non-scrolling siblings above/below
               it - see render_sticky_footer_table's docstring for why: a
               position:sticky-based footer/header turned out not to work at
               all here, confirmed live). Mobile's card stack doesn't need
               that split at all - one `<div class='sft-outer'>` scrolling
               everything together reads perfectly fine as a vertical list,
               so `<tbody>`'s own inline max-height/overflow-y is reset here
               and the OUTER container becomes the one scroll box instead, at
               a viewport-relative height (a card is 3-5x taller than a
               table row, so reusing the desktop px height here clipped
               cards mid-content - confirmed live before this fix existed). */
            .sft-outer {{ max-height: 65vh !important; overflow-y: auto !important; }}
            .sft-scrollx {{ overflow-x: visible !important; }}
            .sft-table thead {{ display: none !important; }}
            /* min-width: 0 - desktop's table/thead/tbody/tfoot/tr all carry
               an inline min-width (the table's own safe-minimum total px,
               see render_sticky_footer_table) now - it's what makes the
               table stretch to fill a wide container without ever
               shrinking narrower than every column's safe minimum on
               desktop. That inline min-width isn't touched by
               `width: 100% !important` below (a different property -
               setting one doesn't clear the other),
               so without this reset it silently won by cascade here too:
               confirmed live (Playwright) that every card's fields beyond
               the first ~1/3 of each row were being laid out past
               .sft-outer's own edge and clipped invisibly by its
               overflow-x:hidden, with no way to scroll to them - the
               mobile card view looked complete (one full column of
               fields) but was actually missing 2 out of every 3 columns.
               table-layout also resets to auto - fixed's algorithm has
               nothing meaningful to do once display is no longer
               table/table-row-group, and leaving it set alongside the
               inline min-width was part of the same layout confusion. */
            .sft-table, .sft-table tbody, .sft-table tfoot {{
                display: block !important;
                width: 100% !important;
                min-width: 0 !important;
                max-height: none !important;
                overflow-y: visible !important;
                table-layout: auto !important;
            }}
            .sft-table tr.sft-row, .sft-table tr.sft-footer-row {{
                display: flex !important;
                flex-wrap: wrap;
                gap: 2px 14px;
                width: 100% !important;
                min-width: 0 !important;
                border: 1px solid {C['outline_variant']};
                border-radius: {R['md']};
                margin: 0 0 8px 0;
                padding: 10px 12px;
                background: {C['surface_container']};
            }}
            .sft-table tr.sft-footer-row {{
                border-top: 2px solid {C['primary']};
                margin-top: 4px;
                border-color: {C['primary']};
                background: {C['surface_container_high']};
            }}
            .sft-table tr.sft-row td, .sft-table tr.sft-footer-row td {{
                display: block !important;
                position: static !important;
                flex: 1 1 26%;
                width: auto !important;
                min-width: 0 !important;
                max-width: none !important;
                padding: 2px 4px !important;
                white-space: normal !important;
                text-align: left !important;
                border: none !important;
                border-radius: {R['sm']};
            }}
            .sft-table tr.sft-row td::before, .sft-table tr.sft-footer-row td::before {{
                content: attr(data-label);
                display: block;
                font-size: 9px;
                font-weight: 700;
                text-transform: uppercase;
                letter-spacing: 0.05em;
                color: {C['on_surface_variant']};
                margin-bottom: 1px;
            }}

            /* --- render_responsive_table's mobile card list (st.dataframe
               replacement) - see that function's own docstring for the
               desktop/mobile toggle mechanism. Cards use the same visual
               language as .sft-table above for consistency. */
            .rt-card {{
                border: 1px solid {C['outline_variant']};
                border-radius: {R['md']};
                padding: 10px 12px;
                margin: 0 0 8px 0;
                background: {C['surface_container']};
                font-family: {F['mono']};
                font-size: 12px;
                color: {C['on_surface']};
            }}
            .rt-card .rt-primary {{
                font-size: 14px;
                font-weight: 700;
                margin-bottom: 6px;
                padding-bottom: 6px;
                border-bottom: 1px solid {C['outline_variant']};
            }}
            .rt-card .rt-fields {{
                display: flex;
                flex-wrap: wrap;
                gap: 4px 14px;
            }}
            .rt-card .rt-field {{
                flex: 1 1 40%;
            }}
            .rt-card .rt-field .rt-label {{
                display: block;
                font-size: 9px;
                font-weight: 700;
                text-transform: uppercase;
                letter-spacing: 0.05em;
                color: {C['on_surface_variant']};
                margin-bottom: 1px;
            }}

            /* --- Touch targets: buttons/selects/inputs/checkbox/slider all
               bumped to >=44x44px (WCAG 2.5.5 / Apple & Material HIG's
               shared minimum) - desktop's own sizing (set earlier in this
               file, outside this media query) is untouched. Every selector
               below is a STABLE Streamlit-assigned class/testid (.stButton,
               .stCheckbox, data-testid="stSlider", etc.), not one of
               Streamlit's own internal emotion-hashed classes (those change
               across versions and would be fragile to depend on). */
            .stButton button, .stDownloadButton button {{
                min-height: 44px;
                min-width: 44px;
                padding: 10px 20px !important;
            }}
            .stSelectbox [role="group"], .stMultiSelect [role="group"],
            .stNumberInput [role="group"], .stDateInput [role="group"],
            div[data-baseweb="select"] > div, .stTextInput input, .stTextArea textarea, .stNumberInput input {{
                min-height: 44px !important;
            }}
            /* Checkbox: the native input is tiny (~13px) but its <label>
               wraps the whole row and IS the real click target per HTML
               semantics - stretch that to 44px instead of resizing the
               checkbox glyph itself (which would look oversized/broken). */
            .stCheckbox {{
                min-height: 44px;
                display: flex;
                align-items: center;
            }}
            /* Slider: the actual thumb lives inside Streamlit's own
               emotion-hashed markup (unstable across versions - not safe to
               target directly). Thickening the stable [role="group"] drag
               strip widens the effective grabbable area without depending
               on those internal class names. */
            div[data-testid="stSlider"] [role="group"] {{
                padding: 10px 0;
            }}
        }}
        </style>
    """, unsafe_allow_html=True)


# 7-stop diverging scale, poor (0) -> elite (100). Ported as-is from NFL
# Scholar's get_pff_color (renamed get_grade_color - see CFB Scholar's
# identical function for why: no longer necessarily PFF-sourced).
_GRADE_COLOR_STOPS = [
    (0, (208, 98, 94)),
    (16, (214, 126, 112)),
    (32, (223, 165, 122)),
    (50, (117, 181, 172)),
    (68, (137, 178, 224)),
    (84, (100, 130, 205)),
    (100, (172, 148, 205)),
]
_GRADE_ALPHA = 0.82


def get_grade_color(val, raw_grade=False):
    try:
        val = float(val)
    except (TypeError, ValueError):
        return C['surface_container_high']
    if pd.isna(val) or val <= 0:
        return C['surface_container_high']
    for (lo_val, lo_rgb), (hi_val, hi_rgb) in zip(_GRADE_COLOR_STOPS, _GRADE_COLOR_STOPS[1:]):
        if lo_val <= val <= hi_val:
            frac = (val - lo_val) / (hi_val - lo_val)
            r = round(lo_rgb[0] + (hi_rgb[0] - lo_rgb[0]) * frac)
            g = round(lo_rgb[1] + (hi_rgb[1] - lo_rgb[1]) * frac)
            b = round(lo_rgb[2] + (hi_rgb[2] - lo_rgb[2]) * frac)
            return f"rgba({r}, {g}, {b}, {_GRADE_ALPHA})"
    r, g, b = _GRADE_COLOR_STOPS[-1][1]
    return f"rgba({r}, {g}, {b}, {_GRADE_ALPHA})"


_MATCHUP_COLOR_STOPS = [
    (0, (176, 62, 56)),
    (25, (196, 130, 68)),
    (50, (196, 178, 76)),
    (75, (150, 189, 104)),
    (100, (99, 163, 105)),
]
_MATCHUP_ALPHA = 0.75


def get_matchup_color(pct):
    try:
        pct = float(pct)
    except (TypeError, ValueError):
        return C['surface_container_high']
    if pd.isna(pct):
        return C['surface_container_high']
    pct = max(0.0, min(100.0, pct))
    for (lo_val, lo_rgb), (hi_val, hi_rgb) in zip(_MATCHUP_COLOR_STOPS, _MATCHUP_COLOR_STOPS[1:]):
        if lo_val <= pct <= hi_val:
            frac = (pct - lo_val) / (hi_val - lo_val)
            r = round(lo_rgb[0] + (hi_rgb[0] - lo_rgb[0]) * frac)
            g = round(lo_rgb[1] + (hi_rgb[1] - lo_rgb[1]) * frac)
            b = round(lo_rgb[2] + (hi_rgb[2] - lo_rgb[2]) * frac)
            return f"rgba({r}, {g}, {b}, {_MATCHUP_ALPHA})"
    r, g, b = _MATCHUP_COLOR_STOPS[-1][1]
    return f"rgba({r}, {g}, {b}, {_MATCHUP_ALPHA})"


def _hex_to_rgb(h):
    h = h.lstrip('#')
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _blend_hex(c1, c2, frac):
    frac = max(0.0, min(1.0, frac))
    r1, g1, b1 = _hex_to_rgb(c1)
    r2, g2, b2 = _hex_to_rgb(c2)
    return f"#{round(r1 + (r2 - r1) * frac):02x}{round(g1 + (g2 - g1) * frac):02x}{round(b1 + (b2 - b1) * frac):02x}"


def get_diverging_color(val, max_abs):
    """Red-green diverging color for signed delta columns, scaled by
    magnitude relative to max_abs. Ported as-is from NFL Scholar."""
    if pd.isna(val) or not max_abs:
        return C['surface_container_high']
    frac = max(-1.0, min(1.0, float(val) / max_abs))
    if abs(frac) < 0.05:
        return C['surface_container_high']
    return _blend_hex(C['surface_container_high'], C['positive'] if frac > 0 else C['negative'], abs(frac))


def style_plain_dataframe(df, numeric_pct_cols=None, diverging_cols=None, matchup_pct_cols=None,
                           team_color_map=None, opponent_col=None, opponent_color_map=None, win_loss_col=None):
    """Sortable Styler for st.dataframe. Ported as-is from NFL Scholar - see
    that module's docstring for why this is a Styler + st.dataframe (not
    raw HTML): the grid draws its own header from .streamlit/config.toml,
    not page CSS, so a proper dark theme config is what actually themes it.

    team_color_map: optional {team_name: hex_color} dict, keyed however the
    caller's own 'Team' column values are keyed. Overrides the static
    config.TEAM_CONFIG lookup below - callers with live team colors (e.g.
    data.loaders.team_color_map(), keyed by full school name) should pass
    theirs in rather than relying on the abbreviation-keyed static dict.
    Both the 'Team' column and any `opponent_col` below try an EXACT key
    match first, then fall back to a normalized (punctuation/case/common-
    suffix-insensitive) match via _normalize_team_name - different sources
    format the same school's name differently (ncaa.com scrape vs CBBD vs
    ESPN), and an exact-only lookup silently renders no color on a mismatch
    rather than erroring, which is easy to miss.

    A 'Conference' column (if present) is always colored too, via config.
    CONFERENCE_COLORS - same exact-then-normalized-alias lookup as 'Team'
    (see _conference_color), not something callers opt into or configure.

    IMPORTANT: 'Team' must be an actual COLUMN of `df`, not the DataFrame's
    index (i.e. don't call this on a `df.set_index('Team')` result if you
    want it colored) - confirmed live (not just by reading the code) that
    Streamlit's dataframe grid does not render ANY pandas-Styler styling
    applied to the index/row-header cells, via either `.apply(axis=1)` or
    `.apply_index(axis=0)` - only real data-column cells pick up Styler
    colors. Use `hide_index=True` on the st.dataframe(...) call plus a
    plain sequential/Rank index instead, the same pattern Conference
    Standings and the game log table already use successfully.

    opponent_col/opponent_color_map: optional - tints just that one column
    (not the whole row) with THAT row's opponent team color at reduced
    opacity, a lighter "colored chip" treatment for tables like the game
    log where 'Team' isn't the row subject but 'Opponent' still benefits
    from an at-a-glance color cue. Defaults opponent_color_map to
    team_color_map when a column is given but no separate map is.

    win_loss_col: optional column name whose 'W'/'L' text gets tinted with
    THIS app's existing positive/negative colors (the same green/red
    ui.charts.render_form_strip already uses for W/L chips elsewhere) -
    kept as its own dedicated param rather than routed through
    numeric_pct_cols' percentile scale, since win/loss has an established
    color meaning in this app that a generic percentile gradient would
    contradict.
    """
    numeric_pct_cols = numeric_pct_cols or {}
    diverging_cols = diverging_cols or {}
    matchup_pct_cols = matchup_pct_cols or {}
    team_color_map = team_color_map if team_color_map is not None else {v['name']: v['color'] for v in TEAM_CONFIG.values()}
    team_color_map = {**team_color_map, **{k: v['color'] for k, v in TEAM_CONFIG.items()}}
    opponent_color_map = opponent_color_map if opponent_color_map is not None else (team_color_map if opponent_col else {})
    pct_arrays = {col: list(vals) for col, vals in numeric_pct_cols.items()}
    matchup_arrays = {col: list(vals) for col, vals in matchup_pct_cols.items()}
    norm_team_map = _expand_with_aliases({_normalize_team_name(k): v for k, v in team_color_map.items()})
    norm_opp_map = _expand_with_aliases({_normalize_team_name(k): v for k, v in opponent_color_map.items()})

    def _lookup(name, exact_map, norm_map):
        color = exact_map.get(str(name))
        return color or norm_map.get(_normalize_team_name(name))

    def style_row(row):
        pos = df.index.get_loc(row.name)
        styles = []
        for col in df.columns:
            if col in diverging_cols:
                bg = get_diverging_color(row[col], diverging_cols[col])
                styles.append(f'background-color:{bg}; color:#ffffff; font-weight:bold;')
            elif col in matchup_arrays and pos < len(matchup_arrays[col]):
                bg = get_matchup_color(matchup_arrays[col][pos])
                styles.append(f'background-color:{bg}; color:#ffffff; font-weight:bold;')
            elif col in pct_arrays and pos < len(pct_arrays[col]):
                bg = get_grade_color(pct_arrays[col][pos])
                styles.append(f'background-color:{bg}; color:#ffffff; font-weight:bold;')
            elif col == 'Team':
                team_color = _lookup(row[col], team_color_map, norm_team_map)
                if team_color:
                    styles.append(f"background-color:{team_color}; color:#ffffff; font-weight:bold;")
                else:
                    styles.append(f"background-color:{C['surface_container']}; color:{C['on_surface']};")
            elif col == 'Conference':
                conf_color = _conference_color(row[col])
                if conf_color:
                    styles.append(f"background-color:{conf_color}; color:#ffffff; font-weight:bold;")
                else:
                    styles.append(f"background-color:{C['surface_container']}; color:{C['on_surface']};")
            elif opponent_col and col == opponent_col:
                opp_color = _lookup(row[col], opponent_color_map, norm_opp_map)
                if opp_color:
                    styles.append(f"background-color:{opp_color}66; color:#ffffff; font-weight:600;")
                else:
                    styles.append(f"background-color:{C['surface_container']}; color:{C['on_surface']};")
            elif win_loss_col and col == win_loss_col:
                v = str(row[col]).strip().upper()
                if v == 'W':
                    styles.append(f"background-color:{C['positive']}2e; color:{C['positive']}; font-weight:800;")
                elif v == 'L':
                    styles.append(f"background-color:{C['negative']}2e; color:{C['negative']}; font-weight:800;")
                else:
                    styles.append(f"background-color:{C['surface_container']}; color:{C['on_surface']};")
            else:
                styles.append(f"background-color:{C['surface_container']}; color:{C['on_surface']};")
        return styles

    styler = df.style.apply(style_row, axis=1)

    fmt = {}
    for col in df.columns:
        if not pd.api.types.is_numeric_dtype(df[col]):
            continue
        non_null = df[col].dropna()
        is_whole = non_null.empty or (non_null.round(0) - non_null).abs().max() < 0.05
        decimals = 0 if is_whole else 1
        fmt[col] = f"{{:.{decimals}f}}"
    if fmt:
        styler = styler.format(fmt, na_rep='--')

    return styler


def df_auto_height(n_rows, row_px=35, header_px=38, padding_px=3):
    """Sizes an st.dataframe to its actual row count so nothing needs an
    internal scrollbar to be fully visible. Ported as-is from NFL Scholar."""
    return header_px + max(n_rows, 1) * row_px + padding_px


def _table_decimals(series):
    """0 decimals if every non-null value in `series` is (near enough)
    whole, else 1 - same rule style_plain_dataframe's own Styler.format
    uses, applied here per-column so a hand-rolled table formats the same
    way a Styler-driven st.dataframe would."""
    s = pd.to_numeric(series, errors='coerce').dropna()
    if s.empty:
        return 1
    return 0 if (s.round(0) - s).abs().max() < 0.05 else 1


def render_sticky_footer_table(df, footer, numeric_cols=None, team_color_map=None,
                                opponent_col=None, win_loss_col=None, height=360,
                                mobile_headline_cols=None):
    """
    Hand-rolled scrollable HTML table with a season-average FOOTER row that
    stays genuinely visible below the scroll area no matter how far you've
    scrolled through the rows above it. st.dataframe/glide-data-grid has no
    row-pinning API at all (only COLUMN pinning via column_config) -
    confirmed no such option exists in this Streamlit version - so two
    stacked st.dataframe widgets (a game log + a separate "average row"
    table, CSS-seamed to look like one) was an earlier approach here, but
    that's still two independent canvas grids under the hood: each has its
    own horizontal scroll state, so scrolling one sideways doesn't move the
    other and the illusion breaks.

    CORRECTION: an earlier version of this function used `position: sticky`
    on the header/footer `<td>`/`<th>` cells. Live-confirmed (Playwright,
    real Chromium, not just reading the code) that this does NOT work at
    all here: `position: sticky` on table cells is unreliable across
    browsers specifically when the table also has `border-collapse:
    collapse` (a long-documented CSS interaction gap), and directly
    measuring header/footer position at several scroll offsets showed both
    moving in exact lockstep with scroll - i.e. no sticky effect
    whatsoever, just an ordinary last/first row a user could scroll past
    entirely, with an invisible spacer row (a prior, still-wrong fix aimed
    at a sticky-overlap theory that never applied) sitting oddly between
    the last real row and the footer. Replaced with a technique that
    doesn't depend on `position: sticky` at all: `<thead>`/`<tbody>`/
    `<tfoot>` are forced to `display: block` (each `<tr>` inside re-asserts
    `display: table` so its own cells still lay out as a row), and the
    SCROLLING itself is moved onto `<tbody>` alone (`overflow-y: auto`,
    `max-height`) - `<thead>`/`<tfoot>` are then simply never part of the
    scrolling region at all, so there's no positioning trick that can fail;
    they're just always-rendered siblings above/below the scrollable body.
    Horizontal scrolling (this table has more columns than fit most
    viewports) still happens once, at the outer wrapping div, moving
    `<thead>`/`<tbody>`/`<tfoot>` together in lockstep.

    Column alignment across the three now-independent sections requires an
    explicit, identical width per column on every cell in all three
    (auto/content-based table layout can't produce consistent widths once
    each section is its own layout context) - `_col_width_px` below sizes
    each column from its header label and actual longest formatted value
    (this font is monospace, so character count is a reliable proxy for
    rendered width), applied via a real, per-instance `<style>` block keyed
    on each column's own `data-label` attribute (already used for mobile's
    card labels) rather than inline styles, so the existing mobile media
    query's `!important` card layout can still cleanly override it below
    768px without a specificity fight.

    `df`: the body rows, already in display order (NOT sorted here - a
    sortable interactive grid isn't the point of this table, a durable
    footer row is, and re-sorting would fight that).
    `footer`: a single-row dict/Series of the SAME columns as `df`, always
    rendered below the scrollable body. `numeric_cols`: which columns
    right-align + get numeric decimal formatting (auto-detected from `df`
    if omitted). `team_color_map`/`opponent_col`/`win_loss_col`: same
    semantics as style_plain_dataframe, applied to `df`'s rows only - the
    footer row gets its own fixed highlighted treatment instead (it isn't a
    real per-game Opponent/Result, so team/W-L tinting doesn't apply).

    Mobile (<=767px): a CSS-only "row becomes a card" transform lives in
    ui.styling.inject_theme()'s `.sft-table` media-query block - every
    `<td>` gets a `data-label` attribute (its column name) so the mobile
    CSS can render a label above each value via `content: attr(data-label)`
    without any Python-side layout logic. `mobile_headline_cols`: which
    columns should visually lead each mobile card (larger, promoted to the
    top via CSS `order` - DOM order is untouched, only visual order
    changes) - defaults to the first 4 columns of `df` if not given.
    """
    if df is None or df.empty:
        return
    cols = list(df.columns)
    numeric_cols = set(numeric_cols) if numeric_cols is not None else {
        c for c in cols if pd.api.types.is_numeric_dtype(df[c])
    }
    decimals = {c: _table_decimals(df[c]) for c in numeric_cols}
    headline_cols = list(mobile_headline_cols) if mobile_headline_cols else cols[:4]

    team_color_map = team_color_map or {}
    norm_team_map = _expand_with_aliases({_normalize_team_name(k): v for k, v in team_color_map.items()})

    def _team_color(name):
        if name is None:
            return None
        return team_color_map.get(str(name)) or norm_team_map.get(_normalize_team_name(str(name)))

    def _fmt(col, value):
        if col in numeric_cols:
            v = pd.to_numeric(pd.Series([value]), errors='coerce').iloc[0]
            return '--' if pd.isna(v) else f"{v:.{decimals.get(col, 1)}f}"
        return '' if value is None or (isinstance(value, float) and pd.isna(value)) else html.escape(str(value))

    footer_get = footer.get if hasattr(footer, 'get') else (lambda c: footer[c])

    def _col_width_px(col):
        """Safe minimum px width for this column - the larger of what its
        HEADER needs and what its widest BODY value needs (deliberately
        NOT the footer's own value - see below) - explicit, content-aware
        desktop column widths so thead/tbody/tfoot (three independent
        layout contexts once each is forced to display:block - see this
        function's docstring) render the same column at the same width in
        all three, instead of each auto-sizing independently.

        CORRECTION: this used to run header AND body text through one
        shared formula (7.2px/char + a flat 16px padding allowance).
        Real deployment kept truncating header labels ("RESU...",
        "TURNOVE...") even though that formula looked generous enough on
        paper - the 16px padding constant was calibrated for the BODY/
        FOOTER cell's own `padding:6px 7px` (14px total), but header cells
        use a wider `padding:8px 10px` (20px total) AND a
        `letter-spacing:0.05em` body cells don't have, neither of which
        the shared formula ever accounted for. Confirmed via Playwright,
        measuring real `scrollWidth` vs `clientWidth` on every header/body
        cell in a live render (not guessed): every truncated header was
        short by exactly the header-vs-body padding/letter-spacing gap,
        never by a character-width error - 7.2px/char itself (JetBrains
        Mono's real 0.6em advance width at the table's 12px body font) was
        independently re-verified live too (via a real DOM span, width
        awaited past `document.fonts.ready`, not canvas measureText) and
        came back exactly 7.2px, so that part was never the bug. Headers
        render at a smaller 10.5px font (-> 6.3px/char, same 0.6em ratio),
        so they need less per character than the body's 7.2px/char - it's
        purely the wider padding + letter-spacing that was pushing them
        over their allotted width. Now computed as two separate
        requirements, one using each section's own real metrics, and the
        larger of the two (plus a flat +6px cushion for cross-browser/
        platform subpixel rounding) wins.

        Excluding the footer's own value matters in practice: its
        Opponent-column text ("SEASON AVG (28 games)", in Player Search's
        actual call site) is routinely LONGER than every real opponent
        name in the column, so measuring it widened that one column (and
        therefore the whole table's total safe-minimum width) enough to
        force horizontal scrolling on every render, not just the rare one
        with a genuinely long team name. The footer cell still gets the
        SAME column width as the body (see _row_cell) - if its own text
        doesn't fit, `text-overflow:ellipsis` truncates it instead of
        stretching the column to accommodate a value real per-game rows
        never need room for.

        Capped at 130px (same ellipsis truncation as the footer case
        above) for the same reason, applied a level further: Opponent is
        real per-game DATA, not a one-off summary string, but a genuinely
        long team name is still rare enough that sizing the WHOLE column -
        and therefore the table's total safe-minimum width, on every
        render - to fit every possible name in full isn't worth forcing
        horizontal scroll on every visit just for that one column. A
        capped, occasionally-truncated Opponent cell (full name still on
        hover, via `title`) beats that trade-off. This is only ever a
        FLOOR now (see total_width/col_pct below) - the column still grows
        past it when the table has room to stretch, it just never
        renders any NARROWER than this.
        """
        values = [_fmt(col, v) for v in df[col]]
        body_longest = max((len(v) for v in values), default=0)
        header_len = len(str(col))
        body_need = body_longest * 7.2 + 14
        header_need = header_len * 6.3 + max(0, header_len - 1) * 0.525 + 20
        return max(50, min(130, round(max(body_need, header_need) + 6)))

    col_widths = {c: _col_width_px(c) for c in cols}
    total_width = sum(col_widths.values())
    # Each column's share of the safe-minimum total, as a percentage - lets
    # the table stretch to fill a wider container (see the closing
    # st.markdown call: table/thead/tbody/tfoot all use width:100% with
    # min-width:{total_width}px, not a fixed width:{total_width}px) while
    # every column still never renders narrower than its own safe
    # `col_widths[c]` floor, since these percentages are defined AS shares
    # of that exact floor total - at the floor itself each column is
    # therefore pixel-identical to the old fixed-width behavior; above it,
    # columns grow proportionally instead of leaving the extra space as
    # bare, table-less background past the table's right edge.
    col_pct = {c: (w / total_width * 100 if total_width else 0) for c, w in col_widths.items()}

    def _row_style(extra=""):
        return f"display:table; table-layout:fixed; width:100%; min-width:{total_width}px; {extra}"

    def _row_cell(col, value, tag='td', extra_style="", raw_text=None):
        # `raw_text` bypasses _fmt entirely - needed for header cells, whose
        # "value" is the column's own NAME, not a data value: running a
        # numeric column's literal name (e.g. "Minutes") through _fmt's
        # numeric coercion would coerce it to NaN and print "--" instead of
        # the label (a real regression caught by rendering this for real -
        # see this function's docstring on why that verification matters).
        text = raw_text if raw_text is not None else _fmt(col, value)
        align = "text-align:right;" if col in numeric_cols else ""
        # overflow/text-overflow: the column's own width is sized to real
        # body data (see _col_width_px) - a value wider than that (in
        # practice, only the footer's own longer summary text) truncates
        # with an ellipsis instead of stretching the column or spilling
        # into the next cell. width is a % share of the table's safe-
        # minimum total (see col_pct) with min-width as the real px floor
        # (no max-width) - the column can grow past that floor when the
        # table has room to stretch, but never renders narrower than it.
        style = (
            f"padding:6px 7px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; "
            f"width:{col_pct[col]:.4f}%; min-width:{col_widths[col]}px; {align} {extra_style}"
        )
        label = html.escape(str(col))
        # `text` is already HTML-escaped where it needs to be (_fmt escapes
        # non-numeric values; raw_text callers pass pre-escaped text too) -
        # reusing it as-is for `title` (not re-escaping) avoids double-
        # escaping something like "Texas A&M" into "Texas A&amp;M".
        return f"<{tag} data-label='{label}' style='{style}' title='{text}'>{text}</{tag}>"

    def _body_row_cell(col, value):
        style = ""
        if opponent_col and col == opponent_col:
            c = _team_color(value)
            if c:
                style = f"background:{c}66; color:#ffffff; font-weight:600;"
        elif win_loss_col and col == win_loss_col:
            v = str(value).strip().upper()
            if v == 'W':
                style = f"background:{C['positive']}2e; color:{C['positive']}; font-weight:800;"
            elif v == 'L':
                style = f"background:{C['negative']}2e; color:{C['negative']}; font-weight:800;"
        return _row_cell(col, value, extra_style=style)

    header_html = "".join(
        _row_cell(
            c, None, tag='th', raw_text=html.escape(str(c)),
            extra_style=(
                f"background:{C['surface_container_high']}; color:{C['on_surface_variant']}; font-size:10.5px; "
                f"font-weight:700; text-transform:uppercase; letter-spacing:0.05em; padding:8px 10px; "
                f"border-bottom:1px solid {C['outline_variant']};"
            ),
        )
        for c in cols
    )
    body_html = "".join(
        f"<tr class='sft-row' style='{_row_style()}'>{''.join(_body_row_cell(c, row[c]) for c in cols)}</tr>"
        for _, row in df.iterrows()
    )
    footer_html = "".join(
        _row_cell(
            c, footer_get(c),
            extra_style=f"background:{C['surface_container_high']}; border-top:2px solid {C['primary']}; font-weight:700;",
        )
        for c in cols
    )
    # Per-column desktop width (see _col_width_px) + per-instance mobile
    # headline-column CSS (which columns visually lead each card), both
    # keyed off each cell's own `data-label` attribute rather than inline
    # styles - scoped to their own media queries so the >=768px width rule
    # and the <=767px card-layout rule never fight over specificity (the
    # mobile block's existing `!important` continues to win below 768px
    # exactly as before; this just adds an equally explicit desktop rule
    # instead of leaning on inline styles that `!important` would have had
    # to fight for the same properties).
    width_css = "".join(
        f"@media (min-width: 768px) {{ [data-label='{html.escape(str(c))}'] {{ width:{col_pct[c]:.4f}% !important; min-width:{w}px; }} }}"
        for c, w in col_widths.items()
    )
    headline_css = "".join(f"td[data-label='{html.escape(str(c))}']," for c in headline_cols).rstrip(',')
    mobile_instance_css = (
        f"@media (max-width: 767px) {{ {headline_css} {{ order: -1; font-weight: 700; font-size: 13px; flex-basis: 46%; }} }}"
        if headline_css else ""
    )
    # width:100% + min-width:{total_width}px on the outer div, table, and
    # every thead/tbody/tfoot section (instead of a fixed width:{total_
    # width}px each) - the table stretches to fill whatever container it's
    # in and its columns grow proportionally with it (see col_pct), so
    # .sft-outer's background is always fully covered instead of leaving
    # bare, table-less space past the table's right edge on a wide
    # viewport. min-width is still the real floor: on a container narrower
    # than total_width (a small viewport, or just many columns), the table
    # stops shrinking at that safe width and .sft-scrollx's own
    # overflow-x:auto takes over exactly as before - horizontal scroll
    # only ever kicks in when the columns' own safe minimums genuinely
    # don't fit, never merely because the table was fixed narrower than
    # available room.
    st.markdown(
        f"<div class='sft-outer' style='border:1px solid {C['outline_variant']}; border-radius:{R['sm']}; "
        f"overflow:hidden; background:{C['surface_container']}; width:100%;'>"
        f"<style>.sft-row:hover td {{ background:rgba({_hex_to_rgb_str(C['primary'])}, 0.06); }} {width_css} {mobile_instance_css}</style>"
        f"<div class='sft-scrollx' style='overflow-x:auto; width:100%;'>"
        f"<table class='sft-table' style='border-collapse:collapse; table-layout:fixed; width:100%; min-width:{total_width}px; "
        f"font-family:{_MONO_FONT_SAFE}; font-size:12px; color:{C['on_surface']};'>"
        f"<thead style='display:block; width:100%; min-width:{total_width}px;'><tr style='{_row_style()}'>{header_html}</tr></thead>"
        f"<tbody style='display:block; width:100%; min-width:{total_width}px; max-height:{height}px; overflow-y:auto;'>{body_html}</tbody>"
        f"<tfoot style='display:block; width:100%; min-width:{total_width}px;'>"
        f"<tr class='sft-footer-row' style='{_row_style()}'>{footer_html}</tr>"
        f"</tfoot>"
        f"</table></div></div>",
        unsafe_allow_html=True,
    )


def _mobile_cell_bg(row, pos, col, diverging_cols, pct_arrays, matchup_arrays,
                     team_color_map, norm_team_map, opponent_col, opponent_color_map,
                     norm_opp_map, win_loss_col):
    """
    One cell's (background, text_color, font_weight) for
    render_responsive_table's mobile card list - (None, None, None) means
    "no special tint, just the card's own default text color."

    Deliberately a SEPARATE, self-contained implementation of the same
    color rules `style_plain_dataframe`'s `style_row` already applies
    (diverging -> matchup -> percentile -> Team -> Conference -> opponent ->
    win/loss - Conference reuses the shared `_conference_color` helper
    directly, same as this function and the Styler already both share
    get_diverging_color/get_matchup_color/get_grade_color), NOT a refactor
    of style_plain_dataframe's own internals - this app's mobile
    overhaul is explicitly required to leave the proven, already-live
    desktop rendering untouched, and the safest way to guarantee that is to
    never modify the function desktop already depends on. A small amount
    of intentional duplication here is the trade-off for that guarantee.
    """
    if col in diverging_cols:
        return get_diverging_color(row[col], diverging_cols[col]), '#ffffff', '700'
    if col in matchup_arrays and pos < len(matchup_arrays[col]):
        return get_matchup_color(matchup_arrays[col][pos]), '#ffffff', '700'
    if col in pct_arrays and pos < len(pct_arrays[col]):
        return get_grade_color(pct_arrays[col][pos]), '#ffffff', '700'
    if col == 'Team':
        team_color = team_color_map.get(str(row[col])) or norm_team_map.get(_normalize_team_name(str(row[col])))
        if team_color:
            return team_color, '#ffffff', '700'
        return None, None, None
    if col == 'Conference':
        conf_color = _conference_color(row[col])
        if conf_color:
            return conf_color, '#ffffff', '700'
        return None, None, None
    if opponent_col and col == opponent_col:
        opp_color = opponent_color_map.get(str(row[col])) or norm_opp_map.get(_normalize_team_name(str(row[col])))
        if opp_color:
            return f"{opp_color}66", '#ffffff', '600'
        return None, None, None
    if win_loss_col and col == win_loss_col:
        v = str(row[col]).strip().upper()
        if v == 'W':
            return f"{C['positive']}2e", C['positive'], '800'
        if v == 'L':
            return f"{C['negative']}2e", C['negative'], '800'
        return None, None, None
    return None, None, None


def render_responsive_table(key, df, primary_col=None, card_fields=None, index_label=None,
                             numeric_pct_cols=None, diverging_cols=None, matchup_pct_cols=None,
                             team_color_map=None, opponent_col=None, opponent_color_map=None,
                             win_loss_col=None, height=None, mobile_max_height="65vh", **dataframe_kwargs):
    """
    Drop-in wrapper around `st.dataframe(style_plain_dataframe(df, ...), ...)`
    that ALSO renders a mobile card-list version of the SAME data, with pure
    CSS choosing which one is visible per viewport width.

    WHY a second, separate rendering instead of a media query reaching
    INTO the dataframe: st.dataframe's grid (glide-data-grid) is canvas-
    rendered, not real DOM - already confirmed elsewhere in this app
    (see the chart-hover-affordance comment in inject_theme(), and
    render_sticky_footer_table's own docstring) that CSS cannot restyle
    individual cells/rows inside it, add hover states, or turn a row into a
    card. The only way to get a card layout for this data on mobile is a
    SECOND, independent rendering - so this renders both every time and
    lets CSS show exactly one, keyed off the `st-key-` class Streamlit
    gives an `st.container(key=...)` (confirmed against this app's pinned
    Streamlit version).

    The desktop path below is BYTE-IDENTICAL to what every existing caller
    used to call directly (`st.dataframe(style_plain_dataframe(df, **kwargs),
    width="stretch", height=height, **dataframe_kwargs)`) - just wrapped in
    a keyed container so CSS can address it. Nothing about `style_plain_
    dataframe` itself changes, and no desktop-visible behavior changes.

    `key`: required, unique per call site (e.g. "team_efficiency_rankings",
    or an f-string interpolating a team/player name) - becomes both
    containers' `st.container(key=...)` value AND the CSS class the
    show/hide media queries target. Sanitized internally (non
    alphanumeric/underscore/hyphen -> hyphen) BEFORE either use, matching
    Streamlit's own key->CSS-class sanitization (confirmed in its frontend
    source) - callers can safely pass a raw team/player name containing
    spaces without producing a broken CSS selector (an earlier version of
    this function didn't do this and silently emitted an invalid selector
    for any key containing a space, e.g. "positional_defense_North
    Carolina State").
    `primary_col`: the card's bold headline field - a column name, a list of
    column names (joined with " — "), or `None` to use `df`'s own index
    (the natural choice for tables indexed on the row subject, e.g.
    Positional Defense's Bucket or Compare's Stat name). Excluded from the
    field grid below when it's a real column (never double-shown).
    `card_fields`: optional explicit ordered list of which OTHER columns to
    show in the card body - defaults to every remaining column in `df`'s
    own order. Every data FIELD desktop shows is still shown on mobile
    either way; this only controls display ORDER, never omission.
    `index_label`: optional short prefix (e.g. "Rank", "#") shown before
    the headline using the row's own pandas index value - for tables where
    the index carries a meaningful rank/order (Transfer Portal, Conference
    Standings) alongside a real `primary_col`. Ignored when `primary_col`
    is `None` (the index IS already the headline in that case).
    `numeric_pct_cols`/`diverging_cols`/`matchup_pct_cols`/`team_color_map`/
    `opponent_col`/`opponent_color_map`/`win_loss_col`: forwarded straight
    to `style_plain_dataframe` for the desktop path, AND used to compute
    matching colors for the mobile cards via `_mobile_cell_bg` (same
    values, independently-implemented color logic - see that function's
    docstring for why it's not shared code with the Styler).
    `height`/`**dataframe_kwargs`: forwarded to the desktop `st.dataframe`
    call exactly as an existing direct call would have passed them
    (column_config, hide_index, etc.). `mobile_max_height`: a CSS max-height
    VALUE (not a bare number - include the unit, e.g. "65vh" or "440px") for
    the mobile card list's own scroll container - defaults to a viewport-
    relative value rather than reusing `height` (which is tuned in px for
    compact table ROWS, not much-taller cards - reusing it as-is clipped
    card content mid-render, confirmed live against render_sticky_footer_
    table's identical height-reuse mistake before this default was added).
    """
    if df is None or df.empty:
        return
    safe_key = re.sub(r'[^a-zA-Z0-9_-]', '-', str(key))
    desktop_key = f"rt-desktop-{safe_key}"
    mobile_key = f"rt-mobile-{safe_key}"

    with st.container(key=desktop_key):
        st.dataframe(
            style_plain_dataframe(
                df, numeric_pct_cols=numeric_pct_cols, diverging_cols=diverging_cols,
                matchup_pct_cols=matchup_pct_cols, team_color_map=team_color_map,
                opponent_col=opponent_col, opponent_color_map=opponent_color_map, win_loss_col=win_loss_col,
            ),
            width="stretch", height=height, **dataframe_kwargs,
        )

    with st.container(key=mobile_key):
        _render_mobile_card_list(
            df, primary_col=primary_col, card_fields=card_fields, index_label=index_label,
            numeric_pct_cols=numeric_pct_cols, diverging_cols=diverging_cols, matchup_pct_cols=matchup_pct_cols,
            team_color_map=team_color_map, opponent_col=opponent_col, opponent_color_map=opponent_color_map,
            win_loss_col=win_loss_col, max_height=mobile_max_height,
        )

    # Per-instance show/hide toggle - the ONLY thing that decides which of
    # the two already-rendered components is visible. Scoped to these two
    # exact keys, so it can never affect any other table's containers.
    st.markdown(
        f"<style>"
        f"@media (max-width: 767px) {{ div.st-key-{desktop_key} {{ display: none !important; }} }}"
        f"@media (min-width: 768px) {{ div.st-key-{mobile_key} {{ display: none !important; }} }}"
        f"</style>",
        unsafe_allow_html=True,
    )


def _render_mobile_card_list(df, primary_col, card_fields, index_label,
                              numeric_pct_cols, diverging_cols, matchup_pct_cols,
                              team_color_map, opponent_col, opponent_color_map, win_loss_col,
                              max_height):
    """The actual mobile card markup for render_responsive_table - see that
    function's docstring for every parameter's meaning."""
    cols = list(df.columns)
    primary_is_column = primary_col is not None
    primary_col_list = [] if not primary_is_column else (
        primary_col if isinstance(primary_col, (list, tuple)) else [primary_col]
    )
    fields = list(card_fields) if card_fields else [c for c in cols if c not in primary_col_list]

    numeric_cols = {c for c in cols if pd.api.types.is_numeric_dtype(df[c])}
    decimals = {c: _table_decimals(df[c]) for c in numeric_cols}

    def _fmt(col, value):
        if col in numeric_cols:
            v = pd.to_numeric(pd.Series([value]), errors='coerce').iloc[0]
            return '--' if pd.isna(v) else f"{v:.{decimals.get(col, 1)}f}"
        return '--' if value is None or (isinstance(value, float) and pd.isna(value)) else html.escape(str(value))

    team_color_map = team_color_map if team_color_map is not None else {v['name']: v['color'] for v in TEAM_CONFIG.values()}
    team_color_map = {**team_color_map, **{k: v['color'] for k, v in TEAM_CONFIG.items()}}
    opponent_color_map = opponent_color_map if opponent_color_map is not None else (team_color_map if opponent_col else {})
    norm_team_map = _expand_with_aliases({_normalize_team_name(k): v for k, v in team_color_map.items()})
    norm_opp_map = _expand_with_aliases({_normalize_team_name(k): v for k, v in opponent_color_map.items()})
    pct_arrays = {col: list(vals) for col, vals in (numeric_pct_cols or {}).items()}
    matchup_arrays = {col: list(vals) for col, vals in (matchup_pct_cols or {}).items()}
    diverging_cols = diverging_cols or {}

    def _tinted(col, value, bg, fg, fw):
        text = _fmt(col, value)
        if not bg:
            return text
        style = f"background:{bg}; color:{fg}; font-weight:{fw}; border-radius:{R['sm']}; padding:1px 7px; display:inline-block;"
        return f"<span style='{style}'>{text}</span>"

    cards = []
    for pos, (idx, row) in enumerate(df.iterrows()):
        if primary_is_column:
            headline_text = " — ".join(html.escape(str(row[c])) for c in primary_col_list)
            bg, fg, fw = _mobile_cell_bg(
                row, pos, primary_col_list[0], diverging_cols, pct_arrays, matchup_arrays,
                team_color_map, norm_team_map, opponent_col, opponent_color_map, norm_opp_map, win_loss_col,
            )
            if bg:
                style = f"background:{bg}; color:{fg}; border-radius:{R['sm']}; padding:2px 8px; display:inline-block;"
                headline_text = f"<span style='{style}'>{headline_text}</span>"
            prefix = f"{html.escape(str(index_label))} {idx} — " if index_label else ""
        else:
            prefix = ""
            headline_text = html.escape(str(idx))

        field_html = []
        for col in fields:
            bg, fg, fw = _mobile_cell_bg(
                row, pos, col, diverging_cols, pct_arrays, matchup_arrays,
                team_color_map, norm_team_map, opponent_col, opponent_color_map, norm_opp_map, win_loss_col,
            )
            field_html.append(
                f"<div class='rt-field'><span class='rt-label'>{html.escape(str(col))}</span>"
                f"{_tinted(col, row[col], bg, fg, fw)}</div>"
            )
        cards.append(
            f"<div class='rt-card'><div class='rt-primary'>{prefix}{headline_text}</div>"
            f"<div class='rt-fields'>{''.join(field_html)}</div></div>"
        )

    st.markdown(
        f"<div style='max-height:{max_height}; overflow:auto;'>{''.join(cards)}</div>",
        unsafe_allow_html=True,
    )
