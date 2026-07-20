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
