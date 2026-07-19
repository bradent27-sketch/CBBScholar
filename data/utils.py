"""
Pure, dependency-free helpers shared by data/loaders.py and data/transforms.py.
Ported as-is from NFL Scholar (C:\\FantasyF\\data\\utils.py) / CFB Scholar -
none of this logic is sport-specific (percentile ranking and name-matching
apply to any player/team name pool). Porting this now, before it's needed,
is cheap insurance against re-discovering the same name-formatting bug
class NFL Scholar's own HANDOFF.md flags as its most-repeated one.
"""
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


def american_odds_to_prob(odds):
    """American odds -> implied probability (includes the book's vig)."""
    odds = float(odds)
    if odds > 0:
        return 100 / (odds + 100)
    return -odds / (-odds + 100)
