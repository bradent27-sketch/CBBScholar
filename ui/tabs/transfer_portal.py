"""Transfer Portal tab: portal entry tracker plus recruiting class rankings,
live via CollegeBasketballData.com. CORRECTION vs. this app's original
DATA_SOURCES.md: that doc claimed no clean free composite recruiting API
exists for college basketball - checked CBBD's API spec directly while
building this and found /recruiting/players does exactly that, same as
CFBD does for football. Fixed here and in DATA_SOURCES.md.

Season default: recruiting/portal activity is about the UPCOMING season's
roster (a recruit committing today enrolls next fall), not the just-
finished/in-progress season current_cbb_season() points at everywhere else
in this app - so this tab uses AVAILABLE_SEASONS_WITH_UPCOMING and defaults
one year ahead of current_cbb_season(). This is a reasoned fix, not a
verified one - this sandbox's network policy blocks reaching CBBD's API
directly to confirm the "year" param's exact semantics - but it's grounded
in the same past-vs-upcoming-season distinction Conference Standings
already uses AVAILABLE_SEASONS_WITH_UPCOMING for.
"""
import streamlit as st

from config import AVAILABLE_SEASONS_WITH_UPCOMING
from data.loaders import current_cbb_season, load_recruiting_rankings, load_transfer_portal, load_teams
from ui.components import render_coming_soon
from ui.styling import style_plain_dataframe, df_auto_height
from ui.tabs.player_search import _fmt_height

_MAX_STARS = 5


def _star_glyphs(stars):
    try:
        n = int(stars)
    except (TypeError, ValueError):
        return '--'
    n = max(0, min(_MAX_STARS, n))
    return '★' * n + '☆' * (_MAX_STARS - n)


def _star_pct(stars):
    """0-100 scale for style_plain_dataframe's numeric_pct_cols, so the
    Stars cell's background tints brighter for more stars via the same
    get_grade_color scale every other grade-like column in this app uses -
    the glyph string above still carries the filled/outline shape."""
    try:
        return max(0.0, min(100.0, float(stars) / _MAX_STARS * 100))
    except (TypeError, ValueError):
        return None


def _fmt_weight(w):
    try:
        return f"{int(w)} lbs"
    except (TypeError, ValueError):
        return '--'


def _fmt_bio_cols(df):
    """Copy of df with Stars/Height/Weight formatted for display - kept
    separate from the raw df so callers can still compute numeric_pct_cols
    from the original numeric Stars values."""
    out = df.copy()
    out['Stars'] = out['Stars'].apply(_star_glyphs)
    if 'Height' in out.columns:
        out['Height'] = out['Height'].apply(_fmt_height)
    if 'Weight' in out.columns:
        out['Weight'] = out['Weight'].apply(_fmt_weight)
    return out


def render():
    st.markdown("<div class='custom-section-header'>TRANSFER PORTAL</div>", unsafe_allow_html=True)

    default_season = current_cbb_season() + 1
    seasons = AVAILABLE_SEASONS_WITH_UPCOMING if default_season in AVAILABLE_SEASONS_WITH_UPCOMING else [default_season] + AVAILABLE_SEASONS_WITH_UPCOMING
    season = st.selectbox(
        "Recruiting class / portal season", seasons, index=seasons.index(default_season),
        format_func=lambda y: f"{y - 1}-{str(y)[2:]}", key="tp_season",
        help="Defaults to the upcoming season — recruiting/portal activity is about who's arriving NEXT, not this season's roster.",
    )

    recruits = load_recruiting_rankings(season)
    portal = load_transfer_portal(season)
    if recruits.empty and portal.empty:
        render_coming_soon(
            eyebrow="NEEDS SETUP",
            blurb="No CollegeBasketballData.com API key is configured yet (or the request failed).",
            data_sources=["CollegeBasketballData.com API — /recruiting/players, /recruiting/portal"],
        )
        return

    teams_df = load_teams(season)
    team_options = ["All teams"] + (sorted(teams_df['Team'].dropna().unique().tolist()) if not teams_df.empty else [])
    fc1, fc2 = st.columns([1, 2])
    with fc1:
        team_filter = st.selectbox(
            "Filter by team", team_options, key="tp_team_filter",
            help="Shows this team's recruiting class AND portal activity together.",
        )
    with fc2:
        text_filter = st.text_input("Filter by player name", key="tp_text_filter")

    st.markdown("**Recruiting Class Rankings**")
    if recruits.empty:
        st.info(f"No recruiting class data found for {season}.")
    else:
        shown = recruits
        if team_filter != "All teams":
            shown = shown[shown['Committed To'] == team_filter]
        if text_filter:
            shown = shown[shown['Player'].str.contains(text_filter, case=False, na=False)]
        # NOT indexed on Rank: recruiting ranks can repeat/be null (same
        # pandas Styler non-unique-index issue hit and fixed elsewhere in
        # both apps' ratings tables) - a clean sequential index sidesteps
        # it regardless of what the underlying data contains.
        display = shown.reset_index(drop=True)
        display.index = display.index + 1
        star_pct = [_star_pct(s) for s in display['Stars']]
        st.caption(f"{len(display):,} of {len(recruits):,} recruits shown")
        st.dataframe(
            style_plain_dataframe(_fmt_bio_cols(display), numeric_pct_cols={'Stars': star_pct}),
            width="stretch", height=df_auto_height(min(len(display), 30)),
        )

    st.markdown("**Transfer Portal**")
    if portal.empty:
        st.info(f"No transfer portal data found for {season}.")
        return

    filtered = portal
    if team_filter != "All teams":
        filtered = filtered[(filtered['From'] == team_filter) | (filtered['To'] == team_filter)]
    if text_filter:
        filtered = filtered[filtered['Player'].str.contains(text_filter, case=False, na=False)]

    st.caption(f"{len(filtered):,} of {len(portal):,} entries shown")
    display = filtered.head(200).reset_index(drop=True)
    display.index = display.index + 1
    star_pct = [_star_pct(s) for s in display['Stars']]
    st.dataframe(
        style_plain_dataframe(_fmt_bio_cols(display), numeric_pct_cols={'Stars': star_pct}),
        width="stretch", height=df_auto_height(min(len(display), 30)),
    )
    st.caption("Source: CollegeBasketballData.com.")
