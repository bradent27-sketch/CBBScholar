"""
Derived/computed data (percentiles, the Four Factors matchup engine, the
tempo-based score projection, form/breakout detection) - the layer between
data/loaders.py's raw ingestion and ui/'s presentation. Everything here is
pure local compute over already-cached loader output: none of these
functions makes an API call of its own.
"""
import pandas as pd


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


# ---------------------------------------------------------------------------
# Team DNA radar profile
# ---------------------------------------------------------------------------

def team_dna_profile(ratings_df, team_stats_df, team):
    """
    Seven-axis percentile profile for ui.charts.render_radar_chart - two
    axes from adjusted efficiency (ratings_df, /ratings/adjusted), five
    from the Four Factors/style sheet (team_stats_df,
    /stats/team/season) - both already full-D-I pulls cached elsewhere in
    the app, so every axis is a real league-wide percentile, not a
    per-matchup one, at zero extra API cost. Ball Security and Takeaways
    are both oriented so higher-on-the-axis always means 'better', even
    though the underlying raw stat (TO Ratio) is 'lower is better' for the
    offense side. Returns (labels, values, help_texts) or None if the team
    is missing from either source.
    """
    er = ratings_df[ratings_df['Team'] == team]
    ts = team_stats_df[team_stats_df['Team'] == team]
    if er.empty or ts.empty:
        return None
    er, ts = er.iloc[0], ts.iloc[0]
    dims = [
        ('Offense', pct_rank(ratings_df['Off Rating'], er['Off Rating'], higher_is_better=True),
         "Adjusted offensive rating percentile — points/100 possessions vs. the D-I average, opponent-adjusted."),
        ('Defense', pct_rank(ratings_df['Def Rating'], er['Def Rating'], higher_is_better=False),
         "Adjusted defensive rating percentile (lower raw rating = better defense, already inverted here)."),
        ('Tempo', pct_rank(team_stats_df['Pace'], ts['Pace'], higher_is_better=True),
         "Possessions per 40 minutes, percentile vs. D-I — style, not a quality judgment; a deliberately slow team scores low here."),
        ('3PT Volume', pct_rank(team_stats_df['3PA Rate'], ts['3PA Rate'], higher_is_better=True),
         "Share of field goal attempts from three, percentile vs. D-I — style, not quality."),
        ('Off. Rebounding', pct_rank(team_stats_df['Off ORB%'], ts['Off ORB%'], higher_is_better=True),
         "Share of the team's own misses that it rebounds, percentile vs. D-I."),
        ('Ball Security', pct_rank(team_stats_df['Off TO Ratio'], ts['Off TO Ratio'], higher_is_better=False),
         "Turnovers per offensive possession, inverted so higher on this axis = fewer turnovers."),
        ('Takeaways', pct_rank(team_stats_df['Def TO Ratio'], ts['Def TO Ratio'], higher_is_better=True),
         "Turnovers forced per defensive possession, percentile vs. D-I — higher = more disruptive defense."),
    ]
    return [d[0] for d in dims], [d[1] for d in dims], [d[2] for d in dims]


# ---------------------------------------------------------------------------
# "What wins" - live correlation of each Four Factor/style stat with
# this season's adjusted Net Rating, across the full D-I field.
# ---------------------------------------------------------------------------

# (display label, team_stats_df column, higher_is_better, help text).
# higher_is_better=None marks a style/tempo stat with no inherent "good"
# direction (pace, shot selection) - its correlation sign is reported as-is
# rather than flipped, and the chart colors it neutrally rather than
# green/red.
WIN_CORRELATES = [
    ('Off eFG%', 'Off eFG%', True, "Effective FG% on offense — the single heaviest Four Factor."),
    ('Def eFG% Allowed', 'Def eFG%', False, "Effective FG% allowed on defense (lower allowed = better D)."),
    ('Off TO Ratio', 'Off TO Ratio', False, "Turnovers per offensive possession (lower = better ball security)."),
    ('Def TO Ratio Forced', 'Def TO Ratio', True, "Turnovers forced per defensive possession (higher = more disruptive)."),
    ('Off ORB%', 'Off ORB%', True, "Share of own misses rebounded."),
    ('Def ORB% Allowed', 'Def ORB%', False, "Opponent offensive rebound rate allowed (lower = better defensive rebounding)."),
    ('Off FT Rate', 'Off FT Rate', True, "Free throw attempts relative to field goal attempts."),
    ('Def FT Rate Allowed', 'Def FT Rate', False, "Opponent FT rate allowed (lower = fouls less)."),
    ('Pace', 'Pace', None, "Possessions per 40 minutes — style, no inherent good/bad direction."),
    ('3PA Rate', '3PA Rate', None, "Share of field goal attempts from three — style."),
    ('Paint Pts %', 'Paint Pts %', None, "Share of points scored in the paint — style."),
    ('Fast Break %', 'Fast Break %', None, "Share of points scored in transition — style."),
]


def stat_win_correlations(team_stats_df, ratings_df, min_n=8):
    """
    Live Pearson correlation of every Four Factors/style column (from the
    already-cached full-D-I /stats/team/season pull) against this season's
    adjusted Net Rating (/ratings/adjusted, also already cached) - zero
    extra API cost, and genuinely recomputed from real current-season data
    rather than a hardcoded assumption about "what wins games." `display_r`
    flips sign for columns whose natural "good" direction is LOWER
    (defensive-allowed stats) so that positive/green always reads "being
    good at this associates with winning" - style/tempo columns keep their
    raw sign and are flagged `neutral`. Returns rows sorted by
    |display_r| descending; a column is skipped if fewer than `min_n` teams
    have both values.
    """
    if team_stats_df is None or team_stats_df.empty or ratings_df is None or ratings_df.empty:
        return []
    merged = team_stats_df.merge(ratings_df[['Team', 'Net Rating']], on='Team', how='inner')
    if merged.empty:
        return []
    y = pd.to_numeric(merged['Net Rating'], errors='coerce')
    rows = []
    for label, col, higher_is_better, help_text in WIN_CORRELATES:
        if col not in merged.columns:
            continue
        x = pd.to_numeric(merged[col], errors='coerce')
        valid = x.notna() & y.notna()
        if valid.sum() < min_n:
            continue
        r = x[valid].corr(y[valid])
        if r is None or pd.isna(r):
            continue
        display_r = r if higher_is_better is not False else -r
        rows.append({
            'label': label,
            'help': help_text,
            'r': float(r),
            'display_r': float(display_r),
            'neutral': higher_is_better is None,
            'n': int(valid.sum()),
        })
    rows.sort(key=lambda d: abs(d['display_r']), reverse=True)
    return rows


# ---------------------------------------------------------------------------
# Season margin trend + volatility/consistency
# ---------------------------------------------------------------------------

ROLE_BALL_HANDLER = 'Ball-Handler'
ROLE_POST = 'Post Player'
ROLE_SHOOTER = 'Shooter'
ROLE_WING = 'Wing/Combo'
ROLE_ORDER = [ROLE_BALL_HANDLER, ROLE_POST, ROLE_SHOOTER, ROLE_WING]


def player_rate_profile(stats):
    """
    Rate-basis tendency profile from one player's raw /stats/player/season
    dict (data.loaders.get_player_season_stats, or any row of
    load_team_player_stats via .to_dict()) - every number here controls for
    playing time or shot volume rather than counting stats, so a bench
    player and a starter with the same TENDENCY read the same even though
    their raw totals don't. This is the "are they a shooter, rebounder,
    passer" question the app previously had no answer for - everything
    else in the app was descriptive percentiles, this is the first
    tendency/role layer. Returns {} if minutes/games are missing (can't
    build a rate off zero playing time).
    """
    if not stats:
        return {}
    games = stats.get('games') or 0
    minutes = stats.get('minutes') or 0
    if not games or not minutes:
        return {}
    fg = stats.get('fieldGoals') or {}
    three = stats.get('threePointFieldGoals') or {}
    ft = stats.get('freeThrows') or {}
    reb = stats.get('rebounds') or {}
    fga = fg.get('attempted') or 0
    turnovers = stats.get('turnovers') or 0
    assists = stats.get('assists') or 0

    def per40(total):
        if total is None:
            return None
        try:
            return float(total) / minutes * 40
        except (TypeError, ZeroDivisionError):
            return None

    return {
        'usage': stats.get('usage'),
        'efg_pct': stats.get('effectiveFieldGoalPct'),
        'ts_pct': stats.get('trueShootingPct'),
        'three_pa_rate': (three.get('attempted') / fga * 100) if fga and three.get('attempted') is not None else None,
        'three_pct': three.get('pct'),
        'ft_rate': (ft.get('attempted') / fga * 100) if fga and ft.get('attempted') is not None else None,
        'ft_pct': ft.get('pct'),
        'ast_per40': per40(assists),
        'reb_per40': per40(reb.get('total')),
        'stl_per40': per40(stats.get('steals')),
        'blk_per40': per40(stats.get('blocks')),
        'pts_per40': per40(stats.get('points')),
        'ast_to_ratio': (assists / turnovers) if turnovers else None,
        'minutes_per_game': (minutes / games) if games else None,
    }


def classify_player_role(rate_profile):
    """
    Single primary offensive role from a rate profile (see
    player_rate_profile above), plus secondary descriptive badges. Fixed,
    basketball-literate thresholds — NOT league-percentile-based, since
    that would need a full-D-I player pull this app deliberately doesn't
    do (360+ extra API calls just to rank one player; see HANDOFF §7's
    "still parked" note). Read this as a heuristic classifier, the same
    "labeled as an estimate" spirit as the Matchup Analyzer's projections,
    not a precise percentile rank.

    Evaluated in priority order so every player gets exactly ONE primary
    role - required so defense-allowed-by-role aggregation (see
    aggregate_defense_by_role) can bucket cleanly without double-counting
    a player who's both a good rebounder AND a decent shooter. Priority:
    a real, high-rate PASSER is a Ball-Handler regardless of usage (a
    pass-first floor general can have modest usage); failing that, a
    high-usage/high-assist combo guard also qualifies. Then: low 3PA rate
    or a heavy rebounding rate reads as playing mostly inside (Post
    Player) - the best proxy available without shot-location data (CBBD
    doesn't have it; see HANDOFF §7). Then: high 3PA rate reads as
    Shooter. Everything else falls to Wing/Combo (secondary scorer, no
    single tendency dominates).

    Returns (primary_role, [secondary_badges]) or (None, []) if the
    profile is empty/too thin.
    """
    if not rate_profile:
        return None, []
    usage = rate_profile.get('usage') or 0
    ast40 = rate_profile.get('ast_per40') or 0
    reb40 = rate_profile.get('reb_per40') or 0
    three_rate = rate_profile.get('three_pa_rate')
    ft_rate = rate_profile.get('ft_rate')
    blk40 = rate_profile.get('blk_per40') or 0
    stl40 = rate_profile.get('stl_per40') or 0
    three_pct = rate_profile.get('three_pct')
    ast_to = rate_profile.get('ast_to_ratio')

    if ast40 >= 5.5 or (usage >= 24 and ast40 >= 3.0):
        primary = ROLE_BALL_HANDLER
    elif (three_rate is not None and three_rate <= 20) or reb40 >= 9:
        primary = ROLE_POST
    elif three_rate is not None and three_rate >= 40:
        primary = ROLE_SHOOTER
    else:
        primary = ROLE_WING

    badges = []
    if reb40 >= 9 and primary != ROLE_POST:
        badges.append('Rebounder')
    if blk40 >= 2.0:
        badges.append('Rim Protector')
    if stl40 >= 2.2:
        badges.append('Disruptor')
    if three_pct is not None and three_pct >= 38 and (three_rate or 0) >= 30 and primary != ROLE_SHOOTER:
        badges.append('Sharpshooter')
    if ft_rate is not None and ft_rate >= 35:
        badges.append('Foul Drawer')
    if ast_to is not None and ast_to >= 2.0 and primary != ROLE_BALL_HANDLER:
        badges.append('Secondary Ball-Handler')

    return primary, badges


# ---------------------------------------------------------------------------
# Defense-allowed-by-role (see data.loaders.load_defense_allowed_by_role for
# how the per-(game, opposing player) rows this consumes get built).
# ---------------------------------------------------------------------------

def aggregate_defense_by_role(role_games_df):
    """
    Per-role PPG/RPG/APG/3PM-per-game allowed, from
    data.loaders.load_defense_allowed_by_role's per-(game, opposing player)
    rows. Averages by GAME, not by player-appearance - a game where two
    different Ball-Handlers both played still divides by 1 game, not 2, so
    "PPG allowed to Ball-Handlers" reads as "how much did the Ball-Handler(s)
    I faced that night combine for," matching how a scout actually reads a
    box score. Returns a DataFrame indexed by Role (Ball-Handler/Post
    Player/Shooter/Wing-Combo order) with Games/Points/Rebounds/Assists/
    Threes-per-game, or empty if the input is empty.
    """
    if role_games_df is None or role_games_df.empty:
        return pd.DataFrame()
    per_game = role_games_df.groupby(['Role', 'Date'], as_index=False).agg(
        Points=('Points', 'sum'), Rebounds=('Rebounds', 'sum'),
        Assists=('Assists', 'sum'), ThreesMade=('ThreesMade', 'sum'),
    )
    summary = per_game.groupby('Role').agg(
        Games=('Date', 'nunique'), PointsG=('Points', 'mean'),
        ReboundsG=('Rebounds', 'mean'), AssistsG=('Assists', 'mean'),
        ThreesG=('ThreesMade', 'mean'),
    )
    summary = summary.rename(columns={
        'PointsG': 'Points/G', 'ReboundsG': 'Rebounds/G',
        'AssistsG': 'Assists/G', 'ThreesG': '3PM/G',
    })
    order = [r for r in ROLE_ORDER if r in summary.index]
    return summary.reindex(order)


def defense_role_game_series(role_games_df, role):
    """
    Chronological per-game totals allowed to ONE role - the trend input for
    ui.charts.render_trend_line (rolling average / game-by-game), so a
    mid-season scheme change or a new-role opposing player shows up in the
    shape of this line before it moves the season aggregate in
    aggregate_defense_by_role. Returns a DataFrame sorted by Date, or empty.
    """
    if role_games_df is None or role_games_df.empty:
        return pd.DataFrame()
    sub = role_games_df[role_games_df['Role'] == role]
    if sub.empty:
        return pd.DataFrame()
    per_game = sub.groupby('Date', as_index=False).agg(
        Points=('Points', 'sum'), Rebounds=('Rebounds', 'sum'),
        Assists=('Assists', 'sum'), ThreesMade=('ThreesMade', 'sum'),
    )
    return per_game.sort_values('Date').reset_index(drop=True)


def margin_volatility(games_df, close_margin=5):
    """
    Season-long scoring-margin descriptives from a team's completed
    schedule (data.loaders.load_team_games): population std dev of margin
    ("volatility" - lower = steadier performance night to night), best/
    worst margins, and the close-game record (games decided by
    `close_margin` points or fewer - the standard "clutch" cut). Returns {}
    if fewer than 2 completed games.
    """
    if games_df is None or games_df.empty:
        return {}
    m = pd.to_numeric(games_df['Margin'], errors='coerce')
    valid = games_df[m.notna()]
    if len(valid) < 2:
        return {}
    mv = pd.to_numeric(valid['Margin'], errors='coerce')
    close = valid[mv.abs() <= close_margin]
    return {
        'std': float(mv.std(ddof=0)),
        'best_margin': int(mv.max()),
        'worst_margin': int(mv.min()),
        'close_wins': int((close['Result'] == 'W').sum()),
        'close_losses': int((close['Result'] == 'L').sum()),
        'close_n': int(len(close)),
    }
