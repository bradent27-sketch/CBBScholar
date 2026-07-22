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
import datetime
import io

import requests
import pandas as pd
import streamlit as st

from data.utils import resolve_team_name, match_player_name
# One deliberate exception to this file's "raw ingestion only" layering
# (see this module's docstring and HANDOFF.md's Architecture section,
# which frames data/transforms.py as pure compute over already-loaded
# data.loaders output, never the reverse): get_player_season_profile below
# reuses espn_player_season_stats_for_teams so the ESPN-sourced path
# computes Usage%/eFG%/TS% exactly the way Player Search already does,
# rather than a second, independently-driftable copy of that logic living
# here instead - see get_player_season_profile's docstring.
from data.transforms import espn_player_season_stats_for_teams

NCAA_NET_RANKINGS_URL = "https://www.ncaa.com/rankings/basketball-men/d1/ncaa-mens-basketball-net-rankings"


def _week_bucket():
    """
    ISO (year, week) string, e.g. '2026-W04' - threaded as a hidden extra
    argument into every weekly, disk-persisted league-wide loader below.

    Necessary because `st.cache_data(ttl=..., persist="disk")` SILENTLY
    IGNORES `ttl` - confirmed directly in Streamlit's own source
    (streamlit.runtime.caching.storage.local_disk_cache_storage: "The
    cached function '%s' has a TTL that will be ignored. Persistent cached
    functions currently don't support TTL."), not just a docs gap. Without
    this, a `persist="disk"` cache never expires on its own - it would
    have kept serving the SAME snapshot forever until someone clicked the
    manual "Refresh league-wide data" button, contrary to every "cached
    ~weekly" claim made about these loaders. Including this bucket as an
    actual (cache-key-hashed) argument makes each entry naturally
    superseded once a week without needing an active TTL at all - the
    standard workaround for this exact Streamlit limitation. Old weeks'
    entries are superseded, not deleted; harmless disk usage at this app's
    scale, not worth adding cleanup for.
    """
    year, week, _ = datetime.date.today().isocalendar()
    return f"{year}-W{week:02d}"


def _twice_weekly_bucket():
    """
    ISO (year, week, half) string, e.g. '2026-W04-A' - same mechanism as
    `_week_bucket()` (a real, hashed cache-key argument, since `ttl=` is
    silently ignored on a `persist="disk"` cache - see that function's
    docstring) but splits each ISO week into two halves (Monday-Wednesday
    = 'A', Thursday-Sunday = 'B'), giving a fresh cache key roughly every
    3-4 days instead of every 7. This is the refresh cadence requested
    specifically for the ESPN/SportsDataverse season box-score file (Player
    Search's CBBD-free pipeline) - a plain file re-download costs nothing
    extra either way (no CBBD-style monthly quota is at stake here), so
    there's no cost reason to keep it weekly once asked for something
    fresher.
    """
    year, week, weekday = datetime.date.today().isocalendar()
    half = 'A' if weekday <= 3 else 'B'
    return f"{year}-W{week:02d}-{half}"


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
# ESPN-native player pipeline (Player Search's CBBD-free path) - team list
# + roster, both live ESPN calls, no key required. Paired with the ESPN/
# SportsDataverse season box file further below (load_espn_season_player_
# box_native) for season stats/game logs - together these replace CBBD
# entirely for Player Search specifically (Compare and Matchup Analyzer's
# player panel are UNCHANGED, still CBBD-based, by explicit scope decision -
# see HANDOFF.md).
# ==========================================

@st.cache_data(ttl=86400)
def load_espn_teams(season=None):
    """
    Full D-I team list (name, ESPN id, conference, colors) - built from the
    SAME standings payload Conference Standings already fetches
    (_fetch_standings_raw), NOT a separate/unverified /teams endpoint.
    ESPN's team object shape is consistent across their API (id/location/
    color/alternateColor show up on every embedded team dict, not just in
    the standings response this app already trusts is live/working) -
    reusing that payload avoids guessing at a brand new endpoint for
    something this app already has a working call for. This is the
    canonical team reference for Player Search's CBBD-free pipeline -
    mirrors the role load_teams() plays for the CBBD-based path elsewhere.

    'Team' uses ESPN's `location` field (short school name, e.g. "Duke"),
    NOT `displayName` ("Duke Blue Devils") - confirmed via a real
    downloaded SportsDataverse box-score file that its own team_location/
    opponent_team_location columns are ALSO short-name format, and
    data.utils.normalize_team_name has no mechanism to bridge "Duke" to
    "Duke Blue Devils" (it strips punctuation/case and " university"-style
    suffixes, not mascot names) - this was a REAL bug, confirmed live: it
    made data.loaders._resolve_espn_box_team_names fail to resolve ANY row
    against a displayName-keyed canonical list, silently returning an
    empty DataFrame for a real, successfully-downloaded box file (see
    HANDOFF.md for the full diagnosis). `DisplayName` is kept as a second
    column (nicer for on-screen labels later) but must never be the join
    key against the box file. Falls back to `displayName` for `Team` only
    if `location` is somehow missing, better than dropping the team.

    id/color/alternateColor fields on the standings' embedded team object
    are NOT independently live-verified in this sandbox (only displayName/
    location were previously confirmed, via conference_standings.py) - a
    reasoned extension of an already-confirmed object, not a cold guess at
    a new shape, same standard this file holds every other addition to.

    Returns columns: Team, DisplayName, EspnId, Conference, Color,
    AltColor. Empty DataFrame if the standings payload is empty/unreachable.
    """
    season = season or current_cbb_season()
    data = _fetch_standings_raw(season)
    rows = []
    for conf in data.get('children', []):
        if not conf.get('isConference'):
            continue
        conf_name = conf.get('name') or conf.get('abbreviation')
        entries = (conf.get('standings') or {}).get('entries', [])
        for e in entries:
            team = e.get('team') or {}
            color = team.get('color')
            alt = team.get('alternateColor')
            name = team.get('location') or team.get('displayName')
            if not name:
                continue
            rows.append({
                'Team': name,
                'DisplayName': team.get('displayName') or name,
                'EspnId': team.get('id'),
                'Conference': conf_name,
                'Color': f"#{color}" if color else None,
                'AltColor': f"#{alt}" if alt else None,
            })
    return pd.DataFrame(rows)


ESPN_ROSTER_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/teams/{team_id}/roster"


@st.cache_data(ttl=3600)
def load_espn_roster(team_espn_id, season=None):
    """
    One team's roster (bio fields) via ESPN's public roster endpoint - the
    `/apis/site/v2/...` base path (the SAME family Conference Standings'
    sibling scoreboard/rankings endpoints use, confirmed distinct from the
    `/apis/v2/...` standings path - see load_conference_standings' own
    docstring for that gotcha). NOT independently live-verified in this
    sandbox (same caveat as every other new endpoint in this pipeline -
    confirm against a real payload before fully trusting it).

    Defensively handles both a flat athlete list and a position-grouped
    one (`{'position': ..., 'items': [...]}`) since which shape ESPN's
    roster response uses for NCAAB specifically couldn't be confirmed here
    - CBBD's own roster endpoint hit an analogous "confirm the real shape"
    gotcha with position granularity (see HANDOFF.md), so this defaults to
    the more defensive parse rather than assuming one shape works.

    Returns columns: sourceId (ESPN athlete id - the SAME id namespace the
    season box file's athleteSourceId already uses, so these join directly
    with no separate id-reconciliation step), name, jersey, position,
    height (inches, if present), displayHeight (formatted string, e.g.
    "6'8\"" - preferred for display since it sidesteps guessing whether
    `height` is really inches), weight, city, state, country. Empty
    DataFrame on any failure or a missing/falsy `team_espn_id`.
    """
    if not team_espn_id:
        return pd.DataFrame()
    try:
        resp = requests.get(ESPN_ROSTER_URL.format(team_id=team_espn_id), timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return pd.DataFrame()

    raw_athletes = data.get('athletes', []) if isinstance(data, dict) else []
    flat = []
    for entry in raw_athletes:
        if isinstance(entry, dict) and 'items' in entry:
            flat.extend(entry.get('items') or [])
        else:
            flat.append(entry)

    rows = []
    for a in flat:
        if not isinstance(a, dict):
            continue
        pos = a.get('position') or {}
        birth = a.get('birthPlace') or {}
        rows.append({
            'sourceId': a.get('id'),
            'name': a.get('displayName') or a.get('fullName'),
            'jersey': a.get('jersey'),
            'position': pos.get('abbreviation') or pos.get('name'),
            'height': a.get('height'),
            'displayHeight': a.get('displayHeight'),
            'weight': a.get('weight'),
            'city': birth.get('city'),
            'state': birth.get('state'),
            'country': birth.get('country'),
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
    the hand-typed config.TEAM_CONFIG otherwise.

    Keyed under BOTH CBBD's short 'school' name ('Duke') AND its
    'displayName' ('Duke Blue Devils') where available - other sources in
    this app format the same team differently (ESPN's Conference Standings
    uses full "School Mascot" names like CBBD's displayName; ncaa.com's NET
    page and CBBD's own other endpoints use the short school name), and a
    single-keying scheme silently misses one or the other (a real bug this
    fixes: Conference Standings' team coloring was only ever resolving via
    the small ~70-team hardcoded config.TEAM_CONFIG fallback - which
    happened to be hand-typed in ESPN's full-name format - not this live
    360+-team map, because the live map was 'school'-only). Short name wins
    on a collision (kept first) since more callers already key on it.
    """
    df = load_teams(season)
    if df.empty:
        from config import TEAM_CONFIG
        return {v['name']: v['color'] for v in TEAM_CONFIG.values()}
    out = dict(zip(df['Team'], df['Color']))
    if 'DisplayName' in df.columns:
        for disp, color in zip(df['DisplayName'], df['Color']):
            if disp and disp not in out:
                out[disp] = color
    return out


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


@st.cache_data(show_spinner=False, persist="disk")
def _load_conference_player_season_stats_cached(conference, season, _week):
    teams_df = load_teams(season)
    if teams_df.empty:
        return pd.DataFrame()
    conf_teams = teams_df[teams_df['Conference'] == conference]['Team'].dropna().tolist()
    frames = [load_team_player_stats(t, season) for t in conf_teams]
    frames = [f for f in frames if not f.empty]
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


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

    Weekly refresh + disk persistence (not the short per-team TTLs): this
    is a LEAGUE-WIDE reference distribution used only for percentile
    context, not a specific team/player's own current stats - the user
    explicitly asked for "pull league averages weekly, compare current
    stats against week-old context" instead of re-fetching/recomputing the
    whole distribution on every tab visit. The actual weekly-refresh
    mechanism is `_week_bucket()` (see its docstring for why - `ttl=` on a
    persist="disk" cache is silently ignored by Streamlit, confirmed in
    its own source, not a real expiry). `persist="disk"` survives an app
    restart (Streamlit Community Cloud can restart the process on
    inactivity, which would otherwise silently drop an in-memory-only
    cache and eat the full fan-out cost again) - see
    clear_league_wide_caches() for the manual-refresh path wired to the
    sidebar, for whenever fresher-than-a-week data is wanted.
    """
    season = season or current_cbb_season()
    return _load_conference_player_season_stats_cached(conference, season, _week_bucket())


@st.cache_data(show_spinner=False, persist="disk")
def _load_all_player_season_stats_cached(season, _week):
    teams_df = load_teams(season)
    if teams_df.empty:
        return pd.DataFrame()
    all_teams = teams_df['Team'].dropna().tolist()
    progress = st.progress(0.0, text="Loading Division I player stats (cached ~weekly - this only runs when the cache is cold)...")
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


def load_all_player_season_stats(season=None):
    """
    Every D-I player's season stats in one cached pull, built the same
    fan-out way as load_conference_player_season_stats but across every
    team in load_teams() - genuinely expensive (one HTTP call per D-I team,
    360+), so this is opt-in from the UI (a "compare vs all of D-I"
    checkbox), never called automatically on every Player Search visit.

    Weekly refresh + disk persistence, not the old 6h in-memory-only
    cache: the fan-out cost was previously being re-paid every 6 hours
    (and on every app restart, since in-memory cache doesn't survive that)
    even though this is league-CONTEXT data, not any specific player's own
    stats - the user explicitly asked to treat this like a weekly snapshot
    ("compare current stats to week-old averages, not a huge deal") rather
    than something that needs to feel live. The actual weekly-refresh
    mechanism is `_week_bucket()` (`ttl=` on a persist="disk" cache is
    silently ignored by Streamlit - confirmed in its own source, not a
    real expiry - see that function's docstring). `persist="disk"` means a
    restarted app reuses last week's pull instead of re-running the full
    360-team fan-out on the next visit. See clear_league_wide_caches() for
    the manual "refresh now" escape hatch (wired to the sidebar).
    """
    season = season or current_cbb_season()
    return _load_all_player_season_stats_cached(season, _week_bucket())


@st.cache_data(show_spinner=False, persist="disk")
def _load_all_rosters_cached(season, _week):
    teams_df = load_teams(season)
    if teams_df.empty:
        return pd.DataFrame()
    all_teams = teams_df['Team'].dropna().tolist()
    progress = st.progress(0.0, text="Loading Division I rosters (cached ~weekly - this only runs when the cache is cold)...")
    frames = []
    for i, t in enumerate(all_teams):
        df = load_team_roster(t, season)
        if not df.empty:
            df = df.copy()
            df['Team'] = t
            frames.append(df)
        progress.progress((i + 1) / len(all_teams), text=f"Loading Division I rosters... ({i + 1}/{len(all_teams)} teams)")
    progress.empty()
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def load_all_rosters(season=None):
    """
    Every D-I team's roster in one cached pull (same per-team fan-out over
    load_teams() as load_all_player_season_stats, just against
    load_team_roster instead of load_team_player_stats) - the corpus behind
    Player Search's "All Teams" option, so a player can be found by name
    without picking their team first (CBBD has no roster-by-name search of
    its own - see HANDOFF.md). Adds a 'Team' column (load_team_roster's own
    output doesn't carry one, since it's normally called already scoped to
    a single team) so a name match can be traced back to the right team's
    stats/game-log calls downstream.

    Weekly refresh + disk persistence via `_week_bucket()`, not a `ttl=`
    (silently ignored on a persist="disk" cache by Streamlit - see that
    function's docstring) - same league-wide-data reasoning as
    load_all_player_season_stats.
    """
    season = season or current_cbb_season()
    return _load_all_rosters_cached(season, _week_bucket())


@st.cache_data(persist="disk")
def _load_efficiency_ratings_cached(season, _week):
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


def load_efficiency_ratings(season=None):
    """
    Adjusted offensive/defensive efficiency and net rating for every D-I
    team - CBBD's KenPom-equivalent. Verified live against /ratings/adjusted
    before writing this parser; field names below are exact.

    Weekly refresh + disk persistence via `_week_bucket()`, not a `ttl=`
    (silently ignored on a persist="disk" cache by Streamlit - see that
    function's docstring) - same league-context-data reasoning as the
    other full-league loaders in this file.
    """
    season = season or current_cbb_season()
    return _load_efficiency_ratings_cached(season, _week_bucket())


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


@st.cache_data(persist="disk")
def _load_all_team_season_stats_cached(season, _week):
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
        o_3p = os_.get('threePointFieldGoals') or {}
        o_fg = os_.get('fieldGoals') or {}
        # twoPointFieldGoals - a documented sibling of the already-verified
        # threePointFieldGoals/fieldGoals sub-objects on the same
        # teamStats/opponentStats parent (same "sibling of a confirmed
        # field" reasoning as every other derived stat in this loader - see
        # HANDOFF.md). Not independently live-verified this pass.
        o_2p = os_.get('twoPointFieldGoals') or {}
        total_pts = (t_pts.get('total') or 0)
        def_orb_pct = off_.get('offensiveReboundPct')
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
            'Def 3PA Rate': (o_3p.get('attempted') / o_fg.get('attempted') * 100) if o_fg.get('attempted') else None,
            'Def 3P%': o_3p.get('pct'),
            'Def 2P%': o_2p.get('pct'),
            'Def DREB%': (100 - def_orb_pct) if def_orb_pct is not None else None,
        })
    return pd.DataFrame(rows)


def load_all_team_season_stats(season=None):
    """
    Every D-I team's full season stat sheet in ONE call via /stats/team/season
    - verified live before writing this (700 rows for 2025; teamStats and
    opponentStats each carry a fourFactors block plus points/fieldGoals/
    threePointFieldGoals detail). This single cached pull powers the Four
    Factors matchup engine, the tempo-based score projection, and the
    Matchup Analyzer's Team Defense profile.

    Def 3PA Rate/Def 3P%/Def 2P%/Def DREB% are derived from the opponentStats
    side of the payload (i.e. what opponents did AGAINST this team), not a
    separate defense endpoint - opponentStats.fourFactors.offensiveReboundPct
    is opponents' OWN offensive rebound rate against this team, so
    Def DREB% = 100 - that value. Def 2P% reads opponentStats.
    twoPointFieldGoals.pct, a documented sibling of the already-verified
    threePointFieldGoals/fieldGoals sub-objects on the same parent object -
    not independently live-verified (see HANDOFF.md's usual caveat for
    fields added without live network access).

    Weekly refresh + disk persistence via `_week_bucket()`, not a `ttl=`
    (silently ignored on a persist="disk" cache by Streamlit - see that
    function's docstring) - same league-wide-data reasoning as the other
    full-league loaders in this file.
    """
    season = season or current_cbb_season()
    return _load_all_team_season_stats_cached(season, _week_bucket())


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


@st.cache_data(show_spinner=False, persist="disk")
def _load_team_opponent_game_logs_cached(team, season, max_recent_games, _week):
    """
    Every OPPOSING player's box score from `team`'s `max_recent_games` MOST
    RECENT games this season - the data source behind the Matchup
    Analyzer's positional defense breakdown ("what have opposing point
    guards/forwards/centers done against this team"), built WITHOUT a
    full-D-I fan-out and without any new/unverified endpoint.

    `max_recent_games` (default 20, `None`/0 = the whole season) exists
    for API-quota reasons, not just performance: CBBD's FREE tier is capped
    at 1,000 calls/MONTH total (confirmed via CBBD's own docs/socials -
    see HANDOFF.md), and this function's cost scales with the number of
    UNIQUE opponents `team` has played (see below) - uncapped, a team 30
    games into its season costs ~30 calls to refresh, once per team per
    week. Capping to the most recent N games bounds that (a 20-game cap
    means this never costs more than ~20 opponent calls regardless of how
    deep into the season `team` is) and is arguably more analytically
    useful anyway: how a defense has played the last month matters more to
    "should I worry about their guards tonight" than a result from
    November. Early/mid-season, when fewer than `max_recent_games` have
    been played, this is a no-op - nothing gets trimmed.

    The trick: `team`'s own schedule (load_team_games) already lists every
    opponent it has actually played - typically 12-30 teams across a full
    season, far fewer than all 360+ D-I teams. For each of THOSE opponents
    (and only those), load_player_game_logs(opponent, season) - the exact
    same per-team /games/players call this app already uses for Player
    Search's game log, already verified live - returns that opponent's own
    full-season game-by-game box scores. Filtering that to
    Opponent == `team` gives every one of that opponent's players' stat
    lines specifically in the game(s) against `team`. Concatenating across
    every actually-played opponent gives the full "who did `team` face, and
    what did they do" dataset.

    This also solves the "season average to compare against" problem for
    free: load_player_game_logs(opponent, season) is that player's FULL
    season log, not just the game vs `team` - so each opposing player's own
    season average is computable from the SAME already-fetched frame, no
    extra /stats/player/season call needed.

    Cost: ~1 API call per opponent `team` has actually played (bounded by
    games played, not by D-I's full 360+ teams) - and each of those calls is
    independently cached per-opponent, so it's shared/reused by every OTHER
    matchup that also involves that same opponent (heavy overlap in-
    conference), not paid fresh per matchup. Weekly refresh + disk
    persistence via `_week_bucket()`, not a `ttl=` (silently ignored on a
    persist="disk" cache by Streamlit - see that function's docstring),
    like the other league-context pulls above.

    Returns columns: Opponent Team (who `team` played), Player,
    PositionSourceId (join key for position - see data.transforms.
    position_bucket and callers that join load_team_roster), Date,
    Points/Rebounds/Assists/FGA/3PA (the game vs `team`), and
    Season Avg Points/Rebounds/Assists/FGA/3PA (that player's own full-
    season average, all games, from the same cached frame).
    """
    games = load_team_games(team, season)
    if games.empty:
        return pd.DataFrame()
    # load_team_games already sorts by Date ascending - .tail(N) is the N
    # MOST RECENT games, not an arbitrary N.
    scoped_games = games.tail(max_recent_games) if max_recent_games else games
    opponents = scoped_games['Opponent'].dropna().unique().tolist()
    avg_cols = ['Points', 'Rebounds', 'Assists', 'FGA', '3PA']
    rows = []
    for opp in opponents:
        log = load_player_game_logs(opp, season)
        if log.empty:
            continue
        vs_team = log[log['Opponent'] == team]
        if vs_team.empty:
            continue
        season_avgs = log.groupby('athleteSourceId')[avg_cols].mean()
        for _, r in vs_team.iterrows():
            sid = r.get('athleteSourceId')
            avg = season_avgs.loc[sid] if sid in season_avgs.index else None
            row = {
                'Opponent Team': opp,
                'Player': r.get('name'),
                'athleteSourceId': sid,
                'Date': r.get('Date'),
            }
            for c in avg_cols:
                row[c] = r.get(c)
                row[f'Season Avg {c}'] = avg[c] if avg is not None else None
            rows.append(row)
    return pd.DataFrame(rows)


def load_team_opponent_game_logs(team, season=None, max_recent_games=20):
    """
    Public wrapper - resolves `season` and threads `_week_bucket()` through
    to `_load_team_opponent_game_logs_cached` (see its docstring for the
    full behavior/cost breakdown). This is CBBD's own positional-matchup
    data source; `load_positional_matchup_data` below tries the free ESPN/
    SportsDataverse season file first and falls back to this.
    """
    season = season or current_cbb_season()
    return _load_team_opponent_game_logs_cached(team, season, max_recent_games, _week_bucket())


# ===========================================================
# ESPN box scores via SportsDataverse's free published season file
# (GitHub Releases, hoopR's Python sibling project) - built specifically
# to cut CBBD's 1,000-call/month free-tier pressure from the positional
# matchup defense engine above: ONE file download covers every D-I team's
# WHOLE SEASON of game logs, vs. load_team_opponent_game_logs' ~1 CBBD
# call per opponent per team. No API key, no CBBD-style monthly quota.
#
# Deliberately NOT using the `sportsdataverse` PyPI package - same "raw
# requests over an SDK wrapper" call this app already made for cbbd (see
# HANDOFF.md), doubly justified here: sportsdataverse pulls in scikit-
# learn/xgboost/scipy/pyreadr/beautifulsoup4/etc (none of which this
# needs just to download one parquet file) and its own pyarrow pin
# actively conflicts with the one streamlit already requires. This hits
# the exact same published parquet file directly with `requests` +
# `pd.read_parquet`, both already dependencies - zero new install weight.
#
# NOT verified against a live payload - this sandbox's network policy
# blocks GitHub release-asset downloads (confirmed via the same egress-
# proxy 403 pattern hit on CBBD/ESPN all along; only raw.githubusercontent
# .com file blobs are reachable here, not release assets) - see
# DATA_SOURCES.md. The URL and schema below come from SportsDataverse's
# own published field docs and R/Python source (fetched via
# raw.githubusercontent.com, which IS reachable), not a live response.
# Every function below treats empty/failed as "unavailable" and falls
# back to the already-proven CBBD path - this can only help, never break
# what already worked. Confirm against real data before fully trusting it.
# ===========================================================
ESPN_SEASON_PLAYER_BOX_URL = (
    "https://github.com/sportsdataverse/sportsdataverse-data/releases/download/"
    "espn_mens_college_basketball_player_boxscores/player_box_{season}.parquet"
)

_ESPN_BOX_AVG_COLS = ['Points', 'Rebounds', 'Assists', 'FGA', '3PA']


@st.cache_data(show_spinner=False, persist="disk")
def _fetch_espn_season_box_raw_cached(season, _bucket):
    """
    Raw download + parquet parse of SportsDataverse's published season
    file - the one actual network/IO cost in this whole subsystem, factored
    out so it's shared by BOTH "finishing" steps below instead of each
    downloading the same file independently: `_load_espn_season_player_box_cached`
    (CBBD-name-resolved, powers positional matchup defense) and
    `_load_espn_season_player_box_native_cached` (ESPN-name-resolved, powers
    Player Search's CBBD-free pipeline - see that function's docstring for
    why it needs its own name resolution instead of reusing the CBBD one).

    Returns RAW columns (team names NOT yet resolved to any canonical list -
    each finisher does that against its own reference) with numeric
    coercion applied. Also carries free-throw and offensive/defensive-
    rebound-split columns the original (CBBD-resolved-only) version didn't
    extract - added for Player Search's Usage%/FT%/FT-rate/ORB-DRB split,
    harmless to the CBBD-resolved finisher since it just doesn't select
    them. FTM/FTA/OREB/DREB field names are a documented sibling-guess of
    the already-relied-on field_goals_made/attempted pattern (same
    reasoning as everywhere else in this module) - NOT independently live-
    verified, same caveat as the rest of this file (see module docstring).

    RAISES on any failure (network, HTTP status, parse, or an unexpectedly
    empty file) instead of swallowing it into an empty DataFrame - letting
    the exception propagate out of this st.cache_data-decorated function
    means Streamlit does NOT cache the failure (only successful returns get
    memoized), so a transient failure (a network blip, the CDN briefly
    erroring) gets retried on the NEXT call instead of being locked in as a
    false "no data" for the rest of the twice-weekly cache window. Hit this
    exact gap for real once already (see HANDOFF.md) - every caller below
    catches this at the public-wrapper level (NOT `@st.cache_data`-
    decorated) and degrades to an empty DataFrame for the UI, so external
    behavior is unchanged - only the CACHING of a failure is fixed.

    Twice-weekly refresh + disk persistence via `_twice_weekly_bucket()`
    (bumped from `_week_bucket()` on request - a plain file re-download
    costs nothing extra, no CBBD-style quota is at stake).
    """
    resp = requests.get(
        ESPN_SEASON_PLAYER_BOX_URL.format(season=season), timeout=45,
        headers={"User-Agent": "Mozilla/5.0 (compatible; CBBScholar/1.0)"},
    )
    resp.raise_for_status()
    raw = pd.read_parquet(io.BytesIO(resp.content))
    if raw is None or raw.empty:
        raise ValueError(f"SportsDataverse season box file for {season} parsed to an empty DataFrame")

    def col(name):
        return raw[name] if name in raw.columns else pd.Series([None] * len(raw), index=raw.index)

    game_date = pd.to_datetime(col('game_date'), errors='coerce')
    return pd.DataFrame({
        'GameId': col('game_id'),
        'Date': game_date.dt.strftime('%Y-%m-%d'),
        'TeamRaw': col('team_location'),
        'OpponentRaw': col('opponent_team_location'),
        'Home/Away': col('home_away').map({'home': 'vs', 'away': '@'}),
        # SportsDataverse's athlete_id IS ESPN's own athlete id - the SAME
        # "ESPN-side id" namespace load_team_roster's sourceId and
        # load_player_game_logs' athleteSourceId already document
        # themselves as being (see HANDOFF.md's id-namespace gotcha) -
        # both this field and CBBD's ultimately trace back to the same
        # ESPN athlete record. Reasoned, not live-confirmed (see module
        # docstring) - kept under the SAME column name so existing
        # sourceId-based joins work unmodified regardless of which source
        # produced a given row; falls back to name matching wherever this
        # assumption is wrong, same as the CBBD path already does.
        'athleteSourceId': col('athlete_id'),
        'name': col('athlete_display_name'),
        'Position': col('athlete_position_name'),
        'Minutes': pd.to_numeric(col('minutes'), errors='coerce'),
        'Points': pd.to_numeric(col('points'), errors='coerce'),
        'Rebounds': pd.to_numeric(col('rebounds'), errors='coerce'),
        'OREB': pd.to_numeric(col('offensive_rebounds'), errors='coerce'),
        'DREB': pd.to_numeric(col('defensive_rebounds'), errors='coerce'),
        'Assists': pd.to_numeric(col('assists'), errors='coerce'),
        'Steals': pd.to_numeric(col('steals'), errors='coerce'),
        'Blocks': pd.to_numeric(col('blocks'), errors='coerce'),
        'Turnovers': pd.to_numeric(col('turnovers'), errors='coerce'),
        'FGM': pd.to_numeric(col('field_goals_made'), errors='coerce'),
        'FGA': pd.to_numeric(col('field_goals_attempted'), errors='coerce'),
        '3PM': pd.to_numeric(col('three_point_field_goals_made'), errors='coerce'),
        '3PA': pd.to_numeric(col('three_point_field_goals_attempted'), errors='coerce'),
        'FTM': pd.to_numeric(col('free_throws_made'), errors='coerce'),
        'FTA': pd.to_numeric(col('free_throws_attempted'), errors='coerce'),
    })


def _resolve_espn_box_team_names(raw_box, canonical_names):
    """
    Maps TeamRaw/OpponentRaw (SportsDataverse's own team_location strings)
    to `canonical_names` via data.utils.resolve_team_name, and drops rows
    that don't resolve on either side - shared logic between the two
    finishing steps below, which differ only in WHICH canonical name list
    they resolve against (CBBD's `load_teams()` vs ESPN's own
    `load_espn_teams()`). Returns columns identical to `raw_box` minus
    TeamRaw/OpponentRaw, plus real Team/Opponent columns, sorted by Date.

    Also drops DNP rows (0 or missing Minutes - injury, coach's decision,
    suspension, etc.). The raw box file carries a full row (0 points, 0
    rebounds, everything zeroed) for a player who was AVAILABLE for a game
    but didn't actually play, not just for players who played. Left in,
    anything that counts rows as "games" (data.transforms.
    espn_player_season_stats_for_teams' `games = len(g)`, in particular)
    counts a DNP as a game played, inflating the denominator and dragging
    every per-game average down - confirmed against a real discrepancy (a
    player who missed real season time to injury showed a season PPG here
    roughly 44% below his actual number, matching almost exactly what a
    games-count inflated by his missed games would produce). Every stat
    SUM is unaffected either way (a DNP row contributes zero regardless),
    so this only fixes counts/averages/game logs, never point totals -
    and it's a strict improvement for positional matchup defense too (an
    opposing player who didn't play is not evidence of anything against a
    team's defense).
    """
    if raw_box is None or raw_box.empty:
        return pd.DataFrame()
    distinct_names = set(raw_box['TeamRaw'].dropna()) | set(raw_box['OpponentRaw'].dropna())
    name_map = {n: resolve_team_name(n, canonical_names) for n in distinct_names} if canonical_names else {}
    out = raw_box.copy()
    out['Team'] = out['TeamRaw'].map(name_map) if name_map else None
    out['Opponent'] = out['OpponentRaw'].map(name_map) if name_map else None
    out = out.drop(columns=['TeamRaw', 'OpponentRaw'])
    out = out.dropna(subset=['Team', 'Opponent', 'Date'])
    out = out[pd.to_numeric(out['Minutes'], errors='coerce') > 0]
    return out.sort_values('Date').reset_index(drop=True) if not out.empty else out


@st.cache_data(show_spinner=False, persist="disk")
def _load_espn_season_player_box_cached(season, _bucket):
    """
    Every D-I player's game-by-game box score for the WHOLE season, team
    names resolved to THIS app's canonical CBBD team names (via
    _resolve_espn_box_team_names against load_teams()) - powers positional
    matchup defense (data.loaders.load_positional_matchup_data). Delegates
    the actual download to `_fetch_espn_season_box_raw_cached` (shared with
    Player Search's CBBD-free pipeline, so the file isn't fetched twice).

    Returns columns: GameId, Date, Team, Opponent, Home/Away,
    athleteSourceId, name, Position, Minutes, Points, Rebounds, Assists,
    Steals, Blocks, Turnovers, FGM, FGA, 3PM, 3PA (unchanged from before
    this function was refactored - positional matchup defense's contract
    with this function is untouched). Raises on failure - see
    `_fetch_espn_season_box_raw_cached`'s docstring for why; caught by the
    public wrapper below, not here (so a real failure doesn't get cached).
    """
    raw_box = _fetch_espn_season_box_raw_cached(season, _bucket)
    teams_df = load_teams(season)
    canonical = teams_df['Team'].dropna().tolist() if not teams_df.empty else []
    out = _resolve_espn_box_team_names(raw_box, canonical)
    if out.empty:
        return out
    keep_cols = ['GameId', 'Date', 'Team', 'Opponent', 'Home/Away', 'athleteSourceId', 'name', 'Position',
                 'Minutes', 'Points', 'Rebounds', 'Assists', 'Steals', 'Blocks', 'Turnovers', 'FGM', 'FGA', '3PM', '3PA']
    return out[keep_cols]


def load_espn_season_player_box(season=None):
    """
    Public wrapper - resolves `season` and threads `_twice_weekly_bucket()`
    through to `_load_espn_season_player_box_cached` (see its docstring for
    the full field-level breakdown and freshness caveats). Powers
    positional matchup defense. Catches any exception the cached chain
    raises (network/parse failure - see `_fetch_espn_season_box_raw_cached`)
    and degrades to an empty DataFrame here, OUTSIDE any `@st.cache_data`
    boundary, so a transient failure isn't memoized as "no data" for the
    rest of the cache window.
    """
    season = season or current_cbb_season()
    try:
        return _load_espn_season_player_box_cached(season, _twice_weekly_bucket())
    except Exception:
        return pd.DataFrame()


@st.cache_data(show_spinner=False, persist="disk")
def _load_espn_season_player_box_native_cached(season, _bucket):
    """
    Same underlying box-score file as `_load_espn_season_player_box_cached`
    (shares the raw download via `_fetch_espn_season_box_raw_cached`), but
    resolved against ESPN's OWN team list (`load_espn_teams`) instead of
    CBBD's `load_teams()` - Player Search's CBBD-free pipeline needs ZERO
    CBBD calls anywhere in it, including team-name canonicalization, which
    the CBBD-resolved sibling function above depends on. Also keeps the
    OREB/DREB/FTM/FTA columns that sibling drops (positional matchup
    defense doesn't need them; Player Search's season totals/Usage%/FT-
    rate computation does - see data.transforms.espn_player_season_stats_for_teams).

    Returns columns: GameId, Date, Team, Opponent, Home/Away,
    athleteSourceId, name, Position, Minutes, Points, Rebounds, OREB, DREB,
    Assists, Steals, Blocks, Turnovers, FGM, FGA, 3PM, 3PA, FTM, FTA.
    Raises on failure - see `_fetch_espn_season_box_raw_cached`'s docstring
    for why; caught by the public wrapper below, not here.
    """
    raw_box = _fetch_espn_season_box_raw_cached(season, _bucket)
    # `season` passed through here - this was a real bug: calling
    # load_espn_teams() with no argument silently used current_cbb_season()
    # regardless of which season was actually being requested, giving the
    # wrong team/conference list (and wrong resolution) for any historical
    # season lookup.
    teams_df = load_espn_teams(season)
    canonical = teams_df['Team'].dropna().tolist() if not teams_df.empty else []
    return _resolve_espn_box_team_names(raw_box, canonical)


def load_espn_season_player_box_native(season=None):
    """
    Public wrapper for Player Search's CBBD-free box-score source -
    resolves `season` and threads `_twice_weekly_bucket()` through to
    `_load_espn_season_player_box_native_cached`. This IS Player Search's
    game log AND season-stats source in one (season totals are just this
    same per-game data summed - see data.transforms.
    espn_player_season_stats_for_teams), unlike the CBBD path, which needs
    two separate endpoints (/stats/player/season and /games/players) for
    the same two things. Catches any exception the cached chain raises
    (network/parse failure, OR the season genuinely not being published -
    see ESPN_SEASON_PLAYER_BOX_URL's module docstring) and degrades to an
    empty DataFrame here, OUTSIDE any `@st.cache_data` boundary, so a
    transient failure isn't memoized as "no data" for the rest of the
    cache window.
    """
    season = season or current_cbb_season()
    try:
        return _load_espn_season_player_box_native_cached(season, _twice_weekly_bucket())
    except Exception:
        return pd.DataFrame()


@st.cache_data(show_spinner=False, persist="disk")
def _espn_di_player_stats_cached(season, _bucket):
    box_df = load_espn_season_player_box_native(season)
    return espn_player_season_stats_for_teams(box_df, teams=None)


def load_espn_di_player_stats(season=None):
    """
    The full-D-I `espn_player_season_stats_for_teams(box_df, teams=None)`
    groupby, cached - this is the "compare against all of Division I"
    comparison group both Player Search and Matchup Analyzer's PLAYER
    panel build, and it was slow enough (a real pandas groupby over every
    D-I player's whole season of box scores) to cause a noticeable pause
    on every widget rerun, not just first load - confirmed as a real,
    user-reported perf complaint, not a hypothetical one. Cached to the
    SAME twice-weekly cadence as the underlying box file itself
    (`_twice_weekly_bucket()` - recomputing more often than the source
    data actually changes is pure waste), `persist="disk"` so a restarted
    app reuses this instead of recomputing on the very next visit. Shared
    by both callers specifically so they don't independently recompute
    (or worse, silently drift on) the exact same D-I-wide aggregation.
    """
    season = season or current_cbb_season()
    return _espn_di_player_stats_cached(season, _twice_weekly_bucket())


def load_positional_matchup_data(team, season=None, max_recent_games=20):
    """
    Positional-matchup-defense data source for `team`, preferring the free
    ESPN season file (load_espn_season_player_box - zero CBBD-quota cost,
    every opposing player's box score already in one place, no per-
    opponent fan-out needed at all) and falling back to the proven CBBD
    path (load_team_opponent_game_logs) whenever the ESPN file is missing,
    unreachable, or too far behind `team`'s actual CBBD-confirmed schedule
    to trust (see _is_espn_data_fresh_enough) - most likely early in a
    brand-new season, before SportsDataverse's own scrape/publish job has
    caught up. This fallback means switching to ESPN can only ever help or
    be a no-op; it can't make this feature less reliable than it already
    was on CBBD alone.

    Same output shape as load_team_opponent_game_logs PLUS a Position
    column when the ESPN path is used (None when the CBBD fallback is
    used) - callers should build their position map from this column when
    present (see ui.tabs.matchup_analyzer._position_map_for_matchup) and
    only fall back to a roster lookup when it's absent, saving the roster
    API calls entirely on top of the game-log savings.
    """
    season = season or current_cbb_season()
    espn_df = load_espn_season_player_box(season)
    if not espn_df.empty and 'Team' in espn_df.columns:
        team_games_espn = espn_df[espn_df['Team'] == team]
        if not team_games_espn.empty and _is_espn_data_fresh_enough(team, season, team_games_espn):
            scoped_dates = sorted(team_games_espn['Date'].dropna().unique())
            if max_recent_games:
                scoped_dates = scoped_dates[-max_recent_games:]
            vs_team = espn_df[(espn_df['Opponent'] == team) & (espn_df['Date'].isin(scoped_dates))]
            if not vs_team.empty:
                season_avgs = espn_df.groupby('athleteSourceId')[_ESPN_BOX_AVG_COLS].mean()
                rows = []
                for _, r in vs_team.iterrows():
                    sid = r.get('athleteSourceId')
                    avg = season_avgs.loc[sid] if sid in season_avgs.index else None
                    # `vs_team` was filtered on Opponent == `team`, so
                    # r['Opponent'] is just `team` itself on every row -
                    # the OTHER team, the one whose defense this row is
                    # evidence against, is r['Team'] (whichever squad this
                    # specific opposing player actually plays for).
                    row = {
                        'Opponent Team': r.get('Team'),
                        'Player': r.get('name'),
                        'athleteSourceId': sid,
                        'Date': r.get('Date'),
                        'Position': r.get('Position'),
                    }
                    for c in _ESPN_BOX_AVG_COLS:
                        row[c] = r.get(c)
                        row[f'Season Avg {c}'] = avg[c] if avg is not None else None
                    rows.append(row)
                return pd.DataFrame(rows)
    # Fallback: the proven CBBD path, unchanged.
    fallback = load_team_opponent_game_logs(team, season, max_recent_games=max_recent_games)
    if not fallback.empty:
        fallback = fallback.copy()
        fallback['Position'] = None
    return fallback


def _is_espn_data_fresh_enough(team, season, team_games_espn, max_lag_days=10):
    """
    True if the ESPN season file's coverage of `team` is recent enough to
    trust over the CBBD fallback - compares the ESPN file's most recent
    game date for `team` against CBBD's own load_team_games (already
    cached, effectively free to check). Missing/unparseable dates on
    either side fail safe (return False -> caller falls back to CBBD).
    """
    try:
        espn_latest = pd.to_datetime(team_games_espn['Date'], errors='coerce').max()
        cbbd_games = load_team_games(team, season)
        if cbbd_games.empty:
            # No CBBD schedule to compare against - trust the ESPN file
            # rather than refusing to use it at all.
            return pd.notna(espn_latest)
        cbbd_latest = pd.to_datetime(cbbd_games['Date'], errors='coerce').max()
        if pd.isna(espn_latest) or pd.isna(cbbd_latest):
            return False
        return (cbbd_latest - espn_latest).days <= max_lag_days
    except Exception:
        return False


def get_player_season_profile(team, season, player_name, cbbd_athlete_id):
    """
    One player's season-stats profile, preferring ESPN's own live
    endpoints plus the ESPN-native SportsDataverse season box file - the
    SAME architecture Player Search already uses successfully
    (load_espn_teams/load_espn_roster/load_espn_season_player_box_native)
    - over CollegeBasketballData.com. Shared by Matchup Analyzer's PLAYER
    panel and Player Compare; both stayed CBBD-only when Player Search's
    CBBD-free pipeline was first built (HANDOFF.md's "Player Search ONLY"
    scope note), then got a first pass at this that used a DIFFERENT,
    CBBD-resolved box-file variant with a date-freshness heuristic - see
    HANDOFF.md for why that fell back to CBBD almost constantly in
    practice (the box file's raw ESPN-sourced team names resolve far more
    reliably against ESPN's OWN team list than against CBBD's
    independently-formatted one) and was replaced with this version.

    `team`/`player_name` are whatever the caller's existing team-first UI
    already resolved (both tabs still pick a team + player from CBBD's
    /teams/roster for the picker itself, unchanged - only the STATS
    source changes here). `team` gets bridged to ESPN's own canonical
    spelling via resolve_team_name (the same team-name aliasing this app
    already relies on everywhere else); `player_name` gets matched against
    ESPN's roster and box-file names via data.utils.match_player_name, NOT
    an id - ESPN's roster endpoint's athlete id and the box file's athlete
    id turned out to be different id namespaces despite the original
    assumption they were the same (confirmed: this exact id join matched
    nothing for any Player Search player - see HANDOFF.md). Name matching
    sidesteps that bad assumption entirely.

    CBBD is only actually CALLED (get_player_season_stats, the one real
    API cost this function can incur) when the ESPN path can't be used -
    this is the real quota saving, not just a source preference.

    Returns (stats_dict, include_net_rating, source, box_df, athlete_source_id):
    - stats_dict is already in the CBBD dict shape data.transforms.
      player_percentile_rows/player_profile_values (and Compare's own
      _numeric_stat_map) expect regardless of which source produced it.
      When source == 'espn', stats_dict['Team'] is the box file's OWN
      (ESPN-spelled) team name - use THAT, not the caller's original
      `team`, for any further box_df filtering (see below).
    - include_net_rating: False when source == 'espn' (box scores alone
      can't produce Net Rating), True for 'cbbd'.
    - source: 'espn' or 'cbbd' - a caller that also needs a MATCHING
      comparison-group DataFrame should build it from the same place:
      espn_player_season_stats_for_teams(box_df, teams=...) for 'espn'
      (using ESPN-spelled team names, e.g. from load_espn_teams), the
      existing load_conference_player_season_stats/
      load_all_player_season_stats(season) for 'cbbd' (unchanged) -
      mixing sources would compare two slightly different stat
      definitions.
    - box_df: the already-downloaded ESPN-native season file (see
      load_espn_season_player_box_native - the SAME twice-weekly-cached
      download Player Search already triggers) when source == 'espn', for
      a group DataFrame or per-game trend without re-fetching anything.
      None when source == 'cbbd'.
    - athlete_source_id: this player's OWN id from the box file (NOT
      whatever id the caller had) when source == 'espn' - use THIS, not
      the caller's id, for any further box_df row lookups (game log,
      trend), since it's guaranteed self-consistent with box_df. None for
      'cbbd'.

    Falls back to CBBD (get_player_season_stats(team, season,
    cbbd_athlete_id), unchanged from before this function existed)
    whenever: `team` doesn't resolve to an ESPN team, that team's ESPN
    roster is empty/unreachable, `player_name` doesn't match anyone on
    it, the ESPN season box file is empty/unreachable, or `player_name`
    doesn't match anyone in this team's box-file rows either (e.g. very
    early season, before the file has this player's first game). Every
    one of these is a pure fallback to the ALREADY-PROVEN CBBD path - can
    only ever help or be a silent no-op, never regress either tab's
    reliability.
    """
    season = season or current_cbb_season()
    fallback = (get_player_season_stats(team, season, cbbd_athlete_id), True, 'cbbd', None, None)

    espn_teams = load_espn_teams(season)
    if espn_teams.empty:
        return fallback
    espn_team = resolve_team_name(team, espn_teams['Team'].dropna().tolist())
    if not espn_team:
        return fallback
    espn_team_row = espn_teams[espn_teams['Team'] == espn_team]
    if espn_team_row.empty:
        return fallback
    roster_df = load_espn_roster(espn_team_row.iloc[0]['EspnId'], season)
    if roster_df.empty:
        return fallback
    if match_player_name(player_name, roster_df['name']) is None:
        return fallback

    box_df = load_espn_season_player_box_native(season)
    if box_df.empty or 'Team' not in box_df.columns:
        return fallback
    team_stats = espn_player_season_stats_for_teams(box_df, espn_team)
    if team_stats.empty:
        return fallback
    stats_idx = match_player_name(player_name, team_stats['name'])
    if stats_idx is None:
        return fallback
    row = team_stats.iloc[stats_idx].to_dict()
    return row, False, 'espn', box_df, row['athleteSourceId']


def clear_league_wide_caches():
    """
    Manual "refresh league-wide data now" escape hatch for every long
    (weekly), disk-persisted cache above - wired to a sidebar button (see
    ui.components.render_setup_status_sidebar) rather than any automatic
    schedule, matching this app's existing manual-refresh precedent
    (fetch_net_rankings_manual). `st.cache_data`'s .clear() drops every
    cached call of that function regardless of arguments (every team/
    season/conference/_week combo at once) - correct here since "refresh"
    should mean everything, not one team at a time.

    Targets the PRIVATE `_..._cached` inner functions, not the public
    wrappers above them - since the `_week_bucket()` refactor (see that
    function's docstring), the public functions are plain Python functions
    with no `.clear()` of their own; `st.cache_data` decorates only the
    inner function now.
    """
    _load_all_player_season_stats_cached.clear()
    _load_all_rosters_cached.clear()
    _load_conference_player_season_stats_cached.clear()
    _load_all_team_season_stats_cached.clear()
    _load_efficiency_ratings_cached.clear()
    _load_team_opponent_game_logs_cached.clear()
    _load_espn_season_player_box_cached.clear()
    # Player Search's CBBD-free pipeline (twice-weekly by default - see
    # _twice_weekly_bucket()) - clearing the shared raw fetch also
    # invalidates both finishing steps' inputs, but each finisher has its
    # own cache entry (the transformed output) that needs clearing too.
    _fetch_espn_season_box_raw_cached.clear()
    _load_espn_season_player_box_native_cached.clear()
    _espn_di_player_stats_cached.clear()


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
