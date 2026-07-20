# CBB Scholar — Handoff Doc

Sibling app to NFL Scholar (`C:\FantasyF`) and CFB Scholar
(`C:\CCodeApps\CFBScholar`), same architecture and design system, built for
college basketball. This doc follows NFL Scholar's own HANDOFF.md section
structure on purpose, so all three stay easy to cross-reference.

**Status as of this writing: 10 of 10 tabs live with real data** via
CollegeBasketballData.com (free key, configured), ESPN's public endpoints
(no key), and The Odds API (free key, configured). No PFF-equivalent
subsystem exists for this app at all — there's no PFF product for college
basketball.

**Latest pass: stale recruiting-commitment data + Matchup Analyzer feeling
like three separate pages.** Two independent user reports.
1. **Transfer Portal showing "Uncommitted" for players who are actually
   committed.** Root cause is genuinely unresolved from this dev
   environment (no live network access - see §6): `/recruiting/players`
   and `/recruiting/portal` both take a `year` param that this app
   previously reused from the main team-season selector
   (`current_cbb_season()`, which labels a season by its SPRING/ending
   year - confirmed for `/stats`/`/ratings`, NOT confirmed for
   recruiting). Recruiting classes everywhere else are labeled by
   HS-grad/enrollment year, a different, unrelated convention - the two
   MAY already coincide for "the class currently enrolling" by
   coincidence, or may not. Rather than guess, `ui/tabs/transfer_portal.py`
   now exposes an independent "Recruiting / Portal Class Year" selector
   (not tied to the team-season picker) plus a "Refresh now" button that
   bypasses the 6-hour cache, a Committed/Total metric, and a
   "show only Uncommitted" filter - lets a real user with real knowledge
   of who's committed self-diagnose which year value is actually current,
   which is more reliable than a guess baked into the code. If commitment
   data is STILL stale on the correct year after a refresh, that's
   CBBD's own database lagging real announcements, not something this app
   computes - see the caveat text now shown under both tables. Considered
   and explicitly NOT done without asking first: scraping a live
   commitment tracker (247Sports/On3) as a fresher supplementary source -
   same "explicit user-authorized exception" bar as the NCAA NET scrape
   (see §8), not extended here without a separate ask.
2. **Matchup Analyzer reorganized into sub-tabs.** Had grown to Projected
   Score, Unit vs Unit, Four Factors, Style Profile, Matchup Edges (three
   sub-sections of its own), Recent Form, and Season Margin Trend all in
   one flat scroll. Team/venue selection and the headline metrics
   (Net Rating x2, Projected Edge, win probability) stay always-visible
   above everything; the rest is now four `st.tabs()` grouped by the
   QUESTION each answers: **Overview** (Projected Score, Unit vs Unit),
   **Efficiency & Style** (Four Factors, Style Profile), **Matchup Edges**
   (shooting/rebounding allowed, roster tendencies, the full
   defense-by-role breakdown), **Form & Trends** (Recent Form, Season
   Margin Trend). Same pattern the Four Factors section already used
   internally (its own nested `st.tabs()` for the two offense/defense
   directions), just applied one level up. No logic changed, purely a
   layout reorganization - see `ui/tabs/matchup_analyzer.py`'s
   `_render_overview`/`_render_efficiency_style`/`_render_matchup_edges`/
   `_render_form_and_trends` helpers.

**Fixed this pass: the "API keys aren't connected" bug.** Both real keys
had been typed into `.streamlit/secrets.toml.example` (git-tracked)
instead of `.streamlit/secrets.toml` (git-ignored, the file `st.secrets`
actually reads) — so `secrets.toml` itself was never created, and the
sidebar correctly reported "Not set" even though real key values existed
*somewhere* in the repo. Symptom and root cause matched exactly: a fresh
clone of this repo had only the `.example` file on disk, no `secrets.toml`.
Fixed by moving the real values into a local, git-ignored
`.streamlit/secrets.toml` and restoring `.example` to placeholder text.
**Consequence: both real keys were committed to git history in the initial
commit.** Even though this is a private repo, that's a live-credential
leak via git history, not just the current file tree — **rotate both
keys** (new CollegeBasketballData.com key at its `/key` page, new Odds API
key at its dashboard) and update the local `secrets.toml` with the new
values; the old ones stay recoverable from history otherwise. Purging git
history (filter-repo/BFG + force-push) is a further option but wasn't done
here — it rewrites shared history and needs sign-off before doing that on
a repo that may have been cloned elsewhere.

**Added this pass: three genuinely new analysis/viz pieces, not ported
from NFL/CFB Scholar** (see §3 for detail): a per-team statistical "DNA"
radar (Team Efficiency), a live stat-vs-Net-Rating correlation panel
("What Wins This Season", Team Efficiency), and a season-long margin/
volatility chart with close-game record (Matchup Analyzer). All three
reuse data already being pulled elsewhere in the app — zero new API
calls, zero new endpoints. `ui/charts.py` gained three new chart functions
for this (`render_radar_chart`, `render_correlation_bars`,
`render_margin_chart`) — **this breaks the "byte-identical with CFB
Scholar" invariant** documented in §4/§8 below, since the new functions
are additions specific to this pass, not yet back-ported to CFB Scholar.
They're written sport-agnostically on purpose (generic radar/correlation/
margin primitives, no CBB-specific logic) so back-porting later is a
straight file sync if wanted — just hasn't been done as part of this pass.

**Also fixed this pass: `cbfd_api_key` vs. `cbbd_api_key`.** A live
instance had the CBBD key pasted into Streamlit Cloud's secrets under the
name `cfbd_api_key` (the CFB Scholar sibling's key name — a one-letter
typo, easy to make copying between the two apps). Every loader here reads
`st.secrets["cbbd_api_key"]` specifically; a key under any other name is
invisible to it. No code changed for this one - it was a secrets-panel
typo on Streamlit Cloud, not a bug in this repo. Also added a **"Test live
connections" button** (sidebar, below Setup Status) that makes one real,
uncached request to each of CBBD/Odds API/ncaa.com and reports the actual
HTTP status/exception instead of every tab's generic "or the request
failed" — see `data.loaders.test_cbbd_connection` /
`test_odds_connection` / `test_ncaa_net_connection`. Use this FIRST
whenever "configured" in the sidebar doesn't match what a tab shows - it
distinguishes a bad/rotated key (401) from a rate limit (429) from a
network block on the hosting side (timeout/connection error), which the
tabs' own error message can't.

**Major pass: role-based matchup intelligence.** This is the app's actual
differentiator vs. raw KenPom/Torvik/CBBD numbers - the user's real
workflow (paraphrased): "check what a defense allows by position, then
check whether the opposing player's own tendencies match that hole, on a
rate basis, and watch for a role/usage trend before it shows up in the
season averages." None of this exists as a single free CBB data source
(checked: CBBD's spec has no shot-location/play-type/defense-by-position
endpoint; `/lineups` and `/plays` in its spec are possession/shot-clock
logs, not role-tagged splits) - it's built by adding a role-tendency layer
on top of data already in this app, plus one new cross-referencing loader.
Three pieces, see §3 for the full technical detail:
1. **Player role tags** (`data.transforms.player_rate_profile` +
   `classify_player_role`) - Ball-Handler / Post Player / Shooter /
   Wing-Combo, from rate stats (per-40s, Usage%, 3PA Rate, AST/TOV, etc.),
   not raw totals. Originally shipped as fixed, basketball-literate
   thresholds only (a full-D-I player pull looked too expensive to
   justify) - **superseded later the same day** once the user pushed back
   on that exact tradeoff: see the "real percentile" addendum below and
   §3's League Player Database writeup. Shown in Player Search (badges +
   rate tiles) and Matchup Analyzer (both rosters, grouped by role) -
   percentile-ranked when a league database exists, heuristic fallback
   otherwise, same UI either way (a caption says which mode is active).
2. **Defense-allowed-by-role** (`data.loaders.load_defense_allowed_by_role`
   + `data.transforms.aggregate_defense_by_role`) - cross-references every
   opponent on a team's schedule (their roster, season stats, and game
   log - all loaders this app already had) to compute what that defense
   actually allows to Ball-Handlers/Post Players/Shooters specifically.
   The heaviest pull in the app (up to ~60-90 calls for a full schedule,
   ~40-60 once a League Player Database exists - see the addendum below)
   - gated behind an explicit "Analyze Defense" button in Matchup
   Analyzer's new MATCHUP EDGES section, same pattern as the NCAA NET
   manual scrape. Direct stats that needed no cross-referencing (3PA
   Rate/3P%/ORB% allowed) are free and shown unconditionally above it.
3. **Trending** (`ui.charts.render_trend_line`, reused for both) - rolling
   5-game average vs. season-average dashed line, for a player's Usage%/
   3PA Rate (Player Search, zero extra cost - already-fetched game logs)
   and for points allowed per role (Matchup Analyzer, from the
   cross-reference above). This is the "beat the market" piece: a real
   role or scheme change shows up as the rolling line pulling away from
   the season dashes before it moves the season number itself.

**Addendum, same day: real percentiles instead of fixed thresholds, and
why "60-90 calls" specifically.** Direct user pushback on both points
above - fair on both. What shipped:
- `data.loaders.load_all_player_season_stats` tries the SAME no-team-
  filter trick `load_all_team_season_stats` uses against
  `/stats/team/season`, but against `/stats/player/season` instead - if
  CBBD's player endpoint secretly supports this too, league-wide
  percentiles are one more free cached call. **UNCONFIRMED** - this dev
  environment has no live network access to check (see §6); it validates
  its own result (`df['team'].nunique() >= 30`) before trusting it, so a
  single-team fallback response can't silently masquerade as league-wide
  data.
- If that fails, `data.loaders.build_league_player_database` is the
  honest fallback: one `/stats/player/season` call per D-I team (~360, via
  `load_teams`), manual button only (`ui/tabs/team_efficiency.py`'s new
  LEAGUE PLAYER DATABASE section), with a live progress bar, cached in
  `st.session_state` for the session (not `st.cache_data` - a real
  progress callback isn't cacheable/hashable, and the point is a one-time
  manual action, not a background job). Same
  expensive-pull/user-gated precedent as the NCAA NET scrape and
  Defense-by-role, just bigger.
- Once either path populates data, `data.transforms.league_rate_profiles`
  + `classify_player_role_percentile` do REAL percentile ranking (via the
  existing `pct_rank` helper) instead of fixed cutoffs - see §3.
  `classify_player_role_best_available` is the single entry point every
  UI call site now uses: percentile when a league table exists and has
  ≥30 qualifying players, fixed-threshold heuristic otherwise, transparent
  to the caller either way.
- The "why 60-90 calls" answer turned out to double as the fix for a
  THIRD thing: `load_team_player_stats` now checks the league-wide cache
  first and filters from it before making a fresh per-team call (see §3's
  gotcha-adjacent note) - so once a league database exists,
  `load_defense_allowed_by_role`'s per-opponent cost drops from 3 calls to
  2 (season stats come free from the cache), automatically, no call-site
  changes needed anywhere that already used `load_team_player_stats`.

## 1. Architecture

Same 3-layer separation as NFL Scholar / CFB Scholar. `data/loaders.py`'s
CBBD client layer mirrors CFB Scholar's CFBD layer exactly:
`_cbbd_headers()` / `_cbbd_get(path, params)`. Every endpoint's field
names were verified live (`curl`/PowerShell `Invoke-RestMethod` against
the real API with a real key) *before* the parser was written.

## 2. Data sources

See DATA_SOURCES.md for the full checklist and two corrections made while
building this (both documented there in detail, summarized here):
Barttorvik was dropped as a data source (bot-walled against automated
access, confirmed live) in favor of CollegeBasketballData.com; and the
original "no clean recruiting API" gap assessment was wrong -
`/recruiting/players` exists and is wired into the Transfer Portal tab.

CBBD has no roster-by-name search (unlike CFBD's `/player/search`) and no
`/roster` endpoint (that path returns the API's own Swagger docs page, not
JSON - confirmed live; the real path is `/teams/roster`, nested under a
per-team wrapper object). Player discovery here is team-first: pick a
team, then a player from that team's roster - this shapes Player Search,
Compare, and Fantasy & Pools identically.

CBBD has no NET-rank or Quad-record endpoint (confirmed against its full
API spec), and neither does ESPN's hidden API (confirmed live: their
`type=net` param is silently ignored, their NET webpage 404s, no NET/Quad
field exists in their standings response). The real source is ncaa.com's
own official NET rankings page - server-rendered HTML, no JSON API, and
NCAA.org's terms of service prohibit automated access. The user
**explicitly authorized scraping this one page** given how often it
updates, on the condition it stays manual (click-triggered, never
automatic/scheduled) - see `data.loaders.fetch_net_rankings_manual()` and
§8. This is the one deliberate exception to this app's "prefer free APIs
over scraping" default; nowhere else in either app scrapes anything.

## 3. Key computed systems

- **Player-search team-first flow**: `load_teams()` → `load_team_roster(team,
  season)` → `get_player_season_stats(team, season, athlete_id)`, joined
  on CBBD's own `athleteId`/`id` (confirmed these match 1:1 across the
  roster and stats endpoints before relying on it).
- **Fantasy scoring** (`ui/tabs/fantasy_pools.py`): linear formula (points
  + rebounds + assists + steals + blocks − turnovers, user-adjustable
  weights) applied to real season totals, with a per-game average computed
  from `games`.
- **Matchup win probability** (`ui/tabs/matchup_analyzer.py`): net-rating
  differential through a logistic curve (`scale=11.0`), explicitly labeled
  as an estimate.
- **Four Factors matchup engine** (`data/transforms.four_factors_matchup` +
  `ui/charts.render_mirror_bars`): Dean Oliver's four factors matched
  offense-vs-defense from `/stats/team/season` — ONE call returns all 700
  D-I teams (verified live: `teamStats.fourFactors` and
  `opponentStats.fourFactors`, plus pace and paint/fast-break point splits),
  so every D-I percentile is free local compute over that cached pull. Each
  side's percentile uses the correct better-direction per factor (e.g. Def
  TO Ratio = turnovers FORCED, higher is better) so both mirrored bars read
  "longer = winning this battle."
- **Projected score** (`data/transforms.project_score`): adjusted
  off/def ratings (per-100-poss) combined additively vs the league-average
  offense, scaled by the two teams' mean pace into an actual score/total,
  with the home-court constant split across the sides. Knowingly mixes
  opponent-adjusted ratings with raw pace — labeled an estimate in the UI.
  The headline "Projected Edge" metric stays on the per-100-possessions
  scale (it feeds the win-prob logistic, whose `scale=11.0` was calibrated
  against that input) and is labeled "(per 100 poss)" so it doesn't read as
  a game-margin claim next to the score projection.
- **Venue adjustment** (`ui/tabs/matchup_analyzer.HOME_COURT_POINTS`): flat
  3-point home-court constant — a selector, not a per-arena model.
- **Game logs + breakout detection** (`data/loaders.load_player_game_logs`,
  `data/transforms.breakout_flags`/`last_n_form`): per-game box scores via
  `/games/players` (one call per team-season, game context included in the
  same response). Breakout = ≥1.5 population-σ above the player's own season
  mean (suppressed under 4 games / ~zero variance); last-5 vs season deltas
  rendered as st.metric rows.
- **Poll trajectories** (`data/transforms.poll_trajectory` +
  `ui/charts.render_rank_trajectory`): the raw `/rankings` payload the NET &
  Resume tab already cached is the FULL season history — the trajectory
  chart is pure re-use, zero extra API cost.
- **Bracketology** (`ui/tabs/bracketology.py`): teams sorted by adjusted
  net rating, split into groups of 4 per seed line (1-16). Explicitly NOT
  a selection-committee simulation - no auto-bids, no resume factors (see
  NET & Resume), no bracket geography. Labeled as such in the tab itself.
- **Team DNA radar** (`data/transforms.team_dna_profile` +
  `ui/charts.render_radar_chart`, in Team Efficiency): a 7-axis percentile
  profile per team - Offense, Defense, Tempo, 3PT Volume, Off. Rebounding,
  Ball Security, Takeaways - all derived from the two full-D-I pulls
  (`/ratings/adjusted`, `/stats/team/season`) already cached for other
  tabs, so this costs zero extra API calls. Ball Security and Takeaways
  are both oriented so "further out on the axis = better", even though the
  underlying raw stat (TO Ratio) is lower-is-better on the offense side -
  every axis on the radar reads the same direction. Up to 3 teams overlay
  on one chart to compare shape (identity), not just size (quality).
- **"What Wins This Season" correlation panel**
  (`data/transforms.stat_win_correlations` +
  `ui/charts.render_correlation_bars`, in Team Efficiency): live Pearson
  correlation of every Four Factor/style column against the current
  season's adjusted Net Rating, across all of D-I, recomputed from real
  data on every load rather than a hardcoded assumption about what
  matters. Sign is flipped for defensive-allowed columns (`Def eFG%`,
  `Def ORB%`, `Def FT Rate`) so the displayed value always means "being
  good at this stat associates with winning" when positive - style/tempo
  columns with no inherent good direction (Pace, 3PA Rate, Paint Pts %,
  Fast Break %) keep their raw sign and render in a neutral color instead
  of green/red. This is the app's first real inferential-statistics
  feature (everything else is descriptive/percentile); it's still
  correlation, not causation, and is labeled as such in the tab.
- **Season margin trend + consistency**
  (`data/transforms.margin_volatility` + `ui/charts.render_margin_chart`,
  in Matchup Analyzer): every completed game's scoring margin as a
  zero-centered bar (green above for wins, red below for losses) plus
  population std-dev of margin ("volatility"), best/worst margins, and the
  close-game (≤5 pt) win-loss split - all computed from the same
  `load_team_games` pull Recent Form already makes for the last-5 strips,
  just over the full season instead of the last 5.
- **Player role tags** (`data/transforms.player_rate_profile` +
  `classify_player_role`): rate-basis tendency profile from one player's
  raw `/stats/player/season` dict - Usage% (direct from the API), 3PA
  Rate/3P%/FT Rate (computed from attempted/made splits), AST/REB/STL/BLK
  per-40 (rate stats, minutes-normalized), AST/TOV ratio, eFG%/TS%. Fed
  into a single PRIMARY role per player (priority order, so defense
  aggregation below can bucket without double-counting): **Ball-Handler**
  if AST/40 ≥ 5.5, or Usage% ≥ 24 AND AST/40 ≥ 3.0 (catches both the
  pass-first low-usage floor general and the high-usage combo guard who
  also creates); **Post Player** if 3PA Rate ≤ 20% (barely plays beyond
  the arc - the best proxy available without shot-location data, which
  CBBD doesn't have) or REB/40 ≥ 9; **Shooter** if 3PA Rate ≥ 40%;
  else **Wing/Combo**. Secondary badges (Rebounder, Rim Protector,
  Disruptor, Sharpshooter, Foul Drawer, Secondary Ball-Handler) layer on
  top from the same rate profile. **This is the FALLBACK classifier now**
  (`data/transforms.classify_player_role`) - fixed, basketball-literate
  thresholds, used only when no league-wide player data is available. See
  the League Player Database entry below for the real-percentile version
  and `classify_player_role_best_available`, the entry point every UI call
  site actually uses (picks whichever classifier has real data to work
  with, transparent to the caller). Read a heuristic-mode tag as a
  heuristic read, same "labeled as an estimate" spirit as the Matchup
  Analyzer's projections - recalibrate the thresholds if they start
  reading players wrong once real data is flowing.
- **League Player Database** (`data/loaders.load_all_player_season_stats`
  / `build_league_player_database` / `get_league_player_stats`,
  `data/transforms.league_rate_profiles` /
  `classify_player_role_percentile` / `classify_player_role_best_available`,
  `ui/tabs/team_efficiency.py`'s new LEAGUE PLAYER DATABASE section): what
  makes player role tags REAL D-I percentiles instead of fixed thresholds.
  Tries a no-team-filter `/stats/player/season` call first (mirrors how
  `/stats/team/season` already works league-wide for free) -
  **UNCONFIRMED whether CBBD's player endpoint actually supports this**
  (no live network access from this dev environment to check; the
  function validates the response spans ≥30 teams before trusting it, so
  a narrow/single-team response can't silently pass as league data). If
  that's unsupported, an explicit "Build League Player Database" button
  fans out one `/stats/player/season` call per D-I team (~360, with a live
  progress bar) - one-time, session-cached, never automatic, same
  expensive-pull/user-gated precedent as the NCAA NET scrape. Once
  populated (either way), `league_rate_profiles` computes the same rate
  stats as `player_rate_profile` across every qualifying player (≥300
  season minutes - `MIN_MINUTES_FOR_PERCENTILE`, filters garbage-time
  noise), and `classify_player_role_percentile` ranks a player against
  that REAL distribution (composite percentile score per role -
  `_ROLE_SIGNAL_DIMENSIONS` - argmax picks primary, `WING_FLOOR_PERCENTILE`
  gates a merely-average player back to Wing/Combo instead of force-fitting
  a weak specialty). **Bonus side effect**: `load_team_player_stats` now
  checks this league cache first before making a fresh per-team API call -
  so once a league database exists, `load_defense_allowed_by_role`'s
  per-opponent cost drops from 3 calls to 2 automatically, no other code
  changed.
- **Defense-allowed-by-role** (`data/loaders.load_defense_allowed_by_role`
  + `data/transforms.aggregate_defense_by_role`/`defense_role_game_series`,
  in Matchup Analyzer's new MATCHUP EDGES section): no free CBB source
  publishes "what does this defense allow to Ball-Handlers vs. Shooters
  vs. Post Players" - it's built by cross-referencing every opponent on a
  team's schedule. For each opponent: pull their roster (id↔sourceId
  bridge - see the id-namespace gotcha below), their season stats (role
  classification, from THEIR OWN season profile, not from what they did
  against the team being analyzed - that would be circular), and their
  game log filtered to just the game(s) against the team being analyzed.
  Bucket by role, average PER GAME (not per player-appearance - two
  Ball-Handlers in one game still divide by 1 game). This is the heaviest
  pull in the app - up to 3 calls/opponent × ~20-30 opponents = up to
  60-90 calls for a full schedule, dropping to ~2 calls/opponent (~40-60)
  once a League Player Database exists (see above - season stats come
  from the cache instead of a fresh call). Gated behind an explicit
  "Analyze Defense" button either way, same pattern as the NCAA NET manual
  scrape; never call it on tab load.
  Direct stats needing no cross-reference (3PA Rate/3P%/ORB% allowed, from
  `opponentStats.threePointFieldGoals`/`fourFactors` - same cached
  `/stats/team/season` pull as everything else) are shown above it for
  free.
- **Rate-stat / role trend** (`ui/charts.render_trend_line`, reused by
  both Player Search and Matchup Analyzer): game-by-game dots plus a
  trailing 5-game rolling average against a dashed season-average line.
  Player Search: Usage%/3PA Rate per game, both already present per-game
  in `/games/players` (Usage directly, 3PA Rate from 3PA/FGA) - zero extra
  API cost, pure re-use of the game log Breakout Games already fetches.
  Matchup Analyzer: points allowed per role per game, from the
  cross-reference above. This is the actual "beat the market" feature the
  role tags exist to support - a real role/usage/scheme change shows up as
  the rolling line pulling away from the season dashes before it moves the
  season number.

## 4. UI conventions

Identical to NFL Scholar / CFB Scholar: dark surface, violet primary
accent (`#c084fc`), Inter + JetBrains Mono, tabs-not-sidebar nav, glass
cards, full-bleed layout. Same `render_coming_soon()` reuse for setup
/error states as CFB Scholar.

## 5. Gotchas — every one of these was a real bug hit while building this

- **`Styler.apply`/`.map` reject a non-unique index** - hit repeatedly
  (Team Efficiency, NET & Resume, Transfer Portal's recruiting table) from
  the same root cause: CBBD's ranking fields can be `null` for some
  entries, and `df.set_index('Rank')` then has multiple `NaN` index
  values. **Fix: index on a guaranteed-unique column (Team) or a clean
  sequential index — never rank/order data that might have ties or
  nulls.** This is now the default assumption for any new table in either
  app, not something to rediscover per tab.
- **`dict.get(key, default)`'s default does NOT cover an explicit `null`
  value** - only a missing key. `r.get('ranking', 999)` still returned
  `None` (crashing a `.sort()`) for entries with `"ranking": null` present
  in the JSON. Use `r.get('ranking') or 999`, or an explicit `is None`
  check, whenever a source can emit an explicit null.
- **`/roster` is not the real CBBD endpoint** - returns the Swagger UI
  HTML page, not JSON (confirmed live, easy to misdiagnose as a network
  problem). The real path, found via CBBD's own `/api-docs.json` spec, is
  `/teams/roster`.
- **Barttorvik's documented `&csv=1`/`&json=1` URL trick does not survive
  contact with a real HTTP client** - confirmed live with `curl` using a
  real browser User-Agent, still returned a JS bot-verification
  interstitial. A blog post or forum saying a URL parameter "just works"
  is not the same claim as "works for a scripted request" - worth testing
  directly rather than trusting a secondhand claim, same lesson as the
  original DATA_SOURCES.md correction.
- **Streamlit's hot-reload is not fully reliable** - see CFB Scholar's
  identical HANDOFF.md entry. When a fix doesn't seem to take effect,
  restart the server process rather than trusting the file-watcher.
- **`pd.read_html(html_string)` fails if you pass the raw string
  directly** - lxml's parser treats a bare string as a file path/URL, not
  literal HTML, and raises a confusing `OSError: Error reading file
  '&lt;!DOCTYPE html&gt;...'` (the error message includes the whole page,
  easy to misread as something else entirely). Wrap it:
  `pd.read_html(io.StringIO(html_string))`.
- **`/games/players`' `athleteId` is a DIFFERENT id namespace from
  `/teams/roster`'s `id`** - confirmed live (Caleb Foster: roster id 208,
  game-log athleteId 4287417) even though roster id DOES match
  `/stats/player/season`'s athleteId (the 1:1 claim in §3 above is still
  true for that pair). The shared key with game logs is the ESPN-side id:
  roster `sourceId` == game-log `athleteSourceId`. Any future per-game
  join must use sourceId (name-within-team as fallback only) - the wrong
  join produces a silent "no data for this player", not an error.
- **THEME's single-quoted font stacks break raw-HTML/SVG blocks in
  `st.markdown`** - see CFB Scholar's identical HANDOFF.md entry (hit
  there first, same `ui/charts.py` fix: module-level `_BODY_FONT`/
  `_MONO_FONT` with double-quoted family names).
- **CBBD 403s requests without a User-Agent header** - the app's own
  `requests`-based loaders are fine (requests sends `python-requests/x`),
  but a bare `urllib` probe gets `403 Forbidden` on every path including
  `/api-docs.json`. Easy to misread as an auth/key problem when testing
  endpoints outside the app.
- **The setup-status sidebar checks `st.secrets`, which ONLY reads
  `.streamlit/secrets.toml` - never `.streamlit/secrets.toml.example`.**
  Hit for real: the live keys ended up typed into the `.example` file
  (git-tracked) instead of `secrets.toml` (git-ignored), so the actual
  secrets file was never created and the sidebar correctly reported both
  keys as "Not set" despite real values existing in the repo. Fresh-machine
  setup (§9) says "copy `.example` to `secrets.toml`" for exactly this
  reason - editing the `.example` file directly and stopping there looks
  like it should work (the values are right there) but Streamlit never
  reads that filename. If setup status ever again disagrees with "I
  definitely entered a key", check which literal filename holds the values
  before assuming the key itself is bad.
- **A key pasted under the wrong SECRET NAME (not the wrong file) produces
  the identical "Configured" ✅ + tab-level failure symptom** - hit for
  real on a live Streamlit Cloud deploy: the CBBD key was pasted in under
  `cfbd_api_key` (CFB Scholar's key name - one letter off, easy mix-up
  copying between the sibling apps) instead of `cbbd_api_key`. The sidebar
  only checks "is SOME value present under this exact name", so it can't
  catch a right-value/wrong-name typo - every tab quietly failed with the
  generic "or the request failed" message instead. This is exactly why the
  "Test live connections" button (§0/sidebar) exists now - it makes one
  real, uncached request and reports the true failure (401/429/timeout),
  which for a wrong-name secret shows as "No cbbd_api_key in st.secrets"
  even though a key IS in there under a neighboring name.
- **`load_defense_allowed_by_role`'s id-bridging needs THREE joins, not
  one** - the `athleteId`/`sourceId` gotcha above (season-stats id
  matches roster id; game-log id matches roster sourceId) means tagging a
  game-log row with a role computed from season stats requires roster as
  the bridge in between: `season_stats.merge(roster[['id','sourceId',
  'name']], left_on='athleteId', right_on='id')` first, THEN join the
  result's `sourceId` to the game log's `athleteSourceId`. Skipping the
  roster pull and trying to join season stats directly to game logs (both
  loaders return an `athleteId` column with the SAME name but a DIFFERENT
  id space) silently produces zero matches, not an error - confirmed by
  testing the join logic against synthetic data shaped like the real
  three payloads before trusting it (this sandbox has no live network to
  confirm against the real API - see §6).

## 6. Verification workflow (what "done" means for this pass)

Every CBBD/ESPN/Odds API endpoint used here was checked live before the
parser was written - field names are confirmed exact. `streamlit run
app.py`, click through all 10 tabs on a **freshly started server**,
confirm zero `"hit an error"` text anywhere, confirm the live tabs show
real current data (Live Odds correctly shows "no games" in July - CBB is
in its off-season).

**Verification note for the API-key-fix + Team DNA / What Wins / Margin
Trend pass:** done from a sandboxed environment with no outbound network
access to `collegebasketballdata.com`, `the-odds-api.com`, `espn.com`, or
`ncaa.com` (confirmed - every direct request was rejected at the network
policy level, not by the APIs themselves). Verified what was possible from
there: the secrets fix via a real headless run of the app (Playwright
screenshot confirmed the sidebar flips from "Not set" to "Configured" for
both keys once `secrets.toml` exists in the right place - this part needed
no external network, since it's purely local file → `st.secrets`); the
three new transforms functions against realistic synthetic DataFrames
shaped exactly like the real loaders' output (column names/dtypes matched
by hand against `data/loaders.py`); and both new tab sections end-to-end
via `streamlit.testing.v1.AppTest` with the loader functions monkeypatched
to return that same synthetic data - confirms no exceptions across the
full render path (radar chart, correlation bars, margin chart, all the
`st.dataframe`/`st.metric`/`st.multiselect` calls around them) without
needing a live server. **Not yet done: a real click-through with live API
data**, since that requires normal internet access this sandbox doesn't
have - do that once on a machine with real connectivity before calling
this pass fully verified, same bar as every prior pass in this doc.

**Verification note for the role-based matchup intelligence pass**
(player role tags, defense-allowed-by-role, rate/role trends): same
sandbox network restriction as above. Verified: `classify_player_role`
against four hand-built synthetic player archetypes (a high-assist PG, a
low-3PA-rate high-rebound center, a high-3PA-rate wing, a
nothing-dominates combo guard) - each landed on the intended role, and the
secondary badges (Rim Protector, Sharpshooter, Foul Drawer) fired
correctly. `aggregate_defense_by_role`/`defense_role_game_series` against
a hand-built role-games table with a known answer (verified the per-game,
not per-appearance, averaging). Most importantly,
`load_defense_allowed_by_role`'s full three-way id-bridging join (roster
↔ season stats ↔ game log, see §5) was tested end-to-end against a
synthetic "mini-league" shaped exactly like the real API responses (two
opponents, a Ball-Handler and a Shooter on each, one deliberately-injected
game against a THIRD team to confirm the opponent-filter excludes it) via
`streamlit.testing.v1.AppTest`, clicking the actual "Analyze Defense"
button - confirmed the right roles, the right game counts (2, not 3 -
proving the off-opponent game was correctly filtered out), and the right
per-game averages. This is real behavioral verification of the hardest
new logic in this pass, not just "it didn't crash." **Still not done:**
running it against the real live API, real `athleteId`/`sourceId` values,
and real CBBD role-stat distributions (the fixed thresholds in
`classify_player_role` were picked from basketball-analytics priors, not
fit to real CBBD data - they may need recalibrating once real numbers are
flowing; watch for a role that obviously reads wrong on a real player and
adjust the threshold, not the architecture).

**Verification note for the same-day percentile addendum:**
`league_rate_profiles`/`classify_player_role_percentile` tested against a
200-player synthetic league spanning 4 archetypes (Ball-Handler/Post/
Shooter/Wing mixed by weighted random draw) - both strong, unambiguous
archetypes (Ball-Handler, Post) classified correctly against the real
distribution; an intentionally moderate "wing" test case landed as Shooter
instead of Wing/Combo, which is CORRECT percentile behavior, not a bug -
relative to that specific synthetic league's archetype mix, its 33% three
rate genuinely ranked high enough to cross `WING_FLOOR_PERCENTILE`. This
is the actual behavioral difference from fixed thresholds worth
remembering: percentile results depend on the real comparison population,
which is the point, but also means results will shift as more real season
data accumulates - a player isn't mis-tagged if their percentile changes
as the sample grows, that's the system working as designed. Also verified
end-to-end via `AppTest`: Team Efficiency's "Build League Player Database"
button (progress callback firing, `st.rerun()` picking up the
session-stored result, the ≥30-teams validation guard), and both Player
Search and Matchup Analyzer correctly switching their caption from
"heuristic" to "REAL D-I player percentiles" once a league table exists
in session state. **Still unconfirmed:** whether
`load_all_player_season_stats`'s no-team-filter call actually works
against the real API (this is the single biggest open question from this
addendum - if it does, the ~360-call manual button becomes unnecessary
for most users) - check the Team Efficiency tab's League Player Database
status message on a live deploy before assuming which path is active.

## 7. Deliberately NOT done / parked

Formerly parked and now DONE in the data-viz pass: game-by-game logs (with
breakout flags and last-5 form), the Compare delta table (relative Edge %
with diverging colors), team-level league-percentile context (Four
Factors/style/efficiency percentiles — the "full-D-I pull" turned out to be
ONE cached call via `/stats/team/season`, not the per-team fan-out
originally feared), and `data/transforms.py` is no longer empty.

Also now DONE (this pass): the Team DNA radar, the "What Wins This Season"
correlation panel, and the season margin trend/consistency chart - see §3.

Also now DONE (role-based matchup intelligence pass): player role tags on
a rate basis (Ball-Handler/Post Player/Shooter/Wing-Combo + secondary
badges), the defense-allowed-by-role cross-reference engine, direct 3PA
Rate/3P% allowed, and rolling role/usage trend charts for both players and
defenses - see §3. This was the app's stated core differentiator vs. raw
KenPom/Torvik numbers and is now built.

Also now DONE (same-day addendum): PLAYER-level league-wide percentiles -
no longer parked. `/stats/player/season` being team-scoped turned out not
to be a hard blocker: a no-team-filter call is tried first (free if CBBD
supports it, unconfirmed), and an explicit "Build League Player Database"
button is the honest fallback (~360 calls, one-time, user-gated) if not -
see the League Player Database entry in §3. Role tags use REAL percentiles
whenever that data exists, fixed thresholds only as the automatic
fallback otherwise.

Still parked: Per-arena home-court values (flat 3-point constant instead).
Shot-location/play-type data specifically (would upgrade the Post Player
role signal past the "low 3PA rate" proxy, and would let defense-allowed-
by-role use actual shot charts instead of season box scores) - CBBD's
`/lineups` and `/plays` were checked this pass (see §3 lead-in) and are
possession/shot-clock logs, not that; no free source for it was found.
`cbbd` Python package vs. raw `requests` - unchanged. UI charts are
hand-rolled inline SVG on purpose (theme-exact, zero deps, native hover
tooltips) - revisit only if interactivity needs outgrow `<title>`
tooltips. Compare tab doesn't show role tags yet (Player Search and
Matchup Analyzer do) - natural next spot, just not done this pass.
Back-porting the new `ui/charts.py` functions (radar/correlation/margin
from the prior pass, role-badges/trend-line from this one) to CFB Scholar
to restore the "byte-identical" invariant (see note at the top of this
doc) - not done, needs a separate pass in that repo.

## 8. Constraints (user-set, don't violate)

- No new paid data sources without asking first — this app has none at all
  by design (no PFF-equivalent product exists for college basketball).
- Prefer free APIs over scraping; Barttorvik specifically is NOT scraped
  even though a URL-parameter trick is documented elsewhere online — it's
  bot-walled in practice, and this app doesn't attempt to defeat that.
  ncaa.com's NET rankings page is the one explicitly user-authorized
  exception (§2) — keep it manual/click-triggered only. Don't add
  auto-refresh, a schedule, or a background poll for it without asking
  first, and don't extend the same scraping exception to any other site
  without separately asking.
- Keep the "same theme, different accent color" relationship to NFL
  Scholar and CFB Scholar intact — don't drift the shared surfaces/fonts
  /layout tokens per-app, only the primary accent pair.
- The Odds API key is shared with CFB Scholar (same account) — the
  ~500 credit/month free-tier allowance is NOT per-app.

## 9. Repo & running on another machine

Lives in a PRIVATE GitHub repo: https://github.com/bradent27-sketch/CBBScholar
(sibling: https://github.com/bradent27-sketch/CFBScholar). Pushed from the
main PC via GitHub CLI, which is installed and authenticated there as
`bradent27-sketch` (token in gh's own config, `repo` scope).

The repo is the complete app EXCEPT `.streamlit/secrets.toml` — the live
CBBD + Odds API keys — which is gitignored and must never be committed,
private repo or not. `.streamlit/secrets.toml.example` is the template.
(Unlike CFB Scholar there's no paid-data folder here; nothing else is
held back.)

Fresh-machine setup: clone (or Code → Download ZIP), `pip install -r
requirements.txt`, copy `.streamlit/secrets.toml.example` to
`.streamlit/secrets.toml` and fill in real keys, `streamlit run app.py`.
Without secrets, tabs that need the APIs show their NEEDS SETUP state but
the app still runs.
