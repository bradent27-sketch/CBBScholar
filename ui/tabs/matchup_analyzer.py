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
    season_slate,
)
from data.transforms import (
    position_bucket, positional_defense_summary, positional_defense_trend,
    player_percentile_rows, player_trend_series, team_defense_profile_rows,
    espn_player_season_stats_for_teams, last_n_form_deltas,
    positional_vulnerability_ranking, defensive_tendency_rows,
    stat_elasticity, game_script_sensitivity, game_link_rows, game_link_rows_for_dates,
)
from data.utils import match_player_name, resolve_team_name
from ui.components import (
    render_coming_soon, sticky_selectbox, sticky_slider, sticky_checkbox,
    render_trend_with_point_links,
)
from ui.charts import render_trend_line, render_relative_bars, render_game_script_curve, render_stat_elasticity_curve
from ui.styling import df_auto_height, render_responsive_table

_PLAYER_TREND_STATS = [('Points', ''), ('Assists', ''), ('Rebounds', ''), ('Minutes', ''), ('3P%', '%')]

# "Games shown" window for the player trend charts below - how many of a
# player's most recent games each chart's line/badges cover. None means "no
# cap" (the whole season); player_trend_series's own `.tail(n)` handles a
# real int fine, so a very large sentinel does the "Full season" case
# without needing a second code path.
_TREND_WINDOW_OPTIONS = ["Last 5", "Last 10", "Last 15", "Last 20", "Full season"]
_TREND_WINDOW_N = {"Last 5": 5, "Last 10": 10, "Last 15": 15, "Last 20": 20, "Full season": None}

_TEAM_PLACEHOLDER = "Select a team..."

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
    season = sticky_selectbox(
        "Season", seasons, key="ma_season", default_index=seasons.index(default_season),
        format_func=lambda y: f"{y - 1}-{str(y)[2:]}",
    )

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

    # No chip strips here: the trend charts' own DATA POINTS are clickable
    # (see render_trend_with_point_links), which is the direct gesture -
    # clicking the dot for the game you're looking at. A strip underneath
    # would be a second, redundant control for the same games.


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
    if no team/roster/stats data is available, OR if no team has been
    picked yet - a None here doesn't stop TEAM DEFENSE's own rows from
    rendering; each row checks its own side independently.
    """
    team_names = sorted(teams_df['Team'].dropna().unique().tolist())
    if not team_names:
        st.info("No team data available.")
        return None
    # Defaults to the placeholder (index 0), not a specific team - this
    # used to default to Duke, so scouting anyone else meant clicking off
    # Duke first even though this whole panel is about PICKING a player,
    # not confirming a pre-made choice. Short-circuits below (same as the
    # "no team data" case just above) until a real team is chosen.
    team_options = [_TEAM_PLACEHOLDER] + team_names
    team_choice = sticky_selectbox("Team", team_options, key="ma_player_team", default_index=0)
    if team_choice == _TEAM_PLACEHOLDER:
        st.info("Pick a team above to scout one of its players.")
        return None

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
    sel_label = sticky_selectbox("Player", labels, key="ma_player_select")
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
    return sticky_selectbox("Team", team_names, key="ma_def_team", default_index=team_names.index(default_team))


def _render_tendency_profile(season, ctx):
    sel_row, stats = ctx['sel_row'], ctx['stats']
    include_net_rating, source, box_df, conf = ctx['include_net_rating'], ctx['source'], ctx['box_df'], ctx['conf']

    compare_all = sticky_checkbox(
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
    """Charts the player's recent-games trend for each stat, with every DATA
    POINT clickable - a dot opens that game's full box score in the Game
    Slate (see ui.components.render_trend_with_point_links). Clicking the
    dot for the game you're already looking at is the direct gesture; a
    chip strip underneath would be a second control for the same games.

    "Games shown" picks the window (5/10/15/20 most recent, or the whole
    season) every chart below covers - a real control now, not just the
    invisible `ma-align-controls` filler this slot used to hold. It still
    does that filler's old job as a side effect: landing in the same spot
    keeps this column roughly level with TEAM DEFENSE's own games/position
    control row (_render_positional_defense), so it's rendered
    unconditionally rather than only `if defense_team`.
    """
    team_choice, sel_row, stats, source, box_df, athlete_source_id = (
        ctx['team_choice'], ctx['sel_row'], ctx['stats'], ctx['source'], ctx['box_df'], ctx['athlete_source_id']
    )
    st.markdown(f"**{sel_row['name']} — trend vs season average**")
    window_choice = sticky_selectbox(
        "Games shown", _TREND_WINDOW_OPTIONS, key="ma_trend_window", default_index=1,
        help="How many of this player's most recent games each chart below covers.",
    )
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
        return []
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

    # Resolved once for the whole panel and indexed BY DATE, because each
    # stat's series drops its own NaN games (a 0-attempt game has no 3P%),
    # so the charts below don't all plot the same set of games.
    all_links = game_link_rows(
        mine, season_slate(season), team=stats.get('Team') or team_choice,
    )
    link_by_date = {e['date']: e for e in all_links}

    trend_n = _TREND_WINDOW_N[window_choice] or len(mine)
    for stat, suffix in _PLAYER_TREND_STATS:
        if stat not in mine.columns:
            continue
        dates, values, avg = player_trend_series(mine, stat, n=trend_n)
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
            # Invisible hit strips are laid over the dots inside this
            # helper - click a point, get that game's box score.
            render_trend_with_point_links(
                lambda: render_trend_line(
                    dates, values, avg=avg, avg_label='season avg', y_suffix=suffix,
                    height=150, corner_stats=corner_stats,
                ),
                [link_by_date.get(str(d)) for d in dates], season,
                key_suffix=f"plr_{stat.replace('%', 'pct')}", chart_height=150,
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
    stat_col = sticky_selectbox(
        "Stat", _ELASTICITY_STAT_OPTIONS, key="ma_elasticity_stat",
        help="Which per-game stat drives both charts below.",
    )
    if defense_team:
        _render_stat_elasticity_chart(mine, defense_team, season, stat_col)
    _render_game_script_curve(mine, team_choice, season, stat_col)

    # Resolve the charted games back to the box score each point came from.
    # The ESPN branch's `mine` carries real ESPN game ids; the CBBD
    # branch's ids are a DIFFERENT namespace entirely, so game_link_rows
    # falls back to matching on date + team rather than mis-linking on a
    # coincidental id collision (see its docstring).



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
    Blowout Loss (>14) / Comfortable Loss (8-14) / Close (+/-8) /
    Comfortable Win (8-14) / Blowout Win (>14) production for the chosen
    stat (same picker as the Elasticity chart above - see
    _render_player_trend's call site; game_script_sensitivity itself
    already took a `stat_col` param, only this function's own hardcoded
    'Points' call kept every other stat off it), shown as a small curve
    rather than plain text, per explicit request. Split win/loss apart per
    a later request too - the tiers used to bucket on |margin| alone, so a
    comfortable win and a comfortable loss landed in the same
    "Comfortable" tier together (see game_script_sensitivity's own
    CORRECTION note). `mine` is this panel's own already-loaded per-game
    log; only the player's team schedule (for game margins) needs a fresh
    load here.
    """
    with st.spinner(f"Loading {team_choice}'s schedule..."):
        team_games = load_team_games(team_choice, season)
    result = game_script_sensitivity(mine, team_games, stat_col=stat_col)
    if not result or len(result.get('tiers') or []) < 2:
        return
    st.markdown(
        f"_{result['stat']} by game script — Blowout Loss (>14) / Comfortable Loss (8–14) / "
        f"Close (±8) / Comfortable Win (8–14) / Blowout Win (>14)_"
    )
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
    # The PLAYER column opens Row 1 with a "Compare against all of Division
    # I" checkbox that this column has no equivalent of, so without this the
    # defensive profile's bars sit a checkbox-height ABOVE the tendency
    # profile's and the two panels read as unrelated - measured at 52px of
    # skew. st.columns only guarantees both sides start level; anything
    # extra on one side pushes only that side down. The spacer's height is
    # Streamlit's real checkbox block height (see .ma-align-checkbox in
    # ui.styling), which puts the two profiles' headers on the same line.
    st.markdown("<div class='ma-align-checkbox'></div>", unsafe_allow_html=True)

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
    """
    ORDER HERE IS THE POINT, and it mirrors the PLAYER column beside it:
    header, then the three stat trends, then the extra analysis - so each
    "allowed over time" chart sits level with the player's own last-10 chart
    for the SAME stat, and the two columns read as three matched pairs
    rather than two unrelated stacks.

    Two things were in the way and both moved:
      * the summary table used to render BEFORE the trends, pushing them
        421px (measured) below the player charts they pair with. It now
        renders after them - it summarizes those same three stats, so it
        reads as a wrap-up rather than a preamble.
      * the two controls sat on their own stacked rows. They share one row
        now, which is the one nested-column level Streamlit allows and this
        function has left unspent (render_trend_with_point_links needs it
        for the hit strips, but that's a sibling, not a parent).

    The stat ORDER also matches the player column's (Points, Assists,
    Rebounds - see _PLAYER_TREND_STATS) instead of the Points/Rebounds/
    Assists it used before. Same three charts, reordered so each one is
    beside its own counterpart; lining them up is the whole request.
    """
    st.markdown(f"**{team} — positional matchup defense**")
    # ONE control row for both pickers, opened here and filled from two
    # different points in this function: the games slider has to exist
    # before the load gate below (its value is part of the gate's key),
    # while the position picker's options don't exist until the data has
    # loaded. Streamlit lets a column context be re-entered later in the
    # script, which is what keeps them on the same line instead of costing
    # two stacked rows above the charts.
    ctl_games, ctl_bucket = st.columns(2)
    with ctl_games:
        recent_games_cap = sticky_slider(
            "Games to include (most recent)", key="ma_pos_defense_window", default_value=20,
            min_value=5, max_value=30, step=5,
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
        return []

    with st.spinner(f"Loading {team}'s opponent game logs..."):
        matchup_df = load_positional_matchup_data(team, season, max_recent_games=recent_games_cap)
    if matchup_df.empty:
        st.info(f"No opponent game log data available for {team} yet.")
        return []
    # load_positional_matchup_data carries a real Position value on every
    # row when the free ESPN file was used, and sets it to None on every
    # row for the CBBD fallback (see that function's docstring) - the
    # cheapest reliable signal for which source this particular click
    # actually used, without needing a second return value threaded
    # through the whole call chain.
    used_espn = 'Position' in matchup_df.columns and matchup_df['Position'].notna().any()
    pos_map = _position_map_for_matchup(matchup_df, season)
    summary = positional_defense_summary(matchup_df, pos_map)
    if summary.empty:
        st.info(
            f"No position-bucketed data for {team} yet — either not enough opponent games loaded, or the "
            "roster position field didn't match a recognized Guard/Forward/Center pattern (see HANDOFF.md)."
        )
        return []

    # Position-group picker + all three stats for whichever bucket is
    # selected, rather than every bucket's Points-only trend stacked at
    # once (3 buckets x 3 stats = 9 charts was too long a page) - Rebounds/
    # Assists trend data was already available from load_positional_
    # matchup_data (positional_defense_trend takes any stat column present
    # on matchup_df), it just wasn't wired into the UI before. Key
    # incorporates team/season/games-cap so switching teams can't leave a
    # stale bucket selection that isn't in the new options list.
    bucket_options = summary['Bucket'].tolist()
    with ctl_bucket:
        selected_bucket = sticky_selectbox(
            "Position group", bucket_options, key=f"ma_pos_defense_bucket_{team}_{season}_{recent_games_cap}",
        )
    defense_links = game_link_rows_for_dates(
        sorted(matchup_df['Date'].dropna().unique()), season_slate(season), team,
    )
    defense_link_by_date = {e['date']: e for e in defense_links}

    # Points, Assists, Rebounds - the PLAYER column's own order (see
    # _PLAYER_TREND_STATS), not the Points/Rebounds/Assists this used
    # before, so each chart lands beside the player's chart for the same
    # stat rather than one stat off.
    for stat in ('Points', 'Assists', 'Rebounds'):
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
            render_trend_with_point_links(
                lambda: render_trend_line(
                    dates, values, avg=baseline, avg_label='avg', height=150,
                    corner_stats=corner_stats,
                ),
                [defense_link_by_date.get(str(d)) for d in dates], season,
                key_suffix=f"def_{stat}", chart_height=150,
            )
        else:
            st.caption("Not enough games yet for a trend.")

    # The wrap-up: the same three stats the charts above just walked
    # through, as one per-position table. It used to render BEFORE them,
    # which pushed every chart 421px (measured) below the player chart it
    # pairs with - the reported misalignment. Reading it after the trends
    # also matches what it is: a summary of what was just shown.
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
    # Sits with the table rather than above the charts, where it was one
    # more line separating them from the player charts they line up with.
    st.caption("Source: free ESPN season file." if used_espn else "Source: CollegeBasketballData.com (CBBD API calls used).")

    # This series is aggregated BY GAME DATE (positional_defense_trend
    # groups opposing players by date), so a date is genuinely all it has
    # to identify a game with - hence the by-date resolver rather than the
    # id-first one. A date alone matches ~150 games in college basketball,
    # which is why it's always scoped to this team.
