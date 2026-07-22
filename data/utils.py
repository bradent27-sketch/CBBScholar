"""
Pure, dependency-free helpers shared by data/loaders.py and data/transforms.py.
Ported as-is from NFL Scholar (C:\\FantasyF\\data\\utils.py) / CFB Scholar -
none of this logic is sport-specific (percentile ranking and name-matching
apply to any player/team name pool). Porting this now, before it's needed,
is cheap insurance against re-discovering the same name-formatting bug
class NFL Scholar's own HANDOFF.md flags as its most-repeated one.
"""
import difflib
import re

import pandas as pd


def calculate_percentile(df, col_name, ascending=True):
    if not df.empty and col_name in df.columns:
        return df[col_name].rank(pct=True, ascending=ascending) * 100
    return pd.Series([0] * len(df), index=df.index)


def clean_name_exact(name_series):
    """Lowercase + strip punctuation/spacing, suffixes (Jr./II/III) left
    intact - first-choice match key so two different players who share a
    base name but are distinguished by a real suffix don't collide."""
    return name_series.astype(str).str.lower().str.replace('[^a-z]', '', regex=True)


def clean_name_for_merge(name_series):
    """Looser FALLBACK key (suffixes stripped too) for when clean_name_exact
    fails to match across two sources that are inconsistent about including
    Jr./Sr./II/III. Only ever use as a second-tier fallback after an exact
    -key match attempt, never as the sole key."""
    cleaned = name_series.astype(str).str.lower()
    cleaned = cleaned.str.replace(r'\s+(jr|sr|ii|iii|iv|v)\.?\s*$', '', regex=True)
    cleaned = cleaned.str.replace('[^a-z]', '', regex=True)
    return cleaned


def match_player_name(name, candidates):
    """
    Finds `name`'s position within `candidates` (any name-like list/
    Series) via clean_name_exact first, falling back to
    clean_name_for_merge (handles two sources being inconsistent about
    Jr./Sr./II/III) if that fails. Returns a positional index (`.iloc`-
    ready, regardless of `candidates`' own index), or None if neither key
    matches anything.

    Built specifically to join two ESPN-sourced player lists (ESPN's live
    roster endpoint vs. SportsDataverse's published box-score file) that
    turned out NOT to share a common id despite that being the original
    assumption - `load_espn_roster`'s 'sourceId' and the box file's
    'athleteSourceId' are different id namespaces in practice, even though
    both ultimately trace back to ESPN (confirmed by this exact join
    silently matching nothing for every player - see HANDOFF.md). Name
    matching sidesteps the bad id assumption entirely, the same fix this
    app's CBBD roster/game-log id-namespace gotcha already established as
    the right instinct for this class of problem.
    """
    cand_series = pd.Series(list(candidates))
    key = clean_name_exact(pd.Series([name])).iloc[0]
    exact_keys = clean_name_exact(cand_series)
    hit = exact_keys[exact_keys == key]
    if not hit.empty:
        return int(hit.index[0])
    key2 = clean_name_for_merge(pd.Series([name])).iloc[0]
    loose_keys = clean_name_for_merge(cand_series)
    hit2 = loose_keys[loose_keys == key2]
    return int(hit2.index[0]) if not hit2.empty else None


_NAME_SUFFIXES = {'jr', 'jr.', 'sr', 'sr.', 'ii', 'iii', 'iv', 'v'}


def build_last_name_index(full_name_pool):
    """Groups a pool of lowercased 'first last[ suffix]' names by last name
    for fast abbreviated-name lookups (see match_abbreviated_name). Build
    once per table render, not per cell."""
    index = {}
    for full_name in full_name_pool:
        parts = str(full_name).split()
        if not parts:
            continue
        last_idx = -2 if (parts[-1] in _NAME_SUFFIXES and len(parts) > 2) else -1
        index.setdefault(parts[last_idx], []).append((parts[0], full_name))
    return index


def match_abbreviated_name(abbrev_name, last_name_index):
    """Bridges a 'F.Last'-abbreviated name to a full 'first last' name pool
    indexed by build_last_name_index. Matches on the FULL prefix before the
    period, not just its first letter - see NFL Scholar's data/utils.py for
    the real same-last-name/same-initial collision this guards against."""
    if '.' not in abbrev_name:
        return None
    prefix, _, last = abbrev_name.partition('.')
    if not prefix or not last:
        return None
    prefix = prefix.lower()
    last = last.lower().strip()
    candidates = [
        full_name for cand_first, full_name in last_name_index.get(last, [])
        if cand_first.lower().startswith(prefix)
    ]
    return candidates[0] if candidates else None


def fuzzy_filter_names(query, candidates, limit=25, min_ratio=0.35):
    """
    Ranks `candidates` (display strings, e.g. "Cooper Flagg (F)") by how
    well they match a user-typed `query` - built for a player-name search
    box where requiring an exact/prefix match was the complaint (a typo or
    a mid-name fragment should still surface the right player). A
    case-insensitive substring hit anywhere in the candidate always ranks
    above a fuzzy-only match (and earlier/tighter substring hits rank
    above later/looser ones); candidates with no substring hit still get a
    chance via `difflib.SequenceMatcher` (stdlib, no new dependency) so a
    misspelled or transposed name doesn't come back empty, as long as its
    similarity ratio clears `min_ratio`.

    Empty query returns `candidates` unchanged (no filtering/ranking) -
    callers should treat that as "nothing typed yet", not "no matches".
    """
    if not query or not str(query).strip():
        return list(candidates)
    q = str(query).strip().lower()
    scored = []
    for c in candidates:
        cl = str(c).lower()
        idx = cl.find(q)
        if idx != -1:
            score = 2.0 + (1.0 - idx / max(len(cl), 1))
        else:
            score = difflib.SequenceMatcher(None, q, cl).ratio()
            if score < min_ratio:
                continue
        scored.append((score, c))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    ranked = [c for _, c in scored]
    return ranked[:limit] if limit else ranked


def american_odds_to_prob(odds):
    """American odds -> implied probability (includes the book's vig)."""
    odds = float(odds)
    if odds > 0:
        return 100 / (odds + 100)
    return -odds / (-odds + 100)


# ---------------------------------------------------------------------------
# Team-name matching - moved here from ui/styling.py (originally built for
# team-color lookups) since data/loaders.py needs the exact same problem
# solved for a different reason: reconciling one source's team names against
# another's (e.g. ESPN/SportsDataverse's team_location field against CBBD's
# `school` field) so cross-source joins don't silently drop rows the way an
# exact-string-only match would. One canonical implementation shared by both
# the UI color-matching path and the data-layer cross-source join path.
# ---------------------------------------------------------------------------

def normalize_team_name(name):
    """
    Loose match key for team names that get formatted differently across
    this app's data sources for the exact same school - punctuation,
    case, a trailing 'University'/'College', possessive apostrophes. An
    exact-string dict lookup silently returns no match (not an error) on
    any of these mismatches, which is easy to miss. Does NOT resolve true
    word-different aliases (see TEAM_NAME_ALIASES below for those -
    normalizing punctuation alone can't turn 'NC State' into 'North
    Carolina State').
    """
    if not name:
        return ''
    s = re.sub(r"[^a-z0-9\s]", "", str(name).lower())
    for noise in (' university', ' univ', ' college'):
        s = s.replace(noise, '')
    return re.sub(r"\s+", " ", s).strip()


# Common short-name/full-name aliases seen across ncaa.com, CBBD, and ESPN
# for the same school - NOT exhaustive (this sandbox's network policy
# blocked live-checking every source's exact naming - see HANDOFF.md), just
# the well-known ones. Keyed/valued as normalized (normalize_team_name)
# strings; both directions get registered under each other's value. Extend
# this list if a real run still shows a team failing to match.
TEAM_NAME_ALIASES = [
    ('uconn', 'connecticut'),
    ('ole miss', 'mississippi'),
    ('pitt', 'pittsburgh'),
    ('nc state', 'north carolina state'),
    ('usc', 'southern california'),
    ('smu', 'southern methodist'),
    ('lsu', 'louisiana state'),
    ('byu', 'brigham young'),
    ('vcu', 'virginia commonwealth'),
    ('unlv', 'nevada las vegas'),
    ('utep', 'texas el paso'),
    ('uab', 'alabama birmingham'),
    ('uic', 'illinois chicago'),
    ('umass', 'massachusetts'),
    ('ucf', 'central florida'),
    ('fiu', 'florida international'),
    ('miami', 'miami fl'),
    ('st johns', 'st johns ny'),
    ("saint marys", "saint marys ca"),
]


def expand_team_name_aliases(norm_map):
    """Adds each TEAM_NAME_ALIASES pair's other spelling to `norm_map`
    (pointing at the same value) whenever exactly one side is already
    present - never overwrites a real direct hit with a guessed one."""
    expanded = dict(norm_map)
    for a, b in TEAM_NAME_ALIASES:
        if a in norm_map and b not in expanded:
            expanded[b] = norm_map[a]
        if b in norm_map and a not in expanded:
            expanded[a] = norm_map[b]
    return expanded


def resolve_team_name(name, canonical_names):
    """
    Resolves a team name from a foreign source (ESPN/SportsDataverse,
    ncaa.com scrape, etc.) to its matching entry in `canonical_names`
    (e.g. CBBD's own team list) - exact match first, then normalized +
    alias match. Returns None if nothing resolves, so callers can drop or
    flag an unattributable row instead of silently mis-joining it to the
    wrong team.
    """
    canonical_names = list(canonical_names)
    if name in canonical_names:
        return name
    norm_map = expand_team_name_aliases({normalize_team_name(c): c for c in canonical_names})
    return norm_map.get(normalize_team_name(name))
