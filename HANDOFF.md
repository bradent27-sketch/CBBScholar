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

**UI copy cleanup + Matchup Analyzer conference-mismatch bug + D-I
comparison caching + a positional-defense source indicator (this doc's
most recent update).** Three requested changes from real usage:

1. **Cut most of the small explanatory `st.caption()` text app-wide** -
   "how to read this chart"/"what does this feature do" prose under
   charts and tables, per explicit request ("just the titles are fine").
   Removed from Team Efficiency, Player Search, NET & Resume, Matchup
   Analyzer, Live Odds, Player Compare, Transfer Portal, Conference
   Standings, and the sidebar (which also had a stale "this pass ships
   navigation and theme only" placeholder left over from early
   development - removed, not accurate for a while). KEPT: short factual/
   status captions (row counts, "Source: X", "no data yet" states) - the
   distinction is explanation-of-mechanics vs. a fact the user needs. On-
   hover `help=` tooltips (checkboxes, sliders, stat bars) were left alone
   - different UX pattern (opt-in, not always-visible clutter).

2. **Matchup Analyzer's PLAYER panel showed no comparison bars for some
   players** even though Player Search worked fine for the same players.
   Root cause: the conference-scoped comparison group was filtered using
   `conf` - CBBD's spelling of the player's conference (e.g. "ACC") -
   against ESPN's OWN team list, whose conference field can be formatted
   differently (e.g. "Atlantic Coast Conference"). A mismatch silently
   produced an empty comparison group (no bars), while the "compare
   against all of Division I" checkbox worked for every player, since
   that path never needs a conference match at all - exactly the reported
   symptom. **Fixed** the same way Player Search already avoided this
   entirely: derive the conference from ESPN's OWN team list for the
   player's own (ESPN-spelled) team, never cross-reference CBBD's
   spelling against ESPN's list.

   Also **cached the "compare against all of Division I" aggregation**
   (new `data.loaders.load_espn_di_player_stats`/
   `_espn_di_player_stats_cached`) - this is a real pandas groupby over
   every D-I player's whole season of box scores, slow enough to cause a
   noticeable pause on every player switch, not just first load (a real,
   reported perf complaint). Cached to the SAME twice-weekly cadence as
   the underlying box file (`_twice_weekly_bucket()` - recomputing more
   often than the source data changes is pure waste), `persist="disk"`
   for cross-restart survival, and wired into `clear_league_wide_caches()`
   for the manual refresh button. Shared by Player Search's own "compare
   against all of D-I" checkbox too (previously recomputed the same
   aggregation independently, unconditionally, on every rerun) - one
   cached computation instead of two independent uncached ones.

3. **Positional matchup defense now shows which source it actually used**
   ("Source: free ESPN season file." / "Source: CollegeBasketballData.com
   (CBBD API calls used)."), right after loading - requested explicitly
   ("i want to know if CBBD calls are occurring"). Determined from
   `load_positional_matchup_data`'s own existing contract: it carries a
   real `Position` value on every row when the free ESPN file was used,
   and sets it to `None` on every row for the CBBD fallback (see that
   function's docstring) - reused as the signal rather than threading a
   new return value through the whole call chain.

Verified via `streamlit.testing.v1.AppTest`: a synthetic conference-name-
mismatch scenario (CBBD "ACC" vs. ESPN "Atlantic Coast Conference")
confirming bars now render; a call-counting mock confirming the D-I
aggregation only actually computes once across multiple reruns (cache
hit, not recompute); and both branches of the source indicator (ESPN vs.
CBBD-fallback `Position` columns) showing the correct caption. Still not
verified against live CBBD/ESPN - same standing sandbox caveat as
everything else in this pipeline.

**Real bugs, live-confirmed after deploy: the ESPN roster/box-file id
mismatch, and DNP rows inflating games
played.** The previous pass's ESPN-native pipeline extension shipped
without live verification (standard caveat for this sandbox). Once
actually run against real data, three real, connected bugs surfaced:

1. **`load_espn_roster`'s 'sourceId' (ESPN's own roster endpoint's
   athlete id) and the SportsDataverse box file's 'athleteSourceId' are
   DIFFERENT id namespaces** - despite `load_espn_roster`'s own docstring
   assuming they were the same. Every id-based join between them matched
   NOTHING, for every player. Two distinct, confusing symptoms from the
   same root cause: Player Search's team-filtered mode showed "No game
   data found" for every player on every team/season (the roster-picked
   player's id never matched anything in the box file's stats); All Teams
   mode's STATS worked fine (it reads name/id straight from the box file,
   bypassing the broken join for that direction) but bio fields (height/
   weight/hometown) came back blank (the REVERSE lookup into the roster,
   by the same broken id, also matched nothing - fell back to a stub
   `pd.Series({'position': ...})` with nothing else set). **Fixed**: join
   by NAME instead of id, in both directions - new `data.utils.
   match_player_name` (clean_name_exact first, clean_name_for_merge
   fallback for Jr./Sr./II/III inconsistencies - both helpers already
   existed in data/utils.py, ported from NFL Scholar, unused until now).
   `ui/tabs/player_search.py`'s `bio_idx`/`stats_idx` lookups use it; the
   box file's OWN `athleteSourceId` (found via the name match) is then
   used for all further box_df lookups (game log) instead of the
   unreliable roster id, so it stays self-consistent going forward.

2. **Matchup Analyzer's PLAYER panel fell back to CBBD almost constantly**
   (caption: "Source: CollegeBasketballData.com (the free box file isn't
   fresh enough for this team...)") - not because the data was actually
   stale, but because the PREVIOUS version of `get_player_season_profile`
   resolved the box file against CBBD's OWN team list
   (`load_espn_season_player_box`, the CBBD-name-resolved twin
   positional matchup defense uses) instead of ESPN's. Since the box
   file's raw team names are themselves ESPN-sourced, they resolve far
   more reliably against ESPN's own team list (`load_espn_teams`) than
   against CBBD's independently-formatted one - opponents that failed to
   resolve against CBBD's list got silently dropped, making a team's
   LATEST game in that CBBD-resolved file look artificially old and
   tripping the 10-day "not fresh enough" fallback for nearly every team.
   Player Search never had this problem because it always resolved
   against ESPN's own list via `load_espn_season_player_box_native`.
   **Fixed**: `get_player_season_profile` was rewritten to use the SAME
   ESPN-native architecture as Player Search (`load_espn_teams` +
   `load_espn_roster` + `load_espn_season_player_box_native`, `team`
   bridged to ESPN's spelling via `resolve_team_name`, `player_name`
   matched via the new `match_player_name` - same id-mismatch fix as
   bug 1 above, since this function ALSO joins ESPN's roster against the
   box file) - falling back to CBBD only when ESPN's own team/roster/
   box-file lookups genuinely come up empty for that player, not a date-
   freshness guess. The team/player PICKER itself (Matchup Analyzer and
   Compare both still pick from CBBD's `/teams/roster`) is UNCHANGED -
   only the stats-lookup source changed. Function signature changed from
   `(team, season, athlete_source_id, cbbd_athlete_id)` to `(team,
   season, player_name, cbbd_athlete_id)` accordingly - both callers
   (`ui/tabs/matchup_analyzer.py`, `ui/tabs/compare.py`) updated. Also
   now returns a 5th value, `athlete_source_id` (the box file's OWN id
   for this player when source=='espn') - callers use THIS, not the
   caller's original id, for any further box_df lookups (Matchup
   Analyzer's trend section), same self-consistency fix as bug 1.
   Positional matchup defense's OWN CBBD-resolved fallback
   (`load_positional_matchup_data`/`_is_espn_data_fresh_enough`) is
   UNCHANGED and still a legitimate use of that pattern there - it needs
   to line up with Team Defense's CBBD-sourced opponent list, a genuinely
   different requirement from PLAYER's season-profile lookup.

3. **DNP rows (0 or missing Minutes) were counting as "games played"**,
   deflating every affected player's season averages - live-confirmed
   against a real discrepancy (Abdi Bashir: 13.2 real PPG vs. 7.4 shown,
   a ~44% gap consistent with several missed games from injury getting
   counted as games). The raw box file carries a full row (0 points, 0
   everything) for a player who was AVAILABLE for a game but didn't
   actually play, not just for players who played -
   `espn_player_season_stats_for_teams`'s `games = len(g)` counted every
   row equally. Every stat SUM was unaffected either way (a DNP row
   contributes zero regardless), only the denominator. **Fixed** at the
   single shared choke point both box-file variants flow through -
   `data.loaders._resolve_espn_box_team_names` now drops rows with
   Minutes <= 0 or missing, so `games = len(g)` becomes correct
   automatically everywhere downstream (season totals, game logs, trend
   charts, positional matchup defense) without needing per-consumer
   patches. (The earlier addition of OREB/DREB/FTM/FTA columns to the
   CBBD-resolved box-file finisher, made to serve the now-replaced
   CBBD-resolved version of `get_player_season_profile`, was reverted -
   no longer needed since that function uses the ESPN-native twin now,
   which already carried those columns.)

**Verification**: this sandbox still can't reach live CBBD/ESPN/GitHub-
release endpoints (same standing caveat), so this was verified via (a)
direct unit tests of `match_player_name` and the DNP filter against
synthetic data replicating the exact reported symptoms (including a
suffix-inconsistent name and a deliberately-mismatched-id scenario), (b)
a synthetic-payload test of the rewritten `get_player_season_profile`
covering the ESPN-native success path and both CBBD-fallback paths, and
(c) `streamlit.testing.v1.AppTest` runs of all three affected tabs
end-to-end against a monkeypatched data layer, explicitly asserting the
bugs' exact symptoms are gone (no "No game data found" in team-filtered
Player Search, real height/weight in All Teams mode's bio strip, Matchup
Analyzer's PLAYER panel resolving to "Source: free ESPN..." rather than
the CBBD fallback caption). **Before trusting this**: run for real once
the season starts and spot-check a player you know across all three tabs,
same discipline every previous pass in this doc has applied.

**Data-import automation pass: the zip
file question, twice-weekly refresh, and extending the free box-score
pipeline past Player Search.** User downloaded a local hoopR bulk-data zip
(2003-current) intending to seed this app with historical data, and asked
how to get it in plus whether the app can auto-refresh twice a week once
the season starts. Two findings, not a code problem: (1) the zip is
unnecessary and was never uploaded - confirmed live via WebFetch that
`sportsdataverse/hoopR-mbb-data` (the repo the user's data actually came
from) has ZERO releases of its own - it's the R/Python processing
pipeline, not a data host. The parquet files it produces get published to
`sportsdataverse/sportsdataverse-data`'s GitHub Releases instead, which is
the exact URL already wired into this file (`ESPN_SEASON_PLAYER_BOX_URL`).
This app already pulls per-season files on demand over HTTPS; no bulk
download/upload was ever needed. (2) The twice-weekly auto-refresh the
user pictured already existed (`_twice_weekly_bucket()`) but only powered
Player Search and positional matchup defense - everywhere else was still
CBBD-only, refreshed weekly, and quota-metered. Nuance explained to the
user: this refresh is lazy-on-next-visit (Streamlit has no background
cron), not a literal push while the app sits closed - normally
indistinguishable from "automatic" for personal use, but not literally
continuous.

Season range trimmed to 2023-2027 (`config.py`'s `AVAILABLE_SEASONS`/
`AVAILABLE_SEASONS_WITH_UPCOMING`, previously 2020-2027) per explicit
request - personal use only needs recent seasons visible/selectable
app-wide. Both data sources still support any season back to ~2003 if
this window is ever widened again - a UI-visibility trim only, not a
data-source limitation.

**Extended the free ESPN/SportsDataverse pipeline to Matchup Analyzer's
PLAYER panel and Player Compare** (`data.loaders.get_player_season_profile`,
new) - both tabs were explicitly scoped OUT when Player Search's CBBD-free
pipeline was first built (see this doc's "Player Search ONLY" note from
that pass); this is the requested follow-up. The new function mirrors
`load_positional_matchup_data`'s already-proven "ESPN first, CBBD fallback
whenever the free file is missing, unreachable, or lagging this team's
actual schedule by more than 10 days" pattern (`_is_espn_data_fresh_enough`,
reused unchanged) - CBBD is only actually CALLED when the free path can't
be used, which is the real quota saving, not just a preference order.
Returns a CBBD-shaped stats dict either way (via
`espn_player_season_stats_for_teams`, reused unchanged from Player Search)
so `player_percentile_rows`/`player_profile_values`/Compare's own
`_numeric_stat_map` need zero source-specific branching beyond the
`include_net_rating` flag this function also returns (False for ESPN, same
reasoning as Player Search: box scores alone can't produce Net Rating).
Matchup Analyzer's PLAYER panel also pulls its "last 10 games" trend from
the SAME already-downloaded box file when ESPN is used (no second CBBD
`/games/players` call, and season totals + game log can never disagree
about which games happened, unlike sourcing them from two different
endpoints); Compare's three sections (stat tiles, delta table, radar) now
resolve both players' profiles ONCE in `render()` and thread the result
down as a parameter instead of each section independently re-fetching,
which the CBBD-only version did.

One real, deliberate exception to this file's established "`data/loaders.py`
is raw ingestion only, never imports `data/transforms.py`" layering (see
§1 Architecture): `get_player_season_profile` needs
`espn_player_season_stats_for_teams` to shape ESPN rows into the CBBD dict
shape, and reusing it beats a second, independently-driftable copy of that
Usage%/eFG%/TS% computation living in loaders.py instead - documented
inline at the import site.

Also extended `_load_espn_season_player_box_cached` (the CBBD-name-resolved
twin positional matchup defense already used) to keep OREB/DREB/FTM/FTA -
it previously dropped them (positional defense never needed them), which
would have silently degraded `get_player_season_profile`'s ESPN branch to
the FTA-free Usage% approximation and no FT%/rebound-split every single
time, purely because of which finisher function got reused, not real data
unavailability. Existing callers are unaffected (they don't select the new
columns).

**Not independently live-verified** - same standing sandbox caveat as
every ESPN/SportsDataverse touchpoint in this app (this build
environment's egress proxy still returns 403/"not enabled for this
session" on both api.collegebasketballdata.com and GitHub release-asset
downloads, confirmed again this pass). What WAS done: confirmed via
WebFetch that `sportsdataverse/hoopR-mbb-data` has no releases of its own
(so `sportsdataverse-data` really is the correct, current URL, not a
guess); a synthetic-payload unit test of `get_player_season_profile`
covering all three branches (ESPN-fresh, CBBD-fallback-on-staleness,
CBBD-fallback-on-empty-file) confirmed the resolver's own logic; and a
`streamlit.testing.v1.AppTest` run of both changed tabs end-to-end
(season/team/player selectbox interactions, the D-I comparison checkbox)
against a monkeypatched data layer confirmed zero exceptions in the actual
UI wiring - including the case where one Compare player resolves to ESPN
and the other falls back to CBBD (a real, un-mocked CBBD call in that run
correctly degraded to an empty result rather than crashing, since this
sandbox can't reach CBBD live either). **Before trusting this**: run
`streamlit run app.py` for real (real network, real cbbd_api_key) once the
2026-27 season is underway, open Matchup Analyzer's PLAYER panel and
Player Compare for a team with recent games, and confirm the new "Source:"
caption says ESPN (not a permanent CBBD fallback) and the numbers look
right.

**Real bug fix - Player Search returned "no data" for every season:** the CBBD-free pipeline shipped last pass
failed completely in real use. Root-caused with ACTUAL live verification
this time (not the usual "reasoned but unverified" caveat) - this dev
sandbox's egress proxy explicitly denies `site.api.espn.com` and GitHub
release-asset hosts (confirmed via the proxy's own status endpoint:
`"kind": "connect_rejected", "detail": "gateway answered 403 to CONNECT
(policy denial or upstream failure)"`), but `WebFetch` routes through a
different path that reached `api.github.com` and even downloaded real
release-asset binaries (saved to disk, then parsed here with real
pandas/pyarrow) - genuine, not synthetic, verification.

**Two real bugs found and fixed, both in `data/loaders.py`:**
1. **`load_espn_teams()` used ESPN's `displayName` field ("Duke Blue
   Devils") as the canonical 'Team' name, but the SportsDataverse box file's
   own `team_location` column (confirmed via a real downloaded
   `player_box_2026.parquet` - 196,876 rows, genuinely current 2025-26
   season data, real player names like Cameron Boozer) uses the SHORT
   school name ("Duke") - and `data.utils.normalize_team_name` has no
   mechanism to bridge the two (it strips punctuation/case/"University"-
   style suffixes, not mascot names). Every single row failed to resolve
   against the canonical list, `_resolve_espn_box_team_names` dropped
   every row via its `.dropna(subset=['Team','Opponent','Date'])`, and the
   whole pipeline silently returned an empty DataFrame - for EVERY season,
   because the bug was in the team-name JOIN, not in the season's data
   availability, which is what the empty result misleadingly suggested.
   Fixed: `load_espn_teams()` now uses `location` first, `displayName`
   only as a fallback (and keeps `DisplayName` as a separate column for
   nicer on-screen labels later). Reproduced and confirmed fixed with a
   standalone `resolve_team_name()` test before touching the real pipeline,
   then re-verified end to end against the real downloaded file (see
   below).
2. **`_load_espn_season_player_box_native_cached` called `load_espn_teams()`
   with no `season` argument**, silently using `current_cbb_season()`
   regardless of which season was actually being requested - wrong
   team/conference list for any historical-season lookup. Fixed to pass
   `season` through.

**Also fixed while in there - a real caching-robustness gap**: every
`@st.cache_data(persist="disk")` loader in this file that swallows
exceptions into `return pd.DataFrame()` has always had this latent risk,
but the ESPN-native box pipeline is where it got fixed first: a single
transient failure (a network blip, the CDN briefly erroring) was getting
memoized by Streamlit's cache JUST as durably as a real success, for the
entire twice-weekly window, with no automatic retry until someone clicked
"Refresh league-wide data." Fixed by having `_fetch_espn_season_box_raw_cached`
RAISE on failure instead of returning empty - Streamlit does not cache an
exception, only a successful return - with the exception caught at the
public-wrapper level (`load_espn_season_player_box`/`_native`, NOT
`@st.cache_data`-decorated), so external behavior (empty DataFrame on
failure) is unchanged but a transient failure now retries on the next call
instead of being locked in. Worth applying the same pattern to this file's
OTHER `except Exception: return pd.DataFrame()` cached loaders if this
class of bug shows up again elsewhere - not done this pass (scope
discipline), but now a known, named risk instead of a surprise.

**What real verification actually confirmed** (downloaded and parsed with
real pandas/pyarrow, not assumed): `player_box_2026.parquet` genuinely
exists and is current (game dates through 2026-04-06, real players, real
box lines); the exact same column schema this app's code already assumed
(`field_goals_made`, `three_point_field_goals_attempted`,
`free_throws_made/attempted`, `offensive_rebounds`/`defensive_rebounds`,
`athlete_id`, `athlete_position_name`, `team_location`,
`opponent_team_location`, etc. - EVERY one of them, including the ones
this app's own prior passes explicitly flagged as unverified guesses);
running the real (fixed) `data.loaders`/`data.transforms` pipeline against
the real file produces correct results end to end - real Duke roster
(Cameron Boozer, Isaiah Evans, Caleb Foster, Cayden Boozer...), sane
Usage%/eFG% ranges, a correct 35-3 W/L record derived purely from summed
box-score points (no separate schedule endpoint), and every spot-checked
team (UConn, North Carolina, Kentucky, Kansas, Gonzaga, Houston) resolving
and aggregating correctly. **Still NOT verified**: the exact response
shape of `_fetch_standings_raw`'s live ESPN standings call specifically
for `id`/`color`/`alternateColor` on the embedded team object (site.api.
espn.com itself stayed unreachable through every path tried, including
WebFetch) - `load_espn_teams()`'s EspnId/Color/AltColor columns are still
the same "sibling of an already-confirmed field" reasoning as before, not
independently confirmed. Also unverified: whether Streamlit Community
Cloud's own outbound network path to GitHub behaves identically to what
WebFetch showed here - the file's existence and schema are proven, but
the exact HTTP path a deployed Streamlit app takes to fetch it was not
independently re-tested post-fix.

**On research method**: large, array-heavy GitHub API JSON responses
(e.g. listing all 100+ release assets) came back INCONSISTENT and
sometimes flatly wrong across repeated identical `WebFetch` calls -
almost certainly the intermediate summarization model truncating/
mis-reading a large payload, not the underlying data changing. Trust a
`WebFetch` list-enumeration result to actually be complete; don't trust it
to be COMPLETE for large arrays. Confirmed-reliable pattern instead:
query one specific known resource at a time (a single release tag, a
single asset's direct download URL) - small, bounded responses came back
correct and consistent every time. Prefer that pattern over "list
everything and scan it" for any future GitHub API research in this app.

**Player Search CBBD-free pipeline:** on
request (reduce reliance on CBBD's 1,000-call/month free tier for the
tab that gets used most), Player Search was rebuilt to source EVERYTHING
from ESPN's public endpoints + a free SportsDataverse season box-score
file instead of CollegeBasketballData.com - the one deliberately CBBD-free
tab in this app. **Scope decision: Player Search ONLY** - Compare and
Matchup Analyzer's PLAYER panel still use CBBD's `/teams/roster`/`/stats/
player/season`/`/games/players` exactly as before, unchanged, including
Net Rating. Don't assume this pipeline extends to those tabs without
separately being asked.

New pieces: `data.loaders.load_espn_teams` (team list/colors/conference,
reused from the SAME standings payload Conference Standings already
fetches, rather than guessing at a new `/teams` endpoint), `load_espn_
roster` (bio fields, a new live ESPN call), and `load_espn_season_player_
box_native` (the CBBD-free twin of the existing `load_espn_season_player_
box` positional-defense source - same underlying file, shared raw
download via the new `_fetch_espn_season_box_raw_cached`, but resolved
against ESPN's own team list instead of CBBD's, and carrying extra columns
- OREB/DREB/FTM/FTA - the CBBD-resolved twin doesn't need). This ONE file
is both season stats AND game log for Player Search (totals are just the
per-game rows summed - `data.transforms.espn_player_season_stats_for_teams`)
- unlike CBBD's two-separate-endpoints design. D-I-wide and conference-wide
percentile comparison groups are now free (no per-team fan-out - the whole
season's already in the one downloaded file), so the "compare vs D-I"
checkbox lost its old "cached ~weekly, first pull takes a bit" framing.

Net Rating is GONE from Player Search, not blank - deprioritized on
request, and genuinely not buildable from box scores alone (on/off point
differential needs lineup-level play-by-play tracking). `data.transforms.
player_profile_values`/`player_percentile_rows` got an `include_net_rating`
flag (default True, unchanged for every other caller) so Player Search can
omit the row's ORDERING SLOT entirely, not just null its value.

Usage% IS built here - CBBD hands it over precomputed, box scores don't -
via the standard formula, summed across the player's games, using that
team's own per-game FGA/FTA/TOV/minutes totals (derived by summing every
player who suited up that game, from the same box file). See
`espn_player_season_stats_for_teams`'s docstring for the exact formula and
its `has_ft`/`has_reb_split` graceful-degradation checks (computed once
per scope, not per-player) - if the guessed FTM/FTA/OREB/DREB column names
turn out to be wrong once this runs against a real payload, FT%/FT-rate/
ORB-DRB/TS% degrade to `None`/'--' and Usage% falls back to an FTA-free
approximation, rather than any of them silently computing a confidently-
wrong number from a phantom zero. Verified this degradation path with a
synthetic "columns entirely absent" test before trusting it - see this
pass's own testing discipline below.

Cache cadence: the ESPN/SportsDataverse box file (both the CBBD-resolved
positional-defense version AND the new CBBD-free version) now refreshes
**twice weekly** (`data.loaders._twice_weekly_bucket()`, same year-week
ISO string as `_week_bucket()` but split Monday-Wednesday/Thursday-Sunday)
instead of once weekly - bumped on request, since a plain file re-download
costs nothing extra (no CBBD-style quota at stake). This is a SHARED bump
- positional matchup defense also gets fresher data as a side effect, not
just Player Search. The sidebar's existing "🔄 Refresh league-wide data"
button is the manual override (both new cache-holding functions were
added to `clear_league_wide_caches()`) - no new UI element needed, unlike
NET Rankings' manual-only scrape (that one's manual because NCAA.org's
terms of service prohibit automation; neither ESPN's JSON API nor
SportsDataverse's published file downloads have that constraint, so both
can be, and are, fully automatic).

**Verification status - the biggest open risk in this pass**: none of
`load_espn_teams`'s reliance on `id`/`color`/`alternateColor` existing on
the standings payload's embedded team object, `load_espn_roster`'s
endpoint path/response shape, or the new OREB/DREB/FTM/FTA parquet column
names are live-verified (same standing network-blocked-sandbox caveat as
every other ESPN/SportsDataverse touchpoint in this app). Tested instead
via `streamlit.testing.v1.AppTest` end-to-end against a synthetic-but-
realistically-shaped monkeypatched data layer (same substitute prior
passes in this doc used) PLUS targeted unit tests of `espn_player_season_
stats_for_teams` confirming: Usage% comes out in a sane 0-100 range,
`include_net_rating=False` omits the key entirely, and - critically - an
"all guessed columns absent" scenario degrades every dependent stat to
`None` rather than a silently-wrong zero. **This cannot confirm the real
endpoint/column shapes are correct** - run this for real (real network)
and sanity-check Usage%/FT%/ORB-DRB specifically against a player you
know before trusting them, same discipline this doc has applied to every
previous ESPN/SportsDataverse addition.

**User-driven optimization pass:** a
tab-by-tab pass based on real usage (personal team-watching, bracketology,
and player-prop betting - the stated primary use case). Player Search: an
"All Teams" option on the team picker plus a fuzzy-matched search box
(`data.utils.fuzzy_filter_names`, stdlib `difflib` - no new dependency) so a
player can be found by name without picking their team first, backed by a
new `data.loaders.load_all_rosters` (same weekly-cached per-team fan-out
pattern as `load_all_player_season_stats`); season stat bars reordered to a
user-specified sequence (`data.transforms.player_profile_values`); last-5
form deltas now color-coded green/red (`ui.components.render_metric_tiles`);
the game log table and its season-average row are now ONE real table with a
CSS `position: sticky` footer (`ui.styling.render_sticky_footer_table`) -
replacing two separately-scrolling `st.dataframe` widgets that never
actually shared horizontal scroll state despite being CSS-seamed to look
connected. Team Efficiency: the rankings table was rendering height-uncapped
for 360+ teams (a ~12,000px-tall grid on every visit to the tab's default
sub-tab) - capped to a scrollable ~30-row window matching NET & Resume's own
existing precedent; the efficiency scatter's SVG-string build is now
`st.cache_data`-cached so it isn't rebuilt from scratch on every unrelated
widget rerun elsewhere on the page. Matchup Analyzer: rebuilt from a
team-vs-team projector (win probability, projected score, Four Factors
matchup, style profile, recent-form chips, OVERVIEW/TEAM DEFENSE/PLAYER
TRENDS sub-tabs) into a two-column PLAYER-vs-TEAM-DEFENSE layout per
explicit request - team-vs-team wasn't the actual use case (prop research
against one player and one defense was) - see §3 below for the new
`team_defense_profile_rows` single-team percentile-bar function and the two
new defensive columns (2P% Allowed, FT Rate Allowed) added to it. The
now-fully-orphaned team-vs-team compute functions (`four_factors_matchup`,
`style_profile`, `project_score`, `recent_form`, the old paired
`team_defense_profile`) were removed from `data/transforms.py` rather than
left as dead code - `ui/charts.py`'s `render_mirror_bars`/`render_form_strip`
were deliberately LEFT IN PLACE despite having no caller left in this app,
since that file is documented as byte-identical across this app and CFB
Scholar (team-vs-team is a much more natural fit for football) - don't
delete from `ui/charts.py` without checking CFB Scholar's own usage first.

**Previous refinement pass:** weekly caching for
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

**Follow-up refinement pass:** app-wide hover feedback on every custom SVG
chart shape (bars/cells/dots/lines) plus bio-strip cells and form chips -
see the `.hz-bar`/`.hz-cell`/`.hz-dot` classes in `ui/charts.py` and their
CSS in `ui/styling.py`'s `inject_theme()`. `st.dataframe`'s grid (glide-
data-grid, canvas-rendered) has NO native row/cell hover highlight and
CSS/Styler cannot add one - confirmed live, see §5 - so table-based tabs
(NET & Resume, Conference Standings, game logs, Transfer Portal) don't get
this treatment; every chart-based stat display does. Also this pass: a
`max_recent_games` cap (default 20, a UI slider) on the positional matchup
defense fan-out specifically because of CBBD's 1,000-call/month free tier
(see §2/DATA_SOURCES.md's "API budget" section for the full arithmetic),
and three hand-crafted demo scenarios (Duke/Kentucky guards, Kansas/
Gonzaga forwards, UNC/UConn centers) run through the real transform
functions to validate the positional defense engine tells the right
story - all three matched their intended narrative.

**Second follow-up pass:** wired in a free, keyless ESPN/SportsDataverse
data source (`data.loaders.load_espn_season_player_box`) as a
zero-CBBD-quota-cost PREFERRED source for the positional matchup defense
feature, with the existing CBBD path (`load_team_opponent_game_logs`) kept
as the automatic fallback whenever the free source is missing, unreachable,
or too stale to trust — see the new "ESPN/SportsDataverse fallback" entry
in §3 below and DATA_SOURCES.md. Also fixed two real bugs found while
building that: (1) `@st.cache_data(ttl=604800, persist="disk")` — the
pattern every "weekly cache" claim in this doc was based on — turns out to
SILENTLY IGNORE the `ttl` entirely once `persist="disk"` is set (confirmed
in Streamlit's own source; caches never expired on their own, contrary to
every "refreshes weekly" claim above), fixed app-wide via a new
`_week_bucket()` mechanism — see §5; (2) a real segfault traced to a
`pyarrow>=25.0` floor in `requirements.txt` conflicting with Streamlit's
own internal `pyarrow<25` pin — fixed to `pyarrow>=14.0,<25.0` — see §5.

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

**CBBD's free tier is capped at 1,000 API calls/MONTH** (confirmed via
CBBD's own docs/socials, not this app's own testing - this sandbox can't
reach the API at all, see §6) - no per-minute throttling, just a hard
monthly ceiling. **This quota is SHARED with CFB Scholar if both apps use
the same CFBD/CBBD account** (same mechanism as the already-documented
shared Odds API allowance in §8) - confirmed: CBBD accounts share one call
pool with CFBD. A free Student/Academic tier (.edu email) raises this to
3,000/month; Patreon tiers go up to 75,000/month (Tier 3, ~$10/mo) and add
GraphQL API access. This is the direct reason
`load_team_opponent_game_logs`'s positional-defense fan-out defaults to a
`max_recent_games` cap (20) instead of a whole season - uncapped, refreshing
a handful of teams late-season could burn a meaningful chunk of the free
1,000/month by itself. See DATA_SOURCES.md's "API budget" section for the
full arithmetic and other free mitigation options (CBBD's own free
"Exporter" web tool for manual CSV snapshots, the paid one-time Starter
Pack for historical backfill).

## 3. Key computed systems

- **Player-search team-first flow**: `load_teams()` → `load_team_roster(team,
  season)` → `get_player_season_stats(team, season, athlete_id)`, joined
  on CBBD's own `athleteId`/`id` (confirmed these match 1:1 across the
  roster and stats endpoints before relying on it).
- **Fantasy scoring** (`ui/tabs/fantasy_pools.py`): linear formula (points
  + rebounds + assists + steals + blocks − turnovers, user-adjustable
  weights) applied to real season totals, with a per-game average computed
  from `games`.
- **~~Matchup win probability~~ / ~~Four Factors matchup engine~~ /
  ~~Projected score~~ / ~~Venue adjustment~~ — REMOVED** in the
  player-vs-team-defense pass (see this doc's top entry): Matchup Analyzer
  is no longer a team-vs-team projector, so the logistic win-probability
  curve, the offense-vs-defense Four Factors matchup (`four_factors_matchup`
  - note `four_factors_percentile_grid`, which reuses the same `FOUR_FACTORS`
  table, is UNRELATED and still powers Team Efficiency's Four Factors
  Tiering sub-tab), the tempo-based score projection (`project_score`), and
  the flat home-court constant (`HOME_COURT_POINTS`) no longer have a
  caller and were deleted from `data/transforms.py` rather than left as
  dead code. `ui/charts.render_mirror_bars`/`render_form_strip` were kept
  despite losing their only caller here - see that entry's note on why.
- **Game logs + breakout detection** (`data/loaders.load_player_game_logs`,
  `data/transforms.breakout_flags`/`last_n_form`): per-game box scores via
  `/games/players` (one call per team-season, game context included in the
  same response). Breakout = ≥1.5 population-σ above the player's own season
  mean (suppressed under 4 games / ~zero variance); last-5 vs season deltas
  rendered via `ui.components.render_metric_tiles` (green when last-5 beats
  the season average, red when it's below - not `st.metric`'s own delta
  coloring, which only reads a plain leading +/- number and this delta text
  is a full sentence).
- **Poll trajectories** (`data/transforms.poll_trajectory` +
  `ui/charts.render_rank_trajectory`): the raw `/rankings` payload the NET &
  Resume tab already cached is the FULL season history — the trajectory
  chart is pure re-use, zero extra API cost.
- **Bracketology** (`ui/tabs/bracketology.py`): teams sorted by adjusted
  net rating, split into groups of 4 per seed line (1-16). Explicitly NOT
  a selection-committee simulation - no auto-bids, no resume factors (see
  NET & Resume), no bracket geography. Labeled as such in the tab itself.
- **Positional matchup defense** (`data/loaders.load_positional_matchup_data`
  + `data/transforms.position_bucket`/`positional_defense_summary`/
  `positional_defense_trend`, rendered in Matchup Analyzer's TEAM DEFENSE
  column): "what have opposing guards/forwards/centers actually done
  against this team" WITHOUT a per-matchup or full-D-I API fan-out.
  `load_positional_matchup_data` tries the free ESPN/SportsDataverse
  season file first (zero CBBD-quota cost - see the entry below) and falls back to
  `load_team_opponent_game_logs`'s CBBD-based approach below whenever that
  free source isn't usable. The CBBD fallback's trick: a team's own
  schedule (`load_team_games`) already lists every
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
- **Team defense profile** (`data/transforms.team_defense_profile_rows`,
  powers Matchup Analyzer's TEAM DEFENSE column, one team at a time - not
  the old team-vs-team paired `team_defense_profile`, removed): eFG%/3PA
  rate/3P%/2P%/FT rate allowed plus this team's own DREB% (the complement
  of opponent ORB% allowed - no separate rebounds sub-object needed) and TO
  ratio forced, percentile vs D-I with the correct direction baked in per
  column, rendered as single-sided bars (`ui.charts.render_relative_bars`,
  the same component Player Search uses) rather than the old mirrored
  two-team bars. Built entirely from the SAME `/stats/team/season` pull
  Four Factors already uses (`opponentStats.threePointFieldGoals`/
  `.fieldGoals`/`.twoPointFieldGoals`, siblings of the already-verified
  `.fourFactors`/`.points`) - zero extra API cost. 2P% Allowed and FT Rate
  Allowed were added on request; FT Rate Allowed was already a computed
  column (`Def FT Rate`) just not previously surfaced here, 2P% Allowed
  needed a new `Def 2P%` column in `data/loaders.load_all_team_season_stats`.
- **Player tendency profile** (`data/transforms.player_profile_values`/
  `player_percentile_rows`, shared by Player Search and Matchup Analyzer's
  PLAYER column): 3PT/2PT/FT shot-selection rate, rebound split, shooting/
  efficiency splits, percentile-ranked vs conference or full D-I - stat
  order is USER-SPECIFIED (PPG/APG/RPG/ORB/DRB/FG%/3P%/3PT rate/2PT rate/FT
  rate/FT%/eFG%/TS%/Net Rating/SPG/BPG/Usage%/MPG), not endpoint/alphabetical
  order, since dict-iteration order drives both callers' bar order at once.
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
  `load_team_opponent_game_logs`, `load_espn_season_player_box`) uses
  `@st.cache_data(persist="disk")` plus a `_week_bucket()`-derived cache
  key instead of the old 1-6h in-memory-only TTLs - this was the direct
  fix for "percentile rankings are a slow load-in": league CONTEXT data
  doesn't need to feel live the way a specific team/player's OWN stats do
  (those keep their short TTLs, unchanged), and `persist="disk"` means an
  app restart (Streamlit Community Cloud can do this on inactivity) reuses
  this week's pull instead of re-running a 360-team fan-out cold. The
  sidebar button clears all of them on demand for whenever fresher-than-
  a-week data is wanted. **Correction:** this originally used
  `@st.cache_data(ttl=604800, persist="disk")` directly - discovered
  mid-build that Streamlit SILENTLY IGNORES `ttl` whenever `persist="disk"`
  is also set (confirmed in Streamlit's own source,
  `local_disk_cache_storage.py`'s `check_context` - it logs a one-line
  warning, not an error, easy to miss), meaning these caches never
  actually expired on their own. Fixed by threading an ISO year-week
  string (`_week_bucket()`, e.g. `'2026-W04'`) through as a real hashed
  argument via a public-wrapper/private-`_..._cached`-inner-function split
  per function (e.g. `load_efficiency_ratings(season=None)` calls
  `_load_efficiency_ratings_cached(season, _week_bucket())`) - a new
  ISO week naturally produces a new cache key, forcing weekly rollover,
  while `persist="disk"` still gives the cross-restart survival within
  that week. `clear_league_wide_caches()` calls `.clear()` on the PRIVATE
  `_..._cached` functions now, not the public wrappers (which are plain
  Python functions post-refactor, with no `.clear()` of their own).
- **ESPN/SportsDataverse fallback for positional matchup defense**
  (`data.loaders.load_espn_season_player_box` / `load_positional_matchup_data`):
  a free, keyless alternative game-log source for the positional-defense
  feature specifically, published by the SportsDataverse project (same team
  as `cfbfastR`/hoopR) as one parquet file per season on GitHub Releases -
  every D-I team's whole season of player box scores in ONE download, vs.
  CBBD's ~1-call-per-opponent fan-out. `load_positional_matchup_data(team,
  season)` tries this first and falls back to the proven CBBD path
  (`load_team_opponent_game_logs`) whenever the ESPN file is missing,
  unreachable, or its coverage of `team` lags CBBD's own schedule by more
  than 10 days (`_is_espn_data_fresh_enough`) - most likely early in a
  brand-new season before SportsDataverse's own scrape/publish job has
  caught up. This fallback means the ESPN path can only ever help (save
  CBBD quota) or be a silent no-op; it cannot make the feature less
  reliable than the CBBD-only version already was. Bonus: the ESPN file
  carries its own `Position` field per player, so when it's used
  `_position_map_for_matchup` (ui/tabs/matchup_analyzer.py) skips the
  roster-lookup fallback entirely - fewer calls on top of the game-log
  savings. Implemented as a direct `requests.get()` + `pd.read_parquet()`
  against SportsDataverse's published URL, NOT the `sportsdataverse` PyPI
  package (pulls in scikit-learn/xgboost/scipy/pyreadr/beautifulsoup4 for
  no benefit here, and its own pyarrow pin conflicts with Streamlit's -
  see the pyarrow gotcha in §5). **Not live-verified** - this sandbox's
  network policy blocks GitHub release-asset downloads the same way it
  blocks CBBD/ESPN (confirmed: 403 from the egress proxy); the URL pattern
  and column names come from reading SportsDataverse's own R/Python source
  via `raw.githubusercontent.com` (which IS reachable here), not a live
  payload. Every failure mode (bad URL, 403, schema drift, empty file)
  degrades to an empty DataFrame, which `load_positional_matchup_data`
  treats as "unavailable" and falls back to CBBD - confirm against a real
  response once the season starts (see DATA_SOURCES.md's freshness note).

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
- **`st.dataframe`'s grid has no native row/cell hover highlight, and
  nothing (CSS, pandas Styler) can add one** - confirmed live: hovering a
  glide-data-grid cell produces zero visual change, before or after adding
  any CSS `:hover` rule targeting it. This is because the grid is drawn to
  a `<canvas>` element, not real DOM - a browser can't apply CSS pseudo-
  classes to pixels inside a canvas. This is DIFFERENT from (but related
  to) the Styler index-cell bug above: that one was fixable (style real
  columns, not the index); this one is a hard platform limitation. Every
  chart-based stat display in this app (SVG bars/dots/cells - see the
  `.hz-*` classes in ui/charts.py) gets real hover feedback instead, since
  those are real DOM elements.
- **A long-running `streamlit run` process does NOT re-import already-
  imported modules on a rerun** - only the top-level script re-executes;
  `ui.charts`, `ui.styling`, etc. stay exactly as they were the moment the
  process started, even many reruns later. Editing charts.py and testing
  again against an already-running dev server silently tested the OLD
  code and looked like the change had no effect (a new CSS class wasn't
  appearing in the rendered HTML at all) until the process was actually
  killed and restarted. This is a sharper version of the hot-reload
  gotcha already listed above - worth remembering that even a server
  started AFTER an edit can be the stale one if it was left running
  through a LATER edit.
- **`@st.cache_data(ttl=..., persist="disk")` silently ignores `ttl`
  entirely** - confirmed in Streamlit's own source
  (`streamlit/runtime/caching/storage/local_disk_cache_storage.py`'s
  `check_context` method): a disk-persisted cache with a finite `ttl` logs
  a one-line warning ("has a TTL that will be ignored...") and then never
  expires anything on its own. Every "cached ~weekly" claim in this app up
  to that point (all six full-league loaders in `data/loaders.py`) was
  built on `ttl=604800, persist="disk"` and was therefore wrong - those
  caches would have lived forever, not refreshed weekly, until the sidebar
  "refresh" button was clicked or the disk cache was manually cleared. The
  warning is easy to miss (it's a log line, not an exception, and the app
  still runs and still returns data - just stale data, silently). **Fix:
  don't rely on `ttl` at all when `persist="disk"` is set - instead make
  the desired refresh cadence part of the CACHE KEY** (a real, hashed
  function argument, not a default), so a new key naturally invalidates
  the old entry. This app's `_week_bucket()` helper (an ISO year-week
  string like `'2026-W04'`) is that key for the weekly-refresh case,
  threaded through a public-wrapper/private-`_..._cached`-function split
  per loader (see the Weekly league-wide caching entry in §3). Worth
  checking for this same silent-ignore pattern before trusting any
  `ttl=`+`persist="disk"` combination in NFL Scholar or CFB Scholar too -
  it wasn't specific to this app's use of it.
- **A `pyarrow` version floor above what Streamlit itself pins internally
  caused a real segfault, not just a pip warning** - `requirements.txt`
  had `pyarrow>=25.0`, but Streamlit 1.59.2 declares its own internal
  `pyarrow<25,>=7.0` requirement; `dmesg` showed a hard `segfault ... in
  libarrow.so.2500` from inside a `streamlit` dataframe render with a
  pyarrow version installed that violated that ceiling (the specific
  trigger here was an unrelated `pip install sportsdataverse` done for
  research, which pulled in a newer pyarrow and tipped an already-latent
  conflict into an actual crash). Fixed by pinning
  `pyarrow>=14.0,<25.0` in `requirements.txt`, matching Streamlit's own
  ceiling - re-ran the full smoke-test suite after the fix and confirmed
  it was the actual root cause (not any of this pass's own code). Keep
  this upper bound in sync with whatever Streamlit itself declares if
  Streamlit is ever upgraded past 1.59.
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
already in `load_positional_matchup_data`'s output) already supports it.
A THIRD data tier for positional matchup defense - live per-game ESPN
calls (`site.api.espn.com`'s scoreboard/summary endpoints, the same
public endpoints already used elsewhere in this app, rather than
SportsDataverse's batch-published season file) - was considered as a
middle ground between "free but possibly laggy at season start" (the
ESPN/SportsDataverse file) and "always current but quota-metered" (CBBD),
but deliberately NOT built this pass: it can't be tested live in this
sandbox either, and stacking a third fallback tier on top of two already-
unverified ones adds real complexity for a case (the bulk file being
stale) that might not even happen. Revisit only if the two-tier fallback
proves insufficient once the 2026-27 season actually starts and the bulk
file's freshness can be checked for real.

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
