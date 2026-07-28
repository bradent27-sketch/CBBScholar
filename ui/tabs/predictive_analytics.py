"""
Predictive Analytics tab: composite matchup-advantage modeling for one
player against one opponent's defense, built at the intersection of the
player's own usage/efficiency profile and the opponent's positional and
scheme tendencies - the deep-level predictive layer described in this
app's brainstorm pass, sitting one level above Matchup Analyzer's raw
side-by-side prep view.

Six metrics, all pure local compute in data.transforms (see that module's
"Predictive Analytics: Matchup Advantage engine" section for every formula
and caveat in full):
  1. Scheme Fingerprint - opponent's inferred paint-sag/perimeter-openness
     tendency, blended per position bucket with that bucket's own
     over/under-performance against this team specifically.
  2. Efficiency Elasticity Curve - how this player's own scoring efficiency
     has actually moved against tougher/faster opponents this season,
     fit as a real regression line over their own game log.
  3. Composite Matchup Advantage Score - the single 0-100 number blending
     usage-weighted efficiency, positional vulnerability, rim/foul
     leverage, and pace into one "how good is this matchup" readout.
  4. Rim-Pressure & Foul-Leverage Exploitation Score.
  5. Game-Script Sensitivity Index - close-game vs. decided-game production
     split, via a Date-only join to the team's own schedule margins.
  6. Positional Leverage / Mismatch Hunting Score - is this player's own
     position bucket actually the opponent's weakest one.

Deliberately NOT possession-level/shot-location based - this app has no
play-by-play or shot-chart source (see DATA_SOURCES.md), so every metric
above is an explicitly-labeled proxy inferred from aggregate allowed-rate
stats and the player's own game-to-game variance, not a literal defensive-
coverage classification. Every number rendered below links back to a
documented formula (see data/transforms.py) rather than being a black box.

Reuses the same ESPN-first/CBBD-fallback player-profile pipeline Matchup
Analyzer and Player Compare already use (data.loaders.
get_player_season_profile) and the same positional-matchup-defense source
(data.loaders.load_positional_matchup_data) Matchup Analyzer's TEAM DEFENSE
panel uses - no new data source, only new derived math and visualization on
top of what this app already fetches.
"""
import pandas as pd
import streamlit as st

from config import AVAILABLE_SEASONS
from data.loaders import (
    current_cbb_season, load_teams, load_team_roster, load_espn_teams,
    load_espn_season_player_box_native, get_player_season_profile,
    load_team_games, load_player_game_logs, load_all_team_season_stats,
    load_efficiency_ratings, load_positional_matchup_data,
    load_conference_player_season_stats,
)
from data.transforms import (
    position_bucket, positional_defense_summary, player_rate_stats,
    player_profile_values, espn_player_season_stats_for_teams,
    build_matchup_advantage_report,
)
from data.utils import match_player_name, resolve_team_name
from ui.components import render_coming_soon, render_hero_tiles, render_stat_tiles
from ui.charts import render_radar, render_percentile_heatmap, render_probability_band

_STAT_OPTIONS = ['Points', 'Rebounds', 'Assists']
_BUCKET_ORDER = ('Guard', 'Forward', 'Center')

_HEATMAP_COL_LABELS = {
    'Points Delta Score': 'Bucket Over/Under Score',
    'Rim Pressure Allowed': 'Rim Pressure Allowed',
    'Perimeter Openness Allowed': 'Perimeter Openness Allowed',
    'Vulnerability Score': 'Vulnerability Score',
}

_RADAR_AXIS_MAP = [
    ('Usage-Wtd Efficiency', 'usage_weighted_pct'),
    ('Positional Vulnerability', 'positional_vulnerability_pct'),
    ('Rim/Foul Leverage', 'rim_foul_pct'),
    ('Opponent Pace', 'pace_pct'),
]


def render():
    st.markdown("<div class='custom-section-header'>PREDICTIVE ANALYTICS</div>", unsafe_allow_html=True)
    st.caption(
        "Composite matchup-advantage modeling: a player's usage/efficiency profile weighed against an "
        "opponent's positional and scheme tendencies. Built from season/game-log data (no play-by-play or "
        "shot-location tracking) — every score below is a documented proxy formula, not a black box. See "
        "the methodology expander at the bottom for the exact math."
    )

    default_season = current_cbb_season()
    seasons = AVAILABLE_SEASONS if default_season in AVAILABLE_SEASONS else [default_season] + AVAILABLE_SEASONS
    season = st.selectbox(
        "Season", seasons, index=seasons.index(default_season),
        format_func=lambda y: f"{y - 1}-{str(y)[2:]}", key="pa_season",
    )

    teams_df = load_teams(season)
    if teams_df.empty:
        render_coming_soon(
            eyebrow="NEEDS SETUP",
            blurb="No CollegeBasketballData.com API key is configured yet (or the request failed). Add cbbd_api_key to .streamlit/secrets.toml — see DATA_SOURCES.md.",
            data_sources=["CollegeBasketballData.com API"],
        )
        return
    team_names = sorted(teams_df['Team'].dropna().unique().tolist())

    col_player, col_opp = st.columns(2)
    with col_player:
        st.markdown("<div class='custom-section-header'>PLAYER</div>", unsafe_allow_html=True)
        player_ctx = _pick_player(season, teams_df)
    with col_opp:
        st.markdown("<div class='custom-section-header'>OPPONENT DEFENSE</div>", unsafe_allow_html=True)
        default_opp_idx = 1 if (player_ctx and len(team_names) > 1 and team_names[0] == player_ctx['team_choice']) else 0
        opponent_team = st.selectbox("Team", team_names, index=min(default_opp_idx, len(team_names) - 1), key="pa_opp_team")

    if not player_ctx:
        return
    if opponent_team == player_ctx['team_choice']:
        st.warning("Pick a different team for Opponent Defense — a team can't have a matchup against itself.")
        return

    stat_col = st.selectbox(
        "Stat to project (Game-Script Sensitivity + probability band)", _STAT_OPTIONS, key="pa_stat_col",
        help="Efficiency Elasticity always models scoring efficiency (TS%/eFG%) regardless of this choice — this only changes which counting stat the other two use.",
    )
    recent_games_cap = st.slider(
        "Opponent games to include (most recent)", min_value=5, max_value=30, value=20, step=5,
        key="pa_pos_defense_window",
        help="Lower = fewer CBBD calls (only matters on the fallback) and a more current read on the opponent's defense; higher = more complete.",
    )

    trigger_key = f"pa_loaded_{season}_{player_ctx['team_choice']}_{player_ctx['sel_row']['name']}_{opponent_team}_{recent_games_cap}_{stat_col}"
    if not st.session_state.get(trigger_key, False):
        if st.button("Run matchup analytics", key="pa_run"):
            st.session_state[trigger_key] = True
        else:
            st.info(f"Click above to compute — free where possible, up to ~{recent_games_cap} CBBD calls otherwise (opponent positional defense fallback).")
            return

    report = _build_report(season, player_ctx, opponent_team, recent_games_cap, stat_col)
    if report is None:
        return
    _render_report(player_ctx, opponent_team, stat_col, report)


# ---------------------------------------------------------------------------
# Pickers / data assembly (loader calls live here, not in data/transforms.py
# - same layering discipline as ui/tabs/matchup_analyzer.py)
# ---------------------------------------------------------------------------

def _pick_player(season, teams_df):
    """
    Team + player selectors and ESPN/CBBD stats-profile resolution -
    deliberately the SAME logic as ui.tabs.matchup_analyzer._pick_player
    (roster UNIONED with this season's own ESPN box-file players, so a
    transfer-portal/walk-on gap in CBBD's roster endpoint doesn't hide a
    player who has real stats) rather than a cross-tab import, matching
    this app's existing convention of small per-tab duplication over
    cross-tab coupling (see HANDOFF.md's _mobile_cell_bg docstring for the
    same reasoning applied elsewhere). Returns a context dict, or None
    (after its own st.info) if no roster/stats data is available.
    """
    team_names = sorted(teams_df['Team'].dropna().unique().tolist())
    if not team_names:
        st.info("No team data available.")
        return None
    default_team = 'Duke' if 'Duke' in team_names else team_names[0]
    team_choice = st.selectbox("Team", team_names, index=team_names.index(default_team), key="pa_player_team")

    with st.spinner("Loading roster..."):
        roster_df = load_team_roster(team_choice, season)

    box_only_rows = []
    espn_teams_season = load_espn_teams(season)
    if not espn_teams_season.empty:
        espn_team = resolve_team_name(team_choice, espn_teams_season['Team'].dropna().tolist())
        if espn_team:
            box_df_for_picker = load_espn_season_player_box_native(season)
            if not box_df_for_picker.empty and 'Team' in box_df_for_picker.columns:
                box_team_players = box_df_for_picker[box_df_for_picker['Team'] == espn_team][['name', 'Position']].drop_duplicates(subset=['name'])
                existing_names = roster_df['name'] if not roster_df.empty else pd.Series([], dtype=str)
                box_only = box_team_players[
                    box_team_players['name'].apply(lambda n: match_player_name(n, existing_names) is None)
                ]
                box_only_rows = [pd.Series({'name': r['name'], 'position': r['Position']}) for _, r in box_only.iterrows()]

    roster_rows = [roster_df.iloc[i] for i in range(len(roster_df))]
    combined_rows = roster_rows + box_only_rows
    if not combined_rows:
        st.info(f"No roster or season data found for {team_choice} in {season}.")
        return None
    labels = [f"{r['name']} ({r.get('position') or '?'})" for r in combined_rows]
    sel_label = st.selectbox("Player", labels, key="pa_player_select")
    sel_row = combined_rows[labels.index(sel_label)]

    with st.spinner("Loading stats..."):
        stats, include_net_rating, source, box_df, athlete_source_id = get_player_season_profile(
            team_choice, season, sel_row['name'], sel_row.get('id'),
        )
    if not stats:
        st.info("No season stats for this player yet.")
        return None

    conf_series = teams_df.loc[teams_df['Team'] == team_choice, 'Conference']
    conf = conf_series.iloc[0] if not conf_series.empty else None

    return {
        'team_choice': team_choice, 'sel_row': sel_row, 'stats': stats,
        'include_net_rating': include_net_rating, 'source': source,
        'box_df': box_df, 'athlete_source_id': athlete_source_id, 'conf': conf,
    }


def _comparison_group(season, source, box_df, stats, conf):
    """Conference-scoped comparison group, matching Matchup Analyzer's
    default (non-D-I) group resolution - ESPN source resolves the player's
    OWN team's conference from ESPN's own team list (not CBBD's spelling,
    see ui.tabs.matchup_analyzer's own bugfix note on this exact mismatch);
    CBBD source uses the roster-picker's own conference. Deliberately no
    "compare vs all D-I" toggle here (unlike Matchup Analyzer) - this tab
    already has enough controls, and a conference-scoped baseline is a
    reasonable, cheap default for the percentile inputs below."""
    if source == 'espn':
        espn_teams_season = load_espn_teams(season)
        if espn_teams_season.empty:
            return pd.DataFrame(), "conference"
        espn_conf_row = espn_teams_season.loc[espn_teams_season['Team'] == stats['Team'], 'Conference']
        espn_conf = espn_conf_row.iloc[0] if not espn_conf_row.empty else None
        if not espn_conf:
            return pd.DataFrame(), "conference"
        espn_conf_teams = espn_teams_season.loc[espn_teams_season['Conference'] == espn_conf, 'Team'].tolist()
        return espn_player_season_stats_for_teams(box_df, teams=espn_conf_teams), espn_conf
    if conf:
        return load_conference_player_season_stats(conf, season), conf
    return pd.DataFrame(), "conference"


def _position_map_for_opponent(matchup_df, season):
    """{athleteSourceId(str): position_bucket} for load_positional_matchup_data's
    output - same logic as ui.tabs.matchup_analyzer._position_map_for_matchup
    (duplicated locally, see _pick_player's docstring for why)."""
    if matchup_df is None or matchup_df.empty:
        return {}
    pos_map = {}
    has_position_col = 'Position' in matchup_df.columns
    if has_position_col:
        with_pos = matchup_df.dropna(subset=['Position', 'athleteSourceId'])
        for _, r in with_pos.iterrows():
            pos_map[str(r['athleteSourceId'])] = position_bucket(r['Position'])
    missing_position = matchup_df[~matchup_df['athleteSourceId'].astype(str).isin(pos_map)] if has_position_col else matchup_df
    for opp in missing_position['Opponent Team'].dropna().unique():
        roster = load_team_roster(opp, season)
        if roster.empty:
            continue
        for _, r in roster.iterrows():
            sid = r.get('sourceId')
            if sid is not None and str(sid) not in pos_map:
                pos_map[str(sid)] = position_bucket(r.get('position'))
    return pos_map


def _build_report(season, player_ctx, opponent_team, recent_games_cap, stat_col):
    team_choice, sel_row, stats = player_ctx['team_choice'], player_ctx['sel_row'], player_ctx['stats']
    include_net_rating, source, box_df, athlete_source_id, conf = (
        player_ctx['include_net_rating'], player_ctx['source'], player_ctx['box_df'],
        player_ctx['athlete_source_id'], player_ctx['conf'],
    )
    player_bucket = position_bucket(sel_row.get('position'))
    if player_bucket not in _BUCKET_ORDER:
        st.warning(
            f"{sel_row['name']}'s position ('{sel_row.get('position') or '?'}') didn't map to Guard/Forward/Center — "
            "positional metrics need a recognized position."
        )
        return None

    with st.spinner("Loading comparison group..."):
        group_df, group_label = _comparison_group(season, source, box_df, stats, conf)
    group_rate_df = player_rate_stats(group_df) if group_df is not None and not group_df.empty else pd.DataFrame()

    with st.spinner("Loading player's per-game log..."):
        if source == 'espn':
            player_games = box_df[
                (box_df['Team'] == stats['Team']) & (box_df['athleteSourceId'].astype(str) == str(athlete_source_id))
            ].copy()
        else:
            logs = load_player_game_logs(team_choice, season)
            player_games = logs[logs['athleteSourceId'].astype(str) == str(sel_row.get('sourceId'))] if not logs.empty else logs
            if player_games is not None and player_games.empty and not logs.empty:
                player_games = logs[logs['name'] == sel_row['name']]
        player_games = player_games.sort_values('Date').reset_index(drop=True) if player_games is not None and not player_games.empty else pd.DataFrame()

    with st.spinner(f"Loading {team_choice}'s schedule..."):
        team_games = load_team_games(team_choice, season)

    with st.spinner("Loading league-wide team profiles..."):
        team_stats_df = load_all_team_season_stats(season)
        eff_ratings_df = load_efficiency_ratings(season)
    if team_stats_df.empty:
        st.info("Team defense profiles need /stats/team/season data, which isn't available right now.")
        return None

    with st.spinner(f"Loading {opponent_team}'s opponent game logs..."):
        matchup_df = load_positional_matchup_data(opponent_team, season, max_recent_games=recent_games_cap)
    used_espn = bool(not matchup_df.empty and 'Position' in matchup_df.columns and matchup_df['Position'].notna().any())
    pos_map = _position_map_for_opponent(matchup_df, season)
    positional_summary_df = positional_defense_summary(matchup_df, pos_map)
    if positional_summary_df.empty:
        st.info(
            f"No position-bucketed data for {opponent_team} yet — either not enough opponent games loaded, or the "
            "roster position field didn't match a recognized Guard/Forward/Center pattern."
        )
        return None

    player_values = player_profile_values(stats, include_net_rating=include_net_rating)

    report = build_matchup_advantage_report(
        player_bucket=player_bucket, player_values=player_values, group_rate_df=group_rate_df,
        player_games=player_games, team_games=team_games, opponent_team=opponent_team,
        team_stats_df=team_stats_df, eff_ratings_df=eff_ratings_df,
        positional_summary_df=positional_summary_df, stat_col=stat_col,
    )
    report['_meta'] = {
        'group_label': group_label, 'used_espn_positional': used_espn,
        'n_player_games': int(len(player_games)),
        'player_source': source,
    }
    return report


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def _render_report(player_ctx, opponent_team, stat_col, report):
    sel_row = player_ctx['sel_row']
    player_name = sel_row['name']
    player_bucket = report['player_bucket']
    meta = report['_meta']
    composite = report.get('composite') or {}

    st.caption(
        f"vs. {meta['group_label']} · player source: {'free ESPN/SportsDataverse' if meta['player_source'] == 'espn' else 'CollegeBasketballData.com'} · "
        f"opponent positional defense source: {'free ESPN season file' if meta['used_espn_positional'] else 'CollegeBasketballData.com (CBBD API calls used)'} · "
        f"{meta['n_player_games']} player games loaded"
    )

    st.markdown(f"### {player_name} ({player_bucket}) vs. {opponent_team}")
    if composite.get('score') is not None:
        render_hero_tiles([{
            'label': 'MATCHUP ADVANTAGE SCORE',
            'value_str': f"{composite['score']:.0f} / 100",
            'sub': composite.get('tier'),
        }])
    else:
        st.info("Not enough data to compute a composite score for this matchup yet.")

    st.markdown("#### Matchup Advantage Radar")
    st.caption("This matchup's four component percentiles vs. a flat league-average matchup (50th percentile on every axis). Missing components render at 50 (neutral), not 0.")
    if composite.get('components'):
        axes = [label for label, _key in _RADAR_AXIS_MAP]
        values_a = {label: (composite['components'].get(key) if composite['components'].get(key) is not None else 50) for label, key in _RADAR_AXIS_MAP}
        values_b = {label: 50 for label in axes}
        render_radar(axes, values_a, values_b, f"{player_name} vs {opponent_team}", "League-Average Matchup")
    else:
        st.caption("No composite components available.")

    st.markdown("#### Scheme-Alignment Heatmap")
    st.caption("Opponent's Guard/Forward/Center vulnerability, decomposed. Green = more exploitable for your player; red = tougher there. Your player's own bucket is marked with →.")
    _render_scheme_heatmap(report, player_bucket)

    st.markdown(f"#### Dynamic Probability Curve — {stat_col}")
    band = report.get('projection_band') or {}
    if band:
        render_probability_band(band, stat_label=stat_col)
        st.caption(
            f"Heuristic projection: this player's own {band['n_games']}-game {stat_col.lower()} distribution this season, "
            f"scaled ×{band['multiplier']:.2f} for this specific matchup (Matchup Advantage Score + opponent pace). "
            "Not a trained statistical model — see the methodology expander below."
        )
    else:
        st.info(f"Not enough {stat_col.lower()} game-log data yet to project a range.")

    st.markdown("#### Supporting metrics")
    _render_supporting_tiles(report)
    _render_detail_sections(report, player_bucket)
    _render_methodology_expander()


def _render_scheme_heatmap(report, player_bucket):
    fingerprint = report.get('scheme_fingerprint') or {}
    buckets = fingerprint.get('buckets') or {}
    if not buckets:
        st.caption("No opponent positional data available.")
        return
    rim_pct = fingerprint.get('rim_pressure_pct')
    perim_pct = fingerprint.get('perimeter_openness_pct')
    rows = []
    for b in _BUCKET_ORDER:
        info = buckets.get(b)
        if not info:
            continue
        label = f"→ {b} (your player)" if b == player_bucket else b
        rows.append({
            'Team': label,
            'Points Delta Score': info.get('delta_score'),
            'Rim Pressure Allowed': rim_pct,
            'Perimeter Openness Allowed': perim_pct,
            'Vulnerability Score': info.get('vulnerability'),
        })
    if not rows:
        st.caption("No opponent positional data available.")
        return
    heat_df = pd.DataFrame(rows)
    cols = ['Points Delta Score', 'Rim Pressure Allowed', 'Perimeter Openness Allowed', 'Vulnerability Score']
    render_percentile_heatmap(heat_df, heat_df, cols, col_labels=_HEATMAP_COL_LABELS, sort_by_avg=False)


def _render_supporting_tiles(report):
    tiles = []
    leverage = report.get('positional_leverage') or {}
    if leverage:
        tiles.append({
            'label': 'Positional Leverage',
            'value_str': f"#{leverage['rank']} of {leverage['of']} weakest",
            'pct': leverage.get('weakest_score') if leverage.get('is_weakest') else None,
        })
    rim_foul = report.get('rim_foul_leverage') or {}
    if rim_foul.get('score') is not None:
        tiles.append({'label': 'Rim/Foul Leverage', 'value_str': f"{rim_foul['score']:.0f}", 'pct': rim_foul['score']})
    elasticity = report.get('efficiency_elasticity') or {}
    if elasticity.get('projected_eff') is not None:
        tiles.append({
            'label': f"Projected {elasticity['efficiency_label']}",
            'value_str': f"{elasticity['projected_eff']:.1f}%",
            'pct': None,
        })
    game_script = report.get('game_script_sensitivity') or {}
    if game_script.get('sensitivity_index') is not None:
        tiles.append({'label': 'Game-Script Sensitivity', 'value_str': f"{game_script['sensitivity_index']:+.1f}%", 'pct': None})
    pace_pct = report.get('pace_pct')
    if pace_pct is not None:
        tiles.append({'label': 'Opponent Pace Pctl', 'value_str': f"{pace_pct:.0f}th", 'pct': pace_pct})
    if tiles:
        render_stat_tiles(tiles)
    else:
        st.caption("No supporting metrics available.")


def _render_detail_sections(report, player_bucket):
    leverage = report.get('positional_leverage') or {}
    if leverage:
        with st.expander("Positional Leverage detail"):
            st.markdown(
                f"**{player_bucket}** ranks **#{leverage['rank']} of {leverage['of']}** most-vulnerable position "
                f"buckets against this opponent. The single weakest bucket is **{leverage['weakest_bucket']}** "
                f"(vulnerability {leverage['weakest_score']:.1f}/100)."
            )
            if leverage.get('edge_vs_avg') is not None:
                direction = "more" if leverage['edge_vs_avg'] >= 0 else "less"
                st.caption(f"{player_bucket} is {abs(leverage['edge_vs_avg']):.1f} points {direction} vulnerable than the opponent's other two buckets, on average.")

    elasticity = report.get('efficiency_elasticity') or {}
    if elasticity:
        with st.expander("Efficiency Elasticity Curve detail"):
            st.markdown(
                f"Season {elasticity['efficiency_label']}: **{elasticity['season_avg_eff']:.1f}%** across "
                f"{elasticity['n_games']} games with a resolvable opponent."
            )
            if elasticity.get('slope_vs_defense') is not None:
                st.caption(
                    f"Slope vs. opponent defensive-rating percentile: {elasticity['slope_vs_defense']:+.3f} "
                    f"{elasticity['efficiency_label']} points per percentile-point of defensive strength faced "
                    "(negative = tends to shoot worse against tougher defenses)."
                )
            if elasticity.get('slope_vs_pace') is not None:
                st.caption(f"Slope vs. opponent pace percentile: {elasticity['slope_vs_pace']:+.3f} points per percentile-point of pace.")
            if elasticity.get('bucket_means'):
                for label, info in elasticity['bucket_means'].items():
                    st.caption(f"{label}: {info['mean']:.1f}% ({info['games']} games)")
            if elasticity.get('projected_adjustment') is not None:
                st.markdown(
                    f"Projected adjustment for tonight's opponent (defense percentile {elasticity['opponent_def_pctl']:.0f}th): "
                    f"**{elasticity['projected_adjustment']:+.1f} points** → projected **{elasticity['projected_eff']:.1f}%**."
                )
    elif report.get('_meta', {}).get('n_player_games', 0) > 0:
        st.caption("Efficiency Elasticity Curve: not enough games with a resolvable opponent yet (needs 5+).")

    rim_foul = report.get('rim_foul_leverage') or {}
    if rim_foul:
        with st.expander("Rim-Pressure & Foul-Leverage detail"):
            if rim_foul.get('player_ft_rate_pct') is not None:
                st.caption(f"Player's own FT Rate percentile (vs. comparison group): {rim_foul['player_ft_rate_pct']:.0f}th")
            if rim_foul.get('player_2pt_rate_pct') is not None:
                st.caption(f"Player's own 2PT Rate percentile: {rim_foul['player_2pt_rate_pct']:.0f}th")
            if rim_foul.get('opponent_def_ft_rate_pct') is not None:
                st.caption(f"Opponent's Def FT Rate allowed percentile (D-I-wide): {rim_foul['opponent_def_ft_rate_pct']:.0f}th")

    game_script = report.get('game_script_sensitivity') or {}
    if game_script:
        with st.expander("Game-Script Sensitivity detail"):
            if game_script.get('insufficient_sample'):
                st.caption(
                    f"Not enough games in both buckets yet to compute an index "
                    f"(close: {game_script['n_close']}, decided: {game_script['n_decided']}, need 3+ each)."
                )
            else:
                st.markdown(
                    f"Close games (±{8} margin): **{game_script['close_mean']:.1f}** {game_script['stat'].lower()}/game "
                    f"({game_script['n_close']} games) vs. decided games: **{game_script['decided_mean']:.1f}** "
                    f"({game_script['n_decided']} games) — season average {game_script['season_mean']:.1f}."
                )
                st.caption("Positive index = production leans toward close games; negative = leans toward already-decided game time.")


def _render_methodology_expander():
    with st.expander("Methodology — how every number above is computed"):
        st.markdown(
            "- **Scheme Fingerprint**: D-I percentile of the opponent's Def 2P%/Def FT Rate/paint-points-allowed "
            "(*rim pressure*) and Def 3PA Rate/Def 3P% allowed (*perimeter openness*), blended per position bucket "
            "with that bucket's own scoring delta against this team specifically.\n"
            "- **Efficiency Elasticity Curve**: a real least-squares line fit over this player's own game log — "
            "efficiency vs. opponent defensive-rating percentile and pace percentile.\n"
            "- **Composite Matchup Advantage Score**: 35% usage-weighted efficiency percentile + 30% positional "
            "vulnerability + 20% rim/foul leverage + 15% opponent pace — weights are a transparent, documented "
            "choice, not fit against historical outcomes (no such dataset exists here).\n"
            "- **Rim-Pressure & Foul-Leverage Exploitation**: player's FT Rate/2PT Rate percentiles blended with "
            "the opponent's Def FT Rate allowed percentile.\n"
            "- **Game-Script Sensitivity**: close-game vs. decided-game production split, joined to the team's own "
            "schedule margins by date.\n"
            "- **Positional Leverage**: ranks the opponent's three position-bucket vulnerability scores and reports "
            "where this player's own bucket falls.\n"
            "- **Dynamic Probability Curve**: this player's own 10th/50th/90th percentile game value this season, "
            "scaled by the Composite score and opponent pace — a transparent heuristic dial, not a fitted model.\n\n"
            "None of this uses play-by-play, shot-location, or lineup/on-off tracking data — this app doesn't have "
            "any of those sources yet (see DATA_SOURCES.md). Every score is a documented proxy built from season "
            "totals, game logs, and team-level allowed-rate stats."
        )
