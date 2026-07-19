"""Team Efficiency tab: adjusted offensive/defensive efficiency and net
rating for every D-I team, live via CollegeBasketballData.com - with an
offense-vs-defense efficiency landscape scatter (the classic KenPom-style
four-quadrant view) and in-table rating meters."""
import streamlit as st

from config import AVAILABLE_SEASONS
from data.loaders import current_cbb_season, load_efficiency_ratings, team_color_map
from ui.components import render_coming_soon
from ui.charts import render_efficiency_scatter
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
