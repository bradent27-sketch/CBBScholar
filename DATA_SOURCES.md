# CBB Scholar — Data Sources

What each tab needs, what's free, and what to go set up. Checklist first,
detail below.

**Verification caveat on the Matchup Analyzer refinement pass:** this
app's whole discipline here is "verified live before the parser was
written" - the build environment for that pass could not reach
api.collegebasketballdata.com or ESPN at all (network policy blocked it,
confirmed via a direct 403). New fields added there lean on already-
verified sibling fields rather than a cold guess, and the app was smoke-
tested end-to-end against synthetic data instead of the real API - see
HANDOFF.md §6 for the full explanation. Treat anything from that pass as
unverified against the real API until it's actually run with real network
access.

**Correction vs. the original plan:** Barttorvik/T-Rank (barttorvik.com)
was originally scoped as a no-signup free source for advanced efficiency
metrics. Live-testing it while building this app found its `&csv=1` export
is actually gated by a JS bot-verification challenge — confirmed with a
direct request using a real browser User-Agent, still blocked. A plain
Python `requests` call (which is what any data pipeline here would use)
cannot get past it; only a real browser tab can. It's **not** used as a
data source in this app. In its place: **CollegeBasketballData.com**, a
proper API from the same team behind CollegeFootballData.com (same
free-tier-with-key model), covers the same ground — team/player stats,
efficiency ratings, rankings — without the bot-wall problem.

## Setup checklist

- [x] **CollegeBasketballData.com API key** — configured in
      `.streamlit/secrets.toml`. Powers the large majority of tabs. A
      `cbbd` Python package exists (`pip install cbbd`), maintained by the
      same team as `cfbd`, if you'd rather use a typed client than the raw
      HTTP calls this app currently uses.
- [x] **The Odds API key** — configured, powers Live Odds. **Note:** this
      key is shared with CFB Scholar (same account) — the ~500 credit/month
      free-tier allowance is not per-app.
- Nothing to do: ESPN's public standings endpoint needs no signup at all —
  it's what powers the Conference Standings tab today.

## Per-tab source map

| Tab | Source | Status |
|---|---|---|
| Player Search | CollegeBasketballData.com API — `/teams/roster`, `/stats/player/season` | **Live** |
| Team Efficiency | CollegeBasketballData.com API `/ratings/adjusted` | **Live** |
| NET & Resume | ncaa.com (manual fetch — see below) + CollegeBasketballData.com API `/rankings` (AP/Coaches poll) | **Live** |
| Conference Standings | ESPN public standings endpoint | **Live**, no key needed |
| Bracketology | CollegeBasketballData.com API `/ratings/adjusted` (simplified seed-line projection) | **Live**, explicitly not a committee simulation |
| Transfer Portal | CollegeBasketballData.com API `/recruiting/players`, `/recruiting/portal` | **Live** |
| Fantasy & Pools | CollegeBasketballData.com API stats + local scoring config | **Live** — season totals only |
| Matchup Analyzer | CollegeBasketballData.com API — `/stats/player/season`, `/stats/team/season`, `/games/players`, `/teams/roster` — PLUS a free ESPN/SportsDataverse season file, preferred first, for the positional defense breakdown | **Live** — a two-column player-vs-team-defense prep tool (not a team-vs-team projection anymore; `/ratings/adjusted` is no longer used here). The positional defense breakdown tries the free ESPN/SportsDataverse file first (zero CBBD-quota cost) and falls back to `/games` + `/games/players` scoped to the selected team's actual opponents (not a full-D-I pull) whenever that free source is stale/unavailable — see "ESPN/SportsDataverse fallback" below and HANDOFF.md §2/§3 |
| Live Odds | The Odds API `basketball_ncaab` | **Live** (shows "no games" in the off-season — correct behavior) |
| Player Compare | CollegeBasketballData.com API | **Live** |

## Correction: recruiting rankings gap (resolved)

This doc originally claimed there was no clean free composite recruiting
API for college basketball, unlike CFBD's endpoint for football. That was
wrong — checked CBBD's API spec directly while wiring the Transfer Portal
tab and found `/recruiting/players` does exactly that (individual recruit
rankings/stars) alongside `/recruiting/portal` (transfer entries). Both are
live and wired in. Leaving this note as a record that the original gap
assessment was corrected, not silently dropped.

## Resolved: true NET rank / Quad-record resume data (manual fetch, user-authorized)

Checked CBBD's full API spec directly — no NET-ranking or Quad-record
endpoint exists anywhere in it. Checked ESPN's hidden API directly too —
their rankings endpoint silently ignores a `type=net` parameter (just
returns the same AP/Coaches poll data), their own NET-rankings webpage
404s, and no NET/Quad field appears anywhere in their standings response.
**ESPN does not have this data**, despite carrying the AP/Coaches polls.

The real source is **ncaa.com's own official NET rankings page** — the
NCAA is the actual publisher of NET. It's server-rendered HTML with no
JSON API behind it (confirmed: team names are baked directly into the
page), and `pandas.read_html()` parses the table cleanly (365 rows: Rank,
School, Record, Conf, Quad 1-4, etc.) with no extra dependency needed
(lxml, already present, is pandas' HTML parser backend).

**NCAA.org's terms of service explicitly prohibit automated access** —
same category as Sports-Reference.com (still excluded below). Scraping
this page is a deliberate, **explicitly user-authorized exception** to
this app's default "prefer free APIs, avoid scraping" policy — approved
specifically for this one case because the data updates regularly enough
that a one-time manual export isn't practical. `data.loaders.fetch_net_rankings_manual()`
is wired as a manual, click-triggered fetch only (24h cache) — never
called automatically on tab load or on any schedule. See
`ui/tabs/net_resume.py`.

## ESPN/SportsDataverse fallback for positional matchup defense

`data.loaders.load_positional_matchup_data` (the data source behind
Matchup Analyzer's Team Defense positional breakdown) now tries a free,
keyless alternative FIRST before falling back to the CBBD approach
described above: **SportsDataverse's published season file**
(`sportsdataverse/sportsdataverse-data` on GitHub Releases — the Python
sibling of the R `hoopR` package, same maintainers as `cfbfastR`). It
publishes one parquet file per season with every D-I team's game-by-game
player box scores already in it — ESPN-sourced, no API key, no CBBD-style
monthly quota, one file download instead of a per-opponent fan-out.

**Why CBBD stays as the fallback, not the other way around:** this file's
freshness depends entirely on SportsDataverse's OWN scrape/publish
schedule, which this project has no control over and — as of this
writing, before the 2026-27 season has started — has not been possible to
verify live (this build environment's network policy blocks GitHub
release-asset downloads the same way it blocks CBBD/ESPN directly).
`load_positional_matchup_data` checks the file's own coverage of a team
against CBBD's confirmed schedule (`_is_espn_data_fresh_enough`, a
10-day-lag tolerance) before trusting it, and falls back to the CBBD path
automatically — silently, no error shown — whenever the file is missing,
unreachable, or too far behind. **What to actually check once the 2026-27
season starts:** open Matchup Analyzer → Team Defense for any team with a
few games played, and see whether the "Positional Matchup Defense" section
loads without hitting the CBBD-cost path (nothing definitive to check for
in the UI yet either way — if this matters, ask for a small "data source
used: ESPN file / CBBD fallback" indicator to be added to that section).
If the file turns out to consistently lag more than a couple weeks behind
the live season, CBBD's per-opponent fan-out (with the `max_recent_games`
cap below) remains the reliable path — nothing about this fallback risks
making the feature WORSE than it already was, only better when it works.

Implemented as a direct `requests.get()` + `pandas.read_parquet()` call
against SportsDataverse's own published URL — deliberately NOT the
`sportsdataverse` PyPI package, which pulls in scikit-learn, xgboost,
scipy, pyreadr, and beautifulsoup4 for no benefit here, and whose own
pyarrow pin conflicts with the one Streamlit itself requires (see
HANDOFF.md §5's pyarrow gotcha for the segfault that combination caused
elsewhere in this app).

## API budget: CBBD's 1,000 calls/month free tier

Confirmed via CBBD's own docs/socials (this sandbox can't reach the API
directly to verify first-hand - see the caveat above): **the free tier is
capped at 1,000 API calls per MONTH**, no per-minute throttling, just a
hard monthly ceiling that resets monthly. **This pool is SHARED with CFB
Scholar if both apps use the same CFBD/CBBD account** (same pattern as the
already-documented shared Odds API allowance) - check both apps' combined
usage, not just this one, before assuming there's headroom. A free
Student/Academic tier (register with a `.edu` email) raises this to
3,000/month. Patreon tiers go up to 75,000/month (Tier 3, ~$10/mo) and add
GraphQL API access for more flexible/efficient querying.

**Cost breakdown** (steady-state, i.e. what a normal week of use costs,
not first-ever-load). **These positional-matchup-defense rows are now the
WORST case, not the expected case** — they're what CBBD-only cost looks
like whenever the free ESPN/SportsDataverse fallback above isn't usable
for a given team; when it IS usable, that cost drops to zero (one shared
file download, cached weekly, covers every team/matchup at once):

| What | Cost | Notes |
|---|---|---|
| Shared baseline (ratings + all-team stats) | ~2 calls/week | Powers Team Efficiency, Four Factors, Team Defense profile, score projection — same 2 calls regardless of how many teams/matchups you look at |
| Browsing one team (roster/stats/schedule/game log) | ~2-4 calls | Player Search, Compare, Matchup Analyzer Overview — cached 1-6h, so repeat visits same day are often free |
| Positional Matchup Defense, ONE team, first time this week | up to ~1 + 2×N calls | N = the "games per team" slider (default 20, capped specifically because of this quota) — e.g. cap=20 → up to 41 calls |
| Positional Matchup Defense, a full two-team matchup, first time | up to ~2×(1+2N) calls, LESS if the teams share opponents | In-conference matchups share most of their schedule, so real cost is usually well below the worst case |
| Positional Matchup Defense, any REPEAT view this week (same team) | 0 calls | Full cache hit |
| Player Trends' conference comparison group | ~8-18 calls, once/week, shared across every player looked up | Full D-I opt-in is ~360 calls, same weekly-shared caching |

**The realistic risk**: checking Positional Matchup Defense for ~5 "watch
list" teams every week, cap=20, non-overlapping schedules, is
~5 × 41 × ~4 weeks ≈ 820 calls/month on that ONE feature alone — most of
the free 1,000/month budget, before counting anything else either app
does. This is exactly why `load_team_opponent_game_logs` defaults to a
`max_recent_games` cap (a UI slider in Matchup Analyzer's Team Defense
sub-tab, not hardcoded) instead of pulling a whole season — turn it down
for a tighter budget, up for more complete history if quota allows.

**Free ways to reduce this further:**
- **Lower the "games per team" slider** — cost scales directly with it.
- **CBBD's own free "Exporter" web tool** (collegebasketballdata.com/
  exporter/games/players) — browse/preview/filter any endpoint and pull a
  CSV by hand, no code. Doing a weekly manual export of `/games/players`
  and dropping the CSV somewhere this app reads from would let the
  positional-defense engine read from a local snapshot instead of hitting
  the live API at all for that data — the SAME "manual, click-triggered,
  never automatic" pattern this app already uses for NET rankings (see
  §2/§8 gotchas in HANDOFF.md). Not built yet — ask if you want this
  wired in; it's a real option, just a workflow change (a weekly manual
  export step) rather than a pure code change.
- **Register for the free Student/Academic tier** if a `.edu` email is
  available — 3,000/month instead of 1,000, zero cost, zero code change.
- **Test whether `/games/players` supports an unscoped (no `team` param)
  season-wide call** — if CBBD returns every team's games in ONE call the
  way `/stats/team/season` already does, that would replace the whole
  per-opponent fan-out with a single call. This sandbox could not test it
  live; worth trying once real network access is available before
  assuming the current per-opponent design is the best possible one.

**Paid option** (flagging per this app's "ask before adding paid sources"
rule — NOT enabled, just documented as a real option): CBBD's Patreon Tier
3 (~$10/mo) raises the ceiling to 75,000 calls/month and unlocks GraphQL,
which would make the "games per team" cap essentially unnecessary. A
separate, one-time option is CBBD's **paid "Starter Pack"** (~$39,
collegefootballdata.gumroad.com/l/cbb-starter-pack) — historical CSVs
(games back to 2003, stats back to 2005) plus notebooks, useful for
BACKFILLING history once, not for keeping current-season data fresh
during the season.

## Explicitly excluded

- **KenPom.com** — paid subscription; not used.
- **Barttorvik/T-Rank direct scraping** — see the correction above. Blocked
  by bot-protection for automated access; not used as a pipeline source.
  (Manually viewing barttorvik.com in your own browser still works fine —
  it's only scripted/automated access that's blocked.)
- **Sports-Reference.com (including Basketball Reference)** — their terms
  of use explicitly prohibit automated/bot access. Not used as a scrape
  target for anything in this app.
- **General web scraping** — avoided by design, with exactly one
  explicitly user-authorized exception (ncaa.com's NET rankings, see
  above), wired as a manual click, never automatic. Every other source
  above is a real, keyless-or-free-key API. If a future feature genuinely
  has no free-API option, that gets called out explicitly here rather
  than quietly scraped.
