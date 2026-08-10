"""
Shared constants: team metadata, stat-formatting rules, and the design-system
THEME token dict. Architecture and token structure ported directly from NFL
Scholar (C:\\FantasyF\\config.py) - only the accent color pair changes
(violet `#c084fc` in place of NFL Scholar's cyan `#00fff9` / CFB Scholar's
amber `#ffb020`) so all three apps read as one family with distinct
identities.
"""

# Major D-I basketball conferences - the programs relevant to the large
# majority of CBB analysis. NOT the full 360+ Division I team list: hand-
# typing every mid-major program's exact hex colors risked getting obscure
# ones wrong. ESPN's own team endpoints (already used keyless elsewhere in
# this app) return official colors for all of Division I - that should
# replace/extend this dict wholesale during the data-wiring pass rather
# than this list growing by hand.
TEAM_CONFIG = {
    # ACC
    'DUKE': {'name': 'Duke Blue Devils', 'color': '#003087', 'conference': 'ACC'},
    'UNC': {'name': 'North Carolina Tar Heels', 'color': '#7BAFD4', 'conference': 'ACC'},
    'NCST': {'name': 'NC State Wolfpack', 'color': '#CC0000', 'conference': 'ACC'},
    'UVA': {'name': 'Virginia Cavaliers', 'color': '#232D4B', 'conference': 'ACC'},
    'LOU': {'name': 'Louisville Cardinals', 'color': '#AD0000', 'conference': 'ACC'},
    'SYR': {'name': 'Syracuse Orange', 'color': '#F76900', 'conference': 'ACC'},
    'ND':  {'name': 'Notre Dame Fighting Irish', 'color': '#0C2340', 'conference': 'ACC'},
    'WAKE': {'name': 'Wake Forest Demon Deacons', 'color': '#9E7E38', 'conference': 'ACC'},
    'FSU': {'name': 'Florida State Seminoles', 'color': '#782F40', 'conference': 'ACC'},
    'MIA': {'name': 'Miami Hurricanes', 'color': '#F47321', 'conference': 'ACC'},
    'CLEM': {'name': 'Clemson Tigers', 'color': '#F56600', 'conference': 'ACC'},
    'VT':  {'name': 'Virginia Tech Hokies', 'color': '#630031', 'conference': 'ACC'},
    'PITT': {'name': 'Pittsburgh Panthers', 'color': '#003594', 'conference': 'ACC'},
    'BC':  {'name': 'Boston College Eagles', 'color': '#98002E', 'conference': 'ACC'},
    'GT':  {'name': 'Georgia Tech Yellow Jackets', 'color': '#B3A369', 'conference': 'ACC'},
    'CAL': {'name': 'California Golden Bears', 'color': '#003262', 'conference': 'ACC'},
    'STAN': {'name': 'Stanford Cardinal', 'color': '#8C1515', 'conference': 'ACC'},
    'SMU': {'name': 'SMU Mustangs', 'color': '#C8102E', 'conference': 'ACC'},
    # Big Ten
    'MSU': {'name': 'Michigan State Spartans', 'color': '#18453B', 'conference': 'Big Ten'},
    'MICH': {'name': 'Michigan Wolverines', 'color': '#00274C', 'conference': 'Big Ten'},
    'PUR': {'name': 'Purdue Boilermakers', 'color': '#CEB888', 'conference': 'Big Ten'},
    'IND': {'name': 'Indiana Hoosiers', 'color': '#990000', 'conference': 'Big Ten'},
    'ILL': {'name': 'Illinois Fighting Illini', 'color': '#E84A27', 'conference': 'Big Ten'},
    'WIS': {'name': 'Wisconsin Badgers', 'color': '#C5050C', 'conference': 'Big Ten'},
    'OSU': {'name': 'Ohio State Buckeyes', 'color': '#BB0000', 'conference': 'Big Ten'},
    'IOWA': {'name': 'Iowa Hawkeyes', 'color': '#FFCD00', 'conference': 'Big Ten'},
    'MD':  {'name': 'Maryland Terrapins', 'color': '#E03A3E', 'conference': 'Big Ten'},
    'RUTG': {'name': 'Rutgers Scarlet Knights', 'color': '#CC0033', 'conference': 'Big Ten'},
    'PSU': {'name': 'Penn State Nittany Lions', 'color': '#041E42', 'conference': 'Big Ten'},
    'NW':  {'name': 'Northwestern Wildcats', 'color': '#4E2A84', 'conference': 'Big Ten'},
    'MINN': {'name': 'Minnesota Golden Gophers', 'color': '#7A0019', 'conference': 'Big Ten'},
    'NEB': {'name': 'Nebraska Cornhuskers', 'color': '#E41C38', 'conference': 'Big Ten'},
    'UCLA': {'name': 'UCLA Bruins', 'color': '#2D68C4', 'conference': 'Big Ten'},
    'USC': {'name': 'USC Trojans', 'color': '#990000', 'conference': 'Big Ten'},
    'ORE': {'name': 'Oregon Ducks', 'color': '#154733', 'conference': 'Big Ten'},
    'WASH': {'name': 'Washington Huskies', 'color': '#4B2E83', 'conference': 'Big Ten'},
    # Big 12
    'KU':  {'name': 'Kansas Jayhawks', 'color': '#0051BA', 'conference': 'Big 12'},
    'BAY': {'name': 'Baylor Bears', 'color': '#003015', 'conference': 'Big 12'},
    'HOU': {'name': 'Houston Cougars', 'color': '#C8102E', 'conference': 'Big 12'},
    'ISU': {'name': 'Iowa State Cyclones', 'color': '#C8102E', 'conference': 'Big 12'},
    'TTU': {'name': 'Texas Tech Red Raiders', 'color': '#CC0000', 'conference': 'Big 12'},
    'TCU': {'name': 'TCU Horned Frogs', 'color': '#4D1979', 'conference': 'Big 12'},
    'KSU': {'name': 'Kansas State Wildcats', 'color': '#512888', 'conference': 'Big 12'},
    'WVU': {'name': 'West Virginia Mountaineers', 'color': '#EAAA00', 'conference': 'Big 12'},
    'BYU': {'name': 'BYU Cougars', 'color': '#002E5D', 'conference': 'Big 12'},
    'CIN': {'name': 'Cincinnati Bearcats', 'color': '#E00122', 'conference': 'Big 12'},
    'ARIZ': {'name': 'Arizona Wildcats', 'color': '#AB0520', 'conference': 'Big 12'},
    'ASU': {'name': 'Arizona State Sun Devils', 'color': '#8C1D40', 'conference': 'Big 12'},
    'COLO': {'name': 'Colorado Buffaloes', 'color': '#CFB87C', 'conference': 'Big 12'},
    'UTAH': {'name': 'Utah Utes', 'color': '#CC0000', 'conference': 'Big 12'},
    'UCF': {'name': 'UCF Knights', 'color': '#BA9B37', 'conference': 'Big 12'},
    'OKST': {'name': 'Oklahoma State Cowboys', 'color': '#FF7300', 'conference': 'Big 12'},
    # SEC
    'UK':  {'name': 'Kentucky Wildcats', 'color': '#0033A0', 'conference': 'SEC'},
    'AUB': {'name': 'Auburn Tigers', 'color': '#0C2340', 'conference': 'SEC'},
    'ALA': {'name': 'Alabama Crimson Tide', 'color': '#9E1B32', 'conference': 'SEC'},
    'TENN': {'name': 'Tennessee Volunteers', 'color': '#FF8200', 'conference': 'SEC'},
    'FLA': {'name': 'Florida Gators', 'color': '#0021A5', 'conference': 'SEC'},
    'ARK': {'name': 'Arkansas Razorbacks', 'color': '#9D2235', 'conference': 'SEC'},
    'LSU': {'name': 'LSU Tigers', 'color': '#461D7C', 'conference': 'SEC'},
    'MISS': {'name': 'Ole Miss Rebels', 'color': '#CE1126', 'conference': 'SEC'},
    'MSST': {'name': 'Mississippi State Bulldogs', 'color': '#660000', 'conference': 'SEC'},
    'SC':  {'name': 'South Carolina Gamecocks', 'color': '#73000A', 'conference': 'SEC'},
    'TAMU': {'name': 'Texas A&M Aggies', 'color': '#500000', 'conference': 'SEC'},
    'MIZ': {'name': 'Missouri Tigers', 'color': '#F1B82D', 'conference': 'SEC'},
    'VAN': {'name': 'Vanderbilt Commodores', 'color': '#866D4B', 'conference': 'SEC'},
    'UGA': {'name': 'Georgia Bulldogs', 'color': '#BA0C2F', 'conference': 'SEC'},
    'OU':  {'name': 'Oklahoma Sooners', 'color': '#841617', 'conference': 'SEC'},
    'TEX': {'name': 'Texas Longhorns', 'color': '#BF5700', 'conference': 'SEC'},
    # Big East
    'UCONN': {'name': 'UConn Huskies', 'color': '#0C2340', 'conference': 'Big East'},
    'NOVA': {'name': 'Villanova Wildcats', 'color': '#00205B', 'conference': 'Big East'},
    'CREI': {'name': 'Creighton Bluejays', 'color': '#003263', 'conference': 'Big East'},
    'MARQ': {'name': 'Marquette Golden Eagles', 'color': '#003366', 'conference': 'Big East'},
    'SJU': {'name': "St. John's Red Storm", 'color': '#BA0C2F', 'conference': 'Big East'},
    'XAV': {'name': 'Xavier Musketeers', 'color': '#0C2340', 'conference': 'Big East'},
    'PROV': {'name': 'Providence Friars', 'color': '#000000', 'conference': 'Big East'},
    'HALL': {'name': 'Seton Hall Pirates', 'color': '#12274F', 'conference': 'Big East'},
    'BUT': {'name': 'Butler Bulldogs', 'color': '#13294B', 'conference': 'Big East'},
    'GTWN': {'name': 'Georgetown Hoyas', 'color': '#041E42', 'conference': 'Big East'},
    # Notable mid-majors
    'GONZ': {'name': 'Gonzaga Bulldogs', 'color': '#002967', 'conference': 'WCC'},
}
MASTER_TEAMS_LIST = sorted(list(TEAM_CONFIG.keys()))
CONFERENCES = sorted(set(t['conference'] for t in TEAM_CONFIG.values()))

# Conference brand colors, keyed by the SHORT conference name (matching
# TEAM_CONFIG's own 'conference' values above - 'ACC', 'Big Ten', etc.),
# for coloring any 'Conference' column the same way TEAM_CONFIG already
# colors 'Team' cells (see ui.styling.style_plain_dataframe/
# render_responsive_table). Hand-curated from each conference's own public
# branding on request - checked both ESPN's standings endpoint and CBBD's
# API directly first for a real conference-level color field to pull from
# instead of guessing; both are unreachable from this sandbox's network
# policy, the same standing limitation this app's whole build history has
# hit on every ESPN/CBBD touchpoint (see HANDOFF.md). These are therefore
# best-effort, publicly-known branding colors, NOT independently verified
# live - spot-check the power-conference shades in particular before fully
# trusting them, same discipline as every other unverified-but-reasoned
# value in this app.
#
# Every value below is deliberately distinct (checked programmatically,
# zero exact duplicates) and nudged apart in hue/lightness from its
# closest neighbors on request - real conference branding clusters heavily
# around navy/blue and red/crimson (ACC, Big Ten, SEC, Big East, Big 12,
# American all lean blue-ish or red-ish), so several entries here are
# shifted from their most literal real-world shade specifically so no two
# conferences ever render as the same color at a glance, even side by side
# in the same table.
CONFERENCE_COLORS = {
    'ACC': '#1D5DBF',
    'Big Ten': '#0B1F4D',
    'Big 12': '#D0103A',
    'SEC': '#2F4B7C',
    'Big East': '#8A1538',
    'American': '#C24914',
    'Atlantic 10': '#046A38',
    'Mountain West': '#F2A900',
    'WCC': '#1B998B',
    'Missouri Valley': '#3A7CA5',
    'Conference USA': '#5B2A86',
    'Sun Belt': '#D4A017',
    'Ivy League': '#B5495B',
    'CAA': '#6B8E23',
    'MAAC': '#5C6BC0',
    'Horizon League': '#3E92CC',
    'MAC': '#6F4E37',
    'SoCon': '#5C6B73',
    'Big Sky': '#1D7874',
    'Big South': '#00A9A5',
    'ASUN': '#E8734A',
    'America East': '#264E70',
    'Patriot League': '#7C1D3F',
    'NEC': '#7B2D8E',
    'OVC': '#2E5339',
    'Summit League': '#C9812D',
    'Southland': '#0D5C63',
    'WAC': '#B5541A',
    'Big West': '#1E6091',
    'MEAC': '#6B2B3A',
    'SWAC': '#3E2472',
    'Independent': '#6B7280',
}

# Season depth - trimmed to 2023+ on request (personal use only needs
# recent seasons usable/visible; older seasons dropped from every season
# dropdown app-wide rather than left in as dead weight). Both this app's
# CBBD calls and the free ESPN/SportsDataverse season-box pipeline
# (data/loaders.py) support any season back to ~2003 if this window is
# ever widened again - this is a UI-visibility limit, not a data-source one.
AVAILABLE_SEASONS_WITH_UPCOMING = [2027, 2026, 2025, 2024, 2023]
AVAILABLE_SEASONS = [2026, 2025, 2024, 2023]

# NCAAB player-prop market keys The Odds API documents. Unavailable markets
# are silently omitted rather than erroring the request (confirmed live in
# NFL Scholar's own fetch_nfl_player_props testing, and the same API/
# behavior underlies this app's odds calls), so requesting this full list
# is safe even for games where only some of them are actually posted.
ODDS_API_PLAYER_PROP_MARKETS = [
    'player_points', 'player_rebounds', 'player_assists', 'player_threes',
    'player_blocks', 'player_steals', 'player_turnovers',
    'player_points_rebounds_assists',
]

STAT_DECIMALS = {
    'ppg': 1, 'rpg': 1, 'apg': 1, 'fg_pct': 1, 'three_pct': 1, 'ft_pct': 1,
    'adj_oe': 1, 'adj_de': 1, 'tempo': 1, 'win_pct': 3,
}

# Exact tab label strings - shared between app.py's st.tabs(...) call and any
# tab that needs to programmatically switch the active tab (see
# ui.components.switch_tab, which assigns one of these to
# st.session_state['active_tab']; they must stay string-identical to the
# labels app.py actually passes to st.tabs).
TAB_SLATE = "GAME SLATE"
TAB_PLAYER_SEARCH = "PLAYER SEARCH"
TAB_EFFICIENCY = "TEAM EFFICIENCY"
TAB_RANKINGS = "RANKINGS"
TAB_PORTAL = "TRANSFER PORTAL"
TAB_MATCHUP = "MATCHUP ANALYZER"
TAB_LIVE_ODDS = "LIVE ODDS"
TAB_COMPARE = "PLAYER COMPARE"
# GAME SLATE leads deliberately: it answers the first question of a real
# prep session ("who is playing"), and its whole purpose is handing a chosen
# game to the tabs after it with both teams already filled in - so it reads
# as the entry point rather than an eighth destination. This does change
# which tab the app opens on; moving it back is a one-line reorder here
# (app.py builds its tab list from TAB_LABELS' order, index for index).
TAB_LABELS = [
    TAB_SLATE, TAB_PLAYER_SEARCH, TAB_EFFICIENCY, TAB_RANKINGS, TAB_MATCHUP, TAB_LIVE_ODDS, TAB_COMPARE, TAB_PORTAL,
]

# ==========================================
# DESIGN SYSTEM TOKENS
# ==========================================
# Structure identical to NFL Scholar's THEME (C:\FantasyF\config.py) and
# CFB Scholar's - same surfaces/text/radius/spacing/fonts, so all three
# apps read as one family. Only primary/primary_container/
# on_primary_container change: violet in place of NFL Scholar's cyan /
# CFB Scholar's amber. #c084fc verified at 7.44:1 contrast against the
# shared #050921 dark surface (AAA) - brighter than an earlier draft violet
# specifically so it reads with the same vividness as the other two apps'
# accents, not washed out.
THEME = {
    'colors': {
        'surface': '#050921',
        'surface_dim': '#030614',
        'surface_bright': '#0a0f2a',
        'surface_container_lowest': '#020409',
        'surface_container_low': '#0a0f2a',
        'surface_container': '#131b38',
        'surface_container_high': '#1a2447',
        'surface_container_highest': '#242d52',
        'on_surface': '#ffffff',
        'on_surface_variant': '#b9c0e0',
        'outline': '#565d8c',
        'outline_variant': '#2c3260',
        'primary': '#c084fc',
        'on_primary': '#050921',
        'primary_container': '#9d4edd',
        'on_primary_container': '#050921',
        'secondary': '#3860be',
        'on_secondary': '#ffffff',
        'tertiary': '#ffae58',
        'on_tertiary': '#050921',
        'error': '#ff5468',
        'on_error': '#ffffff',
        'positive': '#1ed760',
        'negative': '#ef4444',
    },
    'fonts': {
        'display': "'Inter', sans-serif",
        'body': "'Inter', sans-serif",
        'mono': "'JetBrains Mono', monospace",
    },
    'radius': {
        'sm': '2px', 'default': '4px', 'md': '10px', 'lg': '16px', 'xl': '20px', 'full': '9999px',
    },
    'spacing': {
        'xs': '4px', 'sm': '12px', 'md': '24px', 'lg': '40px', 'xl': '64px', 'gutter': '24px',
    },
}

# Light-mode color palette, on request ("dark mode should be exactly what
# is currently being shown, develop a light mode... doesn't lose any of
# the clearness of data or functionality"). Same keys as THEME['colors']
# above (fonts/radius/spacing are shared across both modes - only color
# roles differ), every "on_X" pair checked with a real WCAG contrast-ratio
# script before committing to these values (not eyeballed): on_surface/
# surface 16.7:1, primary/surface 6.6:1, secondary/surface 7.6:1,
# tertiary/surface 4.6:1, error/surface 5.2:1 - all >=AA for normal text.
# positive/negative land at 3.4:1 / 4.5:1 (AA for large/graphical content,
# not small body text) - these are used as chart dot/bar/badge fill colors
# here, never as small printed text, the same usage pattern the original
# dark palette's own '#1ed760'/'#ef4444' already had. Elevation direction
# intentionally INVERTS vs. the dark palette's container family (there,
# higher elevation = lighter; here, higher elevation = slightly more
# tinted/grey, since you can't get lighter than white) - standard practice
# for a light Material-style surface scale, verified by checking the
# actual luminance ordering, not just picking plausible-looking hex values.
THEME_LIGHT_COLORS = {
    'surface': '#F7F5FB',
    'surface_dim': '#E4E1EC',
    'surface_bright': '#FFFFFF',
    'surface_container_lowest': '#FFFFFF',
    'surface_container_low': '#F1EEF8',
    'surface_container': '#EAE6F5',
    'surface_container_high': '#E1DCF0',
    'surface_container_highest': '#D7D0EA',
    'on_surface': '#171426',
    'on_surface_variant': '#4B4566',
    'outline': '#79738F',
    'outline_variant': '#CFC9DD',
    'primary': '#6D28D9',
    'on_primary': '#FFFFFF',
    'primary_container': '#EDE1FE',
    'on_primary_container': '#33146B',
    'secondary': '#2C4A99',
    'on_secondary': '#FFFFFF',
    'tertiary': '#B45309',
    'on_tertiary': '#FFFFFF',
    'error': '#C81E3A',
    'on_error': '#FFFFFF',
    'positive': '#1A9850',
    'negative': '#DC2626',
}

# Snapshot of the ORIGINAL dark-mode values, taken before anything ever
# mutates THEME['colors'] - lets apply_theme_mode below restore dark mode
# exactly (the explicit requirement: "the dark mode should be exactly what
# is currently being shown") without needing a separate THEME_DARK_COLORS
# dict that could silently drift out of sync with THEME['colors'] above.
_THEME_DARK_COLORS = dict(THEME['colors'])


def apply_theme_mode(mode):
    """
    Switches the app's active color palette by mutating THEME['colors']
    IN PLACE (.clear() + .update(), never reassigning THEME['colors'] to a
    new dict object) - ui.styling, ui.charts, and ui.components each do
    their own `C = THEME['colors']` at import time, which binds every one
    of those modules' `C` names to this SAME dict object. Because a
    module's top-level code only runs once per process (Python's import
    cache), re-running this app's script on every Streamlit rerun does NOT
    re-execute those `C = THEME['colors']` lines - so switching modes has
    to change the dict's CONTENTS, not hand out a new dict, or two of the
    three modules would keep reading stale colors. Called from
    ui.styling.inject_theme() (which itself runs at the top of every
    rerun, before anything reads C[...]) with mode resolved from
    st.session_state - config.py itself stays Streamlit-import-free.

    Caveat, honestly flagged rather than glossed over: THEME['colors'] is
    one dict shared by every session in this process (Streamlit session
    state is per-browser-tab; a plain module-level dict is not) - fine for
    this app's actual single-user/personal-use deployment (see this
    file's own season-window comment above for the same assumption), but
    it would cross-contaminate the theme between concurrent sessions in a
    genuinely multi-user deployment. Not attempting a per-session-safe
    refactor here since that would mean threading a colors dict through
    every one of styling.py/charts.py/components.py's many C[...] call
    sites instead of this single mutation point.
    """
    target = THEME_LIGHT_COLORS if mode == 'light' else _THEME_DARK_COLORS
    THEME['colors'].clear()
    THEME['colors'].update(target)
