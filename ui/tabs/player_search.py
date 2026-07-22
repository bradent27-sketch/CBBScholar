"""
Player Search tab: flagship player lookup - bio and season stats, live via
ESPN's public endpoints + SportsDataverse's free published season box-score
file - NOT CollegeBasketballData.com. This tab is the one deliberate CBBD-
free pipeline in the app (Compare and Matchup Analyzer's PLAYER panel still
use CBBD - see HANDOFF.md for that scope decision), built on request to cut
reliance on CBBD's 1,000-call/month free tier for the tab that gets used
most. Team-first UX by default (pick a team, then a player), same reasoning
as before (no global name-search endpoint), but an "All Teams" option on
the team picker plus a fuzzy-matched search box let a player be found by
name alone.

Data sourcing, end to end:
- data.loaders.load_espn_teams: team list + colors + conference, reused
  from the SAME standings payload Conference Standings already fetches.
- data.loaders.load_espn_roster: one team's roster (bio fields) - a live
  ESPN call, no key required.
- data.loaders.load_espn_season_player_box_native: the WHOLE season's
  game-by-game box scores for every D-I player, one file (twice-weekly
  cached, manual "Refresh league-wide data" override in the sidebar) -
  this is BOTH the season-stats source (totals are just this same data
  summed - see data.transforms.espn_player_season_stats_for_teams) AND
  the game log source, unlike CBBD's two-separate-endpoints design.

Net Rating is dropped entirely here (not just blank) - deprioritized on
request, and genuinely not buildable from box scores alone (needs lineup-
level play-by-play tracking - see player_profile_values' include_net_rating
flag). Usage% IS built locally from box-score aggregates - CBBD hands it
over precomputed, this pipeline computes it via the standard formula (see
espn_player_season_stats_for_teams' docstring).

None of the new ESPN team-list/roster endpoints or the extra SportsDataverse
box-file columns (free throws, rebound split) are live-verified in this
sandbox (network-blocked, same standing caveat as every other ESPN/
SportsDataverse touchpoint in this app - see HANDOFF.md) - confirm against
a real payload once deployed before fully trusting Usage%/FT%/ORB-DRB
specifically; everything degrades to '--'/empty rather than a wrong number
if a guessed field name turns out to not exist (see the has_ft/has_reb_split
checks in espn_player_season_stats_for_teams).

**Real bug, live-confirmed after deploy**: load_espn_roster's 'sourceId'
(ESPN roster endpoint's own athlete id) and the box file's
'athleteSourceId' turned out to be DIFFERENT id namespaces, despite the
original assumption they were the same - every id-based join between them
matched nothing, for every player. This produced two distinct symptoms:
team-filtered mode showed "No game data found" for every player on every
team/season (the roster-picked player's id never matched anything in the
box file's stats), while All Teams mode's stats worked fine (it reads
name/id straight from the box file, bypassing the broken join entirely)
but bio fields (height/weight/hometown) came back blank (the reverse
lookup into the roster, by the same broken id, also matched nothing).
Fixed by joining on NAME instead (data.utils.match_player_name) in both
directions - see the bio_idx/stats_idx lookups below. Also fixed:
data.loaders._resolve_espn_box_team_names now drops DNP rows (0/missing
Minutes) - these were getting counted as "games played"
(espn_player_season_stats_for_teams' `games = len(g)`), which silently
deflated the season average of any player who missed real time (confirmed
against a real player: PPG showing ~44% below his actual number, matching
a games-count inflated by his missed games almost exactly).

**Real bug, live-confirmed after deploy**: a real current Duke player
(Cameron Boozer) was missing entirely from the team-filtered player
dropdown despite having real season stats. Root cause: load_espn_roster's
URL has no season parameter at all - it always reflects TODAY's live
roster, not `season`'s - so a player who left the program (draft,
transfer, graduation) since `season` drops off this list completely, even
for a season they demonstrably played. Fixed by unioning the live roster
with this season's own box-file players for the selected team (see the
roster_rows/box_only/combined_rows logic below) - a departed player now
shows up via the box file even when the live roster endpoint no longer
lists them.
"""
import pandas as pd
import streamlit as st

from config import AVAILABLE_SEASONS
from data.loaders import (
    current_cbb_season, load_espn_teams, load_espn_roster, load_espn_season_player_box_native,
    load_espn_di_player_stats,
)
from data.transforms import last_n_form, player_percentile_rows, espn_player_season_stats_for_teams, espn_player_result_map
from data.utils import fuzzy_filter_names, match_player_name
from ui.components import render_coming_soon, render_team_banner, render_bio_strip, render_metric_tiles
from ui.charts import render_relative_bars
from ui.styling import render_sticky_footer_table

_STAT_HELP = {
    'eFG%': "Effective field goal % - field goal % with made threes counted as 1.5 makes.",
    'TS%': "True shooting % - scoring efficiency including free throws, the most complete shooting number.",
    'Usage %': "Share of the team's possessions this player uses while on the floor - computed locally from box-score totals (this pipeline's source doesn't hand it over precomputed the way CBBD does).",
    '3PT Rate': "Share of this player's own field goal attempts that are three-pointers - a high number means a volume three-point shooter, independent of playing time.",
    '2PT Rate': "Share of this player's own field goal attempts from two-point range.",
    'FT Rate': "Free throw attempts relative to field goal attempts - how often this player gets to the line.",
}

_ALL_TEAMS_OPTION = "All Teams (search any player)"


def _fmt_height(inches):
    try:
        inches = int(inches)
        return f"{inches // 12}' {inches % 12}\""
    except (TypeError, ValueError):
        return '--'


def _display_height(row):
    disp = row.get('displayHeight') if hasattr(row, 'get') else None
    return disp or _fmt_height(row.get('height'))


def _pct(v):
    return f"{v:.1f}%" if isinstance(v, (int, float)) else '--'


def _per_game(total, games):
    try:
        return f"{float(total) / float(games):.1f}"
    except (TypeError, ValueError, ZeroDivisionError):
        return '--'


def render():
    st.markdown("<div class='custom-section-header'>PLAYER SEARCH</div>", unsafe_allow_html=True)

    default_season = current_cbb_season()
    seasons = AVAILABLE_SEASONS if default_season in AVAILABLE_SEASONS else [default_season] + AVAILABLE_SEASONS
    c1, c2 = st.columns([1, 2])
    with c1:
        season = st.selectbox("Season", seasons, index=seasons.index(default_season), format_func=lambda y: f"{y - 1}-{str(y)[2:]}", key="ps_season")

    espn_teams = load_espn_teams(season)
    if espn_teams.empty:
        render_coming_soon(
            eyebrow="TEMPORARILY UNAVAILABLE",
            blurb="Couldn't reach ESPN's public endpoints just now (no API key needed here - this is a live network call, not a setup gap). Try reloading in a moment.",
            data_sources=["ESPN public endpoints", "SportsDataverse season box-score file"],
        )
        return

    with c2:
        team_names = sorted(espn_teams['Team'].dropna().unique().tolist())
        team_options = [_ALL_TEAMS_OPTION] + team_names
        default_team = next((t for t in team_names if t.startswith('Duke')), team_names[0] if team_names else None)
        default_team_idx = team_options.index(default_team) if default_team in team_options else 0
        team_choice = st.selectbox("Team", team_options, index=default_team_idx, key="ps_team")

    all_teams_mode = team_choice == _ALL_TEAMS_OPTION
    colors = dict(zip(espn_teams['Team'], espn_teams['Color']))

    with st.spinner("Loading season box scores (ESPN/SportsDataverse — cached, refreshes twice weekly)..."):
        box_df = load_espn_season_player_box_native(season)
    if box_df.empty:
        st.info(
            f"No season box-score data available for {season} yet — this source is a bulk file published a few "
            "times a week, so it can lag early in a brand-new season."
        )
        return

    if all_teams_mode:
        candidates = box_df[['name', 'athleteSourceId', 'Team', 'Position']].drop_duplicates(subset=['athleteSourceId', 'Team']).reset_index(drop=True)
        labels = [f"{r['name']} ({r['Position'] or '?'}) — {r['Team']}" for _, r in candidates.iterrows()]
        query = st.text_input(
            "Search player name", key="ps_player_query",
            placeholder="Start typing any player's name — partial or slightly misspelled is fine",
        )
        if not query:
            st.info(
                "Type a player's name above to search across all of Division I. Covers players who've appeared "
                "in at least one game this season (this source is game-by-game box scores, not a full roster list)."
            )
            return
        matched_labels = fuzzy_filter_names(query, labels, limit=25)
        if not matched_labels:
            st.info("No players matched that spelling — try a shorter or different fragment.")
            return
        sel_label = st.selectbox("Select player", matched_labels, key="ps_player_select")
        sel_candidate = candidates.iloc[labels.index(sel_label)]
        team = sel_candidate['Team']
        source_id = sel_candidate['athleteSourceId']
        player_name = sel_candidate['name']

        espn_row = espn_teams[espn_teams['Team'] == team].iloc[0]
        with st.spinner("Loading bio..."):
            roster_df = load_espn_roster(espn_row['EspnId'], season)
        # Matched by NAME, not id - ESPN's roster endpoint's own athlete id
        # and the box file's athleteSourceId are different id namespaces in
        # practice (confirmed: this join matched nothing for any player),
        # despite the original assumption they were the same. See
        # data.utils.match_player_name's docstring and HANDOFF.md.
        bio_idx = match_player_name(player_name, roster_df['name']) if not roster_df.empty else None
        bio = roster_df.iloc[bio_idx] if bio_idx is not None else pd.Series({'position': sel_candidate['Position']})
    else:
        team = team_choice
        espn_row = espn_teams[espn_teams['Team'] == team].iloc[0]
        with st.spinner("Loading roster..."):
            roster_df = load_espn_roster(espn_row['EspnId'], season)
        # ESPN's roster endpoint has no season parameter at all (see
        # load_espn_roster's docstring) - it always reflects TODAY's
        # actual roster, not `season`'s. A player who left the program
        # since then (drafted, transferred, graduated) drops off this
        # list entirely, even for a season they demonstrably played (real
        # box-score rows exist for them in box_df) - a real, reported bug
        # (a real player was missing from his own team's dropdown despite
        # having played that season). Union the live roster with this
        # season's own box-file players for this team so a departed
        # player still shows up - same box_df already loaded above for
        # stats, no extra fetch. Extra (box-only) rows are bare
        # pd.Series with just name/position set - deliberately NOT merged
        # into one wide DataFrame (which would force pandas to coerce
        # missing numeric fields like height/weight to NaN, and this
        # file's `bio.get(...) or '--'`-style checks below treat NaN as
        # truthy, silently rendering "nan" instead of falling back) - the
        # same safe pattern All Teams mode's own fallback already uses.
        roster_rows = [roster_df.iloc[i] for i in range(len(roster_df))]
        box_team_players = box_df[box_df['Team'] == team][['name', 'Position']].drop_duplicates(subset=['name'])
        box_only = box_team_players[
            box_team_players['name'].apply(lambda n: match_player_name(n, roster_df['name']) is None)
        ] if roster_rows else box_team_players
        extra_rows = [pd.Series({'name': r['name'], 'position': r['Position']}) for _, r in box_only.iterrows()]
        combined_rows = roster_rows + extra_rows
        if not combined_rows:
            st.info(f"No roster or season data found for {team} in {season}.")
            return
        labels = [f"{r['name']} ({r.get('position') or '?'})" for r in combined_rows]
        query = st.text_input(
            "Filter roster (optional)", key="ps_player_query_team",
            placeholder="Start typing to narrow the roster below…",
        )
        matched_labels = fuzzy_filter_names(query, labels, limit=len(labels)) if query else labels
        sel_label = st.selectbox("Select player", matched_labels, key="ps_player_select")
        bio = combined_rows[labels.index(sel_label)]
        source_id = bio.get('sourceId')
        player_name = bio['name']

    render_team_banner(team, subtitle=f"{bio.get('position') or '?'} #{bio.get('jersey') or '?'}", team_color=colors.get(team))

    hometown = f"{bio.get('city', '')}, {bio.get('state', '')}".strip(', ') if bio.get('city') else '--'
    render_bio_strip([
        ('Height', _display_height(bio)),
        ('Weight', f"{bio.get('weight')} lbs" if bio.get('weight') else '--'),
        ('Hometown', hometown or '--'),
    ])

    st.markdown(f"<div class='custom-section-header'>{season - 1}-{str(season)[2:]} SEASON STATS</div>", unsafe_allow_html=True)

    team_stats_df = espn_player_season_stats_for_teams(box_df, team)
    # Matched by NAME, not id - same reason as the bio lookup above (team-
    # filtered mode's `source_id` came from ESPN's roster endpoint, a
    # different id namespace from the box file's athleteSourceId in
    # practice). All-Teams mode's `source_id` already comes from box_df
    # itself, so this is a no-op re-derivation there, not a behavior change.
    stats_idx = match_player_name(player_name, team_stats_df['name']) if not team_stats_df.empty else None
    if stats_idx is None:
        st.info(f"No {season} game data found for this player yet.")
        return
    stats = team_stats_df.iloc[stats_idx].to_dict()
    source_id = stats['athleteSourceId']
    games = stats.get('games') or 0

    player_conf = espn_row.get('Conference')

    compare_all = st.checkbox(
        "Compare against all of Division I instead of just this conference",
        key="ps_compare_all",
        help="Free either way with this source — the whole season's already in one downloaded file, no per-team fan-out needed.",
    )
    if compare_all:
        group_df = load_espn_di_player_stats(season)
        group_label = "D-I"
    elif player_conf:
        conf_teams = espn_teams.loc[espn_teams['Conference'] == player_conf, 'Team'].tolist()
        group_df = espn_player_season_stats_for_teams(box_df, teams=conf_teams)
        group_label = player_conf
    else:
        group_df = pd.DataFrame()
        group_label = "conference"

    rows = player_percentile_rows(stats, group_df, _STAT_HELP, include_net_rating=False)

    render_relative_bars(rows)
    if not group_df.empty:
        st.caption(f"vs. {group_label} · {games} games played.")
    else:
        st.caption(f"No comparison group available. {games} games played.")

    _render_game_log_section(box_df, team, source_id, colors)


_GAME_LOG_COLS = ['Date', 'Result', 'Home/Away', 'Opponent', 'Minutes', 'Points', 'Rebounds', 'Assists',
                  'Steals', 'Blocks', 'Turnovers', 'FGM', 'FGA', '3PM', '3PA']
_GAME_LOG_NON_NUMERIC = ('Date', 'Result', 'Home/Away', 'Opponent')


def _render_game_log_section(box_df, team, source_id, colors):
    """Full game log table (every completed game this source has a box
    score for) with a season-averages row rendered as a real, pinned
    FOOTER of the same table (ui.styling.render_sticky_footer_table). Plus
    a last-5-vs-season form readout, colored green when recent form beats
    the season average and red when it's below. Opponent cells tint with
    that team's color, Result (W/L) tints green/red.

    No Usage/Net Rating columns here (unlike the CBBD-based version this
    replaced) - this source doesn't carry a PER-GAME usage/net-rating
    figure the way CBBD's /games/players response does; season-total
    Usage% is still shown above in the season stats bars."""
    st.markdown("<div class='custom-section-header'>GAME LOG</div>", unsafe_allow_html=True)
    mine = box_df[(box_df['Team'] == team) & (box_df['athleteSourceId'].astype(str) == str(source_id))].copy()
    mine = mine.sort_values('Date').reset_index(drop=True)
    if mine.empty:
        st.info("No per-game data for this player yet this season.")
        return

    result_map = espn_player_result_map(box_df, team)
    mine['Result'] = mine['GameId'].map(result_map)

    # Last-5 form vs season average - season average listed first/primary,
    # last-5 called out below it, colored green when last 5 is ahead of
    # the season average and red when it's behind.
    form = last_n_form(mine)
    if form:
        st.markdown("**Season average — last 5 games below**")
        entries = []
        for stat, (recent, season_avg) in form.items():
            delta = recent - season_avg
            better = None if abs(delta) < 1e-9 else delta > 0
            entries.append({
                'label': stat,
                'value_str': f"{season_avg:.1f}",
                'delta_str': f"last 5: {recent:.1f} ({delta:+.1f})",
                'better': better,
            })
        render_metric_tiles(entries)

    table_cols = [c for c in _GAME_LOG_COLS if c in mine.columns]
    numeric_cols = [c for c in table_cols if c not in _GAME_LOG_NON_NUMERIC]
    avg_row = {c: round(float(pd.to_numeric(mine[c], errors='coerce').mean()), 1) for c in numeric_cols}
    for c in _GAME_LOG_NON_NUMERIC:
        if c in table_cols:
            avg_row[c] = ''
    if 'Opponent' in table_cols:
        avg_row['Opponent'] = f"SEASON AVG ({len(mine)} games)"

    render_sticky_footer_table(
        mine[table_cols], avg_row, numeric_cols=numeric_cols, team_color_map=colors,
        opponent_col='Opponent', win_loss_col='Result', height=360,
    )
