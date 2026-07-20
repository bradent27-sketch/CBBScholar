"""Transfer Portal tab: portal entry tracker plus recruiting class rankings,
live via CollegeBasketballData.com. CORRECTION vs. this app's original
DATA_SOURCES.md: that doc claimed no clean free composite recruiting API
exists for college basketball - checked CBBD's API spec directly while
building this and found /recruiting/players does exactly that, same as
CFBD does for football. Fixed here and in DATA_SOURCES.md.

Recruiting-year gotcha: /recruiting/players and /recruiting/portal both
take a `year` param, but this is almost certainly NOT the same "season"
numbering the rest of the app uses (current_cbb_season() labels a season
by its SPRING/ending year, e.g. the 2025-26 season is "2026" - confirmed
live for /stats and /ratings). Recruiting classes everywhere else
(247Sports, Rivals, CFBD's own /recruiting/players, which CBBD explicitly
mirrors) are labeled by HS-graduation/enrollment year instead - which for
a class enrolling this Fall would ALSO read as this app's current
current_cbb_season() value, so the two conventions may already line up by
coincidence for the "current" class specifically, but there's no live
network access from this dev environment to confirm CBBD's exact
semantics either way (see HANDOFF). Rather than guess, this tab exposes
the recruiting year as its OWN selector (not tied to the main team-season
picker anywhere else in the app) so a real user with real data in front of
them can immediately tell, by paging a year in either direction, which
value actually returns current/accurate commitment data - faster and more
reliable than a guess baked into the code."""
import streamlit as st

from data.loaders import current_cbb_season, load_recruiting_rankings, load_transfer_portal
from ui.components import render_coming_soon
from ui.styling import style_plain_dataframe, df_auto_height

_STALE_DATA_CAVEAT = (
    "\"Uncommitted\"/\"Undecided\" reflects CollegeBasketballData.com's own database, which can lag real "
    "commitment announcements by days or more - this app doesn't compute commitment status itself, just "
    "displays what the source reports. If a player you know has committed still shows as open, try an "
    "adjacent class year above (recruiting-year numbering isn't 100% confirmed against this source - see "
    "this tab's own docstring) or hit Refresh to bypass the 6-hour cache and re-pull right now."
)


def render():
    st.markdown("<div class='custom-section-header'>TRANSFER PORTAL</div>", unsafe_allow_html=True)

    default_year = current_cbb_season()
    year_options = [default_year - 1, default_year, default_year + 1, default_year + 2]
    c1, c2 = st.columns([2, 1])
    with c1:
        year = st.selectbox(
            "Recruiting / Portal Class Year", year_options, index=1, key="tp_year",
            help="Independent from the rest of the app's season picker — recruiting classes are labeled "
                 "by enrollment year, not by season. If commitment data looks stale, try the year on "
                 "either side.",
        )
    with c2:
        st.write("")
        if st.button("🔄 Refresh now", key="tp_refresh", help="Bypass the 6-hour cache and re-pull live data for this year."):
            load_recruiting_rankings.clear()
            load_transfer_portal.clear()
            st.rerun()

    st.markdown("**Recruiting Class Rankings**")
    recruits = load_recruiting_rankings(year)
    if recruits.empty:
        render_coming_soon(
            eyebrow="NEEDS SETUP",
            blurb="No CollegeBasketballData.com API key is configured yet (or the request failed).",
            data_sources=["CollegeBasketballData.com API — /recruiting/players"],
        )
        return

    n_committed = int((recruits['Committed To'] != 'Uncommitted').sum())
    n_total = len(recruits)
    pct = (n_committed / n_total * 100) if n_total else 0
    m1, m2 = st.columns(2)
    m1.metric("Committed", f"{n_committed:,} / {n_total:,}", f"{pct:.0f}%")
    only_uncommitted = m2.checkbox("Show only Uncommitted", key="tp_only_uncommitted", help="Quick way to spot-check entries that look wrong.")

    recruits_display = recruits[recruits['Committed To'] == 'Uncommitted'] if only_uncommitted else recruits
    # NOT indexed on Rank: recruiting ranks can repeat/be null (same
    # pandas Styler non-unique-index issue hit and fixed elsewhere in both
    # apps' ratings tables) - a clean sequential index sidesteps it
    # regardless of what the underlying data contains.
    display = recruits_display.reset_index(drop=True)
    display.index = display.index + 1
    st.dataframe(style_plain_dataframe(display), width="stretch", height=df_auto_height(min(len(display), 30)))
    st.caption(_STALE_DATA_CAVEAT)

    st.markdown("**Transfer Portal**")
    portal = load_transfer_portal(year)
    if portal.empty:
        st.info(f"No transfer portal data found for {year}.")
        return

    filter_text = st.text_input("Filter by player or team name", key="tp_portal_filter")
    filtered = portal
    if filter_text:
        mask = (
            portal['Player'].str.contains(filter_text, case=False, na=False)
            | portal['From'].str.contains(filter_text, case=False, na=False)
            | portal['To'].str.contains(filter_text, case=False, na=False)
        )
        filtered = portal[mask]

    st.caption(f"{len(filtered):,} of {len(portal):,} entries shown")
    display = filtered.head(200).reset_index(drop=True)
    display.index = display.index + 1
    st.dataframe(style_plain_dataframe(display), width="stretch", height=df_auto_height(min(len(display), 30)))
    st.caption("Recruiting and portal data via CollegeBasketballData.com. " + _STALE_DATA_CAVEAT)
