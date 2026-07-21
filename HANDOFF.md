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

**Refinement pass (this doc's most recent update):** weekly caching for
league-wide/percentile data, expanded player rate stats (3PT/2PT/FT rate),
Player Search game log polish (opponent color, W/L, unified pinned average
row), Four Factors tiering now shows raw numbers alongside color, a fixed
team-coloring bug that was silently no-op-ing on any table indexed by
'Team' (NET & Resume, Team Efficiency rankings), and the big one — Matchup
Analyzer split into OVERVIEW/TEAM DEFENSE/PLAYER TRENDS sub-tabs, with a
new positional matchup defense system (what opposing guards/forwards/
centers have done against a team, vs their own season averages, with
trend lines) built WITHOUT a full-D-I API fan-out. See §3 and §5 below for
the architecture and the gotchas hit building it.

**Important caveat on this pass:** this sandbox's network policy blocks
outbound access to api.collegebasketballdata.com and ESPN's endpoints
(confirmed: `curl` gets a 403 from the egress proxy on both hosts) - so
none of this pass's code could be verified against a REAL live API
response, breaking this app's own established discipline of checking every
endpoint live before writing a parser against it. What WAS done instead:
(1) every new field this pass relies on is a documented sibling of an
already-live-verified field on the same parent object (e.g. Def 3PA
Rate/3P%/DREB% read from `opponentStats`, whose `.fourFactors`/`.points`
siblings are already confirmed live) rather than a guess at a wholly new
shape; (2) the whole app was run end-to-end against a monkeypatched data
layer emitting realistically-shaped synthetic payloads, driven with a
real headless browser (Playwright) clicking through every tab/sub-tab, to
catch real Python exceptions and verify rendering - this caught at least
one real, pre-existing bug (see §5) that pure code-reading missed. It did
NOT and CANNOT confirm the assumed field shapes/values are correct against
the real API. **Before trusting Team Defense's positional breakdown or
Player Trends in particular, run `streamlit run app.py` for real (network
available on your machine) and sanity-check the numbers against something
you know** - especially the roster `position` field's exact granularity
(see the position_bucket entry in §5).

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
- **Positional matchup defense** (`data/loaders.load_team_opponent_game_logs`
  + `data/transforms.position_bucket`/`positional_defense_summary`/
  `positional_defense_trend`, rendered in Matchup Analyzer's TEAM DEFENSE
  sub-tab): "what have opposing guards/forwards/centers actually done
  against this team" WITHOUT a per-matchup or full-D-I API fan-out. The
  trick: a team's own schedule (`load_team_games`) already lists every
  opponent it has actually played (typically 12-30, not 360+) - for each of
  those, `load_player_game_logs(opponent, season)` (the SAME already-
  verified per-team `/games/players` call Player Search's game log already
  uses) returns that opponent's full-season box scores, which get filtered
  to `Opponent == this_team`. This also gives each opposing player's own
  season average for free (same cached frame, not a second endpoint call).
  Cost: ~1 call per opponent already played, cached weekly + shared across
  every OTHER matchup touching the same opponent (heavy overlap in-
  conference) - not paid fresh per matchup. Position bucketing (Guard/
  Forward/Center) from `/teams/roster`'s `position` field could NOT be
  verified live this pass (network-blocked sandbox, see the top-of-doc
  caveat) - `position_bucket()` handles both a simple G/F/C scheme and a
  detailed PG/SG/SF/PF/C scheme defensively, but confirm against a real
  payload before trusting the buckets.
- **Team defense profile** (`data/transforms.team_defense_profile`, powers
  Matchup Analyzer's "General Defensive Profile"): eFG%/3PA rate/3P%/ORB%
  allowed plus this team's own DREB% (the complement of opponent ORB%
  allowed - no separate rebounds sub-object needed) and TO ratio forced,
  percentile vs D-I with the correct direction baked in per column. Built
  entirely from the SAME `/stats/team/season` pull Four Factors already
  uses (`opponentStats.threePointFieldGoals`/`.fieldGoals`, siblings of the
  already-verified `.fourFactors`/`.points`) - zero extra API cost.
- **Player tendency profile** (`data/transforms.player_profile_values`/
  `player_percentile_rows`, shared by Player Search and Matchup Analyzer's
  PLAYER TRENDS sub-tab): 3PT/2PT/FT shot-selection rate, rebound split,
  shooting/efficiency splits, percentile-ranked vs conference or full D-I.
  Extracted into `data/transforms.py` specifically so Player Search and
  Matchup Analyzer compute this vocabulary identically instead of two
  independent, driftable implementations.
- **Player trend lines** (`data/transforms.player_trend_series` +
  `ui/charts.render_trend_line`): last-N-games-vs-season-average as an
  actual line (not just the two aggregate numbers `last_n_form` already
  gave `st.metric`) - points above the season average render green, below
  render red, so a "heating up" or "cooling off" run reads as a shape.
  Reused for the positional-defense-over-time chart too (same chart
  function, `data.transforms.positional_defense_trend` feeds it instead).
- **Weekly league-wide caching** (`data/loaders.clear_league_wide_caches`,
  wired to a sidebar button): every full-league/percentile-context pull
  (`load_all_player_season_stats`, `load_all_team_season_stats`,
  `load_efficiency_ratings`, `load_conference_player_season_stats`,
  `load_team_opponent_game_logs`) uses `@st.cache_data(ttl=604800,
  persist="disk")` instead of the old 1-6h in-memory-only TTLs - this was
  the direct fix for "percentile rankings are a slow load-in": league
  CONTEXT data doesn't need to feel live the way a specific team/player's
  OWN stats do (those keep their short TTLs, unchanged), and `persist=
  "disk"` means an app restart (Streamlit Community Cloud can do this on
  inactivity) reuses last week's pull instead of re-running a 360-team
  fan-out cold. The sidebar button clears all of them on demand for
  whenever fresher-than-a-week data is wanted.

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
- **Streamlit's `st.dataframe` does not render ANY pandas-Styler styling
  applied to the index/row-header cells** - confirmed live (not just by
  reading the code): `.apply(func, axis=1)` only ever reaches `df.columns`,
  which is expected, but `.apply_index(func, axis=0)` (the API that's
  supposed to style row headers) is ALSO silently ignored by Streamlit's
  grid - it shows up correctly in `Styler.to_html()` but never makes it
  into the rendered app. Concretely: `style_plain_dataframe(df.set_index(
  'Team'), team_color_map=...)` renders with NO team coloring at all, on
  every row, even though the exact same call with 'Team' left as a regular
  column works perfectly. This was a REAL, pre-existing bug in this app
  (NET & Resume's NET table, its Polls table, and Team Efficiency's
  rankings table all did `.set_index('Team')` before styling) - it's
  exactly why NET & Resume looked like it had no team colors despite the
  code appearing to pass a real color map, and it's the kind of bug that
  only shows up by actually running the app, not by reading the styling
  function and confirming the logic "looks right" for a Team COLUMN.
  **Fix: never `.set_index('Team')` (or any column you want Styler-colored)
  before calling `style_plain_dataframe` - keep it as a real column and use
  `hide_index=True` with a plain sequential index instead**, the pattern
  Conference Standings and the game log table already used correctly.
- **Secrets committed to the wrong file** - `.streamlit/secrets.toml.example`
  (the tracked TEMPLATE file, meant to hold placeholders) had real-looking
  working API keys in it from the initial commit, not placeholder text -
  `.streamlit/secrets.toml` (the real, gitignored file) is where live keys
  belong. Fixed to placeholders in this pass. Since the real values were in
  git history on a (private) GitHub repo, **rotate both keys** (cbbd_api_key
  at collegebasketballdata.com/key, odds_api_key at the-odds-api.com) and
  only ever put new values in the local, gitignored `secrets.toml` - never
  the `.example` file, private repo or not.

## 6. Verification workflow (what "done" means for this pass)

Every CBBD/ESPN/Odds API endpoint used here was checked live before the
parser was written - field names are confirmed exact. `streamlit run
app.py`, click through all 10 tabs on a **freshly started server**,
confirm zero `"hit an error"` text anywhere, confirm the live tabs show
real current data (Live Odds correctly shows "no games" in July - CBB is
in its off-season).

**This pass could not follow that workflow** - this build environment's
network policy blocks api.collegebasketballdata.com and ESPN's endpoints
outright (confirmed: a direct `curl` gets a 403 from the egress proxy on
both hosts). What this pass did instead, as the closest available
substitute: (1) every new field relied on is a sibling of an already-live-
verified field on the same parent object, never a cold guess at a new
shape; (2) the full app was run against a monkeypatched data layer
(synthetic-but-realistically-shaped payloads standing in for every CBBD/
ESPN/Odds call) driven end-to-end with a real headless browser clicking
every tab and sub-tab, confirming zero `"hit an error"` text and visually
confirming the new layouts/colors/charts render as intended - this is
genuinely how the pre-existing `.set_index('Team')` styling bug (§5) got
found. **This substitute CANNOT confirm the real API's field values or
even field NAMES are exactly as assumed** - re-run the real verification
workflow above (real key, real network) before fully trusting anything new
this pass touched, especially the position-bucket granularity assumption.

## 7. Deliberately NOT done / parked

Formerly parked and now DONE: game-by-game logs (with breakout flags and
last-5 form), the Compare delta table (relative Edge % with diverging
colors), team-level league-percentile context (Four Factors/style/
efficiency percentiles — the "full-D-I pull" turned out to be ONE cached
call via `/stats/team/season`, not the per-team fan-out originally
feared), `data/transforms.py` is no longer empty, PLAYER-level league-wide
percentiles (conference by default, full-D-I as an opt-in checkbox -
`load_all_player_season_stats`'s per-team fan-out, now weekly-cached +
disk-persisted so the cost is paid once a week not once every visit), and
positional matchup defense (see §3 - built without the full-D-I fan-out
this item's earlier "genuinely needs a full-D-I pull" note assumed it
would).

Still parked: per-arena home-court values (flat 3-point constant instead).
Tempo-free possession-length or lineup data (`/lineups`, `/plays` exist in
the spec — unexplored). `cbbd` Python package vs. raw `requests` -
unchanged. UI charts are hand-rolled inline SVG on purpose (theme-exact,
zero deps, native hover tooltips) - revisit only if interactivity needs
outgrow `<title>` tooltips. Player-level positional matchup defense trend
charts currently plot Points allowed only (Rebounds/Assists have the
summary-table delta but not their own trend line) - straightforward to
add, just scoped down to keep this pass's UI from getting overloaded with
charts; the data (`positional_defense_trend` accepts any `stat` column
already in `load_team_opponent_game_logs`' output) already supports it.

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
- League-wide/percentile-context data (not a specific team/player's own
  stats) defaults to a ~weekly cache, not live-on-every-visit — this was
  requested explicitly ("pull weekly, compare against week-old averages -
  not a huge deal"). Don't tighten these back to a short TTL without
  asking first; the sidebar's manual refresh button is the intended way to
  get fresher data on demand.

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
