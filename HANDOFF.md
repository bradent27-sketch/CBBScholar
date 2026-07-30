# CBB Scholar — Handoff Doc

Sibling app to NFL Scholar (`C:\FantasyF`) and CFB Scholar
(`C:\CCodeApps\CFBScholar`), same architecture and design system, built for
college basketball. This doc follows NFL Scholar's own HANDOFF.md section
structure on purpose, so all three stay easy to cross-reference.

**Game log width, a real pre-existing font bug found along the way, cut-off
chart labels, and a Matchup Analyzer stat picker (this doc's most recent
update):**

1. **Game log's horizontal scroll.** Root cause was actually two stacked
   issues, both in `ui.styling.render_sticky_footer_table`. First: the
   Opponent column's width was being computed from the FOOTER's own
   "SEASON AVG (28 games)" text, which is routinely longer than any real
   opponent name - excluded the footer value from `_col_width_px`'s
   measurement entirely (the footer cell still gets the column's real
   width; `text-overflow:ellipsis` handles it gracefully if it doesn't
   fit). Second, bigger find while re-measuring: this table's `<table
   style='...font-family:{F['mono']}...'>` has a real, pre-existing bug
   (present since before any pass in this doc touched the file) -
   `THEME['fonts']` values are themselves single-quoted strings (`"'Jet
   Brains Mono', monospace"`), and splicing that raw into a single-quoted
   HTML `style='...'` attribute prematurely closes the attribute at the
   font name's own opening quote, silently dropping every declaration
   after it. Confirmed live (Playwright `getComputedStyle`): this table
   had been rendering in Streamlit's default 16px Source Sans the whole
   time, not the intended 12px JetBrains Mono - which also meant the
   width math was calibrated against the wrong font's metrics without
   knowing it. Same bug found and fixed in `ui.components.render_header`/
   `render_bio_strip`/`render_metric_tiles` (all three had the identical
   pattern). Fixed everywhere via a sanitized (double-quoted)
   `_MONO_FONT_SAFE`/`_DISPLAY_FONT_SAFE`-style constant - the exact
   pattern `ui.charts` already used correctly for its own inline SVG
   styles, just never applied to these. With the real font confirmed,
   `_col_width_px`'s character-width constant was recalibrated from a
   guessed 7.4px/char to a measured-live 7.2px/char (JetBrains Mono at
   12px - exact, not approximate, since monospace fonts have one advance
   width per size). Cell padding also went from 10px/side to 7px/side
   (pure spacing, no column's displayed text changes) and any single
   column is now capped at 130px with ellipsis truncation for genuine
   outliers, so one long value can't blow up the whole table's width.
   Net effect verified live: 1183px -> 1009px total table width; zero
   horizontal scroll at 1440px+ browser width (the vast majority of real
   usage), still scrolls only on notably narrow (~1280px) windows.
2. **Matchup Analyzer's defensive-profile chart had labels clipped off
   the left edge** ("Rim Pressure Allowed" -> "Pressure Allowed", etc.) -
   `ui.charts.render_relative_bars` used a fixed 108px label column sized
   for this app's original short stat names (Pace, eFG% Allowed, ...);
   labels added in later passes (Rim Pressure/Perimeter Openness Allowed,
   Forward/Center/Guard Vulnerability) are longer, and since labels are
   drawn `text-anchor='end'` (growing leftward from that fixed width),
   anything wider than the column lands at a negative x - outside the SVG
   viewBox entirely. Same latent issue found on the RIGHT side too
   (VAL_W's fixed 60px was right at the edge of clipping newer value
   formats like "11th pctl"). Both are now sized to the actual longest
   label/value in each call's own rows (floors match the old fixed
   widths exactly, so every existing short-label call site - Player
   Search's stat bars, Matchup Analyzer's tendency profile - is
   byte-for-byte unchanged). Verified live: zero clipped text at a
   realistic half-column viewport width, confirmed via real text
   bounding-box measurements, not just a screenshot.
3. **Matchup Analyzer's elasticity curve now lets you pick the stat.**
   `data.transforms.efficiency_elasticity` (always derived True Shooting %,
   or effective FG% as a fallback) is renamed `stat_elasticity` and takes
   a `stat_col` param instead - the TS%/eFG% derivation is gone entirely,
   not just hidden behind a default, per explicit request ("get rid of
   the TS%... isn't as relevant"). `ui.tabs.matchup_analyzer` adds a
   "Stat" dropdown (Points/Rebounds/Assists, defaulting to Points) right
   above the chart; `ui.charts.render_efficiency_elasticity_curve` is
   renamed `render_stat_elasticity_curve` (pure rename - it was already
   completely stat-agnostic internally). Verified live end-to-end
   (Playwright): switching the dropdown between all three options
   correctly updates both the chart title and the plotted data.

**Verification**: full unit suite (39 tests, 6 new/updated for the
`stat_elasticity` rename) passing, a full repo-wide `py_compile` sweep,
and every fix above confirmed with a real headless-Chromium Playwright
render against synthetic data shaped like this app's real loader outputs
- not just AppTest/string inspection, per the standing discipline this
doc has converged on after two earlier passes in this same session shipped
fixes that turned out to be real but insufficient (see the entries
directly below this one).

---


**Bio fields: real root cause found via git archaeology, not more guessing
(this doc's most recent update)** - reported still broken after the
previous two passes (a NaN-truthy display fix, then an ESPN-core-API
fallback theory), with one critical new fact: this app used to show these
correctly. That's a real, checkable claim, not a vibe - `git log --follow
ui/tabs/player_search.py` shows exactly one commit where it stopped:
**952a1ea "Rebuild Player Search on a CBBD-free ESPN/SportsDataverse
pipeline"**. Before it, `player_search.py` read height/weight/hometown
straight off `data.loaders.load_team_roster` (CBBD's `/teams/roster` -
confirmed live per that function's own docstring, and Player Compare still
uses it successfully today) - `git show 38e5228:ui/tabs/player_search.py`
has the literal line, `sel_row.get('height')`/`'weight'`/`'city'`/`'state'`.
The rebuild switched to ESPN's own roster endpoint, which its OWN commit
message admits was never live-verified - a guess replaced a proven source,
and the guess was apparently wrong. **Fixed**: `_cbbd_bio_fallback` in
`ui/tabs/player_search.py` calls CBBD's `load_team_roster` (resolving the
ESPN-spelled team/player name against CBBD's own lists first, the same
cross-source join pattern this app uses everywhere else) whenever ESPN's
roster row for the selected player has none of height/weight/hometown -
tried BEFORE the previous pass's ESPN-core-API fallback, since it's proven
rather than reasoned. Season stats/game log are untouched (still fully
ESPN-based, so this tab stays CBBD-light, not CBBD-free only in this one
previously-broken fallback path) and the common case (ESPN roster already
has bio data) still never touches CBBD at all.

**Verified before shipping, not just claimed**: `python3 -m unittest
discover` (36/36 passing) plus a live `streamlit run` + real headless-
Chromium Playwright render of the EXACT regression scenario (a synthetic
ESPN roster row with no bio fields at all, paired with a synthetic-but-
realistically-shaped CBBD roster row matching `load_team_roster`'s actual,
pre-existing column contract - not a new guess) - confirmed the bio strip
renders the real height/weight/hometown through the actual `render()` code
path, confirmed the fallback is correctly SKIPPED when ESPN's own roster
data is already complete (no wasted CBBD calls in the common case), and
confirmed the previous pass's game-log-footer fix is still intact
alongside this change. One honest residual gap: this is still simulated
data, not this session's own live ESPN/CBBD traffic (still network-blocked
here) - what IS newly true this pass is that the fallback path is a
PROVEN, already-relied-upon function (`load_team_roster`), not a fresh
guess, which is a meaningfully stronger footing than the previous two
passes had.

---

**Follow-up: the previous pass's bio-field and game-log-footer fixes were
real but insufficient - both properly root-caused and fixed this time,
verified with a real headless-Chromium/Playwright render, not just
AppTest/string inspection (this doc's most recent update):**

1. **Game log footer, real root cause found**: live DOM measurement
   (Playwright, real Chromium) proved `position: sticky` was doing NOTHING
   at all for either the header or footer `<td>`/`<th>` cells - both moved
   in exact lockstep with scroll at every offset tested, a known browser
   limitation when `position: sticky` on table cells is combined with
   `border-collapse: collapse`. The previous pass's invisible spacer row
   was a fix for the wrong theory (a sticky-overlap that was never actually
   happening) and didn't address the real bug. **Fixed properly**:
   `render_sticky_footer_table` no longer uses `position: sticky` anywhere.
   `<thead>`/`<tbody>`/`<tfoot>` are forced to `display: block` (each
   `<tr>` re-asserts `display: table` for its own cells) and the scrolling
   itself moves onto `<tbody>` alone (`overflow-y: auto`) - `<thead>`/
   `<tfoot>` are then simply never part of the scrolling region at all, so
   there's no CSS trick that can fail; confirmed live that their bounding
   boxes are byte-identical before and after scrolling `<tbody>` to its
   max. Column alignment across the now-independent thead/tbody/tfoot
   needs an explicit, identical width per column (auto-layout can't
   produce consistent widths once each section is its own layout context)
   - new `_col_width_px` sizes each column from its header label and
     longest actual formatted value (the table's font is monospace, so
   character count is a reliable proxy for width), applied via a real
   per-instance `<style>` block keyed on the existing `data-label`
   attribute rather than inline styles, so it can't fight the mobile
   card layout's own `!important` rules. Verified live: zero pixel drift
   between header/body/footer column edges, at every scroll position.
   One regression caught and fixed in the same pass by actually rendering
   it (not just reading the diff): reusing one cell-building helper for
   both header and data cells initially ran the header's own LABEL text
   through the same numeric formatter data cells use, printing "--" for
   every numeric column's header instead of its name.
2. **Bio fields, a real second cause found**: the previous pass's
   NaN-truthy display bug was real and is still fixed, but on its own it
   only changed what a missing value renders AS (clean "--" instead of
   literal "nan") - it didn't address why the value was missing in the
   first place, which is why the report didn't change from a user's
   perspective. Investigated further: hoopR (SportsDataverse's own R
   package for men's college basketball - the same project family this
   app's season box file already comes from) fetches full athlete bio via
   a more detailed ESPN endpoint than the plain team-roster listing
   `load_espn_roster` calls, suggesting that simpler listing may return a
   slimmer athlete object in practice than this pipeline assumed. **Fixed**:
   new `data.loaders.load_espn_athlete_bio(athlete_id)` calls ESPN's core
   API per-athlete endpoint (`sports.core.api.espn.com/.../athletes/{id}`)
   for bio detail, used as a fallback ONLY for the one player being viewed
   and ONLY when the roster-level row has none of height/weight/hometown
   (`ui.tabs.player_search._bio_strip_values`) - never a bulk per-team
   fetch, and deliberately not the same failure mode as the previously-
   confirmed load_espn_roster-vs-box-file id mismatch (that was a cross-
   VENDOR mismatch; this fallback stays within ESPN's own id space, using
   the exact same `sourceId` load_espn_roster already returns). Verified
   live end-to-end with a real render() pass simulating a roster row with
   no bio fields at all, confirming the fallback fetch fires and the real
   value renders - plus the already-good-data path confirmed to skip the
   extra call entirely (stays as cheap as before when the roster data is
   already complete).

**Still not independently live-verified against real CBBD/ESPN traffic**
(this environment's network policy blocks both directly, same standing
caveat as every pass in this doc) - the ESPN-core-API-fallback theory
above is reasoned from a real, independent third-party implementation
(hoopR) rather than a cold guess, but it's still a theory, not a confirmed
fact about ESPN's actual current response shape. If height/weight/hometown
are STILL blank after this, the next step is almost certainly getting a
real captured payload from `load_espn_roster`'s actual live response (a
temporary debug log of the raw JSON on one real request would settle this
definitively) rather than reasoning about it further from this sandbox.

---

**Four reported bugs/requests fixed: bio fields, game-log sticky-footer
overlap, Pace coloring, poll sort order:**

1. **Height/Weight/Hometown were blank for every player in Player Search.**
   Root cause couldn't be 100% confirmed live (this environment's network
   policy blocks ESPN's API directly, same standing limitation as every
   other pass in this doc), but a real, demonstrable bug was found and
   fixed either way: `_display_height`'s `disp or _fmt_height(...)` pattern
   (and the inline weight/hometown checks next to it in `player_search.py`)
   breaks when a missing bio field comes back as `float('nan')` rather than
   `None` - which happens routinely once a value passes through a pandas
   DataFrame column, since `bool(float('nan'))` is `True` in Python. `or`
   then keeps the NaN instead of falling through, rendering the literal
   text "nan" (confirmed with a synthetic mixed-roster DataFrame - see
   commit). New `_display_height`/`_display_weight`/`_display_hometown`
   helpers in `player_search.py` (the last two new, reused by
   `compare.py`'s Weight cell too) type-check before formatting instead of
   relying on truthiness. Independently, `data.loaders.load_espn_roster`
   also gained two defensive fallbacks in case ESPN's real NCAAB roster
   shape diverges from the primary keys this pipeline guesses at: weight
   falls back to parsing a leading number out of `displayWeight` when the
   bare `weight` field is absent, and birthplace tries a top-level
   `hometown` dict alongside `birthPlace`. **Before fully trusting this**:
   spot-check a real player once live API access is available - same
   standing caveat as every ESPN-touchpoint in this app.
2. **Game log's season-average footer row visibly overlapped the last
   game row.** Root cause: `render_sticky_footer_table`'s footer is
   `position: sticky; bottom: 0` and is the LAST row in the same scrolling
   flow as the body rows above it - which means it pins itself to the
   bottom of `.sft-wrap`'s viewport as soon as there's any scroll at all
   (not just once you reach the true end), painting over whatever body
   row currently occupies that same bottom strip. Fixed with the standard
   technique for this sticky-footer-in-a-scroll-container overlap class of
   bug: an invisible spacer row (`visibility:hidden`, same padding/content
   box as the real footer) inserted directly before it, reserving real
   scroll height equal to the footer's own rendered height so the last
   real row can fully clear it. Applied on both the desktop table and the
   mobile card layout (new `.sft-spacer-row` CSS mirrors `.sft-footer-row`
   in both `@media` contexts). Verified via a direct AppTest render of
   Player Search's real game log confirming the spacer row is present,
   precedes the footer row, and the footer's content still reads correctly.
3. **Pace in Team Efficiency's Rankings table was a bare number with no
   color.** Added a D-I percentile-driven background tint (`data.transforms
   .pct_rank`, `higher_is_better=True`) via the existing `numeric_pct_cols`
   mechanism `render_responsive_table` already offers every other
   percentile column - same "just tracks where the raw value falls, not a
   good/bad claim" convention Four Factors Tiering and Matchup Analyzer's
   defensive profile already use for this exact column (`Pace`'s own
   comments elsewhere already establish this isn't a new interpretation).
   Four Factors Tiering's heatmap already had Pace percentile-colored;
   this brings the Rankings table in line with it.
4. **NET & Resume's Polls table needed to open sorted by Points**, so
   teams just outside the Top 25 (unranked but still receiving votes) show
   up in real order right after #25 instead of the arbitrary API order
   `load_latest_poll`'s old `ranking or 999` sort left them in (ties all
   sorted 999, so their relative order was whatever the API happened to
   return). Changed the sort key to `points` descending directly - the
   real metric a poll ranks teams by in the first place, so the Top 25
   stays in (very nearly) the same order while the "just missed it" tail
   now reads correctly.

Verified: all 36 existing unit tests still pass unmodified, a full
`python3 -m py_compile` across every changed file, and live AppTest runs
of `player_search.render()`, `team_efficiency.render()`, and
`net_resume.render()` against synthetic ESPN/CBBD-shaped data (not just
"doesn't crash" - inspected the actual rendered HTML/markdown for the real
bio values with no "nan" leakage, the spacer row's position relative to
the footer, and `load_latest_poll`'s output order with a deliberately
scrambled synthetic payload). Same standing caveat as every pass in this
doc: not run against live CBBD/ESPN data (this environment's network
policy blocks both directly) - worth a real spot-check once that's
available, especially item #1 above.

---

**Positional Vulnerability Ranking relocated again, Efficiency Elasticity
gets a real chart, plus a thorough app-wide review pass (this doc's most
recent update):**

Two follow-up placement/presentation refinements to the previous pass
below, requested after using it, plus a full review pass across the app
looking for bugs/dead code:

1. **Positional Vulnerability Ranking moved from Positional Matchup
   Defense to the BOTTOM of the Defensive Profile chart** (one row-pair
   earlier - Row 1 instead of Row 2), with a genuinely new requirement:
   show grey/placeholder rows there BEFORE "Load positional matchup
   defense" (Row 2) has been clicked, real ranked values after - not
   gated behind its own separate load step. New `_positional_vulnerability_rows(team, season)`
   in `ui/tabs/matchup_analyzer.py` reads `_render_positional_defense`'s
   OWN "games to include" slider (`key='ma_pos_defense_window'`) and
   load-trigger (`ma_pos_defense_loaded_{season}_{team}_{games}`) session_state
   keys directly - safe even though those widgets are declared LATER in
   `render()`'s script order (Row 1 runs before Row 2), because Streamlit
   syncs every keyed widget's current value into `st.session_state`
   BEFORE the script body executes at all on any given rerun. Returns
   three `{'label': '<Bucket> Vulnerability', 'pct': None, 'value_str':
   'Not loaded', ...}` placeholder rows pre-load (`ui.charts.
   render_relative_bars` already draws an empty, colorless track for a
   `None` pct - exactly the requested "grey/transparent" look, no new
   styling needed) and the real `positional_vulnerability_ranking` rows
   (relabeled the same way) post-load, appended onto `_render_defensive_profile`'s
   existing `profile_rows` list (same merged single chart as the
   previous pass's Rim Pressure/Perimeter Openness Allowed rows).

   One real timing bug fixed along the way: on the rerun where "Load
   positional matchup defense" is actually clicked, the button's own
   handler (in Row 2) sets the trigger flag, but Row 1 - which renders
   EARLIER in that same script pass - would still see the OLD (pre-click)
   session_state value and keep showing grey placeholders for one extra,
   unrelated interaction before "catching up." Fixed by calling
   `st.rerun()` immediately after setting the trigger flag, forcing an
   immediate second pass where Row 1 now sees the fresh state - standard
   Streamlit idiom for this exact "a later widget's click needs to affect
   an earlier-rendered section on the SAME click" ordering problem.
   Verified live via AppTest: clicking the button in one step now shows
   real ranked values in the SAME response, not the next one.

2. **Efficiency Elasticity Curve gets a real chart** - the previous pass's
   single caption line is gone. New `ui.charts.render_efficiency_elasticity_curve`
   plots `efficiency_elasticity`'s `bucket_means` (Weaker/Average/Top-Tier
   defense tiers) at each tier's CENTER percentile on a real 0-100
   "opponent defensive strength" axis (16.7/50/83.3 - NOT evenly-spaced
   categorical slots), connected by straight segments (same "real data,
   not a fabricated smooth fit" honesty as `render_game_script_curve`),
   with tonight's specific opponent highlighted as a distinct marker at
   its own exact percentile (`opponent_def_pctl`) showing the projected
   efficiency (`projected_eff`) - and a dashed season-average reference
   line. Kept in the EXACT same position as before (`_render_player_trend`,
   after the last per-stat game-log trend chart, before the Game-Script
   curve) - only the presentation changed, not the placement or the
   underlying `efficiency_elasticity` math (unchanged).

**Thorough review pass** (requested explicitly - "determine any glitches,
imperfections, bugs, straggling unused code"):
- Grepped the whole repo for stale references to every name removed/
  renamed across both Predictive-Analytics-era passes (`predictive_analytics`,
  `scheme_fingerprint`, `rim_foul_leverage_score`, `composite_matchup_advantage`,
  `matchup_projection_band`, `build_matchup_advantage_report`,
  `render_probability_band`, `usage_weighted_efficiency`,
  `_render_efficiency_elasticity_note`, `TAB_PREDICTIVE`) - clean, only
  historical mentions remain in `tests/test_matchup_analytics.py`'s own
  docstring explaining what it supersedes.
- Static unused-import check across `ui/tabs/matchup_analyzer.py` (all 38
  imported names actually referenced) and a used-anywhere check for every
  top-level function in `data/transforms.py` (all used) and `ui/charts.py`.
- **Found, but deliberately NOT removed**: `render_mirror_bars` and
  `render_game_log_bars` in `ui/charts.py` are unused anywhere in this
  app's own code - but they predate everything in this doc (present since
  the initial commit, unrelated to any Predictive-Analytics-era work) and
  `ui/charts.py`'s own module docstring explicitly documents the file as
  "byte-identical between CFB Scholar and CBB Scholar... keep it that
  way" - deleting them here would break that deliberate cross-app parity
  without being able to confirm CFB Scholar doesn't still use them (no
  access to that sibling repo from here). Flagged here as a real, honest
  finding rather than either silently deleting or silently ignoring it -
  worth a conscious call from whoever CAN check the sibling app.
- Full `python3 -m py_compile` across every `.py` file in the repo, and a
  static import-cycle sanity check (`python3 -c "import app"`) - clean.
- Full unit test suite (36 tests) passing.
- Live AppTest run covering BOTH states of the ranking transition (grey
  placeholders before load, real values after, confirming no duplicate
  ranking section reappears under Positional Matchup Defense) AND the
  Efficiency Elasticity chart's exact position (after the last game-log
  trend label, before the Game-Script header) via substring-index
  ordering checks on the rendered markdown - not just "renders without
  exploding."
- **Also verified with a REAL running server this time**, not just
  AppTest's bare-mode simulation: `streamlit run app.py` + a real headless
  Chromium (Playwright) screenshot of both Player Search and Matchup
  Analyzer, checking the browser console for JS errors. Confirmed clean
  chrome/theme/tab rendering and zero unexpected console errors (the only
  console noise is Streamlit's own external usage-metrics beacon failing
  to reach its telemetry endpoint - expected in this sandboxed environment,
  unrelated to this app's code, present on every Streamlit app boot
  regardless of what tab code exists). Both tabs correctly show their
  "NEEDS SETUP" card (no CBBD API key configured in this sandbox) rather
  than crashing - real content still could not be visually verified this
  way (no live API access here), which is exactly why the AppTest-with-
  synthetic-data runs above remain the actual verification for the new
  features' real behavior.

**Verification caveat, same standing discipline as every pass in this
doc**: still not run against live CBBD/ESPN data - this sandbox can't
reach those APIs (see DATA_SOURCES.md). **Before trusting the actual
numbers**: run `streamlit run app.py` for real once live API access is
available and sanity-check the new Defensive Profile ranking rows and the
Efficiency Elasticity chart against a team/player/opponent you know.

---

**Predictive Analytics tab retired, redistributed into Matchup Analyzer:**

The standalone Predictive Analytics tab described in the entry directly
below this one was walked through in real usage and reworked based on that
feedback, point by point:

1. **Positional Leverage kept, but reworked to not require picking a
   player/position first.** The old `positional_leverage` needed a pre-
   selected player bucket (from `scheme_fingerprint`'s blended per-bucket
   score) before it could rank anything. Real positions are often fluid (a
   listed guard who also plays some forward, etc.), so forcing that choice
   up front was the wrong shape. New `data.transforms.
   positional_vulnerability_ranking(positional_summary_df)` instead ranks
   ALL of a team's Guard/Forward/Center buckets at once, purely from each
   bucket's own 'Points Delta' (`score = clip(50 + delta*4, 0, 100)`,
   unchanged formula, just no longer blended with team-wide rim/perimeter
   stats - see #2), letting the viewer apply their own judgment about
   which bucket actually matches whoever they're scouting. **Moved** into
   Matchup Analyzer's TEAM DEFENSE panel, `_render_positional_defense`,
   rendered via `render_relative_bars` right above the "Position group"
   trend-chart picker (i.e. between the existing positional-defense
   summary table and the per-bucket trend charts) - not gated behind any
   pre-selected player, loads for the whole opponent team at once.

2. **Rim Pressure / Perimeter Openness Allowed un-bundled from positional
   scoring - these aren't actually position-specific in this app's data.**
   The old `scheme_fingerprint` blended these two team-wide percentiles
   (Def 2P%/Def FT Rate/Opp Paint Pts% for rim pressure; Def 3PA Rate/Def
   3P% for perimeter openness) into EVERY position bucket's score
   identically, which added noise without adding real positional signal.
   New `data.transforms.defensive_tendency_rows(team_stats_df, team)`
   computes the exact same two percentiles but returns them as two
   standalone rows (unchanged formulas), listed ONCE per team. **Moved**
   into Matchup Analyzer's TEAM DEFENSE panel, `_render_defensive_profile`
   - appended directly onto `team_defense_profile_rows`' existing bar list
   (`profile_rows = team_defense_profile_rows(...) + defensive_tendency_rows(...)`),
   so they read as part of the team's overall defensive shape alongside
   Pace/eFG%/TO Ratio/etc., not a separate section.

3. **Efficiency Elasticity Curve kept - genuinely useful, presentation was
   the problem.** `data.transforms.efficiency_elasticity` is UNCHANGED
   (same regression, same TS%/eFG% fallback logic, same docstring) - only
   how it's surfaced changed. The old tab gave it a whole expander with
   slopes, both bucket means, and a projected-adjustment line. **Moved**
   into Matchup Analyzer's PLAYER side, `_render_player_trend` (new
   `_render_efficiency_elasticity_note` helper), condensed to ONE caption
   line under the existing per-stat trend charts - season average, a
   quick weaker-D-vs-top-tier-D comparison, and the projected number
   against whichever opponent is selected in TEAM DEFENSE, all in one
   sentence, no header/expander/chart. Needs `defense_team` (the TEAM
   DEFENSE side's selected team, now used as "tonight's opponent" for the
   projection) threaded into `_render_player_trend`, which didn't
   previously need it - `render()`'s call site updated accordingly. Reuses
   `mine` (the per-game log `_render_player_trend` already loads/filters
   for its own trend charts) rather than fetching a second copy.

4. **Rim-Pressure & Foul-Leverage Exploitation Score scrapped entirely -
   redundant.** It blended a player's own FT Rate/2PT Rate with the
   opponent's Def FT Rate allowed into one composite score, but FT Rate
   and FT Rate Allowed are both ALREADY shown directly elsewhere (the
   player's tendency profile bars; the team's defensive profile bars) -
   the composite added a number without adding information. `data.
   transforms.rim_foul_leverage_score` deleted outright, not left as dead
   code.

5. **Game-Script Sensitivity kept, redefined as three tiers with a real
   curve instead of a two-bucket text summary.** Old version: two buckets
   (Close: |margin|<=8, Decided: everything else) and a single "Sensitivity
   Index" number. New `data.transforms.game_script_sensitivity` (reworked,
   same Date-only join to the team's own schedule margins as before) now
   buckets into three tiers - Close (|margin|<=8), Comfortable (8 to 14),
   Blowout (>14) - and returns each tier's mean + game count in order
   rather than one collapsed index number. No per-tier minimum-games gate
   (every tier with >=1 game is included, with its real count, so a small
   sample reads honestly instead of being hidden - same "show the real
   count" convention as `last_n_form_deltas`) - only the TOTAL game count
   is gated. New chart, `ui.charts.render_game_script_curve` (replaces the
   old `render_probability_band`, deleted) - straight line segments
   connecting the up-to-3 tier means with a light area fill and a dashed
   season-average reference, deliberately NOT smoothed/splined (only 3
   discrete tiers exist; implying more statistical smoothness would
   misrepresent the data). **Moved** into Matchup Analyzer's PLAYER side,
   `_render_player_trend` (new `_render_game_script_curve` helper),
   hardcoded to Points (no new stat selector - keeps the panel simple)
   right after the elasticity caption.

6. **Scheme Fingerprint heatmap scrapped entirely - "too bulky, don't get
   much out of it."** The whole `scheme_fingerprint` function (the
   composite that blended rim/perimeter percentiles with per-bucket
   points-delta into one "vulnerability" score) and its Scheme-Alignment
   Heatmap visualization are gone. Its two genuinely useful parts survive
   in simpler, un-blended form: the rim/perimeter percentiles as
   `defensive_tendency_rows` (#2 above) and the per-bucket delta ranking
   as `positional_vulnerability_ranking` (#1 above) - not blended together
   anymore, since blending them was exactly what made the old version feel
   bulky without adding clarity.

**Also removed, since nothing survived to justify keeping it**: the
Composite Matchup Advantage Score (`composite_matchup_advantage`) and its
Matchup Advantage Radar visualization. The composite's formula fundamentally
needed one pre-picked player position (item #1's exact complaint) and one
of its four inputs (rim/foul leverage) was being scrapped outright (item
#4) - there was nothing coherent left to compose into a single score. The
entire standalone tab (`ui/tabs/predictive_analytics.py`, its `app.py`/
`config.py` wiring, `tests/test_predictive_analytics.py`) was deleted
rather than kept around half-empty; every function that's still used lives
directly in Matchup Analyzer now. Confirmed via `git status`/grep before
deleting that nothing else in the app referenced any of the removed names.

**New test file**: `tests/test_matchup_analytics.py` replaces
`tests/test_predictive_analytics.py` (deleted), covering
`positional_vulnerability_ranking`, `defensive_tendency_rows`, the
unchanged `efficiency_elasticity` (same test cases as before, just moved),
and the reworked 3-tier `game_script_sensitivity` - 15 tests, all with
hand-checked synthetic values (e.g. a synthetic 6-game season with margins
spanning all three tiers, confirming the exact Close/Comfortable/Blowout
means and season average). Full suite (36 tests across the repo) passing.
Also verified with a live `streamlit.testing.v1.AppTest` run of the
reworked Matchup Analyzer tab end-to-end (pick player, pick opponent team,
click "Load positional matchup defense") confirming all four relocated/
redesigned pieces actually render (ranking, rim/perimeter rows, elasticity
caption, game-script curve) AND that the retired concepts (Scheme
Fingerprint, Rim/Foul Leverage) are genuinely absent from the rendered
output, not just removed from the source - plus a full `app.py` boot
confirming exactly 7 tabs again with Predictive Analytics gone. `python3
-m py_compile` across every `.py` file in the repo also passing.

**Verification caveat, same standing discipline as every pass in this
doc**: not run against live CBBD/ESPN data (this sandbox still can't reach
those APIs - see DATA_SOURCES.md). Verified via synthetic-but-realistically-
shaped data (built via the real `espn_player_season_stats_for_teams`
transform, not hand-typed dicts) through unit tests and the AppTest run
above. **Before trusting the actual numbers**: run `streamlit run app.py`
for real once live API access is available and sanity-check the new
Matchup Analyzer sections against a team/player/opponent you know.

---

**New tab: Predictive Analytics — six composite matchup-advantage metrics
plus three visualizations (retired in the pass above - kept here as
historical record only, per this doc's "correct forward, don't rewrite
history" convention):**

Built per explicit request, following an earlier brainstorm-only pass in
this same session that proposed six advanced predictive-metric concepts
and three visualization concepts, then got approval to fully implement all
of them (not narrowed down to a subset). New 8th top-level tab,
`ui/tabs/predictive_analytics.py`, sitting after Matchup Analyzer in tab
order (`config.TAB_LABELS`/`app.py`'s `_tab_modules`, kept in lockstep as
always).

**Zero new external data sources** — every metric is pure local compute in
a new `data/transforms.py` section ("Predictive Analytics: Matchup
Advantage engine") over data this app already fetches: `get_player_season_profile`
(same ESPN-first/CBBD-fallback pipeline Matchup Analyzer's PLAYER panel and
Player Compare already use), `load_positional_matchup_data` (same source as
Matchup Analyzer's TEAM DEFENSE positional breakdown), `load_all_team_season_stats`,
and `load_efficiency_ratings` (both already power Team Efficiency/Matchup
Analyzer). The tab reuses Matchup Analyzer's exact player-picker logic
(roster UNIONED with the ESPN box file, same bug-fixed pattern) and its
opponent's positional-matchup-defense loading (same "Run" button + games-
per-team slider + free-ESPN/CBBD-fallback source caption) — duplicated
locally into the new tab file rather than cross-imported, matching this
app's established convention of small per-tab duplication over cross-tab
coupling (see `_mobile_cell_bg`'s docstring elsewhere in this file for the
same reasoning applied before).

**The six metrics** (full formulas in each function's own docstring in
`data/transforms.py` — not restated here to avoid drift between the two):
1. **Scheme Fingerprint** (`scheme_fingerprint`) — infers a defense's paint-
   sag/perimeter-openness tendency from D-I percentiles of its allowed
   shooting-profile rates (Def 2P%, Def FT Rate, Opp Paint Pts %, Def 3PA
   Rate, Def 3P%), blended per position bucket with that bucket's own
   scoring delta against this specific team (reusing `positional_defense_summary`,
   already built for Matchup Analyzer).
2. **Efficiency Elasticity Curve** (`efficiency_elasticity`) — a real
   `numpy.polyfit` least-squares line fit over the player's own game log:
   efficiency (TS%, or eFG% when the game log has no free-throw split —
   true for CBBD's `/games/players`, only the ESPN-native box file carries
   FTA/FTM) vs. opponent defensive-rating and pace percentile, then
   projects an adjustment for tonight's specific opponent.
3. **Composite Matchup Advantage Score** (`composite_matchup_advantage`) —
   0-100 blend (35/30/20/15) of usage-weighted efficiency, positional
   vulnerability, rim/foul leverage, and opponent pace, with graceful
   weight-renormalization over missing components and a plain-language tier
   label.
4. **Rim-Pressure & Foul-Leverage Exploitation Score** (`rim_foul_leverage_score`).
5. **Game-Script Sensitivity Index** (`game_script_sensitivity`) — close-
   game vs. decided-game production split, joined to the team's own
   schedule margins by DATE ALONE (deliberately not opponent name — a team
   plays at most one game per date, sidestepping any ESPN-vs-CBBD team-
   name-spelling mismatch entirely).
6. **Positional Leverage / Mismatch Hunting Score** (`positional_leverage`)
   — ranks the opponent's three position-bucket vulnerability scores and
   reports where the selected player's own bucket falls.

Every one of these is an explicitly-labeled PROXY, not a literal defensive-
coverage read — this app has no play-by-play, shot-location, or lineup/
on-off tracking data (see DATA_SOURCES.md), so nothing claims to detect an
actual "drop coverage on a ball screen" the way possession-level tracking
data would. This limitation is stated up front in the tab's own header
caption and again in an in-app "Methodology" expander at the bottom of the
report, not buried only in this doc. Composite/projection weights (35/30/
20/15, the ±20%/±8% projection-band effect sizes) are a documented,
transparent design choice — NOT fit or tuned against any historical
matchup-outcome dataset, because no such labeled dataset exists in this
app's data sources. Flagged honestly rather than presented as calibrated.

**Three visualizations**, all reusing/extending existing chart primitives
rather than adding a new charting dependency (same hand-rolled inline-SVG
discipline as every other chart in this app):
- **Matchup Advantage Radar** — reuses `ui.charts.render_radar` UNCHANGED,
  overlaying the four composite components against a flat 50th-percentile
  "league-average matchup" baseline. Missing components are substituted
  with 50 (neutral), not the render_radar default of 0 — 0 would visually
  read as "worst possible," which is wrong for "no data," so this tab
  fills that gap explicitly before calling the shared primitive rather
  than changing that primitive's own missing-value convention (other
  callers, e.g. Player Compare, still get 0-as-missing unchanged).
- **Scheme-Alignment Heatmap** — reuses `ui.charts.render_percentile_heatmap`
  UNCHANGED, rows = Guard/Forward/Center (the player's own bucket prefixed
  with "→"), columns = the Scheme Fingerprint's decomposed scores. Passes
  the same DataFrame as both the `pct_df` and `raw_df` arguments — these
  scores are already 0-100 by construction, so they double as both the
  color-driving percentile AND the printed raw value with no separate
  distribution needed.
- **Dynamic Probability Curve** (`ui.charts.render_probability_band`, NEW
  chart primitive, same file/style as every other hand-rolled SVG chart
  here) — a floor/median/ceiling band drawn over the player's own real
  per-game dot strip this season, not a smooth bell-curve/violin shape
  (deliberately — a fitted continuous distribution would imply a precision
  this heuristic doesn't have; a band over real dots reads honestly as "the
  real spread, adjusted for this matchup").

**Testing**: `tests/test_predictive_analytics.py` (new, 13 test classes/33
assertions) unit-tests all six metric functions plus the orchestrating
`build_matchup_advantage_report` with hand-checked synthetic values (not
just "doesn't crash" — e.g. confirms the exact renormalized score when a
component is missing, confirms `efficiency_elasticity`'s regression slope
comes back negative when constructed data shows worse shooting against
tougher defenses). Also verified with a live `streamlit.testing.v1.AppTest`
run (this sandbox has real `pandas`/`numpy`/`streamlit` installed for
testing purposes, unlike some earlier passes in this doc — see this
section's own verification note below) driving the actual widget tree
end-to-end: season → player team/player pickers → opponent picker → "Run
matchup analytics" button → full report render (radar, heatmap, probability
curve, all four detail expanders, methodology expander) → switching the
stat selector to Rebounds and re-rendering, all with zero exceptions. Also
ran the full existing `tests/` suite (48 tests total, all passing) and
`python3 -m py_compile` across every `.py` file in the repo.

**Verification caveat, same standing discipline as every other pass in this
doc**: this was NOT run against live CBBD/ESPN data (this sandbox still
cannot reach those APIs directly — see DATA_SOURCES.md's standing network
caveat) — the AppTest run above used monkeypatched loader functions
returning synthetic-but-realistically-shaped data (built via the REAL
`espn_player_season_stats_for_teams` transform, not hand-typed CBBD-shape
dicts, to avoid drifting from the real shape). **Before trusting the actual
numbers this tab produces**: run `streamlit run app.py` for real once live
API access is available, pick a team/player/opponent you know, and sanity-
check the Composite Score and its component breakdown against what you'd
expect — same discipline as every other pass in this file.

---

**Player Compare dumbbell chart, light mode, and a Net Rating cleanup:**

1. **Player Compare's head-to-head delta.** The old plain diverging-color
   table is gone. `ui.charts.render_dumbbell_chart` (new) draws one
   number-line per shared stat, each player's TRUE value marked by a dot
   in their own team color and joined by a connecting line whose length
   reads as the size of the gap - user picked this over two other
   brainstormed options (mirrored bidirectional bars, a broadcast-style
   stat-card grid). Also dropped the `Net Rating` row from both the stat
   tiles and this section - that stat was removed from the app earlier
   and had been left behind here.
2. **Light mode.** New sidebar toggle (Setup Status → Appearance,
   `st.radio(key='theme_mode')`, default `'dark'` so nothing changes
   unless a visitor opts in). Dark mode is untouched by construction, not
   just by care: `config.apply_theme_mode(mode)` mutates `THEME['colors']`
   IN PLACE rather than swapping in a new dict, and the dark branch of
   every mode-dependent value in this pass is the literal pre-existing
   constant, byte-for-byte - "switch to dark" can only ever restore
   exactly what was already there.
   - `config.THEME_LIGHT_COLORS`: a full light palette, same keys as
     `THEME['colors']`, contrast-checked with a real WCAG ratio script
     before committing (not eyeballed) - see the comment above that dict
     for the actual numbers.
   - Mutating `THEME['colors']` in place (instead of reassigning it) matters
     because `ui.styling`/`ui.charts`/`ui.components` each independently do
     `C = THEME['colors']` at import time, and Python only runs a module's
     top-level code once per process - reassignment would leave two of the
     three modules holding a stale reference. `apply_theme_mode` is called
     at the top of `inject_theme()` on every rerun, before any of those `C`
     reads happen. One honest caveat, not glossed over: this is a single
     shared dict across the whole process, fine for this app's actual
     single-user use (same assumption this file's own season-window
     comment already makes) but not safe for concurrent multi-session
     deployments.
   - A handful of CSS rules were hand-tuned literal `rgba(...)` triplets
     rather than `{C['x']}` lookups (glow/tint effects) and don't follow
     `C`'s mutation automatically - each got an explicit light-mode branch
     in `inject_theme()` (header chrome, tab-hover tint, alert/card/
     expander tints, input backgrounds), with the dark branch copied
     verbatim from what was already there.
   - One `@st.cache_data`-decorated chart builder
     (`_build_efficiency_scatter_svg`) reads theme colors internally but
     was keyed only on its data args - switching modes wouldn't have
     busted its cache, so it would've kept showing the OTHER mode's colors
     until the underlying data changed. Fixed by threading
     `st.session_state['theme_mode']` through as an explicit (otherwise
     unused) cache-key argument.
   - Three real bugs found only by live inspection (Chrome DevTools
     Protocol matched-styles, not code-reading): the sidebar `<section>`
     itself carries an explicit native text color that sits BELOW (closer
     to the leaf than) `.stApp`'s color rule in the inheritance chain, so
     setting color only on `.stApp` left every plain sidebar text white
     regardless of mode; a radio option's inner wrapper and the sidebar's
     collapse-icon button each independently re-assert Streamlit's native
     color the same way; and `st.text_input`/`st.checkbox`'s underlying
     wrapper elements carry Streamlit's own hardcoded
     `secondaryBackgroundColor` fill (`.streamlit/config.toml`) with no
     stable testid on the checkbox's own indicator box, requiring a
     `:has()` selector anchored off the widget label that always follows
     it instead of an emotion-hash class.
   - One thing deliberately NOT fixed, because it can't be: `st.dataframe`'s
     own grid chrome (header row, borders) is drawn to a `<canvas>` by
     Streamlit's own JS using colors resolved once from
     `.streamlit/config.toml` at process start - confirmed live (no `:root`
     CSS custom properties exist to override, and the canvas is opaque to
     CSS entirely, same limitation already documented elsewhere in this
     file). The header row stays visually dark in light mode; the actual
     data cells (this app's own Styler-applied colors) correctly follow
     the toggle. Not visible at all on mobile, where the responsive-table
     pattern hides the desktop grid in favor of the (fully theme-aware)
     card view.

---

**Pace stat, conference colors, and L10/L5/L3 form badges:**

1. **Pace in Team Efficiency.** `data.transforms.four_factors_percentile_grid`
   now prepends a `Pace` column (higher-is-better) whenever the caller's
   `stats_df` has one, so the Four Factors table picks it up automatically
   with no call-site change. The Rankings subtab didn't have Pace in its
   frame at all, so `_render_rankings_subtab` now merges it in from
   `load_all_team_season_stats(season)` (same source Matchup Analyzer
   already used) and orders it right after Rank/Team/Conference.
2. **Conference colors.** ESPN and CBBD were checked directly (curl/WebFetch)
   for conference branding data and both are unreachable from this
   environment - consistent with this doc's standing network limitation, so
   this is NOT pulled live. `config.CONFERENCE_COLORS` is a hand-curated,
   one-time dict (32 entries) instead, explicitly NOT verified against any
   live source - flagged as such in a comment at its definition. Per
   explicit instruction, every value is deliberately unique (checked with a
   `len(set(...))` script before committing) even where real branding
   clusters multiple conferences around the same navy/blue/red families, so
   no two conferences are ever visually indistinguishable in this app. Reused
   the existing `TEAM_NAME_ALIASES` / `resolve_team_name` machinery for the
   lookup: `data.utils.expand_team_name_aliases` and `resolve_team_name` both
   grew an optional `aliases=` param (default preserves old behavior exactly)
   so a new `CONFERENCE_NAME_ALIASES` list (ACC/"Atlantic Coast Conference",
   Big Ten/B1G, etc.) can drive conference-name matching the same way team
   names already do. `ui.styling._conference_color` looks up exact name
   first, then falls back through the alias-normalized map. Wired into the
   existing `Conference` column path in both `style_plain_dataframe` (desktop
   Styler) and `_mobile_cell_bg` (mobile cards) alongside the pre-existing
   `Team` coloring branch.
3. **L10/L5/L3 form badges on Matchup Analyzer trend charts.** New
   `data.transforms.last_n_form_deltas(values, baseline, ns=(10,5,3))`
   computes the last-N-game average and whether it's >= the season/period
   baseline for each N. `ui.charts.render_trend_line` grew an optional
   `corner_stats` param that draws small colored badges (green = at/above
   baseline, red = below) in the chart's top-right corner, each with a
   `<title>` tooltip spelling out the comparison - reusing existing SVG
   text/rect drawing in that module, no new rendering path. Wired into both
   `_render_player_trend` (player stat graphs, baseline = season average)
   and `_render_positional_defense` (team-defense-allowed graphs, baseline =
   the same window's average, since there's no single "season average" for
   an opponent-position bucket). Verified via AppTest with synthetic data on
   both call sites, inspecting actual rendered SVG markup for correct color
   and tooltip text, not just absence of exceptions.

---

**Mobile responsiveness overhaul:** every
wide data table now gets a real mobile card layout below 768px, with the
desktop `st.dataframe`/table code paths left completely untouched (verified
live, not just by reading the code - see below). Two different mechanisms
depending on what a table actually IS in the DOM:

1. **`render_sticky_footer_table`** (Player Search's game log - the one
   hand-rolled real-DOM table in this app) gets a pure CSS
   `@media (max-width: 767px)` transform in `ui.styling.inject_theme()`:
   header hidden, each row becomes a bordered card, each cell shows its own
   label via a new `data-label` attribute + CSS `content: attr(data-label)`.
   A new `mobile_headline_cols` param lets the caller promote specific
   fields (Date/Opponent/Result/Points) to the top of each card via CSS
   `order` - DOM order is unchanged, only visual order. The wrapping
   scroll container's `max-height` (tuned in px for compact table rows)
   is overridden to a viewport-relative `65vh` on mobile via a new
   `.sft-wrap` class - reusing the row-height px value clipped card
   content mid-render, a real bug caught via live Playwright screenshot
   before this fix, not just code review.
2. **`st.dataframe` tables** (the other 9 - Team Efficiency, NET rankings,
   Polls, Positional Matchup Defense, Compare's delta table, Live Odds'
   two tables, Transfer Portal's two tables, Conference Standings) are
   canvas-rendered (glide-data-grid) - already confirmed elsewhere in this
   doc that CSS cannot reach into that canvas at all. A media query
   INSIDE the dataframe was never going to work. New
   `ui.styling.render_responsive_table` instead renders BOTH the existing,
   byte-identical desktop `st.dataframe(style_plain_dataframe(df, ...), ...)`
   call AND a new hand-rolled mobile card list for the same data, each
   wrapped in `st.container(key=...)` - Streamlit gives that a real,
   addressable `st-key-<key>` CSS class (confirmed against this app's
   pinned Streamlit 1.60 via direct frontend-bundle inspection, not
   assumed from docs) - and a per-instance CSS block shows exactly one of
   the two based on viewport width. Every existing caller's `style_plain_
   dataframe` kwargs (team_color_map, diverging_cols, numeric_pct_cols,
   opponent_col, win_loss_col) are forwarded unchanged to the desktop
   path AND independently re-implemented (deliberately NOT a shared
   refactor - see `_mobile_cell_bg`'s docstring for why) for the mobile
   cards, so both sides color-code identically without risking the
   proven desktop Styler. `primary_col` accepts a column name, a list of
   column names (for compound-key tables like Live Odds' props comparison
   or Compare's Market/Player/Selection rows), or `None` to use the
   DataFrame's own index (Positional Defense's Bucket, Compare's Stat
   name). A real bug caught and fixed before shipping: the `key` string
   (which can be an f-string interpolating a team/player name, e.g.
   "positional_defense_North Carolina State") needs sanitizing the SAME
   way Streamlit sanitizes it for the CSS class name (non
   alphanumeric/underscore/hyphen -> hyphen) BEFORE building the show/hide
   CSS selector, or a name containing a space produces a broken selector
   - confirmed by reading Streamlit's own frontend bundle's sanitization
   regex and matching it exactly.

Also: every touch target (buttons, selectboxes, multiselect, text inputs,
checkboxes, the positional-defense games-per-team slider) bumped to
>=44x44px below 768px, using only Streamlit's STABLE component classes/
testids (`.stButton`, `.stCheckbox`, `data-testid="stSlider"`, etc.), not
its internal emotion-hashed classes (those change across versions). One
honest limitation flagged, not silently glossed over: `st.dataframe`'s
in-canvas column-sort headers cannot be resized via CSS at all (same
canvas limitation as above) - mitigated, not fixed, by the mobile card
view providing its own real, properly-sized filter/sort controls instead
of asking mobile users to tap the tiny canvas header.

**Verification**: unlike most passes in this doc, this one was checked
against a REAL running app in a REAL headless browser (Playwright,
pre-installed in this environment) at both a 1280px desktop and a 375-
390px mobile viewport, not just AppTest/code-reading - confirmed live:
the desktop `st.dataframe` grid renders pixel-identical to before at
1280px; at mobile width the desktop container's computed `display` is
`none` and the mobile card container's is not, with real team names
appearing in the page's extracted text only in the mobile case (proving
the canvas dataframe truly isn't there vs. the real-DOM cards truly are);
touch targets measured >=44px via `boundingBox()` on mobile and
unchanged at desktop width. This caught two real bugs pure code review
would have missed (the `sft-wrap` height-clipping and the unsanitized-
key CSS selector above) - both fixed before this entry was written.

---


**Status as of this writing: 7 of 7 tabs live with real data** (Player
Search, Team Efficiency, Rankings, Matchup Analyzer, Live Odds, Player
Compare, Transfer Portal - NET & Resume and Conference Standings are
sub-tabs under Rankings, not separate top-level tabs) via
CollegeBasketballData.com (free key, configured), ESPN's public endpoints
(no key), and The Odds API (free key, configured). A short-lived 8th
Predictive Analytics tab (see this doc's top two entries) was retired and
redistributed into Matchup Analyzer based on in-app usage feedback - back
to 7. No PFF-equivalent subsystem exists for this app at all — there's no
PFF product for college basketball.

**CORRECTION (doc-drift fix, this pass): this line previously said "10 of
10 tabs."** Bracketology and Fantasy & Pools, both still described in
present tense in this doc's §3 below, are NOT in `app.py`'s tab list and
have no `ui/tabs/` file - they were removed from the app at some point
without a corresponding HANDOFF.md update. §3's Bracketology/Fantasy
scoring entries are left as historical record rather than deleted (same
"correct forward, don't rewrite history" convention as every other
correction in this doc), but treat them as NOT LIVE - see DATA_SOURCES.md's
own correction note on its per-tab table for the same fix.

**Review-flagged fixes pass:** an external
review of this codebase (not a live-usage report like every other pass
below) flagged several real bugs and gaps, verified against the code and
fixed:

1. **`get_player_season_profile` gated on `load_espn_roster` - TODAY's
   live roster, no season parameter - before ever checking the season box
   file**, the exact same root cause as the earlier-fixed Cameron Boozer
   bug in Player Search, just never ported to this function. A player who
   left the program since `season` (draft/transfer/graduation) has real
   box-file rows but isn't on today's live roster, so this gate silently
   forced a CBBD fallback for a player ESPN's own data could serve.
   **Fixed**: removed the `load_espn_roster` gate entirely - the box-file
   name match (`stats_idx`) was already the real, season-correct existence
   check; the roster gate added nothing but a chance to reject a valid
   ESPN-servable player. Also found and fixed a related, more impactful bug
   while in there: this function's `fallback` tuple was built EAGERLY at
   the top of the function (`fallback = (get_player_season_stats(...), ...)`),
   which calls CBBD's API on every single invocation regardless of whether
   the ESPN path succeeds - directly contradicting this function's own
   documented contract ("CBBD is only actually CALLED when the ESPN path
   can't be used") and burning quota on every Matchup Analyzer PLAYER
   panel / Player Compare lookup, successful or not. Fixed by making it a
   lazily-called `_cbbd_fallback()` closure, invoked only on an actual
   fallback branch.
2. **Positional matchup defense's ESPN box file resolved raw team names
   directly against CBBD's team list in one hop** - any opponent whose
   CBBD spelling diverged from the raw SportsDataverse name (much likelier
   than the specific team being looked up, since an opponent can be any of
   360+ teams) silently dropped that opponent's entire row via
   `_resolve_espn_box_team_names`' dropna, undercounting opponents and
   tripping `_is_espn_data_fresh_enough`'s staleness check for no real
   reason. **Fixed**: resolve against ESPN's OWN team list first (same
   source family as the box file, so this hop rarely misses), then bridge
   that ESPN-canonical name to CBBD's list - a row whose CBBD bridge fails
   now keeps its ESPN-spelled name instead of being dropped. Factored the
   actual two-step logic into a new pure function,
   `_bridge_espn_box_to_cbbd_names`, specifically so it's unit-testable
   without touching the surrounding `persist="disk"` cache.
3. **`data.utils.normalize_team_name`/`resolve_team_name` had no mascot-
   stripping mechanism** - "Duke Blue Devils" never resolved against a
   mascot-free canonical list like "Duke" (the original live Cameron
   Boozer-adjacent bug, see the `load_espn_teams` entry further down).
   **Fixed**: added a generic (not hardcoded-per-school) word-prefix
   matching fallback tier, `_mascot_prefix_match` - picks the LONGEST
   canonical name whose words are a whole-word prefix of the raw name's
   words, operating on the alias-EXPANDED map so an alias like `'miami' ->
   'Miami (FL)'` also covers "Miami Hurricanes" for free. Longest-match-
   wins avoids a real collision class (a short name like "Washington"
   winning over the correct, more specific "Washington State" for
   "Washington State Cougars").
4. **Several `@st.cache_data(persist="disk")` CBBD loaders swallowed a
   transient fetch failure into an empty DataFrame INSIDE the cached
   function body** - Streamlit then memoized that empty result as
   durably as a real success for up to a week (this app's own
   `_fetch_espn_season_box_raw_cached` had already fixed this exact
   pattern for the ESPN box pipeline - see the "caching-robustness gap"
   entry further down - but it was explicitly left unapplied to the CBBD
   side "if this class of bug shows up again elsewhere," which it did).
   **Fixed** the same way, extended to the CBBD side: a new
   `_cbbd_get_or_raise` propagates a real network/HTTP-status/JSON failure
   instead of swallowing it; `_load_efficiency_ratings_cached` (Team
   Efficiency) and `_load_all_team_season_stats_cached` (Team Defense
   profile) call it directly. `load_teams`/`load_team_player_stats`/
   `load_team_games`/`load_player_game_logs` were each split into a
   raising `_..._cached` inner (still the SAME cache entry, so no loss of
   call-sharing) plus a thin, unchanged-contract public wrapper that
   catches at the boundary - `_load_conference_player_season_stats_cached`/
   `_load_all_player_season_stats_cached`/`_load_team_opponent_game_logs_cached`
   now call those raising inner variants directly so a genuine failure
   anywhere in their fan-out propagates out of the whole weekly aggregation
   uncaught, instead of silently caching an incomplete result for a week.
   `_fetch_standings_raw` (1h cache, not persist="disk", but the same
   swallow-into-`{}` pattern - explicitly named as breaking "Player
   Search's entire ESPN path when standings fail transiently") got the
   same raise/catch-at-callers treatment via a new `_safe_standings`
   helper. `fetch_net_rankings_manual` too, split into a raising
   `_fetch_net_rankings_manual_cached` + safe public wrapper.
5. **Matchup Analyzer's and Player Compare's player pickers only used
   `load_team_roster` (CBBD)** - CBBD's roster endpoint IS season-aware
   (unlike ESPN's live-only roster endpoint), but can still desync from
   box-score reality (transfer-portal timing, a walk-on added mid-season),
   hiding a player from the dropdown despite them having real season
   stats. **Fixed**: both pickers now union CBBD's roster with this
   season's own ESPN box-file players for the team, same pattern Player
   Search already used for its own version of this problem. Box-only rows
   are bare `pd.Series` with every field the rest of each tab accesses set
   (position, and in Compare's case jersey/height/weight/id, all `None`)
   so bracket access downstream never `KeyError`s.
6. **`fetch_net_rankings_manual`'s "Fetch latest NET rankings" button
   didn't bust its own 24h cache** - clicking it again the same day
   silently reused the cached HTML, misleading a user who explicitly asked
   for a refresh. **Fixed**: the button handler now calls
   `fetch_net_rankings_manual.clear()` before triggering a fetch - only on
   an actual click (not on every rerun from, say, typing in the team
   filter box), so ordinary reruns still benefit from the cache.
7. **No visibility into CBBD call volume this session** - the app has
   detailed quota-arithmetic documentation (DATA_SOURCES.md's API budget
   section) but nothing in the UI itself. **Fixed**: a lightweight,
   session-local counter (`st.session_state['cbbd_calls_this_session']`,
   incremented inside the new `_cbbd_get_or_raise`) now shows in the
   sidebar whenever it's nonzero - not a real quota readout (session-local
   only, doesn't account for disk-cached calls from earlier sessions), but
   enough to make quota risk visible at a glance, same spirit as Live
   Odds' real "requests remaining" caption.
8. **`load_all_rosters`/`_load_all_rosters_cached` had no caller anywhere
   except `clear_league_wide_caches()`** - dead code that would fan out to
   all 360+ CBBD teams if ever wired in. **Removed** both functions and
   the now-invalid `clear_league_wide_caches()` reference to the deleted
   one.
9. **`live_odds.py`'s game-lines table did `.set_index('Book')` before
   `style_plain_dataframe`** - the same Styler-index-cell limitation
   documented elsewhere in this file (§5) that silently no-ops any
   team/row coloring on index cells. Harmless today (no color map is
   passed here), but inconsistent with this app's own established
   convention. **Fixed**: kept `Book` as a real column with
   `hide_index=True`, matching every other table in this app.
10. **Zero `test_*.py` files existed anywhere in this repo**, despite this
    doc repeatedly citing `AppTest`/synthetic verification as this app's
    testing discipline. **Added** a `tests/` directory (stdlib `unittest`,
    no new dependency) covering `match_player_name`/`resolve_team_name`
    (including the new mascot-stripping fallback and a documented,
    NOT-yet-fixed ambiguous-name-collision case - see the "meaningful
    UX/correctness gap" flagged but not fixed this pass, below), the DNP
    row filter, the ESPN/CBBD team-name bridge, and
    `get_player_season_profile`'s ESPN-vs-CBBD-fallback branches
    (including a regression test for the eager-fallback quota bug found
    while fixing #1). Run via `python3 -m unittest discover -s tests -v`.

**Flagged but deliberately NOT fixed this pass** (scope discipline - real,
but lower-priority or judgment-call items):
- `match_player_name` still returns the FIRST match when two players share
  an exact normalized name with no distinguishing suffix - no warning
  surfaced. Documented as a known limitation with its own test
  (`tests/test_utils.py`'s `test_ambiguous_names_resolve_to_first_occurrence`)
  rather than silently left unverified.
- Mixed-source Player Compare (one player resolves via ESPN, the other via
  CBBD) still runs the delta table/radar - the existing caption already
  warns which case this is; a harder gate (refusing to compare at all)
  wasn't requested and would make the tab less useful for exactly the case
  (a player only one source has data for yet) where comparison is most
  wanted.
- Position-bucket granularity, ESPN standings' embedded color/id fields,
  SportsDataverse's exact FTM/FTA/OREB/DREB column names, CBBD's
  recruiting height/weight field names, and whether `trueShootingPct` is a
  0-1 ratio or 0-100 - all still unverified against a real live payload,
  same standing sandbox caveat as every prior pass. Nothing code-side to
  fix here without live network access; worth a spot-check once the season
  starts, per this doc's usual discipline.

**Not independently live-verified** - same standing sandbox caveat as
every pass in this doc: this environment still can't reach
api.collegebasketballdata.com or ESPN's live endpoints. Verified instead
via direct unit tests (see #10 above) against synthetic payloads
replicating each bug's exact reported symptom, plus a full
`python3 -m py_compile` pass and manual monkeypatched exercise of the
`_cbbd_get`/`_cbbd_get_or_raise` split confirming a simulated transient
failure is retried on the next call instead of being cached as a false
"empty" result. **Before trusting this**: run `streamlit run app.py` for
real once the season starts, same discipline as every previous pass.

**Four polish items: confirmed D-I caching
is already shared, fixed a missing-player bug in Player Search, aligned
Matchup Analyzer's two columns into synchronized rows, and reordered
tabs.**

1. **"Compare vs all D-I" caching parity** - checked: Player Search and
   Matchup Analyzer's PLAYER panel already call the exact same
   `data.loaders.load_espn_di_player_stats(season)` (added last pass) for
   this checkbox - no discrepancy found, no code change needed here.

2. **Real bug: a real, current player (Cameron Boozer) was missing
   entirely from Player Search's team-filtered Duke dropdown**, despite
   having real season stats (findable fine via All Teams mode - the same
   "team-filtered vs. All Teams" split symptom pattern as the earlier
   roster/box-file id bug, but a different root cause this time).
   `load_espn_roster`'s URL has NO season parameter at all - it always
   reflects TODAY's live roster, never `season`'s - so a player who left
   the program since (draft, transfer, graduation) drops off the
   team-filtered picker completely, even for a season they demonstrably
   played. **Fixed**: the team-filtered player list now unions the live
   roster with this season's own box-file players for that team (same
   `box_df` already loaded for stats, no extra fetch) - a departed
   player's box-file row keeps them visible even after the live roster
   no longer lists them. Extra (box-only) entries are bare `pd.Series`
   with just name/position set, deliberately NOT merged into one wide
   DataFrame - concatenating would force pandas to coerce missing numeric
   fields (height/weight) to NaN, and this file's `bio.get(...) or
   '--'`-style checks treat NaN as truthy (a real Python gotcha - `bool(
   float('nan'))` is `True`), which would have silently rendered literal
   "nan" text instead of falling back - the same safe all-keys-absent
   pattern All Teams mode's own fallback bio already used, applied here
   too.

3. **Matchup Analyzer restructured into three synchronized row-pairs**
   instead of two independently-stacked columns, per explicit request to
   visually align PLAYER against TEAM DEFENSE despite them being separate
   Streamlit columns: Row 0 (pickers, kept short on both sides), Row 1
   (tendency profile beside defensive profile), Row 2 (last-10-games
   trend beside positional matchup defense). `_render_player_panel`/
   `_render_team_defense_panel` split into `_pick_player`/
   `_pick_defense_team` (Row 0) plus `_render_tendency_profile`/
   `_render_player_trend` (PLAYER's Row 1/Row 2) and
   `_render_defensive_profile`/`_render_positional_defense` (TEAM
   DEFENSE's Row 1/Row 2) - `_pick_player` returns a context dict (or
   `None`, after showing its own message) consumed by the two PLAYER-side
   row functions. Each row's two sides render independently - a
   PLAYER-side failure (no roster, no stats) doesn't block TEAM DEFENSE,
   and vice versa, exactly as before this refactor - verified via
   AppTest with an empty-roster PLAYER scenario confirming TEAM DEFENSE's
   profile still renders. Two columns within the SAME `st.columns()` call
   are guaranteed to start at the same height, so Row 1 and Row 2 each
   start together on both sides - genuinely "aligned," not just visually
   close - though a row can still end at different heights per side (e.g.
   PLAYER's longer stat-bar list vs. TEAM DEFENSE's shorter one), leaving
   whitespace under the shorter side before the next row starts - "some
   what matched up," which is what was asked for, not pixel-perfect
   synchronization (not achievable across independent Streamlit columns
   without fragile height-hardcoding).

4. **Tabs reordered** to Player Search, Team Efficiency, Rankings, Matchup
   Analyzer, Live Odds, Player Compare, Transfer Portal (`config.py`'s
   `TAB_LABELS` and `app.py`'s `_tab_modules`, kept in lockstep - both
   lists are zipped together positionally, so they must stay in the same
   order).

Verified via `streamlit.testing.v1.AppTest`: a synthetic "player left the
program" scenario (in the box file, absent from a mocked live roster)
confirming the player now appears in the team-filtered dropdown with real
stats and no stray "nan" text; an empty-PLAYER-roster scenario confirming
TEAM DEFENSE's row still renders; and the reordered tab label list. Still
not verified against live CBBD/ESPN - same standing sandbox caveat as
everything else in this pipeline.

**UI copy cleanup + Matchup Analyzer conference-mismatch bug + D-I
comparison caching + a positional-defense source indicator.** Three
requested changes from real usage:

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
- **Every completed round of upgrades gets pushed to `main`**, not just
  parked on a feature branch — explicitly requested standing instruction,
  not a one-time approval. Develop on the feature branch as usual, verify
  the changes (tests/AppTest run, this doc updated), then fast-forward
  `main` to it and push, same pattern as every pass in this doc's history.
  Still confirm the risky-git-operation basics (fetch first, prefer
  fast-forward, don't clobber unrelated commits) - this removes the need
  to separately ASK before the main-push step each time, not the need to
  do that step carefully.

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
