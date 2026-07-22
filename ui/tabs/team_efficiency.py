"""Team Efficiency tab: adjusted offensive/defensive efficiency and net
rating for every D-I team, live via CollegeBasketballData.com - with an
offense-vs-defense efficiency landscape scatter (the classic KenPom-style
four-quadrant view) and in-table rating meters."""
import streamlit as st

from config import AVAILABLE_SEASONS
from data.loaders import current_cbb_season, load_efficiency_ratings, load_all_team_season_stats, team_color_map
from data.transforms import four_factors_percentile_grid
from ui.components import render_coming_soon, render_hero_tiles
from ui.charts import render_efficiency_scatter, render_percentile_heatmap
from ui.styling import style_plain_dataframe, df_auto_height, build_column_help_config


def render():
    st.markdown("<div class='custom-section-header'>TEAM EFFICIENCY</div>", unsafe_allow_html=True)

    default_season = current_cbb_season()
    seasons = AVAILABLE_SEASONS if default_season in AVAILABLE_SEASONS else [default_season] + AVAILABLE_SEASONS
    season = st.selectbox("Season", seasons, index=seasons.index(default_season), format_func=lambda y: f"{y - 1}-{str(y)[2:]}")

    df = load_efficiency_ratings(season)
    if df.empty:
        render_coming_soon(
            eyebrow="NEEDS SETUP",
            blurb=(
                "No CollegeBasketballData.com API key is configured yet (or the request "
                "failed). Add cbbd_api_key to .streamlit/secrets.toml — see "
                "DATA_SOURCES.md — and this tab will populate automatically."
            ),
            data_sources=["CollegeBasketballData.com API — /ratings/adjusted"],
        )
        return

    # Indexed on Team, not Rank: CFB Scholar's identical pattern hit a live
    # bug where some teams have a null rank (pandas' Styler raises "not
    # compatible with non-unique index" once more than one row shares a NaN
    # index value) - applying the same fix here proactively rather than
    # waiting to hit it again. Team names are reliably unique within a season.
    colors = team_color_map(season)

    # League-leader hero strip - spotlights the single most important
    # number in each direction before the full scatter/table detail below.
    ranked = df.dropna(subset=['Rank'])
    if not ranked.empty:
        top_net = ranked.sort_values('Net Rating', ascending=False).iloc[0]
        top_off = ranked.sort_values('Off Rating', ascending=False).iloc[0]
        top_def = ranked.sort_values('Def Rating', ascending=True).iloc[0]  # lower Def Rating = better
        render_hero_tiles([
            {'label': 'Best Net Rating', 'value_str': top_net['Team'], 'sub': f"{top_net['Net Rating']:+.1f}"},
            {'label': 'Best Offense', 'value_str': top_off['Team'], 'sub': f"{top_off['Off Rating']:.1f} Off Rtg"},
            {'label': 'Best Defense', 'value_str': top_def['Team'], 'sub': f"{top_def['Def Rating']:.1f} Def Rtg"},
        ])

    # Two sub-tabs, lazily rendered (same tab.open + key/on_change="rerun"
    # pattern app.py's top-level tabs use) so the expensive Four Factors
    # pull below only fires when that sub-tab is actually opened - this is
    # what was making the whole tab feel laggy on first click before.
    sub_rankings, sub_four_factors = st.tabs(
        ["RANKINGS", "FOUR FACTORS TIERING"], key="te_subtab", on_change="rerun"
    )
    if sub_rankings.open:
        with sub_rankings:
            _render_rankings_subtab(df, colors, ranked)
    if sub_four_factors.open:
        with sub_four_factors:
            _render_four_factors_subtab(df, ranked, season)


def _render_rankings_subtab(df, colors, ranked):
    # Efficiency landscape: offense (x, right = better) vs defense
    # (y, inverted so up = better since a LOWER defensive rating is better).
    st.markdown("<div class='custom-section-header'>EFFICIENCY LANDSCAPE</div>", unsafe_allow_html=True)
    top1 = ranked.sort_values('Rank')['Team'].head(1).tolist()
    extra = st.multiselect("Highlight teams", sorted(df['Team'].dropna().tolist()), key="te_highlight",
                           help="The #1 team is highlighted by default — add any others you want to compare.")
    render_efficiency_scatter(
        df, 'Off Rating', 'Def Rating', colors, invert_y=True,
        highlight=set(top1) | set(extra),
        x_label="Adjusted offensive rating (right = better offense)",
        y_label="Adjusted defensive rating (up = better defense)",
    )
    # 'Team' stays a real column, not the index - Streamlit's dataframe
    # grid doesn't render Styler colors on index/row-header cells at all
    # (confirmed live), only on data columns, so a `.set_index('Team')`
    # here silently rendered every row with no team color despite passing
    # team_color_map - see style_plain_dataframe's docstring. 'Rank' is
    # still pinned via column_config, no index needed for that.
    display_df = df.sort_values('Rank').reset_index(drop=True)
    # In-table meters: Net and Off ratings scale higher-is-better. Def
    # Rating is deliberately left numeric (lower = better there - a meter
    # would visually reward the worst defenses).
    meter_cols = {}
    for col in ('Net Rating', 'Off Rating'):
        vals = df[col].dropna()
        if not vals.empty:
            meter_cols[col] = (float(vals.min()), float(vals.max()))
    column_config = build_column_help_config(display_df, pinned_cols=['Rank'], meter_cols=meter_cols)
    # Height capped to ~30 visible rows (internal scroll for the rest) - not
    # sized to fit all 360+ D-I teams. An uncapped df_auto_height(len(...))
    # here was rendering a ~12,000px-tall grid on every single visit to this
    # (default, eagerly-rendered) sub-tab, a real and measurable contributor
    # to "this tab feels slow to load in" - the NET & Resume table already
    # caps the same way for the same reason (see ui/tabs/net_resume.py);
    # this just brings Team Efficiency's rankings table in line with that
    # established pattern instead of being the one outlier.
    st.dataframe(
        style_plain_dataframe(display_df, team_color_map=colors),
        width="stretch", height=df_auto_height(min(len(display_df), 30)),
        column_config=column_config, hide_index=True,
    )

def _render_four_factors_subtab(df, ranked, season):
    team_stats = load_all_team_season_stats(season)
    if team_stats.empty:
        st.info("Four Factors tiering needs /stats/team/season data, which isn't available right now.")
        return
    conf_options = ["Top 25 (Net Rating)"] + sorted(df['Conference'].dropna().unique().tolist())
    scope = st.selectbox("Scope", conf_options, key="te_ff_scope")
    if scope == "Top 25 (Net Rating)":
        scope_teams = ranked.sort_values('Net Rating', ascending=False)['Team'].head(25).tolist()
    else:
        scope_teams = df[df['Conference'] == scope]['Team'].dropna().tolist()
    pct_grid, raw_grid, ff_cols = four_factors_percentile_grid(team_stats, teams=scope_teams)
    if pct_grid.empty:
        st.info("No Four Factors data for this scope yet.")
    else:
        render_percentile_heatmap(pct_grid, raw_grid, ff_cols)
