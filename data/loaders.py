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


# ==========================================
# Live connection diagnostics - every loader above swallows its own
# exception and returns None/empty on ANY failure (missing key, bad key,
# rate limit, timeout, network block - all indistinguishable from the
# tab's "or the request failed" message). These functions make one real,
# uncached request each and report exactly what happened, so a deployed
# instance can self-diagnose instead of guessing. Never called on tab
# load - only from the sidebar's "Test live connections" button.
# ==========================================

def test_cbbd_connection():
    """One real (uncached) hit against /teams with today's season. Returns
    {'ok', 'detail'} - 'detail' is the actual status code/exception, not a
    generic message, specifically so a 401 (bad/rotated key) reads
    differently from a timeout/connection error (network block on the
    hosting side, e.g. Streamlit Community Cloud's shared egress IPs being
    rate-limited or blocked by the upstream) or a 429 (rate limit)."""
    key = ""
    try:
        key = st.secrets.get("cbbd_api_key", "")
    except Exception:
        pass
    if not key:
        return {'ok': False, 'detail': "No cbbd_api_key in st.secrets."}
    try:
        resp = requests.get(
            f"{CBBD_BASE}/teams", headers={"Authorization": f"Bearer {key}"},
            params={"season": current_cbb_season()}, timeout=15,
        )
    except requests.exceptions.Timeout:
        return {'ok': False, 'detail': "Timed out reaching api.collegebasketballdata.com — likely a network/firewall issue on the hosting side, not the key."}
    except requests.exceptions.ConnectionError as e:
        return {'ok': False, 'detail': f"Connection failed (DNS/network block, not the key): {e}"}
    except Exception as e:
        return {'ok': False, 'detail': f"Unexpected error: {e}"}
    if resp.status_code == 401:
        return {'ok': False, 'detail': "401 Unauthorized — the key itself is invalid, expired, or was rejected. Not a network problem."}
    if resp.status_code == 429:
        return {'ok': False, 'detail': "429 Too Many Requests — free-tier rate limit hit. Wait and retry, not a bad key."}
    if resp.status_code != 200:
        return {'ok': False, 'detail': f"HTTP {resp.status_code}: {resp.text[:200]}"}
    try:
        n = len(resp.json())
    except Exception:
        return {'ok': False, 'detail': f"HTTP 200 but response wasn't valid JSON: {resp.text[:200]}"}
    return {'ok': True, 'detail': f"HTTP 200 — {n} teams returned."}


def test_odds_connection():
    """Same idea as test_cbbd_connection for the-odds-api.com."""
    key = ""
    try:
        key = st.secrets.get("odds_api_key", "")
    except Exception:
        pass
    if not key:
        return {'ok': False, 'detail': "No odds_api_key in st.secrets."}
    try:
        resp = requests.get(
            'https://api.the-odds-api.com/v4/sports/basketball_ncaab/odds',
            params={'apiKey': key, 'regions': 'us', 'markets': 'h2h'}, timeout=15,
        )
    except requests.exceptions.Timeout:
        return {'ok': False, 'detail': "Timed out reaching api.the-odds-api.com — likely a network/firewall issue on the hosting side, not the key."}
    except requests.exceptions.ConnectionError as e:
        return {'ok': False, 'detail': f"Connection failed (DNS/network block, not the key): {e}"}
    except Exception as e:
        return {'ok': False, 'detail': f"Unexpected error: {e}"}
    if resp.status_code == 401:
        return {'ok': False, 'detail': "401 Unauthorized — the key itself is invalid or expired."}
    if resp.status_code == 429:
        return {'ok': False, 'detail': "429 — monthly free-tier credits exhausted (shared with CFB Scholar if same account)."}
    if resp.status_code != 200:
        return {'ok': False, 'detail': f"HTTP {resp.status_code}: {resp.text[:200]}"}
    remaining = resp.headers.get('x-requests-remaining', '?')
    return {'ok': True, 'detail': f"HTTP 200 — {remaining} credits remaining this month."}


def test_ncaa_net_connection():
    """Same idea for the ncaa.com NET-rankings scrape - a totally separate,
    keyless data source. If this ALSO fails alongside CBBD, that's a
    strong signal the problem is outbound network access from the hosting
    environment in general (or that ncaa.com is specifically blocking that
    host's IP - Cloudflare-protected sites often rate-limit/block shared
    hosting IP ranges like Streamlit Community Cloud's), not anything about
    the CBBD key."""
    try:
        resp = requests.get(
            NCAA_NET_RANKINGS_URL,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
            timeout=15,
        )
    except requests.exceptions.Timeout:
        return {'ok': False, 'detail': "Timed out reaching ncaa.com."}
    except requests.exceptions.ConnectionError as e:
        return {'ok': False, 'detail': f"Connection failed: {e}"}
    except Exception as e:
        return {'ok': False, 'detail': f"Unexpected error: {e}"}
    if resp.status_code != 200:
        return {'ok': False, 'detail': f"HTTP {resp.status_code} — ncaa.com may be blocking this host's IP (common for shared hosting ranges)."}
    try:
        tables = pd.read_html(io.StringIO(resp.text))
    except Exception as e:
        return {'ok': False, 'detail': f"HTTP 200 but couldn't parse a table out of the page (layout may have changed): {e}"}
    if not tables:
        return {'ok': False, 'detail': "HTTP 200 but no HTML tables found on the page."}
    return {'ok': True, 'detail': f"HTTP 200 — parsed a table with {len(tables[0])} rows."}


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
def _load_team_player_stats_uncached(team, season):
    """The actual single-team /stats/player/season call - split out from
    load_team_player_stats below so the league-wide cache check in that
    function doesn't recurse into itself."""
    data = _cbbd_get("/stats/player/season", params={"team": team, "season": season})
    if not data:
        return pd.DataFrame()
    return pd.DataFrame(data)


def load_team_player_stats(team, season=None):
    """
    One team's full season stats, already WIDE format (one row per player,
    unlike CFBD's long/pivot-needed shape) - verified live against
    /stats/player/season before writing this. Field names below (games,
    points, fieldGoals.pct, etc.) are exact.

    Checks the league-wide cache (get_league_player_stats) FIRST and
    filters from it if available - zero extra API cost, and automatically
    cuts load_defense_allowed_by_role's per-opponent cost once a league
    database has been built (see build_league_player_database), since that
    function's season-stats call for each opponent becomes a free filter
    instead of a fresh request. Falls back to the original single-team
    call when no league data is cached (the common case until a league
    database is explicitly built - see ui/tabs/team_efficiency.py).
    """
    season = season or current_cbb_season()
    league = get_league_player_stats(season)
    if not league.empty and 'team' in league.columns:
        subset = league[league['team'] == team]
        if not subset.empty:
            return subset.reset_index(drop=True)
    return _load_team_player_stats_uncached(team, season)


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


# ==========================================
# League-wide player stats - what real (not fixed-threshold) player role
# percentiles and a cheaper defense-by-role pull both need. See
# data/transforms.py's league_rate_profiles/classify_player_role_percentile
# and ui/tabs/team_efficiency.py's "Build League Player Database" button.
# ==========================================

@st.cache_data(ttl=21600)
def load_all_player_season_stats(season=None):
    """
    Attempts the SAME no-team-filter call load_all_team_season_stats makes
    against /stats/team/season, but against /stats/player/season instead -
    if CBBD's player endpoint supports omitting `team` the same way its
    team endpoint does, this is one cheap cached call for every D-I
    player's season, exactly mirroring the team-level bulk pull.

    UNCONFIRMED - this dev environment has no live network access to CBBD
    to verify whether the player endpoint actually supports this (see
    HANDOFF's verification note). If it doesn't, CBBD returns an
    empty/error response and this function returns an empty DataFrame,
    same "never raises" contract as every other loader here - callers
    (get_league_player_stats) transparently fall back to
    build_league_player_database's per-team fan-out. Costs nothing to
    attempt either way (one cached call), so this always runs first.
    """
    season = season or current_cbb_season()
    data = _cbbd_get("/stats/player/season", params={"season": season})
    if not data:
        return pd.DataFrame()
    df = pd.DataFrame(data)
    # A real league-wide response should span many teams - a single-team
    # response (the endpoint silently defaulting to something narrow
    # instead of erroring) would be worse than no data at all here, since
    # league_rate_profiles would build "percentiles" off one roster.
    if 'team' not in df.columns or df['team'].nunique() < 30:
        return pd.DataFrame()
    return df


def build_league_player_database(season=None, _progress_callback=None):
    """
    Manual fallback if load_all_player_season_stats's bulk call isn't
    supported: fans out /stats/player/season across every D-I team from
    load_teams (~360 calls as of this writing - confirm the real count via
    len(load_teams(season)) before running this on a live instance).
    NEVER call this automatically - see ui/tabs/team_efficiency.py's
    "Build League Player Database" button, same expensive-pull/user-gated
    pattern as the NCAA NET manual scrape and load_defense_allowed_by_role.

    `_progress_callback(done, total)`, if given, is called after every
    team so the caller can drive a progress bar - the leading underscore
    is Streamlit's own convention for "exclude this param from the cache
    key," not just a style choice (a real callable can't be hashed for
    caching anyway). Returns a combined DataFrame (one row per player,
    every team) or empty if no team's pull succeeded. Stores nothing
    itself - the caller (ui/tabs/team_efficiency.py) is responsible for
    putting the result in st.session_state so it survives reruns without
    re-fetching (get_league_player_stats reads it from there).
    """
    season = season or current_cbb_season()
    teams_df = load_teams(season)
    teams = sorted(teams_df['Team'].dropna().unique().tolist()) if not teams_df.empty else []
    frames = []
    for i, team in enumerate(teams):
        df = _load_team_player_stats_uncached(team, season)
        if not df.empty:
            if 'team' not in df.columns:
                df = df.assign(team=team)
            frames.append(df)
        if _progress_callback:
            _progress_callback(i + 1, len(teams))
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def get_league_player_stats(season=None):
    """
    Single accessor every caller should use for "all D-I players' season
    stats" - tries the free bulk call first (load_all_player_season_stats),
    then whatever's been manually built this session via
    build_league_player_database (stored in st.session_state by
    ui/tabs/team_efficiency.py's button), and returns an empty DataFrame
    (never raises) if neither is available. Callers should fall back
    further to fixed-threshold role classification
    (data.transforms.classify_player_role) rather than block on this -
    league-wide data is an upgrade, not a requirement, for every feature
    that uses it.
    """
    season = season or current_cbb_season()
    bulk = load_all_player_season_stats(season)
    if not bulk.empty:
        return bulk
    try:
        return st.session_state.get(f'_league_player_db_{season}', pd.DataFrame())
    except Exception:
        return pd.DataFrame()


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
        # Opponent-side shooting splits - same nesting as the offensive side
        # above, mirrored under opponentStats (confirmed: opponentStats
        # carries the identical sub-dict shape as teamStats throughout this
        # payload, e.g. fourFactors/points already relied on that symmetry).
        # Powers "3PA Rate/3P% allowed" for the defensive matchup profile -
        # same cached call as everything else here, zero extra API cost.
        o_3p = os_.get('threePointFieldGoals') or {}
        o_fg = os_.get('fieldGoals') or {}
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
            'Def 3PA Rate': (o_3p.get('attempted') / o_fg.get('attempted') * 100) if o_fg.get('attempted') else None,
            # pct fields from CBBD are already 0-100 (same convention as
            # Off/Def eFG% above, which are used unscaled elsewhere in this
            # file) - no extra *100 here, unlike the *_Rate fields which are
            # ratios this loader computes itself from raw attempted counts.
            'Def 3P%': o_3p.get('pct'),
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


@st.cache_data(ttl=21600)
def load_defense_allowed_by_role(team, season=None):
    """
    Cross-references every opponent on `team`'s schedule to find out what
    its defense allows by opposing-player ROLE (Ball-Handler/Post Player/
    Shooter/Wing-Combo, see data.transforms.classify_player_role) - a stat
    no single CBBD endpoint provides, since "defense vs. role" isn't
    published anywhere free for CBB (checked directly: CBBD's spec has no
    shot-location or play-type breakdown; the closest things, /lineups and
    /plays, are possession/shot-clock logs, not role-tagged defensive
    splits - see HANDOFF §7).

    Built entirely from three loaders this app already has (zero new
    endpoints): for every opponent on `team`'s schedule (load_team_games),
    pulls that OPPONENT's own roster (load_team_roster, for the id<->
    sourceId bridge - see load_team_roster's docstring on why the season-
    stats id namespace and the game-log id namespace don't match), their
    season stats (load_team_player_stats, to compute each of THEIR
    players' role from their OWN season-long tendency - not from what they
    did against `team`, which would be circular), and their game log
    (load_player_game_logs, filtered to just the game(s) they played
    against `team`). That's "what did this specific opposing player, who
    IS a Ball-Handler on his own team all season, produce against `team`'s
    defense specifically" - repeated across the whole schedule.

    This is the heaviest pull in the app - up to 3 extra API calls per
    opponent (roster + season stats + game log), so up to ~60-90 calls for
    a full ~20-30 game schedule IF no league player database has been
    built yet. Once one has (see get_league_player_stats/
    build_league_player_database, triggered from Team Efficiency), the
    season-stats call drops out entirely - load_team_player_stats below
    serves it from the cached league table instead - cutting this to ~2
    calls/opponent (roster + game log), roughly a third less. Every
    underlying loader is independently cached and shared with Player
    Search/Compare/Matchup Analyzer, so opponents already viewed elsewhere
    this session are free either way; this function itself is also cached.
    NEVER call this on tab load - only from an explicit "Analyze Defense"
    button click (see ui/tabs/matchup_analyzer.py), same expensive-pull/
    user-gated pattern as the NCAA NET manual scrape.

    Returns a DataFrame with one row per (game, opposing player who could
    be role-classified): Date, Opponent, OpposingPlayer, Role, Points,
    Rebounds, Assists, ThreesMade - or empty if the schedule can't be
    resolved. A given opponent is silently skipped (not an error) if any
    of its three pulls comes back empty, same "never raises" contract as
    every other loader here.
    """
    from data.transforms import player_rate_profile, classify_player_role_best_available, league_rate_profiles

    season = season or current_cbb_season()
    games = load_team_games(team, season)
    if games.empty:
        return pd.DataFrame()
    opponents = sorted(games['Opponent'].dropna().unique().tolist())

    # Computed once, not per-opponent - if a league player database has
    # been built (see ui/tabs/team_efficiency.py), every opponent's players
    # get REAL percentile role classification instead of the fixed-
    # threshold fallback, at no extra cost (same cached league table
    # load_team_player_stats below is already drawing from).
    league_rates = league_rate_profiles(get_league_player_stats(season))

    rows = []
    for opp in opponents:
        roster = load_team_roster(opp, season)
        season_stats = load_team_player_stats(opp, season)
        if roster.empty or season_stats.empty:
            continue
        merged = season_stats.merge(
            roster[['id', 'sourceId', 'name']], left_on='athleteId', right_on='id', how='inner',
        )
        if merged.empty:
            continue
        role_by_source_id = {}
        for _, p in merged.iterrows():
            profile = player_rate_profile(p.to_dict())
            primary, _, _ = classify_player_role_best_available(profile, league_rates)
            if primary and pd.notna(p.get('sourceId')):
                role_by_source_id[p['sourceId']] = (primary, p.get('name'))
        if not role_by_source_id:
            continue

        opp_logs = load_player_game_logs(opp, season)
        if opp_logs.empty:
            continue
        vs_team = opp_logs[opp_logs['Opponent'] == team]
        if vs_team.empty:
            continue
        for _, g in vs_team.iterrows():
            role_info = role_by_source_id.get(g.get('athleteSourceId'))
            if not role_info:
                continue
            role, player_name = role_info
            rows.append({
                'Date': g.get('Date'),
                'Opponent': opp,
                'OpposingPlayer': player_name or g.get('name'),
                'Role': role,
                'Points': g.get('Points') or 0,
                'Rebounds': g.get('Rebounds') or 0,
                'Assists': g.get('Assists') or 0,
                'ThreesMade': g.get('3PM') or 0,
            })
    return pd.DataFrame(rows)


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
