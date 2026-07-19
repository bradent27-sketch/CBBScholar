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

## 7. Deliberately NOT done / parked

Formerly parked and now DONE in the data-viz pass: game-by-game logs (with
breakout flags and last-5 form), the Compare delta table (relative Edge %
with diverging colors), team-level league-percentile context (Four
Factors/style/efficiency percentiles — the "full-D-I pull" turned out to be
ONE cached call via `/stats/team/season`, not the per-team fan-out
originally feared), and `data/transforms.py` is no longer empty.

Also now DONE (this pass): the Team DNA radar, the "What Wins This Season"
correlation panel, and the season margin trend/consistency chart - see §3.

Still parked: PLAYER-level league-wide percentiles (that one genuinely
needs a full-D-I player pull; `/stats/player/season` is team-scoped).
Per-arena home-court values (flat 3-point constant instead). Tempo-free
possession-length or lineup data (`/lineups`, `/plays` exist in the spec —
unexplored). `cbbd` Python package vs. raw `requests` - unchanged. UI
charts are hand-rolled inline SVG on purpose (theme-exact, zero deps,
native hover tooltips) - revisit only if interactivity needs outgrow
`<title>` tooltips. Back-porting the three new `ui/charts.py` functions to
CFB Scholar to restore the "byte-identical" invariant (see note at the top
of this doc) - not done, needs a separate pass in that repo.

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
