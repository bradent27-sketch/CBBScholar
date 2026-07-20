"""
Raw data ingestion. Every loader returns an empty DataFrame on any failure
and never raises - callers check `.empty` and degrade gracefully, same
convention as NFL Scholar's data/loaders.py. Real cbbd-backed loaders (the
large majority of this app's eventual tabs) get built here during the
follow-up data-wiring pass once the API key from DATA_SOURCES.md is
available; this file currently holds only the one source that needs zero
setup: ESPN's public standings endpoint, which powers the shell's one live
tab (Conference Standings).

Note on Barttorvik: DATA_SOURCES.md originally treated barttorvik.com's
&csv=1 export as a no-setup free source. Live-tested before writing this
file and found it's actually gated by a JS bot-verification challenge that
a plain HTTP client (requests, or Streamlit's own server-side fetch) cannot
get past - confirmed via direct curl with a real browser User-Agent, still
blocked. It is NOT used here. See DATA_SOURCES.md for the corrected plan
(CollegeBasketballData.com's cbbd API in its place).
"""
import io

import requests
import pandas as pd
import streamlit as st

NCAA_NET_RANKINGS_URL = "https://www.ncaa.com/rankings/basketball-men/d1/ncaa-mens-basketball-net-rankings"


@st.cache_data(ttl=86400)
def fetch_net_rankings_manual():
    """
    Real NCAA NET rankings + Quad 1-4 records, scraped from ncaa.com's
    official page - the ONLY source found for this data anywhere in this
    build (checked CBBD's full API spec and ESPN's hidden API directly;
    neither has it - see net_resume.py). Verified live: the page is
    server-rendered HTML with the real table, no separate JSON API behind
    it, and `pd.read_html` parses it cleanly (365 rows: Rank, School,
    Record, Conf, Road, Neutral, Home, Non-Div I, Prev, Quad 1-4).

    NCAA.org's own terms of service prohibit automated access - this is a
    DELIBERATE, EXPLICITLY USER-AUTHORIZED exception to this app's default
    "prefer free APIs over scraping" policy (see HANDOFF.md), not a default
    this app applies anywhere else. It stays a manual action by design:
    this function is never called on tab load or on any schedule, only
    from an explicit button click in ui/tabs/net_resume.py, and the 24h
    cache means one click covers a full day rather than hitting the page
    repeatedly.
    """
    try:
        resp = requests.get(
            NCAA_NET_RANKINGS_URL,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
            timeout=15,
        )
        resp.raise_for_status()
        tables = pd.read_html(io.StringIO(resp.text))
    except Exception:
        return pd.DataFrame()
    if not tables:
        return pd.DataFrame()
    df = tables[0].rename(columns={'School': 'Team', 'Conf': 'Conference'})
    required = {'Rank', 'Team', 'Record', 'Quad 1', 'Quad 2', 'Quad 3', 'Quad 4'}
    if not required.issubset(set(df.columns)):
        return pd.DataFrame()
    return df

ESPN_CBB_STANDINGS_URL = "https://site.api.espn.com/apis/v2/sports/basketball/mens-college-basketball/standings"


def current_cbb_season():
    """
    ESPN numbers a CBB season by its SPRING (ending) year - the season that
    tips off Nov 2025 and ends in the April 2026 tournament is "season
    2026" in their scheme (confirmed live: a 2026-tagged response showed
    displayName "2025-26"). Before November, the upcoming season hasn't
    tipped off yet, so this points at the most recently COMPLETED season
    instead of an all-zero in-progress one.
    """
    import datetime
    today = datetime.date.today()
    return today.year + 1 if today.month >= 11 else today.year


@st.cache_data(ttl=3600)
def _fetch_standings_raw(season):
    """Cached raw fetch (1hr TTL) of the FULL standings response (every
    conference at once) - shared by both accessors below so picking a
    different conference in the UI doesn't refetch."""
    try:
        resp = requests.get(ESPN_CBB_STANDINGS_URL, params={'season': season}, timeout=10)
        resp.raise_for_status()
        return resp.json()
    except Exception:
        return {}


def list_conferences(season):
    """[(display_name, espn_abbreviation), ...] for whatever conferences
    ESPN's response actually contains this season - not a hardcoded list,
    so it won't silently go stale if ESPN adds/renames a conference."""
    data = _fetch_standings_raw(season)
    confs = [
        (c.get('name'), c.get('abbreviation'))
        for c in data.get('children', []) if c.get('isConference')
    ]
    return sorted(confs)


def load_conference_standings(season, espn_conference_abbr):
    """
    One conference's standings table. Field names below are exact - verified
    live against the real endpoint (`/apis/v2/...` - note this is NOT the
    same base path as the scoreboard/rankings endpoints, which live under
    `/apis/site/v2/...`; the site/v2 standings path returns an empty stub)
    before writing this parser.

    Returns an empty DataFrame if the conference isn't found or the request
    fails - never raises.
    """
    data = _fetch_standings_raw(season)
    conf = next(
        (c for c in data.get('children', []) if c.get('abbreviation') == espn_conference_abbr),
        None,
    )
    if conf is None:
        return pd.DataFrame()
    entries = (conf.get('standings') or {}).get('entries', [])
    if not entries:
        return pd.DataFrame()

    rows = []
    for e in entries:
        team = e.get('team', {})
        stats = {s.get('name'): s.get('displayValue') for s in e.get('stats', [])}
        rows.append({
            'Team': team.get('displayName', team.get('location', '--')),
            'Overall': stats.get('overall', '--'),
            'W': stats.get('wins', '--'),
            'L': stats.get('losses', '--'),
            'PCT': stats.get('winPercent', '--'),
            'Streak': stats.get('streak', '--'),
        })
    return pd.DataFrame(rows)


# ==========================================
# CollegeBasketballData.com (cbbd) - verified live with a real key before
# any of the loaders below were written; field names are exact.
# ==========================================
CBBD_BASE = "https://api.collegebasketballdata.com"


def _cbbd_headers():
    try:
        key = st.secrets.get("cbbd_api_key", "")
    except Exception:
        key = ""
    if not key:
        return None
    return {"Authorization": f"Bearer {key}"}


def _cbbd_get(path, params=None):
    headers = _cbbd_headers()
    if headers is None:
        return None
    try:
        resp = requests.get(f"{CBBD_BASE}{path}", headers=headers, params=params or {}, timeout=15)
        resp.raise_for_status()
        return resp.json()
    except Exception:
        return None


@st.cache_data(ttl=86400)
def load_teams(season=None):
    """
    Every Division I team with CBBD's own official name/colors/conference -
    verified live against /teams before writing this. Replaces the
    hand-typed ~70-team TEAM_CONFIG in config.py with the real, full D-I
    list (360+ teams) once a key is configured; falls back to an empty
    DataFrame (callers fall back to config.TEAM_CONFIG) otherwise.
    """
    season = season or current_cbb_season()
    data = _cbbd_get("/teams", params={"season": season})
    if not data:
        return pd.DataFrame()
    rows = []
    for t in data:
        color = t.get('primaryColor')
        rows.append({
            'Team': t.get('school'),
            'DisplayName': t.get('displayName'),
            'Mascot': t.get('mascot'),
            'Abbreviation': t.get('abbreviation'),
            'Conference': t.get('conference'),
            'Color': f"#{color}" if color and not str(color).startswith('#') else color,
        })
    return pd.DataFrame(rows)


def team_color_map(season=None):
    """{school_name: hex_color} for style_plain_dataframe's team_color_map
    override - live CBBD colors when a key is configured, falling back to
    the hand-typed config.TEAM_CONFIG otherwise."""
    df = load_teams(season)
    if df.empty:
        from config import TEAM_CONFIG
        return {v['name']: v['color'] for v in TEAM_CONFIG.values()}
    return dict(zip(df['Team'], df['Color']))


@st.cache_data(ttl=3600)
def load_team_roster(team, season=None):
    """
    One team's roster with bio fields, nested under a per-team wrapper
    object - verified live against /teams/roster before writing this
    (note the real path is /teams/roster, NOT /roster - that returns the
    API's Swagger docs page instead of JSON, confirmed live). Flattened to
    one row per player here so callers don't need to know about the
    wrapper shape.
    """
    season = season or current_cbb_season()
    data = _cbbd_get("/teams/roster", params={"team": team, "season": season})
    if not data:
        return pd.DataFrame()
    players = (data[0] or {}).get('players', []) if data else []
    rows = []
    for p in players:
        hometown = p.get('hometown') or {}
        rows.append({
            'id': p.get('id'),
            # ESPN-side id ("5105337") - the ONLY id shared with
            # /games/players, whose athleteId is a DIFFERENT namespace from
            # this endpoint's id (confirmed live: Caleb Foster is roster id
            # 208 but game-log athleteId 4287417, while sourceId matches
            # athleteSourceId). Game-log joins must use this, not 'id'.
            'sourceId': p.get('sourceId'),
            'name': p.get('name'),
            'jersey': p.get('jersey'),
            'position': p.get('position'),
            'height': p.get('height'),
            'weight': p.get('weight'),
            'city': hometown.get('city'),
            'state': hometown.get('state'),
            'country': hometown.get('country'),
        })
    return pd.DataFrame(rows)


@st.cache_data(ttl=3600)
def load_team_player_stats(team, season=None):
    """
    One team's full season stats, already WIDE format (one row per player,
    unlike CFBD's long/pivot-needed shape) - verified live against
    /stats/player/season before writing this. Field names below (games,
    points, fieldGoals.pct, etc.) are exact.
    """
    season = season or current_cbb_season()
    data = _cbbd_get("/stats/player/season", params={"team": team, "season": season})
    if not data:
        return pd.DataFrame()
    return pd.DataFrame(data)


def get_player_season_stats(team, season, athlete_id):
    """One player's stat row (a dict, with the nested fieldGoals/rebounds/
    winShares sub-dicts intact) from load_team_player_stats, or {} if not
    found."""
    df = load_team_player_stats(team, season)
    if df.empty:
        return {}
    match = df[df['athleteId'] == athlete_id]
    if match.empty:
        return {}
    return match.iloc[0].to_dict()


@st.cache_data(ttl=21600, show_spinner=False)
def load_conference_player_season_stats(conference, season=None):
    """
    Every player's season stats for every team in one conference, fanned
    out over the existing per-team load_team_player_stats (already cached
    individually - a team looked up elsewhere this session is a cache hit
    here too). This is the 'compare this player to their own conference'
    distribution ui.tabs.player_search uses by default: cheap enough (one
    conference is ~8-18 teams) to run automatically, unlike a full-D-I
    pull. Returns one concatenated wide DataFrame, same shape as
    load_team_player_stats.
    """
    season = season or current_cbb_season()
    teams_df = load_teams(season)
    if teams_df.empty:
        return pd.DataFrame()
    conf_teams = teams_df[teams_df['Conference'] == conference]['Team'].dropna().tolist()
    frames = [load_team_player_stats(t, season) for t in conf_teams]
    frames = [f for f in frames if not f.empty]
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


@st.cache_data(ttl=21600, show_spinner=False)
def load_all_player_season_stats(season=None):
    """
    Every D-I player's season stats in one cached pull, built the same
    fan-out way as load_conference_player_season_stats but across every
    team in load_teams() - genuinely expensive (one HTTP call per D-I team,
    360+), so this is opt-in from the UI (a "compare vs all of D-I"
    checkbox), never called automatically on every Player Search visit.
    Long TTL so the cost is paid once per cache window, not per view.
    """
    season = season or current_cbb_season()
    teams_df = load_teams(season)
    if teams_df.empty:
        return pd.DataFrame()
    all_teams = teams_df['Team'].dropna().tolist()
    progress = st.progress(0.0, text="Loading Division I player stats (first time this session)...")
    frames = []
    for i, t in enumerate(all_teams):
        df = load_team_player_stats(t, season)
        if not df.empty:
            frames.append(df)
        progress.progress((i + 1) / len(all_teams), text=f"Loading Division I player stats... ({i + 1}/{len(all_teams)} teams)")
    progress.empty()
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


@st.cache_data(ttl=3600)
def load_efficiency_ratings(season=None):
    """
    Adjusted offensive/defensive efficiency and net rating for every D-I
    team - CBBD's KenPom-equivalent. Verified live against /ratings/adjusted
    before writing this parser; field names below are exact.
    """
    season = season or current_cbb_season()
    data = _cbbd_get("/ratings/adjusted", params={"season": season})
    if not data:
        return pd.DataFrame()
    rows = []
    for t in data:
        rankings = t.get('rankings') or {}
        rows.append({
            'Rank': rankings.get('net'),
            'Team': t.get('team'),
            'Conference': t.get('conference'),
            'Net Rating': t.get('netRating'),
            'Off Rating': t.get('offensiveRating'),
            'Off Rank': rankings.get('offense'),
            'Def Rating': t.get('defensiveRating'),
            'Def Rank': rankings.get('defense'),
        })
    df = pd.DataFrame(rows)
    return df.sort_values('Rank') if not df.empty and 'Rank' in df.columns else df


@st.cache_data(ttl=3600)
def _fetch_rankings_raw(season):
    """Cached raw fetch of the FULL season's poll history (all weeks, all
    poll types) - verified live against /rankings before writing this.
    NOTE: this is AP/Coaches poll data, NOT a true NET ranking or Quad
    -record resume metric - CBBD has no such endpoint (confirmed via its
    own API spec), and neither does any other free source found during
    this build. See DATA_SOURCES.md."""
    data = _cbbd_get("/rankings", params={"season": season})
    return data or []


def list_cbb_poll_types(season):
    data = _fetch_rankings_raw(season)
    return sorted(set(r.get('pollType') for r in data if r.get('pollType')))


def load_latest_poll(season, poll_type='AP Top 25'):
    """Most recent week's rankings for one poll type. Returns
    (DataFrame, week_number) - week_number is None on failure."""
    data = _fetch_rankings_raw(season)
    rows = [r for r in data if r.get('pollType') == poll_type]
    if not rows:
        return pd.DataFrame(), None
    latest_week = max(r.get('week', 0) for r in rows)
    latest_rows = [r for r in rows if r.get('week') == latest_week]
    # r.get('ranking', 999) alone doesn't help here - .get()'s default only
    # applies when the KEY is missing, not when it's present but null
    # (confirmed live: some entries have "ranking": null explicitly), which
    # crashed this sort comparing None < int. `or 999` catches both cases.
    latest_rows.sort(key=lambda r: r.get('ranking') or 999)
    df = pd.DataFrame([{
        'Rank': r.get('ranking'),
        'Team': r.get('team'),
        'Conference': r.get('conference'),
        'Points': r.get('points'),
        '1st Place Votes': r.get('firstPlaceVotes', 0),
    } for r in latest_rows])
    return df, latest_week


@st.cache_data(ttl=3600)
def load_recruiting_rankings(season=None):
    """
    Individual recruit rankings (composite) - verified live against
    /recruiting/players before writing this. CORRECTION to this app's
    original DATA_SOURCES.md, written before this endpoint was checked
    directly: it claimed no clean free composite recruiting source exists
    for college basketball. That was wrong - CBBD has one, same as CFBD
    does for football. Fixed here and in DATA_SOURCES.md.
    """
    season = season or current_cbb_season()
    data = _cbbd_get("/recruiting/players", params={"year": season})
    if not data:
        return pd.DataFrame()
    rows = []
    for p in data:
        committed = p.get('committedTo') or {}
        rows.append({
            'Rank': p.get('ranking'),
            'Player': p.get('name'),
            'Position': p.get('position'),
            'Stars': p.get('stars'),
            'Committed To': committed.get('name') or 'Uncommitted',
            # Height/weight field names are UNVERIFIED - this sandbox's
            # network policy blocks reaching CBBD's API spec directly to
            # confirm them. Guessed from /teams/roster's confirmed 'height'
            # (inches)/'weight' (lbs) field names on the same API; degrades
            # to None -> '--' in the UI if the real field is named
            # differently or absent, same as every other .get() here.
            'Height': p.get('height'),
            'Weight': p.get('weight'),
        })
    df = pd.DataFrame(rows)
    return df.sort_values('Rank') if not df.empty else df


@st.cache_data(ttl=3600)
def load_transfer_portal(season=None):
    """Transfer portal entries - verified live against /recruiting/portal
    before writing this."""
    season = season or current_cbb_season()
    data = _cbbd_get("/recruiting/portal", params={"year": season})
    if not data:
        return pd.DataFrame()
    rows = []
    for p in data:
        origin = p.get('origin') or {}
        dest = p.get('destination') or {}
        rows.append({
            'Player': f"{p.get('firstName', '')} {p.get('lastName', '')}".strip(),
            'Position': p.get('position'),
            'From': origin.get('name') or '--',
            'To': dest.get('name') or 'Undecided',
            'Stars': p.get('stars'),
            'Eligibility': p.get('eligibility'),
            # Same unverified-field-name caveat as load_recruiting_rankings.
            'Height': p.get('height'),
            'Weight': p.get('weight'),
        })
    return pd.DataFrame(rows)


@st.cache_data(ttl=21600)
def load_all_team_season_stats(season=None):
    """
    Every D-I team's full season stat sheet in ONE call via /stats/team/season
    - verified live before writing this (700 rows for 2025; exact shape:
    pace at top level, teamStats/opponentStats sub-dicts each containing a
    fourFactors dict, a points dict with inPaint/fastBreak splits, and
    made/attempted/pct shooting splits). This single cached pull powers the
    Four Factors matchup engine and the tempo-based score projection.
    """
    season = season or current_cbb_season()
    data = _cbbd_get("/stats/team/season", params={"season": season})
    if not data:
        return pd.DataFrame()
    rows = []
    for t in data:
        ts = t.get('teamStats') or {}
        os_ = t.get('opponentStats') or {}
        tff = ts.get('fourFactors') or {}
        off_ = os_.get('fourFactors') or {}
        t_pts = ts.get('points') or {}
        o_pts = os_.get('points') or {}
        t_3p = ts.get('threePointFieldGoals') or {}
        t_fg = ts.get('fieldGoals') or {}
        total_pts = (t_pts.get('total') or 0)
        rows.append({
            'Team': t.get('team'),
            'Conference': t.get('conference'),
            'Games': t.get('games'),
            'Pace': t.get('pace'),
            'Off eFG%': tff.get('effectiveFieldGoalPct'),
            'Off TO Ratio': tff.get('turnoverRatio'),
            'Off ORB%': tff.get('offensiveReboundPct'),
            'Off FT Rate': tff.get('freeThrowRate'),
            'Def eFG%': off_.get('effectiveFieldGoalPct'),
            'Def TO Ratio': off_.get('turnoverRatio'),
            'Def ORB%': off_.get('offensiveReboundPct'),
            'Def FT Rate': off_.get('freeThrowRate'),
            '3PA Rate': (t_3p.get('attempted') / t_fg.get('attempted') * 100) if t_fg.get('attempted') else None,
            'Paint Pts %': (t_pts.get('inPaint') / total_pts * 100) if total_pts else None,
            'Fast Break %': (t_pts.get('fastBreak') / total_pts * 100) if total_pts else None,
            'Opp Paint Pts %': (o_pts.get('inPaint') / o_pts.get('total') * 100) if o_pts.get('total') else None,
        })
    return pd.DataFrame(rows)


@st.cache_data(ttl=21600)
def load_team_games(team, season=None):
    """
    One team's completed schedule/results via /games - verified live before
    writing this (39 rows for a real 2025 team; field names below exact,
    including homeTeamEloStart/End and excitement). Normalized to the
    requested team's perspective.
    """
    season = season or current_cbb_season()
    data = _cbbd_get("/games", params={"season": season, "team": team})
    if not data:
        return pd.DataFrame()
    rows = []
    for g in data:
        if g.get('status') and g.get('status') != 'final':
            continue
        is_home = g.get('homeTeam') == team
        pf = g.get('homePoints') if is_home else g.get('awayPoints')
        pa = g.get('awayPoints') if is_home else g.get('homePoints')
        if pf is None or pa is None:
            continue
        rows.append({
            'GameId': g.get('id'),
            'Date': (g.get('startDate') or '')[:10],
            'Opponent': g.get('awayTeam') if is_home else g.get('homeTeam'),
            'Home/Away': 'vs' if is_home else '@',
            'Neutral': bool(g.get('neutralSite')),
            'PF': int(pf),
            'PA': int(pa),
            'Result': 'W' if pf > pa else 'L',
            'Margin': int(pf) - int(pa),
            'Elo Start': g.get('homeTeamEloStart') if is_home else g.get('awayTeamEloStart'),
            'Elo End': g.get('homeTeamEloEnd') if is_home else g.get('awayTeamEloEnd'),
            'Excitement': g.get('excitement'),
        })
    df = pd.DataFrame(rows)
    return df.sort_values('Date').reset_index(drop=True) if not df.empty else df


@st.cache_data(ttl=21600)
def load_player_game_logs(team, season=None):
    """
    Per-game player box scores for one team's season via /games/players -
    verified live before writing this (39 games for a real 2025 team; each
    game row carries startDate/opponent/isHome context plus a players list
    with minutes/points/rebounds/assists/gameScore/usage etc.). Returns one
    row per (game, player), already joined to game context - unlike CFBD's
    equivalent, no second call is needed for opponent/date.
    """
    season = season or current_cbb_season()
    data = _cbbd_get("/games/players", params={"season": season, "team": team})
    if not data:
        return pd.DataFrame()
    rows = []
    for g in data:
        for p in g.get('players', []):
            reb = p.get('rebounds') or {}
            fg = p.get('fieldGoals') or {}
            three = p.get('threePointFieldGoals') or {}
            rows.append({
                'GameId': g.get('gameId'),
                'Date': (g.get('startDate') or '')[:10],
                'Opponent': g.get('opponent'),
                'Home/Away': 'vs' if g.get('isHome') else '@',
                'athleteId': p.get('athleteId'),
                # Joinable to load_team_roster's 'sourceId' - athleteId here
                # is NOT the roster/season-stats id namespace (see
                # load_team_roster's sourceId comment; confirmed live).
                'athleteSourceId': p.get('athleteSourceId'),
                'name': p.get('name'),
                'Minutes': p.get('minutes'),
                'Points': p.get('points'),
                'Rebounds': reb.get('total'),
                'Assists': p.get('assists'),
                'Steals': p.get('steals'),
                'Blocks': p.get('blocks'),
                'Turnovers': p.get('turnovers'),
                'FGM': fg.get('made'), 'FGA': fg.get('attempted'),
                '3PM': three.get('made'), '3PA': three.get('attempted'),
                'Game Score': p.get('gameScore'),
                'Usage': p.get('usage'),
                'Net Rating': p.get('netRating'),
            })
    df = pd.DataFrame(rows)
    return df.sort_values('Date').reset_index(drop=True) if not df.empty else df


def _odds_api_key():
    try:
        return st.secrets.get("odds_api_key", "")
    except Exception:
        return ""


@st.cache_data(ttl=900)
def fetch_ncaab_odds(markets='h2h,spreads,totals'):
    """Refresh-on-demand (15min cache + manual refresh button), same design
    as NFL Scholar's fetch_nfl_odds."""
    api_key = _odds_api_key()
    if not api_key:
        return None, "No Odds API key configured — see DATA_SOURCES.md", None
    try:
        resp = requests.get(
            'https://api.the-odds-api.com/v4/sports/basketball_ncaab/odds',
            params={'apiKey': api_key, 'regions': 'us', 'markets': markets, 'oddsFormat': 'american'},
            timeout=15,
        )
        if resp.status_code == 200:
            return resp.json(), None, resp.headers.get('x-requests-remaining')
        return None, f"API returned {resp.status_code}: {resp.text[:300]}", None
    except Exception as e:
        return None, str(e), None


@st.cache_data(ttl=900)
def fetch_ncaab_player_props(event_id, markets):
    api_key = _odds_api_key()
    if not api_key:
        return None, "No Odds API key configured — see DATA_SOURCES.md"
    try:
        resp = requests.get(
            f'https://api.the-odds-api.com/v4/sports/basketball_ncaab/events/{event_id}/odds',
            params={'apiKey': api_key, 'regions': 'us', 'markets': markets, 'oddsFormat': 'american'},
            timeout=15,
        )
        if resp.status_code == 200:
            return resp.json(), None
        return None, f"API returned {resp.status_code}: {resp.text[:300]}"
    except Exception as e:
        return None, str(e)
