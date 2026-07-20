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

    # Efficiency landscape: offense (x, right = better) vs defense
    # (y, inverted so up = better since a LOWER defensive rating is better).
    st.markdown("<div class='custom-section-header'>EFFICIENCY LANDSCAPE</div>", unsafe_allow_html=True)
    top5 = df.dropna(subset=['Rank']).sort_values('Rank')['Team'].head(5).tolist()
    extra = st.multiselect("Highlight teams", sorted(df['Team'].dropna().tolist()), key="te_highlight",
                           help="Top 5 by net rating are always highlighted; add any others here.")
    render_efficiency_scatter(
        df, 'Off Rating', 'Def Rating', colors, invert_y=True,
        highlight=set(top5) | set(extra),
        x_label="Adjusted offensive rating (right = better offense)",
        y_label="Adjusted defensive rating (up = better defense)",
    )
    st.caption("Each dot is a team in its own colors — hover for exact ratings. Dashed lines are the D-I medians, so the top-right quadrant is 'above-median both ways'.")

    indexed = df.set_index('Team')
    # In-table meters: Net and Off ratings scale higher-is-better. Def
    # Rating is deliberately left numeric (lower = better there - a meter
    # would visually reward the worst defenses).
    meter_cols = {}
    for col in ('Net Rating', 'Off Rating'):
        vals = df[col].dropna()
        if not vals.empty:
            meter_cols[col] = (float(vals.min()), float(vals.max()))
    column_config = build_column_help_config(indexed, pinned_cols=['Rank'], meter_cols=meter_cols)
    st.dataframe(
        style_plain_dataframe(indexed, team_color_map=colors),
        width="stretch", height=df_auto_height(len(indexed)),
        column_config=column_config,
    )
    st.caption(
        "Net Rating: points per 100 possessions better than an average team, adjusted "
        "for opponent strength — this app's KenPom-equivalent (Def Rating: lower = better). "
        "Net and Off Rating columns render as league-scaled meters."
    )

    # --- Four Factors tiering heatmap (new, additive) --------------------
    st.markdown("<div class='custom-section-header'>FOUR FACTORS TIERING</div>", unsafe_allow_html=True)
    team_stats = load_all_team_season_stats(season)
    if team_stats.empty:
        st.info("Four Factors tiering needs /stats/team/season data, which isn't available right now.")
    else:
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
            st.caption(
                "Each cell is that team's D-I percentile on Dean Oliver's Four Factors (shooting, turnovers, "
                "rebounding, free-throw rate), offense and defense sides shown separately — hover a cell for the "
                "raw value. Rows sorted by average percentile across all eight columns, best profile first."
            )
