"""
Derived/computed data (percentiles, the Four Factors matchup engine, the
tempo-based score projection, form/breakout detection) - the layer between
data/loaders.py's raw ingestion and ui/'s presentation. Everything here is
pure local compute over already-cached loader output: none of these
functions makes an API call of its own.
"""
import pandas as pd


def player_rate_stats(df, min_games=5):
    """
    Given a wide player-stats DataFrame (one row per player, nested
    fieldGoals/threePointFieldGoals/freeThrows/rebounds dicts - the same
    shape data.loaders.load_team_player_stats returns), compute the flat
    per-game/percentage columns this app displays (PPG, RPG, ... Net
    Rating) as a new DataFrame - the group-level equivalent of
    ui.tabs.compare's per-player _numeric_stat_map, used to build a
    comparison distribution for ui.charts.render_relative_bars. Players
    under `min_games` are dropped from the distribution (not from any
    single-player display elsewhere) so garbage-time/injury-shortened
    small samples don't distort the comparison group's spread.
    """
    if df is None or df.empty or 'games' not in df.columns:
        return pd.DataFrame()
    games_raw = pd.to_numeric(df['games'], errors='coerce')
    work = df[games_raw >= min_games].copy()
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


def four_factors_matchup(stats_df, team_a, team_b):
    """
    Rows for the Four Factors panel: Team A's offensive factor vs what Team
    B's defense allows/forces, percentile-ranked against all of D-I with
    the correct better-direction per side (see FOUR_FACTORS) so both bars
    read "longer = winning this battle." Returns (rows_a_off_vs_b_def,
    rows_b_off_vs_a_def) or (None, None) if either team is missing.
    """
    a = stats_df[stats_df['Team'] == team_a]
    b = stats_df[stats_df['Team'] == team_b]
    if a.empty or b.empty:
        return None, None
    a, b = a.iloc[0], b.iloc[0]

    def rows(off_row, def_row):
        out = []
        for label, off_col, def_col, off_hib, def_hib, help_text in FOUR_FACTORS:
            out.append({
                'label': label,
                'help': help_text,
                'off_val': off_row[off_col],
                'off_pct': pct_rank(stats_df[off_col], off_row[off_col], higher_is_better=off_hib),
                'def_val': def_row[def_col],
                'def_pct': pct_rank(stats_df[def_col], def_row[def_col], higher_is_better=def_hib),
            })
        return out

    return rows(a, b), rows(b, a)


def four_factors_percentile_grid(stats_df, teams=None):
    """
    Team x Four-Factors D-I percentile grid (offense AND defense side of
    each factor - 8 columns), for a league-wide tiering heatmap - the
    "whole league at a glance" complement to four_factors_matchup's
    pairwise (two-team) view above. Reuses FOUR_FACTORS' own column/
    direction mapping so the heatmap and the matchup engine can't silently
    drift apart. teams=None keeps every team in stats_df; pass a list to
    scope to one conference or group.

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
    for _, off_col, def_col, off_hib, def_hib, _help in FOUR_FACTORS:
        cols += [off_col, def_col]
        higher_is_better[off_col], higher_is_better[def_col] = off_hib, def_hib
    raw = work[['Team'] + cols].reset_index(drop=True)
    pct = raw[['Team']].copy()
    for col in cols:
        pct[col] = raw[col].apply(lambda v, c=col: pct_rank(stats_df[c], v, higher_is_better=higher_is_better[c]))
    return pct, raw, cols


def style_profile(stats_df, team_a, team_b):
    """Scoring-style rows (3PA rate, paint share, fast-break share, pace)
    for both teams - descriptive contrast, percentiles vs D-I to show HOW
    each offense generates points, not who is better."""
    a = stats_df[stats_df['Team'] == team_a]
    b = stats_df[stats_df['Team'] == team_b]
    if a.empty or b.empty:
        return None
    a, b = a.iloc[0], b.iloc[0]
    metrics = [
        ('Pace (poss/40)', 'Pace', "Possessions per 40 minutes — tempo, not quality."),
        ('3PA Rate', '3PA Rate', "Share of field goal attempts from three."),
        ('Paint Points %', 'Paint Pts %', "Share of points scored in the paint."),
        ('Fast Break %', 'Fast Break %', "Share of points from the fast break."),
    ]
    out = []
    for label, col, help_text in metrics:
        out.append({
            'label': label,
            'help': help_text,
            'left_val': a[col], 'left_pct': pct_rank(stats_df[col], a[col]),
            'right_val': b[col], 'right_pct': pct_rank(stats_df[col], b[col]),
        })
    return out


# ---------------------------------------------------------------------------
# Tempo-based score projection
# ---------------------------------------------------------------------------

def project_score(eff_df, stats_df, team_a, team_b, hfa_margin=0.0):
    """
    Projected final score from adjusted efficiency + tempo. Standard
    log5-style additive model on the points-per-100-possessions scale:

        A's expected pts/100 = A Off Rating + B Def Rating - league average
        possessions = mean(pace A, pace B)  (both already per 40 minutes)
        score = pts/100 x possessions / 100, HFA split across the two sides

    Returns {'score_a', 'score_b', 'possessions', 'total'} or None if any
    input is missing. Ratings come from /ratings/adjusted (opponent-
    adjusted), pace from /stats/team/season (raw) - a knowingly mixed pair,
    labeled an estimate in the UI like every model number in this app.
    """
    ea = eff_df[eff_df['Team'] == team_a]
    eb = eff_df[eff_df['Team'] == team_b]
    sa = stats_df[stats_df['Team'] == team_a]
    sb = stats_df[stats_df['Team'] == team_b]
    if ea.empty or eb.empty or sa.empty or sb.empty:
        return None
    ea, eb = ea.iloc[0], eb.iloc[0]
    pace_a, pace_b = sa.iloc[0]['Pace'], sb.iloc[0]['Pace']
    if pd.isna(pace_a) or pd.isna(pace_b):
        return None
    league_off = pd.to_numeric(eff_df['Off Rating'], errors='coerce').mean()
    poss = (float(pace_a) + float(pace_b)) / 2
    pts100_a = float(ea['Off Rating']) + float(eb['Def Rating']) - league_off
    pts100_b = float(eb['Off Rating']) + float(ea['Def Rating']) - league_off
    score_a = pts100_a * poss / 100 + hfa_margin / 2
    score_b = pts100_b * poss / 100 - hfa_margin / 2
    return {
        'score_a': score_a,
        'score_b': score_b,
        'possessions': poss,
        'total': score_a + score_b,
    }


# ---------------------------------------------------------------------------
# Poll trajectory + recent form
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


def recent_form(games_df, n=5):
    """Last-n completed games as chip dicts for render_form_strip, plus the
    Elo change across the window."""
    if games_df is None or games_df.empty:
        return [], None
    tail = games_df.tail(n)
    chips = [{
        'result': g['Result'],
        'margin': g['Margin'],
        'opponent': g['Opponent'],
        'venue': g['Home/Away'],
        'score': f"{g['PF']}-{g['PA']}",
    } for _, g in tail.iterrows()]
    elos = pd.to_numeric(games_df['Elo End'], errors='coerce').dropna()
    elo_delta = None
    if len(elos) >= 2:
        window = elos.tail(n)
        if len(window) >= 2:
            elo_delta = float(window.iloc[-1] - window.iloc[0])
    return chips, elo_delta


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


# ---------------------------------------------------------------------------
# Player tendency profile (shared vocabulary between Player Search and
# Matchup Analyzer's Player Trends, so the two don't compute the same
# shooting-rate/rebounding numbers two different ways and silently drift).
# ---------------------------------------------------------------------------

_PCT_SUFFIX_LABELS = {'3PT Rate', '2PT Rate', 'FT Rate'}


def player_profile_values(stats):
    """
    Flat {label: raw_value} for one player's season stat dict (the shape
    data.loaders.get_player_season_stats returns) - PPG/RPG/rebound split/
    APG/shooting splits/shot-selection rates/efficiency/usage. Returns {}
    if `stats` is falsy or the player has no games played.
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

    return {
        'PPG': per_game(stats.get('points')),
        'RPG': per_game(reb.get('total')),
        'ORB/G': per_game(reb.get('offensive')),
        'DRB/G': per_game(reb.get('defensive')),
        'APG': per_game(stats.get('assists')),
        'SPG': per_game(stats.get('steals')),
        'BPG': per_game(stats.get('blocks')),
        'MPG': per_game(stats.get('minutes')),
        'FG%': fg.get('pct'),
        '3P%': three.get('pct'),
        'FT%': ft.get('pct'),
        '3PT Rate': rate(tpa, fga),
        '2PT Rate': rate(twa, fga),
        'FT Rate': rate(fta, fga),
        'eFG%': stats.get('effectiveFieldGoalPct'),
        'TS%': (ts_pct * 100) if ts_pct is not None else None,
        'Net Rating': stats.get('netRating'),
        'Usage %': stats.get('usage'),
    }


def player_percentile_rows(stats, group_df, stat_help=None):
    """
    Ready-to-render rows for ui.charts.render_relative_bars: this player's
    raw values (player_profile_values) plus their percentile (and the
    comparison group's own average percentile) against `group_df` - a wide
    player-stats DataFrame (conference or full D-I, whatever the caller
    already loaded via data.loaders). `stat_help`: optional {label: help
    text} - kept as a caller-supplied param rather than baked in here so
    this stays UI-copy-free (data/ layer convention).
    """
    stat_help = stat_help or {}
    values = player_profile_values(stats)
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

def team_defense_profile(stats_df, team_a, team_b):
    """Mirrored defensive-shape rows for both teams - eFG%/3PA rate/3P%/
    ORB% allowed plus this team's own DREB% and TO ratio forced - percentile
    vs D-I with the correct better-direction per column (an ALLOWED rate is
    good when LOW; DREB% and TO ratio forced are good when HIGH)."""
    a = stats_df[stats_df['Team'] == team_a]
    b = stats_df[stats_df['Team'] == team_b]
    if a.empty or b.empty:
        return None
    a, b = a.iloc[0], b.iloc[0]
    metrics = [
        ('eFG% Allowed', 'Def eFG%', False, "Effective field goal % allowed to opponents — lower is better defense."),
        ('3PA Rate Allowed', 'Def 3PA Rate', False, "Share of opponent field goal attempts that are threes — lower means this defense forces/contests more twos relative to threes."),
        ('3P% Allowed', 'Def 3P%', False, "Opponent three-point percentage against this team — lower is better three-point defense."),
        ('Off. Reb % Allowed', 'Def ORB%', False, "Opponent offensive rebound rate — lower means this defense boxes out better."),
        ('Def. Reb %', 'Def DREB%', True, "This team's own defensive rebound rate (complement of Off. Reb % Allowed) — higher is better."),
        ('TO Ratio Forced', 'Def TO Ratio', True, "Turnovers forced per possession — higher is better defense."),
    ]
    out = []
    for label, col, higher_is_better, help_text in metrics:
        if col not in stats_df.columns:
            continue
        out.append({
            'label': label,
            'help': help_text,
            'left_val': a[col], 'left_pct': pct_rank(stats_df[col], a[col], higher_is_better=higher_is_better),
            'right_val': b[col], 'right_pct': pct_rank(stats_df[col], b[col], higher_is_better=higher_is_better),
        })
    return out
