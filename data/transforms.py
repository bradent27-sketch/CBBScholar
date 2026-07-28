"""
Derived/computed data (percentiles, the Four Factors matchup engine, the
tempo-based score projection, form/breakout detection) - the layer between
data/loaders.py's raw ingestion and ui/'s presentation. Everything here is
pure local compute over already-cached loader output: none of these
functions makes an API call of its own.
"""
import numpy as np
import pandas as pd

from data.utils import resolve_team_name


def player_rate_stats(df, min_games=5, min_mpg=15.0):
    """
    Given a wide player-stats DataFrame (one row per player, nested
    fieldGoals/threePointFieldGoals/freeThrows/rebounds dicts - the same
    shape data.loaders.load_team_player_stats returns), compute the flat
    per-game/percentage columns this app displays (PPG, RPG, ... Net
    Rating) as a new DataFrame - the group-level equivalent of
    ui.tabs.compare's per-player _numeric_stat_map, used to build a
    comparison distribution for ui.charts.render_relative_bars.

    Players under `min_games` OR averaging under `min_mpg` minutes are
    dropped from the distribution (not from any single-player display
    elsewhere). `min_games` alone wasn't enough of a filter: a player who
    checked into 5 games for two garbage-time minutes each still cleared
    it, and a comparison group full of those still counts every bench
    scrub as a full "player" in the average - which is exactly why a
    real rotation guard averaging a modest 3 RPG could come back reading
    as "average" against a group whose mean was dragged down by players
    who barely play. `min_mpg=15` restricts the comparison group to
    players with a real per-game role (starters plus meaningful bench
    rotation, not end-of-bench/garbage-time appearances) - requested
    explicitly: compare against players who "play a lot."
    """
    if df is None or df.empty or 'games' not in df.columns:
        return pd.DataFrame()
    games_raw = pd.to_numeric(df['games'], errors='coerce')
    minutes_raw = pd.to_numeric(df['minutes'], errors='coerce') if 'minutes' in df.columns else pd.Series([None] * len(df), index=df.index)
    mpg_raw = minutes_raw / games_raw
    qualifies = (games_raw >= min_games) & (mpg_raw >= min_mpg)
    work = df[qualifies].copy()
    if work.empty:
        return pd.DataFrame()
    games = pd.to_numeric(work['games'], errors='coerce')

    def nested(col, key):
        if col not in work.columns:
            return pd.Series([None] * len(work), index=work.index)
        return work[col].apply(lambda d: (d or {}).get(key) if isinstance(d, dict) else None)

    def col_or_none(col):
        return work[col] if col in work.columns else pd.Series([None] * len(work), index=work.index)

    ts = pd.to_numeric(col_or_none('trueShootingPct'), errors='coerce')
    fga = pd.to_numeric(nested('fieldGoals', 'attempted'), errors='coerce')
    tpa = pd.to_numeric(nested('threePointFieldGoals', 'attempted'), errors='coerce')
    fta = pd.to_numeric(nested('freeThrows', 'attempted'), errors='coerce')
    return pd.DataFrame({
        'PPG': pd.to_numeric(col_or_none('points'), errors='coerce') / games,
        'RPG': pd.to_numeric(nested('rebounds', 'total'), errors='coerce') / games,
        # Offensive/defensive rebound split - same nested-dict shape as the
        # already-confirmed made/attempted/pct shooting dicts, degrades to
        # all-None (no bar drawn) via the same .get() pattern if this
        # particular sub-key isn't present in a given payload.
        'ORB/G': pd.to_numeric(nested('rebounds', 'offensive'), errors='coerce') / games,
        'DRB/G': pd.to_numeric(nested('rebounds', 'defensive'), errors='coerce') / games,
        'APG': pd.to_numeric(col_or_none('assists'), errors='coerce') / games,
        'SPG': pd.to_numeric(col_or_none('steals'), errors='coerce') / games,
        'BPG': pd.to_numeric(col_or_none('blocks'), errors='coerce') / games,
        'MPG': pd.to_numeric(col_or_none('minutes'), errors='coerce') / games,
        'FG%': pd.to_numeric(nested('fieldGoals', 'pct'), errors='coerce'),
        '3P%': pd.to_numeric(nested('threePointFieldGoals', 'pct'), errors='coerce'),
        'FT%': pd.to_numeric(nested('freeThrows', 'pct'), errors='coerce'),
        'eFG%': pd.to_numeric(col_or_none('effectiveFieldGoalPct'), errors='coerce'),
        'TS%': ts * 100 if ts.notna().any() else ts,
        # Shot-selection style rates (Bart Torvik style 3PAr/FTr) - share of
        # a player's own field goal attempts that are threes/twos, and free
        # throw attempts relative to field goal attempts. "Is this player a
        # high-volume shooter" at a glance, independent of playing time.
        '3PT Rate': (tpa / fga * 100).where(fga > 0),
        '2PT Rate': ((fga - tpa) / fga * 100).where(fga > 0),
        'FT Rate': (fta / fga * 100).where(fga > 0),
        'Net Rating': pd.to_numeric(col_or_none('netRating'), errors='coerce'),
        'Usage %': pd.to_numeric(col_or_none('usage'), errors='coerce'),
    })


def pct_rank(series, value, higher_is_better=True):
    """League percentile (0-100) of `value` within `series`. NaN-safe:
    returns None when the value or the distribution is missing, so callers
    can skip a percentile bar instead of drawing a misleading 0."""
    if value is None or pd.isna(value):
        return None
    s = pd.to_numeric(series, errors='coerce').dropna()
    if s.empty:
        return None
    pct = (s < value).mean() * 100 + (s == value).mean() * 50
    return pct if higher_is_better else 100 - pct


# ---------------------------------------------------------------------------
# Four Factors matchup engine (Dean Oliver's four factors: shooting,
# turnovers, rebounding, free throws - the canonical decomposition of why
# basketball games are won).
# ---------------------------------------------------------------------------

# (label, offense col, defense col, offense higher better?, defense-allowed
# higher better for the DEFENSE?, help text). Defense columns are what that
# team ALLOWS its opponents, so "good defense" = low eFG% allowed, HIGH
# turnover ratio forced, LOW ORB% allowed, LOW FT rate allowed.
FOUR_FACTORS = [
    ('Shooting (eFG%)', 'Off eFG%', 'Def eFG%', True, False,
     "Effective field goal % — field goal % with made threes counted as 1.5 makes. The heaviest of the four factors (~40% of winning)."),
    ('Turnovers (TO Ratio)', 'Off TO Ratio', 'Def TO Ratio', False, True,
     "Turnovers per possession. Offense side: lower = better ball security. Defense side: higher = forces more turnovers."),
    ('Off. Rebounding (ORB%)', 'Off ORB%', 'Def ORB%', True, False,
     "Share of own misses rebounded. Defense side = opponent ORB% allowed (lower = better defensive rebounding)."),
    ('Free Throw Rate', 'Off FT Rate', 'Def FT Rate', True, False,
     "Free throw attempts relative to field goal attempts — getting to the line (offense) / defending without fouling (defense)."),
]


def four_factors_percentile_grid(stats_df, teams=None):
    """
    Team x Four-Factors D-I percentile grid (offense AND defense side of
    each factor, plus Pace as a leading context column - 9 columns total),
    for a league-wide tiering heatmap. Reuses FOUR_FACTORS' own column/
    direction mapping so the four-factor columns can't silently drift from
    the underlying stat definitions. teams=None keeps every team in
    stats_df; pass a list to scope to one conference or group.

    Pace is prepended (not one of the four factors - it's tempo, not a
    quality claim) when `stats_df` has a 'Pace' column, same "higher_is_
    better=True tracks the raw value for bar direction, not a claim that
    fast is better" convention Matchup Analyzer's own team_defense_profile_
    rows already uses for this exact column - kept consistent here rather
    than inventing a second interpretation of the same stat. Silently
    omitted if 'Pace' isn't present (older/partial stats_df), same
    graceful-degradation style as every other optional column in this file.

    Returns (pct_df, raw_df, cols): both DataFrames share a 'Team' column
    plus the same ordered `cols` list - pct_df's cells are 0-100 D-I
    percentiles (for cell color), raw_df's are the actual stat values (for
    tooltip text). Empty inputs return (empty df, empty df, []).
    """
    if stats_df is None or stats_df.empty:
        return pd.DataFrame(), pd.DataFrame(), []
    work = stats_df if teams is None else stats_df[stats_df['Team'].isin(teams)]
    if work.empty:
        return pd.DataFrame(), pd.DataFrame(), []
    cols, higher_is_better = [], {}
    if 'Pace' in stats_df.columns:
        cols.append('Pace')
        higher_is_better['Pace'] = True
    for _, off_col, def_col, off_hib, def_hib, _help in FOUR_FACTORS:
        cols += [off_col, def_col]
        higher_is_better[off_col], higher_is_better[def_col] = off_hib, def_hib
    raw = work[['Team'] + cols].reset_index(drop=True)
    pct = raw[['Team']].copy()
    for col in cols:
        pct[col] = raw[col].apply(lambda v, c=col: pct_rank(stats_df[c], v, higher_is_better=higher_is_better[c]))
    return pct, raw, cols


# ---------------------------------------------------------------------------
# Poll trajectory
# ---------------------------------------------------------------------------

def poll_trajectory(rankings_raw, poll_type, teams=None, top_n=10):
    """
    Wide week-by-week rank table for one poll from the raw /rankings rows
    (already the FULL season history - the same cached payload
    load_latest_poll consumes only the last week of). Returns (pivot_df,
    week_labels). `teams=None` selects the most recent week's top `top_n`.
    """
    rows = [r for r in rankings_raw if r.get('pollType') == poll_type and r.get('ranking')]
    if not rows:
        return pd.DataFrame(), {}
    df = pd.DataFrame([{
        'Week': r.get('week'),
        'Team': r.get('team'),
        'Rank': r.get('ranking'),
    } for r in rows]).dropna(subset=['Week'])
    if df.empty:
        return pd.DataFrame(), {}
    last_week = df['Week'].max()
    if teams is None:
        latest = df[df['Week'] == last_week].sort_values('Rank')
        teams = latest['Team'].head(top_n).tolist()
    sub = df[df['Team'].isin(teams)]
    pivot = sub.pivot_table(index='Week', columns='Team', values='Rank', aggfunc='first').sort_index()
    labels = {w: f"W{int(w)}" for w in pivot.index}
    return pivot, labels


# ---------------------------------------------------------------------------
# Game logs + breakout detection
# ---------------------------------------------------------------------------

def breakout_flags(values, z_threshold=1.5, min_games=4):
    """
    Boolean breakout flag per game: value >= season mean + z_threshold
    standard deviations (population std). Fewer than `min_games` games or
    a ~zero-variance season yields all-False.
    """
    s = pd.Series(values, dtype=float)
    if len(s) < min_games:
        return [False] * len(s)
    std = s.std(ddof=0)
    if not std or pd.isna(std) or std < 1e-9:
        return [False] * len(s)
    return ((s - s.mean()) / std >= z_threshold).tolist()


def last_n_form(player_games, cols=('Points', 'Rebounds', 'Assists'), n=5):
    """{col: (last-n avg, season avg)} for one player's game-log DataFrame -
    the 'is this player heating up or cooling off' readout."""
    out = {}
    if player_games is None or player_games.empty:
        return out
    for col in cols:
        s = pd.to_numeric(player_games[col], errors='coerce').dropna()
        if len(s) >= max(n, 2):
            out[col] = (float(s.tail(n).mean()), float(s.mean()))
    return out


def player_trend_series(player_games, col, n=10):
    """
    Chronological (dates, values, season_avg) for one player's game log -
    the full per-game time series ui.charts.render_trend_line needs to draw
    "trending up or down" as an actual line, not just last_n_form's two
    aggregate numbers. `dates`/`values` cover the last `n` games (oldest
    first); `season_avg` is the flat reference line across the WHOLE season,
    not just the shown window. Returns ([], [], None) if there's nothing
    usable (missing column, all-NaN, or an empty log).
    """
    if player_games is None or player_games.empty or col not in player_games.columns:
        return [], [], None
    s = player_games.copy()
    s[col] = pd.to_numeric(s[col], errors='coerce')
    s = s.dropna(subset=[col])
    if s.empty:
        return [], [], None
    season_avg = float(s[col].mean())
    tail = s.tail(n)
    return tail['Date'].tolist(), tail[col].tolist(), season_avg


def last_n_form_deltas(values, baseline, ns=(10, 5, 3)):
    """
    [(label, avg_value, is_above)] for the last N=10/5/3 entries of
    `values` (chronological, oldest-first - the exact shape both
    player_trend_series and positional_defense_trend already return) vs
    `baseline` - the compact "L10/L5/L3 average" corner readout for
    Matchup Analyzer's trend charts (ui.charts.render_trend_line's
    `corner_stats` param). One flat rule for every caller, PLAYER stats and
    TEAM DEFENSE allowed stats alike: higher than baseline is always
    "above" (renders green), lower is always "below" (renders red) - no
    stat-specific "lower is better" interpretation (e.g. fewer turnovers,
    fewer points allowed). This matches this exact chart's own pre-existing
    per-dot coloring rule (`dot_color = positive if v >= avg else
    negative`) rather than inventing a second, different convention for
    the same chart.

    `n` beyond `len(values)` just uses everything available (plain Python
    slice semantics) - a player with 6 games logged still gets a real, if
    noisier, "L10" entry (mean of all 6) instead of a missing one. Skips
    an `n` entirely only if `values` itself is empty. `is_above` is None
    (renders neutral) only when `baseline` is None.
    """
    out = []
    for n in ns:
        window = values[-n:] if n else values
        if not window:
            continue
        avg_n = sum(window) / len(window)
        is_above = None if baseline is None else avg_n >= baseline
        out.append((f'L{n}', avg_n, is_above))
    return out


# ---------------------------------------------------------------------------
# Player tendency profile (shared vocabulary between Player Search and
# Matchup Analyzer's Player Trends, so the two don't compute the same
# shooting-rate/rebounding numbers two different ways and silently drift).
# ---------------------------------------------------------------------------

_PCT_SUFFIX_LABELS = {'3PT Rate', '2PT Rate', 'FT Rate'}


def player_profile_values(stats, include_net_rating=True):
    """
    Flat {label: raw_value} for one player's season stat dict (the shape
    data.loaders.get_player_season_stats returns) - PPG/RPG/rebound split/
    APG/shooting splits/shot-selection rates/efficiency/usage. Returns {}
    if `stats` is falsy or the player has no games played.

    `include_net_rating=False` omits the 'Net Rating' row entirely (not
    just a '--' value) - Player Search's CBBD-free pipeline has no source
    for it (on/off point differential needs lineup-level play-by-play
    tracking, not just box-score totals - not worth building for a stat
    explicitly deprioritized) and passes False; every other caller
    (Matchup Analyzer's Player panel, still CBBD-based) keeps the default.
    """
    if not stats:
        return {}
    games = stats.get('games') or 0
    if not games:
        return {}
    fg = stats.get('fieldGoals') or {}
    three = stats.get('threePointFieldGoals') or {}
    ft = stats.get('freeThrows') or {}
    reb = stats.get('rebounds') or {}
    ts_pct = stats.get('trueShootingPct')
    fga, tpa, fta = fg.get('attempted'), three.get('attempted'), ft.get('attempted')
    twa = (fga - tpa) if fga is not None and tpa is not None else None

    def per_game(total):
        try:
            return float(total) / float(games)
        except (TypeError, ValueError, ZeroDivisionError):
            return None

    def rate(numer, denom):
        try:
            if numer is None or denom is None or float(denom) == 0:
                return None
            return float(numer) / float(denom) * 100
        except (TypeError, ValueError):
            return None

    # Order below is DELIBERATE and user-specified (not alphabetical/
    # endpoint order) - every caller of this function (Player Search's
    # season stats bars, Matchup Analyzer's Player Trends panel) renders
    # rows in dict-iteration order, so reordering here reorders both at
    # once instead of drifting. Volume counting stats first (scoring,
    # playmaking, rebounding split), then shooting/efficiency, then Net
    # Rating, then the "other" per-game counting stats, then Usage last.
    # MPG has no requested slot - kept at the very end rather than dropped.
    # Built via sequential assignment (not one dict literal) so
    # include_net_rating=False can OMIT that key - and its ordering slot -
    # entirely rather than just nulling its value, while every other key
    # keeps the exact user-specified order regardless of the flag.
    out = {
        'PPG': per_game(stats.get('points')),
        'APG': per_game(stats.get('assists')),
        'RPG': per_game(reb.get('total')),
        'ORB/G': per_game(reb.get('offensive')),
        'DRB/G': per_game(reb.get('defensive')),
        'FG%': fg.get('pct'),
        '3P%': three.get('pct'),
        '3PT Rate': rate(tpa, fga),
        '2PT Rate': rate(twa, fga),
        'FT Rate': rate(fta, fga),
        'FT%': ft.get('pct'),
        'eFG%': stats.get('effectiveFieldGoalPct'),
        'TS%': (ts_pct * 100) if ts_pct is not None else None,
    }
    if include_net_rating:
        out['Net Rating'] = stats.get('netRating')
    out['SPG'] = per_game(stats.get('steals'))
    out['BPG'] = per_game(stats.get('blocks'))
    out['Usage %'] = stats.get('usage')
    out['MPG'] = per_game(stats.get('minutes'))
    return out


def player_percentile_rows(stats, group_df, stat_help=None, include_net_rating=True):
    """
    Ready-to-render rows for ui.charts.render_relative_bars: this player's
    raw values (player_profile_values) plus their percentile (and the
    comparison group's own average percentile) against `group_df` - a wide
    player-stats DataFrame (conference or full D-I, whatever the caller
    already loaded via data.loaders). `stat_help`: optional {label: help
    text} - kept as a caller-supplied param rather than baked in here so
    this stays UI-copy-free (data/ layer convention). `include_net_rating`:
    passed straight through to player_profile_values - see its docstring.
    """
    stat_help = stat_help or {}
    values = player_profile_values(stats, include_net_rating=include_net_rating)
    rates = player_rate_stats(group_df)
    rows = []
    for label, value in values.items():
        is_pct = label.endswith('%') or label in _PCT_SUFFIX_LABELS
        value_str = f"{value:.1f}%" if (value is not None and is_pct) else (f"{value:.1f}" if value is not None else '--')
        pct = avg_pct = None
        if value is not None and not rates.empty and label in rates.columns:
            dist = rates[label].dropna()
            if not dist.empty:
                pct = pct_rank(dist, value)
                avg_pct = pct_rank(dist, dist.mean())
        rows.append({'label': label, 'help': stat_help.get(label, ''), 'value_str': value_str, 'pct': pct, 'avg_pct': avg_pct})
    return rows


# ---------------------------------------------------------------------------
# ESPN/SportsDataverse-native player season stats (Player Search's CBBD-
# free pipeline - data.loaders.load_espn_season_player_box_native). Builds
# a wide, CBBD-shaped ('games'/'points'/nested fieldGoals-threePointField
# Goals-freeThrows-rebounds dicts) DataFrame from raw per-game box scores,
# so player_rate_stats/player_percentile_rows/player_profile_values (all
# built against that CBBD shape) work COMPLETELY UNCHANGED regardless of
# which source produced a given row - only the loader function differs.
# ---------------------------------------------------------------------------

def espn_player_season_stats_for_teams(box_df, teams=None):
    """
    Wide, CBBD-shaped player-season-stats DataFrame from the ESPN/
    SportsDataverse box file, scoped to `teams` (a single team name, a
    list of team names, or None for every team in `box_df`) - this is
    Player Search's CBBD-free season-stats AND percentile-comparison-group
    source in ONE function: a single row (filtered to one team + one
    athleteSourceId) is that player's own season totals; the whole
    returned DataFrame IS a ready-made comparison group for
    player_rate_stats (conference = scope to that conference's teams, D-I
    = scope=None). All local computation, no per-team API fan-out the way
    the CBBD path needs (see data.loaders.load_conference_player_season_stats
    /load_all_player_season_stats) - the whole season is already in the one
    already-downloaded file, so a D-I-wide comparison group costs nothing
    extra here, unlike CBBD's opt-in-because-expensive equivalent.

    No 'netRating' key anywhere in the output (see player_profile_values'
    include_net_rating flag) - box scores alone can't produce an on/off,
    per-100-possession stat without lineup-level play-by-play tracking,
    and it was explicitly deprioritized rather than worth building.

    Usage% IS computed here (CBBD hands it over precomputed; box scores
    don't), via the standard formula summed across the player's games:
        100 * Σ[(FGA + 0.44*FTA + TOV) * (teamMIN/5)]
            / Σ[MIN * (teamFGA + 0.44*teamFTA + teamTOV)]
    where teamMIN/teamFGA/teamFTA/teamTOV are that TEAM's own totals for
    each specific game (every player who suited up that game, summed from
    the same box file - not a separate call).

    Free-throw fields (FTM/FTA) and the offensive/defensive rebound split
    (OREB/DREB) are a documented but NOT live-verified guess at
    SportsDataverse's column names (see data.loaders.
    _fetch_espn_season_box_raw_cached's docstring). If a real payload
    turns out not to carry them, `box_df` will show those columns as
    entirely null - detected here (`has_ft`/`has_reb_split`, checked once
    across the whole scope, not per-player) and degraded to None/'--'
    rather than silently computing FT%/FT-rate/Usage%/TS% from a phantom
    zero, which would look confidently wrong instead of honestly missing.
    Usage% falls back to an FTA-free approximation (FGA+TOV only) in that
    case rather than going missing entirely, since it was specifically
    requested; TS% (which fundamentally needs FTA) goes to None instead.

    Returns an empty DataFrame if `box_df` is empty or `teams` matches
    nothing in it.
    """
    if box_df is None or box_df.empty:
        return pd.DataFrame()
    if teams is None:
        scoped = box_df
    elif isinstance(teams, str):
        scoped = box_df[box_df['Team'] == teams]
    else:
        scoped = box_df[box_df['Team'].isin(teams)]
    if scoped.empty:
        return pd.DataFrame()

    has_ft = (
        'FTA' in scoped.columns and 'FTM' in scoped.columns
        and scoped['FTA'].notna().any() and scoped['FTM'].notna().any()
    )
    has_reb_split = (
        'OREB' in scoped.columns and 'DREB' in scoped.columns
        and scoped['OREB'].notna().any() and scoped['DREB'].notna().any()
    )
    ft_multiplier = 0.44 if has_ft else 0.0
    team_fta_for_totals = scoped['FTA'].fillna(0) if has_ft else 0

    team_totals = scoped.assign(_teamFTA=team_fta_for_totals).groupby(['GameId', 'Team']).agg(
        teamFGA=('FGA', 'sum'), teamFTA=('_teamFTA', 'sum'), teamTOV=('Turnovers', 'sum'), teamMIN=('Minutes', 'sum'),
    ).reset_index()

    rows = []
    for (team, sid), g in scoped.groupby(['Team', 'athleteSourceId']):
        if pd.isna(sid):
            continue
        games = len(g)
        fga, tov = g['FGA'].sum(), g['Turnovers'].sum()
        fgm, tpm, tpa = g['FGM'].sum(), g['3PM'].sum(), g['3PA'].sum()
        pts, reb, ast, stl, blk, mins = (
            g['Points'].sum(), g['Rebounds'].sum(), g['Assists'].sum(),
            g['Steals'].sum(), g['Blocks'].sum(), g['Minutes'].sum(),
        )
        fta = g['FTA'].sum() if has_ft else None
        ftm = g['FTM'].sum() if has_ft else None
        oreb = g['OREB'].sum() if has_reb_split else None
        dreb = g['DREB'].sum() if has_reb_split else None

        player_fta_for_usage = g['FTA'].fillna(0) if has_ft else 0
        joined = g.assign(_playerFTA=player_fta_for_usage).merge(team_totals, on=['GameId', 'Team'], how='left')
        numer = ((joined['FGA'] + ft_multiplier * joined['_playerFTA'] + joined['Turnovers']) * (joined['teamMIN'] / 5)).sum()
        denom = (joined['Minutes'] * (joined['teamFGA'] + ft_multiplier * joined['teamFTA'] + joined['teamTOV'])).sum()
        usage = (numer / denom * 100) if denom else None

        efg = ((fgm + 0.5 * tpm) / fga * 100) if fga else None
        ts = (pts / (2 * (fga + 0.44 * fta))) if (has_ft and pd.notna(fta) and (fga or fta)) else None

        rows.append({
            'Team': team, 'athleteSourceId': sid, 'name': g['name'].iloc[0], 'games': games,
            'points': float(pts), 'assists': float(ast), 'steals': float(stl), 'blocks': float(blk),
            'minutes': float(mins), 'usage': usage, 'effectiveFieldGoalPct': efg, 'trueShootingPct': ts,
            'fieldGoals': {'made': float(fgm), 'attempted': float(fga), 'pct': (fgm / fga * 100) if fga else None},
            'threePointFieldGoals': {'made': float(tpm), 'attempted': float(tpa), 'pct': (tpm / tpa * 100) if tpa else None},
            'freeThrows': {
                'made': float(ftm) if pd.notna(ftm) else None,
                'attempted': float(fta) if pd.notna(fta) else None,
                'pct': (float(ftm) / float(fta) * 100) if (pd.notna(ftm) and pd.notna(fta) and fta) else None,
            },
            'rebounds': {
                'total': float(reb),
                'offensive': float(oreb) if pd.notna(oreb) else None,
                'defensive': float(dreb) if pd.notna(dreb) else None,
            },
        })
    return pd.DataFrame(rows)


def espn_player_result_map(box_df, team):
    """
    {GameId: 'W'/'L'} for every game `team` played, derived entirely from
    box_df itself (summing every one of that team's players' Points for
    each GameId gives the team's own score for that game; the same GameId
    filtered to the Opponent side gives the opponent's score) - no
    separate schedule/scores endpoint needed, unlike the CBBD path's
    load_team_games. Returns {} if `team` has no rows in `box_df`.
    """
    if box_df is None or box_df.empty:
        return {}
    team_games = box_df[box_df['Team'] == team]
    if team_games.empty:
        return {}
    team_scores = team_games.groupby('GameId')['Points'].sum()
    result = {}
    for game_id, team_pts in team_scores.items():
        opp_rows = box_df[(box_df['GameId'] == game_id) & (box_df['Opponent'] == team)]
        if opp_rows.empty:
            continue
        opp_pts = opp_rows['Points'].sum()
        result[game_id] = 'W' if team_pts > opp_pts else ('L' if team_pts < opp_pts else None)
    return result


# ---------------------------------------------------------------------------
# Positional matchup defense (Matchup Analyzer's "how does this team defend
# guards/forwards/centers" breakdown) - built entirely on top of
# data.loaders.load_team_opponent_game_logs, which scopes the underlying API
# fan-out to only the teams actually played (not all of D-I) - see that
# function's docstring for the full cost/architecture rationale.
# ---------------------------------------------------------------------------

_GUARD_TOKENS = {'PG', 'SG', 'G'}
_FORWARD_TOKENS = {'SF', 'PF', 'F'}
_CENTER_TOKENS = {'C'}
_POSITION_ORDER = {'Guard': 0, 'Forward': 1, 'Center': 2}


def position_bucket(position):
    """
    Normalizes a roster position string into Guard/Forward/Center. CBBD's
    /teams/roster 'position' field granularity was NOT confirmed live this
    pass (this sandbox's network policy blocked reaching the API to check
    it directly, unlike every other field in this app, which was checked
    live before being relied on - see HANDOFF.md) - handles both a simple
    G/F/C scheme and a detailed PG/SG/SF/PF/C scheme via exact-token
    matching, then falls back to substring/combo-string handling (e.g.
    'Guard', 'F-C') for anything else. Unrecognized or missing values
    return 'Unknown' and are EXCLUDED from the positional summary below
    (never force-bucketed and silently wrong) - verify this against a real
    payload before trusting the buckets, per the module-level caveat.
    """
    if position is None or (isinstance(position, float) and pd.isna(position)):
        return 'Unknown'
    p = str(position).strip().upper()
    if not p:
        return 'Unknown'
    if p in _CENTER_TOKENS:
        return 'Center'
    if p in _GUARD_TOKENS:
        return 'Guard'
    if p in _FORWARD_TOKENS:
        return 'Forward'
    if 'CENTER' in p:
        return 'Center'
    if 'GUARD' in p:
        return 'Guard'
    if 'FORWARD' in p:
        return 'Forward'
    first_token = p.replace('-', '/').split('/')[0].strip()
    if first_token in _CENTER_TOKENS:
        return 'Center'
    if first_token in _GUARD_TOKENS:
        return 'Guard'
    if first_token in _FORWARD_TOKENS:
        return 'Forward'
    return 'Unknown'


def positional_defense_summary(matchup_df, position_map):
    """
    Buckets every opposing player-game in `matchup_df` (data.loaders.
    load_team_opponent_game_logs output for one team) by position - via
    `position_map`: {athleteSourceId: position_bucket_string}, built by the
    caller from each opponent's roster (see ui.tabs.matchup_analyzer) - and
    aggregates: games faced, mean points/rebounds/assists ALLOWED to that
    position bucket, and the mean delta vs. those same players' own season
    averages (positive = that bucket is outperforming their normal
    production against this team specifically - the "should I worry about
    their guards" readout). Returns a DataFrame sorted Guard/Forward/
    Center, or empty if there's nothing to summarize.
    """
    if matchup_df is None or matchup_df.empty:
        return pd.DataFrame()
    work = matchup_df.copy()
    work['Bucket'] = work['athleteSourceId'].astype(str).map(position_map).fillna('Unknown')
    work = work[work['Bucket'] != 'Unknown']
    if work.empty:
        return pd.DataFrame()
    for stat in ('Points', 'Rebounds', 'Assists'):
        work[f'{stat} Delta'] = pd.to_numeric(work[stat], errors='coerce') - pd.to_numeric(work[f'Season Avg {stat}'], errors='coerce')
    grouped = work.groupby('Bucket').agg(
        Games=('Player', 'count'),
        **{'Points Allowed': ('Points', 'mean'), 'Points Delta': ('Points Delta', 'mean')},
        **{'Rebounds Allowed': ('Rebounds', 'mean'), 'Rebounds Delta': ('Rebounds Delta', 'mean')},
        **{'Assists Allowed': ('Assists', 'mean'), 'Assists Delta': ('Assists Delta', 'mean')},
    ).reset_index()
    grouped['_order'] = grouped['Bucket'].map(_POSITION_ORDER).fillna(9)
    return grouped.sort_values('_order').drop(columns='_order').reset_index(drop=True)


def positional_defense_trend(matchup_df, position_map, bucket, stat='Points'):
    """
    Chronological per-GAME-DATE series of `stat` allowed to one position
    bucket (mean across however many of that bucket's players played that
    date, for the rare case of facing two guards in the same game) - the
    'trending up or down over the season' line chart. Returns (dates,
    values), both empty if this bucket never faced this team.
    """
    if matchup_df is None or matchup_df.empty:
        return [], []
    work = matchup_df.copy()
    work['Bucket'] = work['athleteSourceId'].astype(str).map(position_map).fillna('Unknown')
    sub = work[work['Bucket'] == bucket]
    if sub.empty or stat not in sub.columns:
        return [], []
    sub = sub.copy()
    sub[stat] = pd.to_numeric(sub[stat], errors='coerce')
    by_date = sub.dropna(subset=[stat]).groupby('Date')[stat].mean().sort_index()
    if by_date.empty:
        return [], []
    return by_date.index.tolist(), by_date.values.tolist()


# ---------------------------------------------------------------------------
# Team defense profile (general shooting/rebounding rates ALLOWED, vs D-I -
# the Bart Torvik-style "who is this defense" contrast, complementing Four
# Factors with the shot-selection-specific columns Four Factors doesn't
# cover: 3PA rate allowed and opponent 3P%).
# ---------------------------------------------------------------------------

# (label, stats_df column, higher-is-better?, is a percentage?, help text) -
# powers team_defense_profile_rows below (Matchup Analyzer's TEAM DEFENSE
# panel). Pace is listed first and isn't itself "good/bad" defense the way
# every ALLOWED-rate stat after it is - `higher_is_better=True` here just
# means the percentile bar tracks the RAW pace value directly (fast team ->
# long/high-colored bar), not a claim that fast is the "better" tempo -
# every other stat's direction below is a real defensive-quality claim,
# this one is purely descriptive context for reading them (a fast team
# concedes more raw points/rebounds/assists per game than its per-
# possession rates alone would suggest, just from extra possessions).
_TEAM_DEFENSE_METRICS = [
    ('Pace', 'Pace', True, False, "Possessions per 40 minutes — tempo, not quality. Shows whether this team plays fast or slow relative to D-I; a fast pace means more raw possessions (and more raw points/rebounds/assists) to defend per game, even at identical per-possession rates."),
    ('eFG% Allowed', 'Def eFG%', False, True, "Effective field goal % allowed to opponents — lower is better defense."),
    ('3PA Rate Allowed', 'Def 3PA Rate', False, True, "Share of opponent field goal attempts that are threes — lower means this defense forces/contests more twos relative to threes."),
    ('3P% Allowed', 'Def 3P%', False, True, "Opponent three-point percentage against this team — lower is better three-point defense."),
    ('2P% Allowed', 'Def 2P%', False, True, "Opponent two-point field goal percentage against this team — lower is better interior/mid-range defense."),
    ('FT Rate Allowed', 'Def FT Rate', False, True, "Opponent free throw attempts relative to their own field goal attempts — lower means fouling less / sending opponents to the line less often."),
    ('Off. Reb % Allowed', 'Def ORB%', False, True, "Opponent offensive rebound rate — lower means this defense boxes out better."),
    ('Def. Reb %', 'Def DREB%', True, True, "This team's own defensive rebound rate (complement of Off. Reb % Allowed) — higher is better."),
    ('TO Ratio Forced', 'Def TO Ratio', True, False, "Turnovers forced per possession — higher is better defense."),
]


def team_defense_profile_rows(stats_df, team):
    """
    Single-team defensive-shape percentile rows, ready for
    ui.charts.render_relative_bars (the same single-sided bar-plus-value
    treatment Player Search uses for a player's own tendency profile) - Pace
    (context, not a quality claim - see _TEAM_DEFENSE_METRICS) plus eFG%/
    3PA rate/3P%/2P%/FT rate/ORB% allowed, this team's own DREB%, and TO
    ratio forced, D-I percentile per column with the correct better-
    direction baked in (an ALLOWED rate/percentage is good when LOW; DREB%
    and TO ratio forced are good when HIGH). Powers Matchup Analyzer's TEAM
    DEFENSE panel (one team at a time, not team-vs-team, so a single-sided
    bar is the right shape here, not a mirrored one) - Pace renders inline
    in this same bar list rather than as a separate metric, per explicit
    request ("a number isn't telling... it can be inline with the other
    stats" - a bare `st.metric` doesn't show where the value falls in the
    D-I distribution the way a percentile bar does).
    Returns [] if `team` isn't found.
    """
    row = stats_df[stats_df['Team'] == team]
    if row.empty:
        return []
    row = row.iloc[0]
    rows = []
    for label, col, higher_is_better, is_pct, help_text in _TEAM_DEFENSE_METRICS:
        if col not in stats_df.columns:
            continue
        val = row[col]
        value_str = f"{val:.1f}{'%' if is_pct else ''}" if pd.notna(val) else '--'
        dist = pd.to_numeric(stats_df[col], errors='coerce').dropna()
        pct = pct_rank(dist, val, higher_is_better=higher_is_better)
        avg_pct = pct_rank(dist, dist.mean(), higher_is_better=higher_is_better) if not dist.empty else None
        rows.append({'label': label, 'help': help_text, 'value_str': value_str, 'pct': pct, 'avg_pct': avg_pct})
    return rows


# ---------------------------------------------------------------------------
# Predictive Analytics: Matchup Advantage engine.
#
# Six composite metrics - Scheme Fingerprint, Efficiency Elasticity Curve,
# Composite Matchup Advantage Score, Rim-Pressure & Foul-Leverage
# Exploitation, Game-Script Sensitivity, and Positional Leverage - built
# entirely from data this app already loads: team-level shooting/Four-
# Factors profile allowed rates (load_all_team_season_stats), adjusted
# efficiency ratings (load_efficiency_ratings), the existing positional-
# matchup-defense breakdown (positional_defense_summary, just above), and a
# player's own season stats/game log (get_player_season_profile).
#
# Deliberately NOT possession-level or shot-location-based: this app has no
# play-by-play, shot-chart, or lineup/on-off tracking data (see
# DATA_SOURCES.md), so nothing here claims to identify a literal defensive
# coverage (e.g. "drop coverage on a ball screen"). Every metric below is an
# explicitly-labeled PROXY inferred from aggregate allowed-rate stats and a
# player's own game-to-game variance - each function's docstring spells out
# the exact formula so a reader can see what assumption produced a given
# number, not just trust an opaque score. Weights throughout are a
# transparent, documented design choice, NOT fit/tuned against historical
# matchup outcomes - no such labeled dataset exists to fit against (a real,
# named limitation, not glossed over).
#
# Every function here is pure local compute over already-loaded DataFrames/
# dicts (same layering discipline as the rest of this file) - no loader/API
# calls happen anywhere below.
# ---------------------------------------------------------------------------

_POSITION_BUCKETS = ('Guard', 'Forward', 'Center')

_MATCHUP_TIER_THRESHOLDS = (
    (70, 'Strong Edge'), (55, 'Slight Edge'), (45, 'Neutral'),
    (30, 'Slight Disadvantage'), (0, 'Tough Matchup'),
)


def _matchup_tier_label(score):
    for threshold, label in _MATCHUP_TIER_THRESHOLDS:
        if score >= threshold:
            return label
    return _MATCHUP_TIER_THRESHOLDS[-1][1]


def scheme_fingerprint(team_stats_df, team, positional_summary_df):
    """
    Metric 1 - Scheme Fingerprint (positional vulnerability index).

    Infers a defense's shot-profile "tendency" from two D-I-wide percentiles
    computed off team_stats_df (data.loaders.load_all_team_season_stats):
      - rim_pressure_pct: mean D-I percentile of Def 2P% allowed, Def FT
        Rate allowed, and Opp Paint Pts % allowed (higher = this defense
        concedes MORE interior/rim scoring than a typical D-I defense - a
        proxy for a defense that sags/drops rather than pressuring at the
        level of a ball screen, NOT a literal coverage classification we
        can actually observe without play-by-play).
      - perimeter_openness_pct: mean D-I percentile of Def 3PA Rate allowed
        and Def 3P% allowed (higher = concedes more/better three-point
        volume than typical - a proxy for over-helping or switch/closeout
        breakdowns, again inferred, not observed).

    Then, per position bucket present in positional_summary_df (Guard/
    Forward/Center - this function's sibling positional_defense_summary's
    own output, already scoped to THIS opponent team), blends those two
    team-wide tendencies with the bucket-specific 'Points Delta' (how much
    that bucket has outscored ITS OWN season average specifically against
    this team) into one 0-100 Vulnerability Score:
        delta_score   = clip(50 + Points Delta * 4, 0, 100)
        vulnerability = 0.45*delta_score + 0.30*rim_pressure_pct
                       + 0.25*perimeter_openness_pct
    (renormalized over whichever of the three components are available -
    e.g. a bucket with no Points Delta yet still gets a score from the two
    team-wide components alone). `delta_score`'s "+4 pts per point of
    delta, centered at 50" is a deliberately simple, transparent linear
    transform - not a real D-I-wide percentile of positional deltas, which
    would require computing this same breakdown for all 360+ teams (out of
    scope/cost - CBBD's positional data is already the expensive part of
    this app, see DATA_SOURCES.md's API budget section).

    Returns {} if `team` isn't in team_stats_df. `buckets` is {} (not
    missing) if positional_summary_df has no usable rows - the two team-
    wide percentiles are still returned on their own in that case.
    """
    if team_stats_df is None or team_stats_df.empty:
        return {}
    row = team_stats_df[team_stats_df['Team'] == team]
    if row.empty:
        return {}
    row = row.iloc[0]

    def _team_pct(col):
        if col not in team_stats_df.columns:
            return None
        return pct_rank(team_stats_df[col], row.get(col), higher_is_better=True)

    rim_components = [c for c in (_team_pct('Def 2P%'), _team_pct('Def FT Rate'), _team_pct('Opp Paint Pts %')) if c is not None]
    perim_components = [c for c in (_team_pct('Def 3PA Rate'), _team_pct('Def 3P%')) if c is not None]
    rim_pressure_pct = (sum(rim_components) / len(rim_components)) if rim_components else None
    perimeter_openness_pct = (sum(perim_components) / len(perim_components)) if perim_components else None

    buckets = {}
    if positional_summary_df is not None and not positional_summary_df.empty:
        for _, r in positional_summary_df.iterrows():
            bucket = r.get('Bucket')
            if bucket not in _POSITION_BUCKETS:
                continue
            delta = r.get('Points Delta')
            delta_score = None
            if pd.notna(delta):
                delta_score = max(0.0, min(100.0, 50 + float(delta) * 4))
            parts, weights = [], []
            if delta_score is not None:
                parts.append(delta_score); weights.append(0.45)
            if rim_pressure_pct is not None:
                parts.append(rim_pressure_pct); weights.append(0.30)
            if perimeter_openness_pct is not None:
                parts.append(perimeter_openness_pct); weights.append(0.25)
            vulnerability = (sum(p * w for p, w in zip(parts, weights)) / sum(weights)) if parts else None
            buckets[bucket] = {
                'vulnerability': round(vulnerability, 1) if vulnerability is not None else None,
                'points_delta': round(float(delta), 1) if pd.notna(delta) else None,
                'delta_score': round(delta_score, 1) if delta_score is not None else None,
                'games': int(r['Games']) if pd.notna(r.get('Games')) else None,
                'points_allowed': round(float(r['Points Allowed']), 1) if pd.notna(r.get('Points Allowed')) else None,
            }
    return {
        'team': team,
        'rim_pressure_pct': round(rim_pressure_pct, 1) if rim_pressure_pct is not None else None,
        'perimeter_openness_pct': round(perimeter_openness_pct, 1) if perimeter_openness_pct is not None else None,
        'buckets': buckets,
    }


def positional_leverage(fingerprint, player_bucket):
    """
    Metric 6 - Positional Leverage / Mismatch Hunting Score.

    Ranks the opponent's position-bucket Vulnerability Scores
    (scheme_fingerprint's 'buckets') from most to least exploitable, and
    reports where the selected player's OWN bucket falls in that ranking,
    plus how much more (or less) vulnerable it is than the other buckets'
    average - "is this matchup actually pointed at the defense's real weak
    spot, or somewhere it's fine." Returns {} if the fingerprint has no
    scored buckets or the player's own bucket isn't one of them (e.g. an
    'Unknown' position that positional_defense_summary already excludes).
    """
    buckets = (fingerprint or {}).get('buckets') or {}
    scored = {b: v['vulnerability'] for b, v in buckets.items() if v.get('vulnerability') is not None}
    if not scored or player_bucket not in scored:
        return {}
    ranked = sorted(scored.items(), key=lambda kv: kv[1], reverse=True)
    rank = next(i for i, (b, _v) in enumerate(ranked, start=1) if b == player_bucket)
    others = [v for b, v in scored.items() if b != player_bucket]
    avg_other = (sum(others) / len(others)) if others else None
    edge_vs_avg = (scored[player_bucket] - avg_other) if avg_other is not None else None
    return {
        'player_bucket': player_bucket,
        'rank': rank,
        'of': len(ranked),
        'weakest_bucket': ranked[0][0],
        'weakest_score': ranked[0][1],
        'edge_vs_avg': round(edge_vs_avg, 1) if edge_vs_avg is not None else None,
        'ranked': ranked,
        'is_weakest': rank == 1,
    }


def usage_weighted_efficiency(player_values, group_rate_df):
    """
    Composite Matchup Advantage Score input - Usage-Weighted Efficiency.

    A player's TS% edge over the comparison group's average, scaled by how
    large a share of their team's possessions they command:
        edge = (player TS% - group mean TS%) * (player Usage% / 100)
    A modest efficiency edge at a high usage rate counts for more than the
    same edge at a low usage rate (it touches more of the offense) - the
    same intuition as a points-produced-above-average rate, without needing
    play-by-play on/off tracking to compute it. Percentile-ranked against
    the SAME edge computed for every player in group_rate_df (data.
    transforms.player_rate_stats' output - not raw TS% alone), so what
    actually gets ranked is "how much value is this player creating with
    the possessions they're given," not efficiency in isolation.

    Returns {} if TS%/Usage% aren't available for the player, or the group
    is empty/missing those columns.
    """
    if not player_values or group_rate_df is None or group_rate_df.empty:
        return {}
    ts = player_values.get('TS%')
    usage = player_values.get('Usage %')
    if ts is None or usage is None or pd.isna(ts) or pd.isna(usage):
        return {}
    if 'TS%' not in group_rate_df.columns or 'Usage %' not in group_rate_df.columns:
        return {}
    group_ts = pd.to_numeric(group_rate_df['TS%'], errors='coerce')
    group_usage = pd.to_numeric(group_rate_df['Usage %'], errors='coerce')
    group_mean_ts = group_ts.mean()
    if pd.isna(group_mean_ts):
        return {}
    edge = (float(ts) - float(group_mean_ts)) * (float(usage) / 100.0)
    group_edge = (group_ts - group_mean_ts) * (group_usage / 100.0)
    pct = pct_rank(group_edge.dropna(), edge, higher_is_better=True)
    return {'edge': round(edge, 2), 'pct': pct, 'group_mean_ts': round(float(group_mean_ts), 1)}


def rim_foul_leverage_score(player_values, group_rate_df, team_stats_df, opponent_team):
    """
    Metric 4 - Rim-Pressure & Foul-Leverage Exploitation Score.

    Blends the player's own FT Rate and 2PT Rate percentiles (within
    group_rate_df - how often they get to the line relative to their own
    field goal attempts, and how much of their own shot diet is two-point/
    interior) with the opponent's Def FT Rate ALLOWED percentile (how
    foul-prone this defense is D-I-wide - higher means more free trips to
    the line against them, independent of who's shooting):
        score = 0.35 * player FT Rate pctl
              + 0.25 * player 2PT Rate pctl
              + 0.40 * opponent Def FT Rate allowed pctl
    (renormalized over whichever components are actually available).
    Returns {} if none of the three components can be computed.
    """
    components, weights, detail = [], [], {}
    if player_values and group_rate_df is not None and not group_rate_df.empty and 'FT Rate' in group_rate_df.columns:
        ft_rate = player_values.get('FT Rate')
        if ft_rate is not None and pd.notna(ft_rate):
            pct = pct_rank(group_rate_df['FT Rate'], ft_rate, higher_is_better=True)
            if pct is not None:
                components.append(pct); weights.append(0.35); detail['player_ft_rate_pct'] = round(pct, 1)
    if player_values and group_rate_df is not None and not group_rate_df.empty and '2PT Rate' in group_rate_df.columns:
        two_rate = player_values.get('2PT Rate')
        if two_rate is not None and pd.notna(two_rate):
            pct = pct_rank(group_rate_df['2PT Rate'], two_rate, higher_is_better=True)
            if pct is not None:
                components.append(pct); weights.append(0.25); detail['player_2pt_rate_pct'] = round(pct, 1)
    if team_stats_df is not None and not team_stats_df.empty and 'Def FT Rate' in team_stats_df.columns:
        opp_row = team_stats_df[team_stats_df['Team'] == opponent_team]
        if not opp_row.empty:
            opp_ft = opp_row.iloc[0].get('Def FT Rate')
            pct = pct_rank(team_stats_df['Def FT Rate'], opp_ft, higher_is_better=True)
            if pct is not None:
                components.append(pct); weights.append(0.40); detail['opponent_def_ft_rate_pct'] = round(pct, 1)
    if not components:
        return {}
    score = sum(c * w for c, w in zip(components, weights)) / sum(weights)
    detail['score'] = round(score, 1)
    return detail


def efficiency_elasticity(player_games, eff_ratings_df, team_stats_df, opponent_team, min_games=5):
    """
    Metric 2 - Efficiency Elasticity Curve.

    Fits how a player's own scoring efficiency moves as a function of
    opponent defensive strength and pace, purely from their own game log
    this season - a straight-line fit over already-played games, no
    external model and no play-by-play. For each game with a resolvable
    opponent:
      - game efficiency: True Shooting % (Points / (2*(FGA + 0.44*FTA)) *
        100) when that game log carries a free-throw split, else effective
        FG% ((FGM + 0.5*3PM) / FGA * 100) as a documented fallback - CBBD's
        per-game log (data.loaders.load_player_game_logs) has no FTA/FTM
        columns, only the ESPN-native box file does (see data.loaders.
        _fetch_espn_season_box_raw_cached), so which formula applies
        depends entirely on which source produced `player_games`.
      - opponent quality: that game's Opponent resolved against
        eff_ratings_df/team_stats_df (both D-I-wide, CBBD-sourced), then
        Def Rating percentile (LOWER Def Rating assumed better defense -
        the standard adjusted-efficiency-rating convention, e.g. KenPom's
        AdjD - not independently confirmed against CBBD's own docs; see
        HANDOFF.md's standing network-access caveat) and Pace percentile.
    A simple least-squares line (numpy.polyfit, degree 1) is fit for
    efficiency vs. defense percentile and efficiency vs. pace percentile
    across every resolvable game - the slope is directly "efficiency points
    gained or lost per percentile-point of opponent quality/pace," not a
    black box. That defense-percentile slope is then applied to project an
    efficiency adjustment for THIS specific opponent, relative to the
    percentile of defense this player has faced on average this season.

    Requires at least `min_games` games with a resolvable opponent AND a
    computable efficiency value; returns {} otherwise (a 2-3 game fit is
    too noisy for a slope to mean anything).
    """
    if player_games is None or player_games.empty or team_stats_df is None or team_stats_df.empty \
            or eff_ratings_df is None or eff_ratings_df.empty:
        return {}
    if 'Opponent' not in player_games.columns or 'FGA' not in player_games.columns or 'Points' not in player_games.columns:
        return {}
    canonical = team_stats_df['Team'].dropna().tolist()
    work = player_games.copy()
    work['_opp_resolved'] = work['Opponent'].apply(lambda o: resolve_team_name(o, canonical) if pd.notna(o) else None)
    work = work.dropna(subset=['_opp_resolved'])
    if work.empty:
        return {}

    fga = pd.to_numeric(work['FGA'], errors='coerce')
    pts = pd.to_numeric(work['Points'], errors='coerce')
    has_fta = 'FTA' in work.columns and pd.to_numeric(work['FTA'], errors='coerce').notna().any()
    if has_fta:
        fta = pd.to_numeric(work['FTA'], errors='coerce').fillna(0)
        denom = 2 * (fga + 0.44 * fta)
        work['_eff'] = (pts / denom.where(denom > 0)) * 100
        efficiency_label = 'TS%'
    elif 'FGM' in work.columns:
        fgm = pd.to_numeric(work['FGM'], errors='coerce')
        tpm = pd.to_numeric(work['3PM'], errors='coerce').fillna(0) if '3PM' in work.columns else 0
        work['_eff'] = ((fgm + 0.5 * tpm) / fga.where(fga > 0)) * 100
        efficiency_label = 'eFG%'
    else:
        return {}
    work = work.replace([np.inf, -np.inf], np.nan).dropna(subset=['_eff'])
    if work.empty:
        return {}

    def_dist = pd.to_numeric(eff_ratings_df['Def Rating'], errors='coerce')
    pace_dist = pd.to_numeric(team_stats_df['Pace'], errors='coerce')
    eff_by_team = eff_ratings_df.set_index('Team')['Def Rating']
    pace_by_team = team_stats_df.set_index('Team')['Pace']

    work['_def_pctl'] = work['_opp_resolved'].apply(
        lambda opp: pct_rank(def_dist, eff_by_team.get(opp), higher_is_better=False) if opp in eff_by_team.index else None
    )
    work['_pace_pctl'] = work['_opp_resolved'].apply(
        lambda opp: pct_rank(pace_dist, pace_by_team.get(opp), higher_is_better=True) if opp in pace_by_team.index else None
    )
    work = work.dropna(subset=['_def_pctl', '_pace_pctl'])
    if len(work) < min_games:
        return {}

    def _slope(x, y):
        try:
            m, _b = np.polyfit(x.astype(float), y.astype(float), 1)
            return float(m)
        except Exception:
            return None

    slope_def = _slope(work['_def_pctl'], work['_eff'])
    slope_pace = _slope(work['_pace_pctl'], work['_eff'])
    season_avg_eff = float(work['_eff'].mean())
    mean_def_pctl_faced = float(work['_def_pctl'].mean())

    opp_def_rating = eff_by_team.get(opponent_team)
    opp_def_pctl = pct_rank(def_dist, opp_def_rating, higher_is_better=False) if opp_def_rating is not None else None
    opp_pace = pace_by_team.get(opponent_team)
    opp_pace_pctl = pct_rank(pace_dist, opp_pace, higher_is_better=True) if opp_pace is not None else None

    projected_adjustment = projected_eff = None
    if opp_def_pctl is not None and slope_def is not None:
        projected_adjustment = slope_def * (opp_def_pctl - mean_def_pctl_faced)
        projected_eff = season_avg_eff + projected_adjustment

    bins = [-0.01, 33.34, 66.67, 100.01]
    tier_labels = ['vs Weaker Defenses', 'vs Average Defenses', 'vs Top-Tier Defenses']
    work['_def_tier'] = pd.cut(work['_def_pctl'], bins=bins, labels=tier_labels)
    bucket_means = {}
    for lbl in tier_labels:
        sub = work.loc[work['_def_tier'] == lbl, '_eff']
        if len(sub):
            bucket_means[lbl] = {'mean': round(float(sub.mean()), 1), 'games': int(len(sub))}

    return {
        'efficiency_label': efficiency_label,
        'n_games': int(len(work)),
        'season_avg_eff': round(season_avg_eff, 1),
        'slope_vs_defense': round(slope_def, 3) if slope_def is not None else None,
        'slope_vs_pace': round(slope_pace, 3) if slope_pace is not None else None,
        'bucket_means': bucket_means,
        'opponent_def_pctl': round(opp_def_pctl, 1) if opp_def_pctl is not None else None,
        'opponent_pace_pctl': round(opp_pace_pctl, 1) if opp_pace_pctl is not None else None,
        'projected_adjustment': round(projected_adjustment, 1) if projected_adjustment is not None else None,
        'projected_eff': round(projected_eff, 1) if projected_eff is not None else None,
    }


def game_script_sensitivity(player_games, team_games, stat_col='Points', close_margin=8, min_games=3):
    """
    Metric 5 - Game-Script Sensitivity Index.

    A coarser proxy than true live win-probability/score-by-time tracking,
    which this app doesn't have (no play-by-play source - see this
    feature's own brainstorm caveat): buckets a player's games by their
    TEAM's final margin (Close: |Margin| <= close_margin; Decided:
    everything else, win or loss) via a join on Date ALONE - deliberately
    not Opponent name, since team_games (CBBD-spelled) and player_games
    (which can be ESPN-spelled) don't always agree on spelling, but a team
    plays at most one game per date, so Date is an unambiguous, source-
    agnostic join key.

    Reports the mean of `stat_col` in each bucket and a Sensitivity Index:
        (close_game_mean - decided_game_mean) / season_mean * 100
    Positive = produces MORE in close games relative to decided ones
    ("tightens up" when it matters); negative = the reverse (production
    leans on already-decided game time - garbage-time-compiler territory).

    Requires at least `min_games` games in EACH bucket to compute a real
    index; returns {'insufficient_sample': True, ...} with the raw counts
    instead of a misleadingly precise index from a tiny sample. Returns {}
    only if there's no usable data to bucket at all.
    """
    if player_games is None or player_games.empty or team_games is None or team_games.empty:
        return {}
    if stat_col not in player_games.columns or 'Date' not in player_games.columns or 'Margin' not in team_games.columns:
        return {}
    margin_by_date = team_games.dropna(subset=['Date']).drop_duplicates(subset=['Date']).set_index('Date')['Margin']
    work = player_games.copy()
    work['_margin'] = pd.to_numeric(work['Date'].map(margin_by_date), errors='coerce')
    work[stat_col] = pd.to_numeric(work[stat_col], errors='coerce')
    work = work.dropna(subset=['_margin', stat_col])
    if work.empty:
        return {}
    close = work[work['_margin'].abs() <= close_margin]
    decided = work[work['_margin'].abs() > close_margin]
    if len(close) < min_games or len(decided) < min_games:
        return {'insufficient_sample': True, 'n_close': int(len(close)), 'n_decided': int(len(decided))}
    season_mean = float(work[stat_col].mean())
    close_mean = float(close[stat_col].mean())
    decided_mean = float(decided[stat_col].mean())
    index = ((close_mean - decided_mean) / season_mean * 100) if season_mean else None
    return {
        'stat': stat_col, 'season_mean': round(season_mean, 1),
        'close_mean': round(close_mean, 1), 'decided_mean': round(decided_mean, 1),
        'n_close': int(len(close)), 'n_decided': int(len(decided)),
        'sensitivity_index': round(index, 1) if index is not None else None,
    }


def composite_matchup_advantage(usage_weighted_pct, positional_vulnerability_pct, rim_foul_pct, pace_pct):
    """
    Metric 3 - Composite Matchup Advantage Score.

    Single 0-100 score (plus a plain-language tier label) blending four
    already-computed percentiles/scores for this specific player-vs-team
    matchup:
        35% Usage-Weighted Efficiency percentile (usage_weighted_efficiency)
        30% Positional Vulnerability score at the player's own bucket
            (scheme_fingerprint's per-bucket 'vulnerability')
        20% Rim-Pressure & Foul-Leverage score (rim_foul_leverage_score)
        15% Opponent Pace percentile (more possessions -> more chances for
            whatever edge exists above to actually show up in a box score)
    Missing components are dropped and the remaining weights renormalized
    (e.g. a player with no resolvable elasticity/game-log history still
    gets a composite score from the other three) - only returns {} if
    every single component is missing. Weights are a documented,
    transparent design choice, NOT fit/tuned against historical matchup
    outcomes (no such labeled dataset exists) - shown in the UI's radar
    chart broken out by component so nothing here is a black box.
    """
    components = {
        'usage_weighted_pct': (usage_weighted_pct, 0.35),
        'positional_vulnerability_pct': (positional_vulnerability_pct, 0.30),
        'rim_foul_pct': (rim_foul_pct, 0.20),
        'pace_pct': (pace_pct, 0.15),
    }
    parts = [(v, w) for v, w in components.values() if v is not None and pd.notna(v)]
    if not parts:
        return {}
    score = max(0.0, min(100.0, sum(v * w for v, w in parts) / sum(w for _v, w in parts)))
    return {
        'score': round(score, 1),
        'tier': _matchup_tier_label(score),
        'components': {k: (round(v, 1) if v is not None and pd.notna(v) else None) for k, (v, _w) in components.items()},
    }


def matchup_projection_band(values, composite_score, pace_pctile, effect_size=0.20, pace_effect=0.08, min_games=3):
    """
    Range-of-outcomes projection powering the 'Dynamic Probability Curve'
    visualization. NOT a trained statistical model - there is no historical
    matchup-outcome dataset to fit against (same caveat as
    composite_matchup_advantage) - this is a transparent heuristic that
    scales a player's OWN empirical game-to-game distribution this season
    by how favorable this specific matchup grades out:
        floor / median / ceiling = this player's own 10th / 50th / 90th
        percentile game value this season, each multiplied by:
            (1 + (composite_score - 50)/50 * effect_size)   -- matchup edge
          * (1 + (pace_pctile   - 50)/50 * pace_effect)      -- pace/volume
    A composite score of 100 (max edge) scales the projection up by
    `effect_size` above the player's own empirical shape; a composite of 0
    scales it down by the same amount. Both multipliers default to modest,
    explicitly-labeled swings (20%/8%) since this is a heuristic dial, not
    a fitted model - and the combined multiplier is clamped to [0.5, 1.75]
    as a sanity bound against a degenerate combination of extremes.

    Requires at least `min_games` values; returns {} otherwise.
    """
    vals = pd.to_numeric(pd.Series(values), errors='coerce').dropna()
    if len(vals) < min_games:
        return {}
    p10, p50, p90 = (float(x) for x in vals.quantile([0.10, 0.50, 0.90]))
    season_avg = float(vals.mean())
    matchup_mult = 1.0
    if composite_score is not None and pd.notna(composite_score):
        matchup_mult = 1 + ((float(composite_score) - 50) / 50) * effect_size
    pace_mult = 1.0
    if pace_pctile is not None and pd.notna(pace_pctile):
        pace_mult = 1 + ((float(pace_pctile) - 50) / 50) * pace_effect
    total_mult = max(0.5, min(1.75, matchup_mult * pace_mult))
    return {
        'floor': round(max(0.0, p10 * total_mult), 1),
        'median': round(max(0.0, p50 * total_mult), 1),
        'ceiling': round(max(0.0, p90 * total_mult), 1),
        'season_avg': round(season_avg, 1),
        'multiplier': round(total_mult, 3),
        'raw_values': [float(v) for v in vals.tolist()],
        'n_games': int(len(vals)),
    }


def build_matchup_advantage_report(
    player_bucket, player_values, group_rate_df, player_games, team_games,
    opponent_team, team_stats_df, eff_ratings_df, positional_summary_df,
    stat_col='Points',
):
    """
    Orchestrates all six Predictive Analytics metrics (plus the probability-
    band projection) into one report dict for ui.tabs.predictive_analytics
    to render. Pure local compute over already-loaded DataFrames/dicts, same
    layering discipline as every other function in this file - no loader/API
    calls happen here. See each individual metric function's own docstring
    for its formula and caveats; this just resolves the couple of shared
    inputs they all need (the opponent's Pace percentile, the player's own
    bucket's Vulnerability Score) and assembles the results.
    """
    fingerprint = scheme_fingerprint(team_stats_df, opponent_team, positional_summary_df)
    leverage = positional_leverage(fingerprint, player_bucket)
    usage_eff = usage_weighted_efficiency(player_values, group_rate_df)
    rim_foul = rim_foul_leverage_score(player_values, group_rate_df, team_stats_df, opponent_team)
    elasticity = efficiency_elasticity(player_games, eff_ratings_df, team_stats_df, opponent_team)
    game_script = game_script_sensitivity(player_games, team_games, stat_col=stat_col)

    pace_pct = None
    if team_stats_df is not None and not team_stats_df.empty and 'Pace' in team_stats_df.columns:
        opp_row = team_stats_df[team_stats_df['Team'] == opponent_team]
        if not opp_row.empty:
            pace_pct = pct_rank(team_stats_df['Pace'], opp_row.iloc[0].get('Pace'), higher_is_better=True)

    bucket_vuln = (fingerprint.get('buckets') or {}).get(player_bucket, {}).get('vulnerability')
    composite = composite_matchup_advantage(usage_eff.get('pct'), bucket_vuln, rim_foul.get('score'), pace_pct)

    band = {}
    if player_games is not None and not player_games.empty and stat_col in player_games.columns:
        band = matchup_projection_band(
            pd.to_numeric(player_games[stat_col], errors='coerce').dropna().tolist(),
            composite.get('score'), pace_pct,
        )

    return {
        'scheme_fingerprint': fingerprint,
        'positional_leverage': leverage,
        'usage_weighted_efficiency': usage_eff,
        'rim_foul_leverage': rim_foul,
        'efficiency_elasticity': elasticity,
        'game_script_sensitivity': game_script,
        'pace_pct': round(pace_pct, 1) if pace_pct is not None else None,
        'composite': composite,
        'projection_band': band,
        'player_bucket': player_bucket,
        'opponent_team': opponent_team,
        'stat_col': stat_col,
    }
