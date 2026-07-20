"""
Bracketology tab: a simplified seed-line projection from adjusted net
rating, live via CollegeBasketballData.com. This is NOT a real selection
-committee simulation - no conference auto-bid logic, no bracket
geography/balancing, no resume factors (see NET & Resume tab for why true
resume data isn't available from any free source found during this build).
It's a straightforward "sort by power rating, split into groups of 4"
projection, clearly labeled as such rather than presented as authoritative.
"""
import streamlit as st

from config import AVAILABLE_SEASONS
from data.loaders import current_cbb_season, load_efficiency_ratings
from ui.components import render_coming_soon
from ui.charts import render_bubble_strip
from ui.styling import style_plain_dataframe, df_auto_height


def render():
    st.markdown("<div class='custom-section-header'>BRACKETOLOGY</div>", unsafe_allow_html=True)
    st.info(
        "A simplified projection — teams sorted by adjusted net rating and split into "
        "groups of 4 per seed line. Real bracket selection also weighs conference "
        "auto-bids, resume/Quad data (not available free — see NET & Resume), and "
        "regional bracket balancing, none of which this does."
    )

    default_season = current_cbb_season()
    seasons = AVAILABLE_SEASONS if default_season in AVAILABLE_SEASONS else [default_season] + AVAILABLE_SEASONS
    season = st.selectbox("Season", seasons, index=seasons.index(default_season), format_func=lambda y: f"{y - 1}-{str(y)[2:]}", key="br_season")

    ratings = load_efficiency_ratings(season)
    if ratings.empty:
        render_coming_soon(
            eyebrow="NEEDS SETUP",
            blurb="No CollegeBasketballData.com API key is configured yet (or the request failed).",
            data_sources=["CollegeBasketballData.com API — /ratings/adjusted"],
        )
        return

    field = ratings.dropna(subset=['Rank']).sort_values('Rank').head(68).reset_index(drop=True)
    field['Seed Line'] = (field.index // 4) + 1
    field.loc[field['Seed Line'] > 16, 'Seed Line'] = 16

    seed_filter = st.selectbox("Seed line", list(range(1, 17)), key="br_seed")
    shown = field[field['Seed Line'] == seed_filter][['Rank', 'Team', 'Conference', 'Net Rating']].reset_index(drop=True)
    shown.index = shown.index + 1

    st.dataframe(style_plain_dataframe(shown), width="stretch", height=df_auto_height(len(shown)))
    st.caption(f"Projected field of 68 (last 4 teams on the seed-line-16 group are effectively First Four). Source: CollegeBasketballData.com adjusted ratings.")

    st.markdown("<div class='custom-section-header'>BUBBLE WATCH</div>", unsafe_allow_html=True)
    full_sorted = ratings.dropna(subset=['Rank']).sort_values('Rank')
    render_bubble_strip(full_sorted, 'Rank', 'Team', cutoff=68, window=10, value_col='Net Rating', value_label='Net Rating')
    st.caption(
        "Teams within 10 spots of the projected cutoff (rank 68) — green = projected in the field, red = "
        "projected out, fading toward the line. A proximity gradient, not a selection-committee probability "
        "(this app has no resume/auto-bid model — see the note above)."
    )
