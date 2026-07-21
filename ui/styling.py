"""
Theme CSS injection + Styler-based table renderers. Structure and CSS ported
directly from NFL Scholar (C:\\FantasyF\\ui\\styling.py) / CFB Scholar -
only the color values differ (violet primary). Every place the cyan/amber
siblings hardcoded their accent as a literal rgba(...) for a glow/tint
effect, this version computes the same rgba string from config.THEME's
primary color instead, so the accent is driven entirely by config.py.
"""
import base64
import os
import re

import pandas as pd
import streamlit as st

from config import THEME, TEAM_CONFIG

C = THEME['colors']
F = THEME['fonts']
R = THEME['radius']
S = THEME['spacing']

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


_PRIMARY_RGB = _hex_to_rgb_str(C['primary'])
_SECONDARY_RGB = _hex_to_rgb_str(C['secondary'])


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
    st.markdown(f"""
        <style>
        {_font_face_css()}

        .stApp {{
            background:
                radial-gradient(1100px 420px at 18% -8%, rgba({_SECONDARY_RGB}, 0.16) 0%, rgba({_SECONDARY_RGB}, 0) 60%),
                radial-gradient(900px 380px at 85% -12%, rgba({_PRIMARY_RGB}, 0.07) 0%, rgba({_PRIMARY_RGB}, 0) 55%),
                linear-gradient(180deg, {C['surface']} 0%, {C['surface_dim']} 100%) !important;
            color: {C['on_surface']} !important;
            font-family: {F['body']} !important;
            font-variant-numeric: tabular-nums;
        }}

        header[data-testid="stHeader"] {{
            background: rgba(5, 9, 33, 0.72) !important;
            backdrop-filter: blur(8px);
            border-bottom: 1px solid rgba(44, 50, 96, 0.6);
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
            box-shadow: 0 0 8px rgba({_PRIMARY_RGB}, 0.5);
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
            background-color: rgba(255, 255, 255, 0.05) !important;
        }}
        [data-testid="stTab"] p, button[data-baseweb="tab"] p {{
            color: {C['on_surface_variant']} !important;
            font-family: {F['display']};
            font-size: 12.5px !important;
            font-weight: 600 !important;
            letter-spacing: 0.02em;
        }}
        [data-testid="stTab"][aria-selected="true"], button[data-baseweb="tab"][aria-selected="true"] {{
            background-color: rgba({_PRIMARY_RGB}, 0.10) !important;
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
            background: rgba(19, 27, 56, 0.55) !important;
            border: 1px solid {C['outline_variant']} !important;
            border-radius: {R['md']} !important;
            backdrop-filter: blur(6px);
            color: {C['on_surface']} !important;
        }}
        div[data-testid="stAlert"] p {{ color: {C['on_surface']} !important; }}

        section[data-testid="stSidebar"] {{
            background: {C['surface_dim']} !important;
            border-right: 1px solid {C['outline_variant']};
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
            background: rgba(19, 27, 56, 0.4);
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
            background: rgba(19, 27, 56, 0.4) !important;
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
            background-color: rgba({_PRIMARY_RGB}, 0.06) !important;
        }}
        .stButton button[kind="primary"] {{
            background-color: {C['primary']} !important;
            color: {C['on_primary']} !important;
            border: none !important;
        }}

        .stSelectbox [role="group"], .stMultiSelect [role="group"],
        .stNumberInput [role="group"], .stDateInput [role="group"],
        div[data-baseweb="select"] > div, .stTextInput input, .stTextArea textarea, .stNumberInput input {{
            background-color: rgba(0, 0, 0, 0.25) !important;
            border-radius: {R['default']} !important;
            border: 1px solid {C['outline_variant']} !important;
            color: {C['on_surface']} !important;
        }}
        .stSelectbox [role="group"] input, .stMultiSelect [role="group"] input, .stNumberInput [role="group"] input {{
            background-color: transparent !important;
            border: none !important;
            color: {C['on_surface']} !important;
        }}
        .stSelectbox [role="group"]:focus-within, .stMultiSelect [role="group"]:focus-within,
        .stNumberInput [role="group"]:focus-within, .stDateInput [role="group"]:focus-within,
        div[data-baseweb="select"] > div:focus-within, .stTextInput input:focus, .stTextArea textarea:focus {{
            border-color: {C['primary']} !important;
            box-shadow: 0 0 0 2px rgba({_PRIMARY_RGB}, 0.15) !important;
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
            border-color: rgba({_PRIMARY_RGB}, 0.55);
            box-shadow: 0 1px 2px rgba(0, 0, 0, 0.35), 0 10px 22px -10px rgba({_PRIMARY_RGB}, 0.3) !important;
            transform: translateY(-1px);
        }}

        /* Game log table + pinned season-average row (ui.tabs.player_search)
           - two separate st.dataframe widgets scoped inside one
           st.container(key="ps_game_log_wrap") so they read as ONE table
           with a highlighted footer row, not two stacked disconnected
           cards (each st.dataframe otherwise draws its own full border +
           shadow + margin, which is what read as "broken"/split before). */
        .st-key-ps_game_log_wrap div[data-testid="stVerticalBlock"] {{
            gap: 0 !important;
        }}
        .st-key-ps_game_log_wrap div[data-testid="stElementContainer"]:has(div[data-testid="stDataFrame"]) {{
            margin: 0 !important;
        }}
        .st-key-ps_game_log_wrap div[data-testid="stElementContainer"]:has(div[data-testid="stDataFrame"]):first-of-type div[data-testid="stDataFrame"] {{
            border-bottom-left-radius: 0 !important;
            border-bottom-right-radius: 0 !important;
            border-bottom: none !important;
        }}
        .st-key-ps_game_log_wrap div[data-testid="stElementContainer"]:has(div[data-testid="stDataFrame"]):last-of-type div[data-testid="stDataFrame"] {{
            border-top-left-radius: 0 !important;
            border-top-right-radius: 0 !important;
            border-top: 2px solid {C['primary']} !important;
            background-color: rgba({_PRIMARY_RGB}, 0.10) !important;
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


def _normalize_team_name(name):
    """
    Loose match key for team names that get formatted differently across
    this app's data sources for the exact same school - punctuation,
    case, a trailing 'University'/'College', possessive apostrophes. An
    exact-string dict lookup silently returns no color (not an error) on
    any of these mismatches, which is why a team-colored table can end up
    mostly uncolored even though the code path passes a real color map -
    this loose key is the fallback `style_plain_dataframe` tries when the
    exact key misses. Does NOT resolve true word-different aliases (see
    _TEAM_NAME_ALIASES below for those - normalizing punctuation alone
    can't turn 'NC State' into 'North Carolina State').
    """
    if not name:
        return ''
    s = re.sub(r"[^a-z0-9\s]", "", str(name).lower())
    for noise in (' university', ' univ', ' college'):
        s = s.replace(noise, '')
    return re.sub(r"\s+", " ", s).strip()


# Common short-name/full-name aliases seen across ncaa.com, CBBD, and ESPN
# for the same school - NOT exhaustive (this sandbox's network policy
# blocked live-checking every source's exact naming - see HANDOFF.md), just
# the well-known ones. Keyed/valued as normalized (_normalize_team_name)
# strings both directions get registered under each other's color. Extend
# this list if a real run still shows a team missing its color.
_TEAM_NAME_ALIASES = [
    ('uconn', 'connecticut'),
    ('ole miss', 'mississippi'),
    ('pitt', 'pittsburgh'),
    ('nc state', 'north carolina state'),
    ('usc', 'southern california'),
    ('smu', 'southern methodist'),
    ('lsu', 'louisiana state'),
    ('byu', 'brigham young'),
    ('vcu', 'virginia commonwealth'),
    ('unlv', 'nevada las vegas'),
    ('utep', 'texas el paso'),
    ('uab', 'alabama birmingham'),
    ('uic', 'illinois chicago'),
    ('umass', 'massachusetts'),
    ('ucf', 'central florida'),
    ('fiu', 'florida international'),
    ('miami', 'miami fl'),
    ('st johns', 'st johns ny'),
    ("saint marys", "saint marys ca"),
]


def _expand_with_aliases(norm_map):
    """Adds each _TEAM_NAME_ALIASES pair's other spelling to `norm_map`
    (pointing at the same color) whenever exactly one side is already
    present - never overwrites a real direct hit with a guessed one."""
    expanded = dict(norm_map)
    for a, b in _TEAM_NAME_ALIASES:
        if a in norm_map and b not in expanded:
            expanded[b] = norm_map[a]
        if b in norm_map and a not in expanded:
            expanded[a] = norm_map[b]
    return expanded


def df_auto_height(n_rows, row_px=35, header_px=38, padding_px=3):
    """Sizes an st.dataframe to its actual row count so nothing needs an
    internal scrollbar to be fully visible. Ported as-is from NFL Scholar."""
    return header_px + max(n_rows, 1) * row_px + padding_px
