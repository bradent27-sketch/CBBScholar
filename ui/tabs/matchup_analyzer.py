"""
Matchup Analyzer tab: player-vs-team-defense prep, built for individual
matchup research (props, "how does this player fare against this defense")
rather than a team-vs-team score projection. Two independent columns: PLAYER
(any player's own tendency percentiles plus a last-10-games-vs-season-average
trend, the same vocabulary Player Search uses) on the left, TEAM DEFENSE (any
one team's defensive shape vs D-I, plus the positional matchup defense
breakdown - what opposing Guards/Forwards/Centers have actually done against
that team) on the right.

Laid out as three synchronized row-pairs, not two independently-stacked
columns, per explicit request to visually align the two sides despite them
being separate Streamlit columns: Row 0 (team/player pickers, kept short on
both sides), Row 1 (tendency profile beside defensive profile), Row 2
(last-10-games trend beside positional matchup defense). Each row's two
sides render independently - a PLAYER-side failure (no roster, no stats)
doesn't block TEAM DEFENSE rendering, and vice versa - see _pick_player/
_pick_defense_team's None return and render()'s `if player_ctx`/
`if defense_team` guards. Two side-by-side st.columns() in the SAME row
call are guaranteed to start at the same height; a later row can still
start lower on the shorter side if the row above it was taller there -
"somewhat matched up," not pixel-perfect, which is what was asked for.

PLAYER prefers ESPN's own live endpoints + the ESPN-native SportsDataverse
season box file (data.loaders.get_player_season_profile - the SAME
architecture Player Search uses) over CollegeBasketballData.com, falling back
to CBBD only when ESPN's own team/roster/box-file lookups genuinely come up
empty for that player - NOT a date-freshness guess. An earlier version of
this used a DIFFERENT, CBBD-name-resolved box-file variant with a freshness
heuristic and fell back to CBBD almost constantly in practice (the box
file's ESPN-sourced team names resolve far more reliably against ESPN's own
team list than CBBD's independently-formatted one) - see HANDOFF.md. The
team/player PICKER itself still uses CBBD's /teams/roster either way (cheap,
not the quota-heavy part, and TEAM DEFENSE still needs a CBBD key for its
defensive-profile numbers regardless). TEAM DEFENSE's positional matchup
breakdown is separate and unchanged - it prefers a DIFFERENT free ESPN file
(load_positional_matchup_data, CBBD-name-resolved on purpose since it must
line up with Team Defense's CBBD-sourced opponent list) with CBBD fallback
on staleness, still a legitimate use of that pattern there.

Deliberately not team-vs-team anymore: no venue/win-probability/projected-
score/Four-Factors-matchup/style-profile/recent-form content, all of which
lived here in an earlier "Team A vs Team B" version of this tab - removed
per explicit request (player-vs-team prep matters here, not head-to-head
team projection). See HANDOFF.md for the positional-defense architecture
writeup (still unchanged) and the position-granularity caveat that couldn't
be verified live against a real payload.
"""
import pandas as pd
import streamlit as st

from config import AVAILABLE_SEASONS
from data.loaders import (
    current_cbb_season, load_all_team_season_stats, load_team_roster, load_positional_matchup_data,
    get_player_season_profile, load_player_game_logs, load_conference_player_season_stats,
    load_all_player_season_stats, load_teams, load_espn_teams, load_espn_di_player_stats,
    load_espn_season_player_box_native, load_efficiency_ratings, load_team_games,
)
from data.transforms import (
    position_bucket, positional_defense_summary, positional_defense_trend,
    player_percentile_rows, player_trend_series, team_defense_profile_rows,
    espn_player_season_stats_for_teams, last_n_form_deltas,
    positional_vulnerability_ranking, defensive_tendency_rows,
    stat_elasticity, game_script_sensitivity,
)
from data.utils import match_player_name, resolve_team_name
from ui.components import render_coming_soon
from ui.charts import render_trend_line, render_relative_bars, render_game_script_curve, render_stat_elasticity_curve
from ui.styling import df_auto_height, render_responsive_table

_PLAYER_TREND_STATS = [('Points', ''), ('Assists', ''), ('Rebounds', ''), ('Minutes', ''), ('3P%', '%')]

_PLAYER_STAT_HELP = {
    'eFG%': "Effective field goal % - field goal % with made threes counted as 1.5 makes.",
    'TS%': "True shooting % - scoring efficiency including free throws, the most complete shooting number.",
    'Net Rating': "Team point differential per 100 possessions while this player is on the floor.",
    'Usage %': "Share of the team's possessions this player uses while on the floor.",
    '3PT Rate': "Share of this player's own field goal attempts that are three-pointers.",
    '2PT Rate': "Share of this player's own field goal attempts from two-point range.",
    'FT Rate': "Free throw attempts relative to field goal attempts - how often this player gets to the line.",
    'ORB/G': "Offensive rebounds per game.",
    'DRB/G': "Defensive rebounds per game.",
}


def _safe_max_abs(series):
    m = series.abs().max()
    return float(m) if pd.notna(m) and m else 1.0


def render():
    st.markdown("<div class='custom-section-header'>MATCHUP ANALYZER</div>", unsafe_allow_html=True)

    default_season = current_cbb_season()
    seasons = AVAILABLE_SEASONS if default_season in AVAILABLE_SEASONS else [default_season] + AVAILABLE_SEASONS
    season = st.selectbox("Season", seasons, index=seasons.index(default_season), format_func=lambda y: f"{y - 1}-{str(y)[2:]}", key="ma_season")

    teams_df = load_teams(season)
    if teams_df.empty:
        render_coming_soon(
            eyebrow="NEEDS SETUP",
            blurb="No CollegeBasketballData.com API key is configured yet (or the request failed). Add cbbd_api_key to .streamlit/secrets.toml — see DATA_SOURCES.md.",
            data_sources=["CollegeBasketballData.com API"],
        )
        return

    # Row 0: pickers only (kept short on both sides so Row 1 below starts
    # at roughly the same height in both columns).
    col_player, col_defense = st.columns(2)
    with col_player:
        st.markdown("<div class='custom-section-header'>PLAYER</div>", unsafe_allow_html=True)
        player_ctx = _pick_player(season, teams_df)
    with col_defense:
        st.markdown("<div class='custom-section-header'>TEAM DEFENSE</div>", unsafe_allow_html=True)
        defense_team = _pick_defense_team(teams_df)

    # Row 1: tendency profile beside defensive profile.
    col_a, col_b = st.columns(2)
    with col_a:
        if player_ctx:
            _render_tendency_profile(season, player_ctx)
    with col_b:
        if defense_team:
            _render_defensive_profile(defense_team, season)

    # Row 2: last-10-games trend beside positional matchup defense.
    col_c, col_d = st.columns(2)
    with col_c:
        if player_ctx:
            _render_player_trend(season, player_ctx, defense_team)
    with col_d:
        if defense_team:
            _render_positional_defense(defense_team, season)


def _pick_player(season, teams_df):
    """Team + player selectors, roster load, and ESPN/CBBD stats-profile
    resolution (data.loaders.get_player_season_profile) - the shared setup
    both _render_tendency_profile and _render_player_trend need. Split out
    from a single monolithic panel specifically so PLAYER and TEAM DEFENSE
    can be interleaved into synchronized row-pairs (see render()) instead
    of each column independently stacking picker+profile+trend end to end.

    The player dropdown is CBBD's own season-scoped `/teams/roster` UNIONED
    with this season's own ESPN box-file players for the team, same fix
    Player Search already applies (see ui/tabs/player_search.py) - CBBD's
    roster endpoint IS season-aware (unlike ESPN's live-only roster
    endpoint), but can still desync from box-score reality (transfer-portal
    timing, a walk-on added mid-season, etc.), silently hiding a player
    from this dropdown despite them having real stats this tab could show.
    Box-only rows are bare pd.Series with just name/position set (no CBBD
    `id`) - get_player_season_profile resolves those via ESPN's own data
    anyway, and its CBBD-fallback path degrades gracefully to "no stats"
    rather than crashing on a missing id (see get_player_season_stats).

    Returns a context dict, or None (after showing its own st.info message)
    if no team/roster/stats data is available - a None here doesn't stop
    TEAM DEFENSE's own rows from rendering; each row checks its own side
    independently.
    """
    team_names = sorted(teams_df['Team'].dropna().unique().tolist())
    if not team_names:
        st.info("No team data available.")
        return None
    default_team = 'Duke' if 'Duke' in team_names else team_names[0]
    team_choice = st.selectbox("Team", team_names, index=team_names.index(default_team), key="ma_player_team")

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
    sel_label = st.selectbox("Player", labels, key="ma_player_select")
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


def _pick_defense_team(teams_df):
    team_names = sorted(teams_df['Team'].dropna().unique().tolist())
    if not team_names:
        st.info("No team data available.")
        return None
    default_team = 'Duke' if 'Duke' in team_names else team_names[0]
    return st.selectbox("Team", team_names, index=team_names.index(default_team), key="ma_def_team")


def _render_tendency_profile(season, ctx):
    sel_row, stats = ctx['sel_row'], ctx['stats']
    include_net_rating, source, box_df, conf = ctx['include_net_rating'], ctx['source'], ctx['box_df'], ctx['conf']

    compare_all = st.checkbox(
        "Compare against all of Division I instead of just this conference"
        + ("" if source == 'espn' else " (cached ~weekly)"),
        key="ma_player_compare_all",
        help="Free either way when the ESPN box file is in use — same already-downloaded season file, no per-team fan-out." if source == 'espn' else None,
    )
    if source == 'espn':
        # box_df is the SAME already-downloaded file get_player_season_profile
        # used for `stats` above. Conference is looked up from ESPN's OWN
        # team list for stats['Team'] (the box file's own spelling), NOT
        # from `conf` (CBBD's spelling for team_choice) - those two
        # sources don't always agree on conference-name formatting, and
        # filtering ESPN's team list by a CBBD-spelled conference string
        # was silently coming back empty for some players (no comparison
        # bars at all - only the D-I checkbox worked, since that path
        # never needs a conference match) - a real, reported bug. The
        # D-I case is cached (load_espn_di_player_stats) since the full
        # groupby was slow enough to cause a noticeable pause on every
        # player switch, not just first load.
        if compare_all:
            group_df = load_espn_di_player_stats(season)
            group_label = "D-I"
        else:
            espn_teams_season = load_espn_teams(season)
            espn_conf_row = espn_teams_season.loc[espn_teams_season['Team'] == stats['Team'], 'Conference']
            espn_conf = espn_conf_row.iloc[0] if not espn_conf_row.empty else None
            if espn_conf:
                espn_conf_teams = espn_teams_season.loc[espn_teams_season['Conference'] == espn_conf, 'Team'].tolist()
                group_df = espn_player_season_stats_for_teams(box_df, teams=espn_conf_teams)
                group_label = espn_conf
            else:
                group_df = pd.DataFrame()
                group_label = "conference"
    elif compare_all:
        with st.spinner("Loading Division I player stats..."):
            group_df = load_all_player_season_stats(season)
        group_label = "D-I"
    elif conf:
        with st.spinner(f"Loading {conf} player stats..."):
            group_df = load_conference_player_season_stats(conf, season)
        group_label = conf
    else:
        group_df = pd.DataFrame()
        group_label = "conference"

    st.markdown(f"**{sel_row['name']} — tendency profile**")
    rows = player_percentile_rows(stats, group_df, _PLAYER_STAT_HELP, include_net_rating=include_net_rating)
    render_relative_bars(rows)
    if not group_df.empty:
        st.caption(f"vs. {group_label}")
    else:
        st.caption("No comparison group available.")
    st.caption("Source: free ESPN/SportsDataverse box file." if source == 'espn' else "Source: CollegeBasketballData.com.")


def _render_player_trend(season, ctx, defense_team=None):
    team_choice, sel_row, stats, source, box_df, athlete_source_id = (
        ctx['team_choice'], ctx['sel_row'], ctx['stats'], ctx['source'], ctx['box_df'], ctx['athlete_source_id']
    )
    st.markdown(f"**{sel_row['name']} — last 10 games vs season average**")
    if source == 'espn':
        # Same box_df, no second download - this is the per-game rows
        # get_player_season_profile's season totals were themselves summed
        # from, so season stats and this trend can never disagree about
        # which games happened, unlike sourcing them from two different
        # endpoints the way the CBBD branch below does. stats['Team']/
        # athlete_source_id are the box file's OWN values (see
        # get_player_season_profile's docstring) - self-consistent with
        # box_df, unlike sel_row's CBBD-sourced id.
        mine = box_df[
            (box_df['Team'] == stats['Team']) & (box_df['athleteSourceId'].astype(str) == str(athlete_source_id))
        ].copy()
    else:
        with st.spinner("Loading game log..."):
            logs = load_player_game_logs(team_choice, season)
        mine = logs[logs['athleteSourceId'].astype(str) == str(sel_row.get('sourceId'))] if not logs.empty else logs
        if mine.empty and not logs.empty:
            mine = logs[logs['name'] == sel_row['name']]
    if mine.empty:
        st.info("No per-game data for this player yet this season.")
        return
    mine = mine.sort_values('Date').reset_index(drop=True)
    # 3P% isn't a column load_player_game_logs returns directly (it has
    # 3PM/3PA, makes and attempts, not a precomputed percentage) - derived
    # here per game. `.where(attempts > 0)` (same divide-by-zero guard
    # data.transforms.player_rate_stats already uses for 3PT/2PT/FT rate)
    # turns a 0-attempt game into NaN instead of a raw ZeroDivisionError/inf,
    # which player_trend_series already drops via its own dropna(subset=[col]).
    if {'3PM', '3PA'}.issubset(mine.columns):
        attempts = pd.to_numeric(mine['3PA'], errors='coerce')
        makes = pd.to_numeric(mine['3PM'], errors='coerce')
        mine['3P%'] = (makes / attempts.where(attempts > 0)) * 100

    for stat, suffix in _PLAYER_TREND_STATS:
        if stat not in mine.columns:
            continue
        dates, values, avg = player_trend_series(mine, stat, n=10)
        st.markdown(f"_{stat} — last {len(values)} games_")
        if len(values) >= 2:
            # Corner badges: last-10/5/3-game average vs the player's own
            # season average (the SAME `avg` already driving the dashed
            # reference line and per-dot coloring below) - green when the
            # recent window is running above season average, red when
            # below, matching this chart's own existing per-dot rule.
            corner_stats = [
                (label, f"{avg_n:.1f}{suffix}", is_above)
                for label, avg_n, is_above in last_n_form_deltas(values, avg)
            ]
            render_trend_line(
                dates, values, avg=avg, avg_label='season avg', y_suffix=suffix, height=150,
                corner_stats=corner_stats,
            )
        else:
            st.caption("Not enough games yet for a trend.")

    # One "Stat" picker drives BOTH charts below (elasticity curve AND
    # game-script curve) - these used to be two independently-controlled
    # sections (elasticity had its own Points/Rebounds/Assists dropdown;
    # game-script was hardcoded to Points with no picker at all), merged
    # into one shared control on request since there's no reason to make
    # a viewer pick the same stat twice, or leave one chart unable to show
    # Rebounds/Assists at all. data.transforms.game_script_sensitivity
    # already took a `stat_col` param before this change (only its CALLER
    # here hardcoded 'Points') - stat_elasticity is the one that actually
    # needed a real signature change (see its own CORRECTION note).
    stat_col = st.selectbox(
        "Stat", _ELASTICITY_STAT_OPTIONS, key="ma_elasticity_stat",
        help="Which per-game stat drives both charts below.",
    )
    if defense_team:
        _render_stat_elasticity_chart(mine, defense_team, season, stat_col)
    _render_game_script_curve(mine, team_choice, season, stat_col)


_ELASTICITY_STAT_OPTIONS = ('Points', 'Rebounds', 'Assists')


def _render_stat_elasticity_chart(mine, defense_team, season, stat_col):
    """
    <Stat> Elasticity Curve (data.transforms.stat_elasticity) - how this
    player's own per-game production in the chosen stat (the SAME picker
    _render_player_trend's caller also feeds to _render_game_script_curve
    below - see that call site) actually moves against tougher/faster
    opponents this season, fit from their real game log. Replaced the old
    fixed TS%/eFG% "efficiency" framing on request (a raw counting stat is
    more directly useful for matchup/prop prep than a shooting-efficiency
    abstraction; see data.transforms.stat_elasticity's own CORRECTION
    note). Rendered as a real chart (ui.charts.render_stat_elasticity_curve)
    - the tier-mean curve plus tonight's specific opponent highlighted on
    it - positioned right after the per-stat game-log trend charts above
    and before the Game-Script curve below. Uses `mine` (this panel's own
    already-loaded per-game log, same rows the trend charts above just
    rendered) so no extra game-log fetch is needed - only team_stats_df/
    eff_ratings_df (both already weekly-cached league-wide pulls shared
    with the rest of this tab) get loaded here.
    """
    team_stats_df = load_all_team_season_stats(season)
    eff_ratings_df = load_efficiency_ratings(season)
    result = stat_elasticity(mine, eff_ratings_df, team_stats_df, defense_team, stat_col=stat_col)
    if not result or len(result.get('bucket_means') or {}) < 2:
        return
    st.markdown(f"_{result['efficiency_label']} vs. opponent defensive strength — {result['n_games']} games_")
    render_stat_elasticity_curve(result, opponent_team=defense_team)


def _render_game_script_curve(mine, team_choice, season, stat_col):
    """
    Game-Script Sensitivity (data.transforms.game_script_sensitivity) -
    Close (|margin| <= 8) / Comfortable (8-14) / Blowout (>14) production
    for the chosen stat (same picker as the Elasticity chart above - see
    _render_player_trend's call site; game_script_sensitivity itself
    already took a `stat_col` param, only this function's own hardcoded
    'Points' call kept every other stat off it), shown as a small curve
    rather than plain text, per explicit request. `mine` is this panel's
    own already-loaded per-game log; only the player's team schedule (for
    game margins) needs a fresh load here.
    """
    with st.spinner(f"Loading {team_choice}'s schedule..."):
        team_games = load_team_games(team_choice, season)
    result = game_script_sensitivity(mine, team_games, stat_col=stat_col)
    if not result or len(result.get('tiers') or []) < 2:
        return
    st.markdown(f"_{result['stat']} by game script — Close (±8) / Comfortable (8–14) / Blowout (>14)_")
    render_game_script_curve(result)


def _position_map_for_matchup(matchup_df, season):
    """{athleteSourceId(str): position_bucket} for every opposing player in
    `matchup_df` (data.loaders.load_positional_matchup_data output).

    Prefers the 'Position' column directly on `matchup_df` when present -
    the ESPN/SportsDataverse source (see data.loaders.load_positional_
    matchup_data) carries athlete_position_name on every row, so no extra
    lookup is needed at all for those rows: zero CBBD roster calls. Only
    rows without a usable Position (the CBBD-fallback path, which doesn't
    carry position) fall back to pulling that opponent's roster - already
    independently cached per-team, so this reuses whatever's already been
    fetched elsewhere this session/week rather than adding new API
    surface."""
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


_POS_VULN_BUCKETS = ('Guard', 'Forward', 'Center')


def _positional_vulnerability_rows(team, season):
    """
    Positional Vulnerability Ranking (data.transforms.
    positional_vulnerability_ranking), shaped for appending onto the
    BOTTOM of _render_defensive_profile's own bar list, right below the
    rest of the team's defensive shape - which of this team's Guard/
    Forward/Center buckets is actually worth targeting, ranked most-
    exploitable first. Deliberately not gated on picking a player/position
    first - real positions are often fluid (a listed guard who also plays
    some forward, etc.), so this shows all three buckets and lets the
    viewer apply their own judgment about which one actually matches
    whoever they're scouting.

    Reads the SAME "games to include" slider and load-trigger session_state
    keys _render_positional_defense's own widgets set (key='ma_pos_defense_
    window', trigger_key built the identical way) - safe to read here even
    though those widgets are declared LATER in render()'s Row 2 (this
    function runs as part of Row 1): Streamlit syncs every widget's current
    value into st.session_state BEFORE the script body runs at all on any
    given rerun, so a keyed widget's value is already available from
    session_state regardless of where in the script it's actually
    instantiated. _render_positional_defense's button handler calls
    st.rerun() immediately after setting the trigger flag specifically so
    this picks up the fresh state on the SAME click, not one interaction
    later.

    Before that button has ever been clicked (for the current games-cap
    value), returns three grey/placeholder rows (pct=None -
    ui.charts.render_relative_bars draws an empty track with no colored
    fill for a None pct, which is exactly the "grey/transparent before
    loading" look with no special styling needed). After it's been
    clicked, fetches the SAME positional matchup data _render_positional_
    defense itself fetches - a cache hit against load_positional_matchup_
    data's own already-`@st.cache_data`-decorated inner calls, so this
    costs no extra CBBD/ESPN fetch, just a second cheap local DataFrame
    pass - and returns the real ranking rows, relabeled "<Bucket>
    Vulnerability" so they read clearly sitting among the other stat rows.
    """
    recent_games_cap = st.session_state.get('ma_pos_defense_window', 20)
    trigger_key = f"ma_pos_defense_loaded_{season}_{team}_{recent_games_cap}"
    if not st.session_state.get(trigger_key, False):
        return [
            {
                'label': f'{bucket} Vulnerability', 'pct': None, 'value_str': 'Not loaded',
                'help': f'Click "Load positional matchup defense" below (up to {recent_games_cap} most recent games) to populate this.',
            }
            for bucket in _POS_VULN_BUCKETS
        ]
    matchup_df = load_positional_matchup_data(team, season, max_recent_games=recent_games_cap)
    if matchup_df.empty:
        return []
    pos_map = _position_map_for_matchup(matchup_df, season)
    summary = positional_defense_summary(matchup_df, pos_map)
    return [{**row, 'label': f"{row['label']} Vulnerability"} for row in positional_vulnerability_ranking(summary)]


def _render_defensive_profile(team, season):
    team_stats = load_all_team_season_stats(season)
    if team_stats.empty:
        st.info("Team defense profile needs /stats/team/season data, which isn't available right now.")
        return

    # Pace renders as the FIRST row inside profile_rows below (data.
    # transforms.team_defense_profile_rows/_TEAM_DEFENSE_METRICS) - a
    # percentile bar inline with the rest of the defensive stats, not a
    # separate st.metric, per explicit request: a bare number doesn't show
    # whether that pace is fast or slow relative to D-I the way a bar does.
    # Rim Pressure/Perimeter Openness Allowed (data.transforms.
    # defensive_tendency_rows) append onto the SAME bar list - these are
    # team-wide tendency reads, not position-specific (see that function's
    # docstring for why an earlier per-position version of this was
    # reworked). The Positional Vulnerability Ranking (_positional_
    # vulnerability_rows) appends onto the BOTTOM of this same chart too,
    # per explicit request - grey/placeholder rows until Positional
    # Matchup Defense below is actually loaded, real ranking after.
    profile_rows = (
        team_defense_profile_rows(team_stats, team)
        + defensive_tendency_rows(team_stats, team)
        + _positional_vulnerability_rows(team, season)
    )
    if profile_rows:
        st.markdown(f"**{team} — defensive profile (vs D-I)**")
        render_relative_bars(profile_rows)
    else:
        st.info(f"No defensive profile available for {team} yet.")


def _render_positional_defense(team, season):
    st.markdown(f"**{team} — positional matchup defense**")
    recent_games_cap = st.slider(
        "Games to include (most recent)", min_value=5, max_value=30, value=20, step=5,
        key="ma_pos_defense_window",
        help="Lower = fewer CBBD calls (only matters on the fallback) and a more current read; higher = more complete.",
    )
    trigger_key = f"ma_pos_defense_loaded_{season}_{team}_{recent_games_cap}"
    if not st.session_state.get(trigger_key, False):
        if st.button("Load positional matchup defense", key="ma_load_pos_defense"):
            st.session_state[trigger_key] = True
            # Immediate rerun (rather than just letting this script pass
            # continue) so _render_defensive_profile - which renders BEFORE
            # this function in render()'s Row 1/Row 2 order - picks up the
            # freshly-set trigger flag on this same click, instead of
            # needing a second, unrelated interaction to "catch up" (see
            # _positional_vulnerability_rows' docstring for the full
            # session_state-timing explanation).
            st.rerun()
        st.info(f"Click above to pull it — free where possible, up to ~{recent_games_cap} CBBD calls otherwise.")
        return

    with st.spinner(f"Loading {team}'s opponent game logs..."):
        matchup_df = load_positional_matchup_data(team, season, max_recent_games=recent_games_cap)
    if matchup_df.empty:
        st.info(f"No opponent game log data available for {team} yet.")
        return
    # load_positional_matchup_data carries a real Position value on every
    # row when the free ESPN file was used, and sets it to None on every
    # row for the CBBD fallback (see that function's docstring) - the
    # cheapest reliable signal for which source this particular click
    # actually used, without needing a second return value threaded
    # through the whole call chain.
    used_espn = 'Position' in matchup_df.columns and matchup_df['Position'].notna().any()
    st.caption("Source: free ESPN season file." if used_espn else "Source: CollegeBasketballData.com (CBBD API calls used).")
    pos_map = _position_map_for_matchup(matchup_df, season)
    summary = positional_defense_summary(matchup_df, pos_map)
    if summary.empty:
        st.info(
            f"No position-bucketed data for {team} yet — either not enough opponent games loaded, or the "
            "roster position field didn't match a recognized Guard/Forward/Center pattern (see HANDOFF.md)."
        )
        return
    display = summary.set_index('Bucket')
    render_responsive_table(
        f"positional_defense_{team}", display, primary_col=None,
        diverging_cols={
            'Points Delta': _safe_max_abs(display['Points Delta']),
            'Rebounds Delta': _safe_max_abs(display['Rebounds Delta']),
            'Assists Delta': _safe_max_abs(display['Assists Delta']),
        },
        height=df_auto_height(len(display)),
    )

    # Position-group picker + all three stats for whichever bucket is
    # selected, rather than every bucket's Points-only trend stacked at
    # once (3 buckets x 3 stats = 9 charts was too long a page) - Rebounds/
    # Assists trend data was already available from load_positional_
    # matchup_data (positional_defense_trend takes any stat column present
    # on matchup_df), it just wasn't wired into the UI before. Key
    # incorporates team/season/games-cap so switching teams can't leave a
    # stale bucket selection that isn't in the new options list.
    bucket_options = summary['Bucket'].tolist()
    selected_bucket = st.selectbox(
        "Position group", bucket_options, key=f"ma_pos_defense_bucket_{team}_{season}_{recent_games_cap}",
    )
    for stat in ('Points', 'Rebounds', 'Assists'):
        dates, values = positional_defense_trend(matchup_df, pos_map, selected_bucket, stat)
        st.markdown(f"_{selected_bucket}s — {stat.lower()} allowed, over time_")
        if len(values) >= 2:
            # Same corner-badge treatment as the PLAYER trend charts above -
            # last-10/5/3-game average vs this chart's own baseline (the
            # mean of however many games are actually loaded here, capped
            # by the "games to include" slider above - there's no broader
            # "season" figure available beyond that window for this CBBD/
            # ESPN-fallback data source, same baseline the dashed reference
            # line already uses). Green = recent average running above that
            # baseline, red = below - flat rule, not "fewer points allowed
            # is better" - matching this chart's own existing per-dot rule.
            baseline = sum(values) / len(values)
            corner_stats = [
                (label, f"{avg_n:.1f}", is_above)
                for label, avg_n, is_above in last_n_form_deltas(values, baseline)
            ]
            render_trend_line(dates, values, avg=baseline, avg_label='avg', height=150, corner_stats=corner_stats)
        else:
            st.caption("Not enough games yet for a trend.")
