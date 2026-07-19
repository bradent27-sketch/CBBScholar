"""Team Efficiency tab: adjusted offensive/defensive efficiency and net
rating for every D-I team, live via CollegeBasketballData.com - with an
offense-vs-defense efficiency landscape scatter (the classic KenPom-style
four-quadrant view), in-table rating meters, a per-team "Team DNA" radar
(statistical identity across 7 percentile axes), and a live "What Wins"
correlation panel (every Four Factor/style stat's real correlation with
this season's Net Rating, recomputed from the current data - not a
hardcoded assumption)."""
import streamlit as st

from config import AVAILABLE_SEASONS
from data.loaders import (
    current_cbb_season, load_efficiency_ratings, load_all_team_season_stats, team_color_map,
    get_league_player_stats, build_league_player_database,
)
from data.transforms import team_dna_profile, stat_win_correlations, league_rate_profiles, MIN_MINUTES_FOR_PERCENTILE
from ui.components import render_coming_soon
from ui.charts import render_efficiency_scatter, render_radar_chart, render_correlation_bars
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

    team_stats = load_all_team_season_stats(season)

    # --- Team DNA radar -----------------------------------------------------
    if not team_stats.empty:
        st.markdown("<div class='custom-section-header'>TEAM DNA</div>", unsafe_allow_html=True)
        st.caption(
            "Seven-axis statistical identity — every axis is a real D-I percentile, so the SHAPE "
            "is what matters: a big, round shape is elite everywhere, a spiky one is boom-or-bust "
            "by design (e.g. elite three-point volume but weak rebounding). Overlay a second team to "
            "compare identities, not just quality."
        )
        all_teams = sorted(df['Team'].dropna().tolist())
        dna_default = [t for t in top5[:1] if t in all_teams] or all_teams[:1]
        dna_teams = st.multiselect(
            "Team(s) to profile", all_teams, default=dna_default, key="te_dna_teams",
            help="Pick up to 3 — more than that gets visually noisy on one radar.",
        )
        dna_teams = dna_teams[:3]
        if not dna_teams:
            st.info("Pick at least one team to see its statistical DNA.")
        else:
            radar_series = []
            radar_labels, radar_help = None, None
            for t in dna_teams:
                profile = team_dna_profile(df, team_stats, t)
                if not profile:
                    continue
                labels, values, help_texts = profile
                radar_labels, radar_help = labels, help_texts
                radar_series.append({'name': t, 'color': colors.get(t), 'values': values})
            if radar_series:
                render_radar_chart(radar_labels, radar_series, radar_help)
            else:
                st.info("No Four Factors data available for the selected team(s) this season.")

        # --- What wins this season ------------------------------------------
        st.markdown("<div class='custom-section-header'>WHAT WINS IN COLLEGE HOOPS — THIS SEASON</div>", unsafe_allow_html=True)
        st.caption(
            "Live Pearson correlation of every Four Factor/style stat against this season's adjusted "
            "Net Rating, across all of D-I — recomputed from the real current data every time this "
            "loads, not a fixed assumption. Green = being good at that stat associates with winning "
            "this season; red = it counterintuitively associates with losing. Amber rows (pace, shot "
            "selection) have no inherent 'good' direction — sign there just shows which way the "
            "correlation runs, not good vs. bad."
        )
        corr_rows = stat_win_correlations(team_stats, df)
        if corr_rows:
            render_correlation_bars(corr_rows)
            top = corr_rows[0]
            st.caption(
                f"Strongest signal this season: **{top['label']}** (r = {top['display_r']:+.2f} vs. Net Rating, "
                f"n={top['n']} teams). Correlation, not causation — and this season's ranking can shift as more games are played."
            )
        else:
            st.info("Not enough teams with both Four Factors and Net Rating data yet to compute correlations.")

    # --- League player database (real percentile role tags) ----------------
    st.markdown("<div class='custom-section-header'>LEAGUE PLAYER DATABASE</div>", unsafe_allow_html=True)
    st.caption(
        "Powers REAL percentile-based player role tags in Player Search and Matchup Analyzer "
        "(Ball-Handler/Post Player/Shooter, ranked against actual D-I players, not fixed cutoffs) — "
        "without it, those tabs fall back to fixed-threshold heuristics."
    )
    league_stats = get_league_player_stats(season)
    if not league_stats.empty:
        rates = league_rate_profiles(league_stats)
        n_teams = league_stats['team'].nunique() if 'team' in league_stats.columns else '?'
        st.success(
            f"✅ League database loaded — {n_teams} teams, {len(rates)} qualifying players "
            f"(≥{MIN_MINUTES_FOR_PERCENTILE} season minutes). Role tags elsewhere in the app are using REAL percentiles."
        )
    else:
        st.warning(
            f"Not built yet for {season - 1}-{str(season)[2:]}. CBBD's player-stats endpoint appears to be "
            f"team-scoped (no free bulk pull like the team-level stats above), so building this requires "
            f"one API call per D-I team — roughly {len(df)} calls. One-time, cached 24 hours in this "
            "session. Role tags elsewhere fall back to fixed-threshold heuristics until this is built."
        )
        if st.button("Build League Player Database (all D-I teams)", key="te_build_league_db"):
            progress = st.progress(0.0, text="Starting...")

            def _update(done, total):
                progress.progress(done / total, text=f"Pulling player stats... {done}/{total} teams")

            result = build_league_player_database(season, _progress_callback=_update)
            progress.empty()
            if result.empty:
                st.error("Couldn't build the league database — no team pulls succeeded. Check the sidebar's live-connection test.")
            else:
                st.session_state[f'_league_player_db_{season}'] = result
                n_teams = result['team'].nunique() if 'team' in result.columns else '?'
                st.success(f"Built — {len(result)} player rows across {n_teams} teams. Reload this page to see percentile-based role tags everywhere.")
                st.rerun()
