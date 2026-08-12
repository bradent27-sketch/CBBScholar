# Box scores, cross-tab links, clickable chart points, and Back

**How CBB Scholar stops being eight separate tabs.** This document covers
four things that only make sense together:

1. a per-game **box score** panel,
2. **cross-tab links** — every per-game stat in the app opens the box score
   for the game it came from, and the box score opens the rest of the app,
3. **clickable data points** on trend charts, and
4. a single **Back** control that restores where you came from.

Companion to `PORTING_GAME_SLATE.md`, which covers the Game Slate tab this
box score lives inside. **Read that one first if you're porting from
scratch** — the slate is the destination every link here points at, and §2
of that document defines the game frame this one joins against.

**Audience: an agent adding these to NFL Scholar (`C:\FantasyF`), or anyone
returning to this code in six months.** Every number quoted here was
measured against real data or a real browser, not estimated. Where
something is unverified it says so.

**Source files:**

| File | What it holds |
|---|---|
| `data/loaders.py` | `load_game_box`, `_season_team_box`, `season_slate`, `find_slate_game`, `slate_date_for_timestamp` |
| `data/transforms.py` | `game_link_rows`, `game_link_rows_for_dates`, `_link_entry` — the game resolver |
| `ui/components.py` | `switch_tab`, `open_box_score`, `open_slate_date`, `render_game_links`, `render_trend_with_point_links`, `push_nav_history`/`go_back`/`sync_nav_history`/`render_back_button`, `set_sticky_value`/`seed_sticky_value` |
| `ui/tabs/game_slate.py` | the box panel (`_render_box_panel` and its `_*_html` helpers) |
| `ui/styling.py` | the `.bs-*` block, plus `st-key-gamelinks_` / `st-key-cpl_row_` / `st-key-cpl_wrap_` rules |
| `tests/test_game_links.py` | resolver, navigation, history, overlay |
| `tests/test_game_slate.py` | box-score rendering |

---

## 0. Read this first: four constraints that shape everything

Everything below is a consequence of one of these. If a design choice here
looks convoluted, it is almost certainly one of these four.

### 0.1 Only a widget can run Python. HTML and SVG cannot.

The tables in this app are hand-rolled HTML and the charts are inline SVG,
because Streamlit's `st.dataframe` is a `<canvas>` that CSS cannot reach
into. That buys full styling control and costs the ability to put a
clickable control inside a row or on a data point.

So **every** link in this system is a real `st.button`, styled to not look
like one. There is no way around this short of rewriting the tables and
charts into a different rendering stack.

### 0.2 A link that changes the URL destroys the session.

The obvious way to make an SVG dot clickable is to wrap it in
`<a href="?game=401856600">` and read `st.query_params`. **It works, and
you must not do it.**

A query-string link is a real page navigation, which starts a **new
Streamlit session**. Every picker, every sticky mirror, and the whole back
stack are wiped. Confirmed in a browser rather than reasoned about: a
random session token printed before and after the click came back
different.

That single finding is why §5 exists in the shape it does.

### 0.3 `active_tab` can only be assigned from a callback.

The app's tabs are `st.tabs(TAB_LABELS, key="active_tab", on_change="rerun")`.
Streamlit raises `StreamlitAPIException` if `st.session_state["active_tab"]`
is reassigned during the same script run that already read it to render
those tabs — which `app.py` does, before any tab's `render()` is reached.

A callback runs in the **pre-script** phase, so the assignment is legal
there. Everything that navigates is therefore an `on_click`, never
something called from a render body. Anything that must run before the
tabs render (`sync_nav_history`, `render_back_button`) goes in `app.py`
above the `st.tabs()` call.

### 0.4 Two id namespaces and two team-name namespaces.

This app's per-game data arrives from two sources that agree on nothing:

- **Game ids**: the published box files use ESPN's ids; CBBD's `gameId` is
  an unrelated namespace. Matching on the wrong one either misses or, far
  worse, *collides*.
- **Team names**: the box/schedule files use ESPN's `location` ("UConn");
  CBBD uses `school` ("Connecticut"). Several tabs key on one, several on
  the other.

**The failure mode is silent in both cases** — you get a perfectly good box
score for a game nobody asked about, or a destination tab quietly opening
on its default team. §4 is mostly about defending against this.

---

## 1. The box score

### 1.1 Data

Two published files, both from the same GitHub Releases namespace the app
already downloads player box scores from:

| | File | Size | Cost |
|---|---|---|---|
| Players | `player_box_{season}.parquet` | ~3.4 MB | **Free** — already downloaded for Player Search / Compare / Matchup Analyzer |
| Teams | `team_box_{season}.parquet` | ~728 KB | One new download per season |

Both join to a slate row on `game_id` at **100%**, and all **5,752**
completed D-I games in the real 2026 season have both. The schedule row
itself carries `player_box` / `team_box` availability booleans, so a card
can decide whether to offer a box score without loading anything.

Measured: **3.0 s** to open the first box of a session (the one-time team
box download), **0.33 s** for every box after it.

### 1.2 `load_game_box(game_id, season) -> {'teams', 'players', 'team_totals'}`

Four things in that function are load-bearing:

**Compare `game_id` AS A STRING on both sides.** The published files type
it `int32`; the slate frame stringifies it. The natural
`box['GameId'] == row['GameId']` matches **nothing** and returns an empty
box with no error anywhere. Hit live before the function was written.

**Read the RAW box frame, not the name-resolved one.** The app's
`load_espn_season_player_box_native` resolves team names against ESPN's
standings endpoint and drops DNP rows. A box score needs neither: the raw
file's `team_location` already *is* the slate's `Away`/`Home` spelling, so
they join directly. It also means the box still works when the standings
endpoint is unreachable — not hypothetical, it was down for this entire
build.

**Do NOT sum player rows to get team totals.** Team rebounds and team
turnovers belong to no player. Measured on the real 2026 championship:
Michigan OREB 10 by sum vs 12 actual, UConn turnovers 10 vs 11. Anything
four-factors-shaped built on sums inherits that error invisibly. The team
box also carries points in paint, fast-break points, points off turnovers,
largest lead and lead changes, none of which are derivable at all.

**Widen the shared raw fetch additively.** The box score needs
`starter` / `did_not_play` / jersey / position-abbreviation / fouls, which
the existing parser didn't extract. Adding them to
`_fetch_espn_season_box_raw_cached` is one download for everyone; the
name-resolving function downstream is pinned to the column set it always
returned, so no existing consumer sees the change.

### 1.3 UI

Rendered **full width above the card grid**, not as an expander inside a
card. Two reasons: a card has already spent Streamlit's single level of
column nesting (grid column → button row), and a two-team box is
unreadable at half width.

Top to bottom:

- **Header** — both teams with logos, rank, conference, score; winner's
  score brightened. Venue, status and broadcast underneath.
- **Head-to-head comparison bars** — one shared track per stat, split by
  each side's share. **Shooting compares PERCENTAGE, not makes**: 21-68 and
  21-55 are the same makes and very different games.
- **Chips** for the team-box extras (paint, fast break, points off
  turnovers, largest lead, lead changes).
- **Per-team sections** — starters marked, a points heat bar behind each
  row so the scoring line reads without scanning a column, DNPs listed by
  name rather than dropped.

`_render_box_panel` resolves its game against the **whole season**
(`find_slate_game`), not the page on screen, and renders **before** the
empty-day early return. Both matter because this panel is the destination
for every cross-tab link: requiring the game to also survive the slate's
current date, filters and paging would make links fail for reasons that
have nothing to do with the game they name.

---

## 2. Where the links go

| From | To |
|---|---|
| Player Search → game log (chip strip under the table) | that game's box score |
| Matchup Analyzer → **the dots on every trend chart** | that game's box score |
| Live Odds → selected game | the Game Slate on that game's date |
| Box score → player name | that player's Player Search profile |
| Box score → team | Team Efficiency · the opponent's Matchup Analyzer defense profile · conference standings |

Two deliberate omissions, both for the same reason — a wrong destination is
worse than no link:

- **Game Slate → Live Odds.** Its game picker is keyed on a label string
  built from Odds API team names plus a formatted tip time: a third
  team-name namespace, and a format that breaks if either side's rendering
  changes.
- **Box score → Player Compare** (seeded with both teams' leading scorers).
  Compare's player pickers have no search box to narrow on, so a
  label-format mismatch would land on the *first roster player* rather than
  degrading harmlessly. Fixable by giving Compare a query filter like
  Player Search's; not done.

---

## 3. Resolving a stat back to its game

`data.transforms.game_link_rows(log_df, slate_df, team=None, id_col='GameId', date_col='Date', limit=None)`

Returns `[{'game_id', 'date', 'label', 'help', 'won', 'opponent'}]`, one per
row of the log that resolves, in the log's own order.

**Two resolution paths, because of §0.4:**

1. **By id**, when the log carries ESPN game ids — everything from the
   published box file.
2. **By date + team**, as the fallback — CBBD-sourced logs, whose ids are
   meaningless here. This is a real second path, not a hopeful id match.

`team` may be spelled in either convention; it's resolved against the
slate's own team pool via `resolve_team_name` first, which is what lets a
CBBD-spelled "Connecticut" find ESPN's "UConn".

**A row that resolves to nothing is DROPPED**, never emitted with a null
id. A dead link that navigates nowhere is worse than no link.

`game_link_rows_for_dates(dates, slate_df, team)` is the variant for a
series that only knows dates (the positional-defense trend aggregates
opponents by game date). It **requires** `team` — a date alone matches
~150 games in college basketball.

**Verified on a real 40-game season log: 100% resolved, and the date
fallback selected the identical games as the id path.** That cross-checks
both paths against each other and is worth re-running after any port.

---

## 4. Navigating: `switch_tab`, and the seeding rule that bites

```python
def switch_tab(tab_label, _record=True, **sticky_state):
    if _record:
        push_nav_history([k for key in sticky_state
                          for k in (key, _sticky_mirror_key(key))])
    st.session_state['active_tab'] = tab_label
    for key, value in sticky_state.items():
        seed_sticky_value(key, value)
```

`sticky_state` keys are the **destination widgets' own `key=` values**.

### The asymmetry you must get right

This app wraps every widget in "sticky" helpers that mirror each value into
a second, non-widget key, because Streamlit **prunes a widget-scoped key
whenever its tab isn't rendered**. That gives two ways to write a value,
with *opposite* failure modes:

```python
def set_sticky_value(key, value):     # target is on the OPEN tab
    st.session_state[f"_sticky__{key}"] = value
    st.session_state[key] = value      # widget key still exists; Streamlit
                                       # prefers it over the computed index

def seed_sticky_value(key, value):    # target is on a CLOSED tab
    st.session_state[f"_sticky__{key}"] = value
    st.session_state.pop(key, None)    # mirror only — see below
```

**Writing the raw widget key across a tab boundary makes Streamlit RAISE**
whenever the seeded value isn't a member of the destination selectbox's
options — which is not rare, because seeding a matchup seeds a team, the
option list comes from a different source's spelling, and the season may
change out from under it. The mirror has no such problem: every sticky
wrapper checks `remembered in options` and falls back to its own default,
so an unresolvable value degrades to "opened on the default" instead of a
traceback.

**If the target app has no sticky wrappers**, seed the widget keys directly
— but then you must guarantee validity: resolve the name *before* seeding
and disable the button if it doesn't resolve.

### Seed defensively when the destination's label format is unknown

Player Search builds its player labels from two sources with different
position formats — ESPN's roster gives `G`, the box file gives `Guard`. An
exact-label seed can therefore miss. The player link seeds **three layers**:

```python
kwargs={
    'ps_season': season,
    'ps_team': team,                    # ESPN spelling, matches the slate
    'ps_player_query_team': name,       # 1: narrows the roster list
    'ps_player_select': f"{name} ({pos_abbr})",   # 2: exact label
    'ps_player_query': name,            # 3: All-Teams-mode fallback
}
```

If layer 2 hits, it's exact. If it misses, layer 1 has narrowed the list to
one player and the sticky fallback selects index 0 — the same player.
Layer 3 covers the team itself failing to resolve, where Player Search
opens in All-Teams mode and needs a non-empty query to show anything.

**This is not theoretical: layer 2 missed in the end-to-end test** (roster
endpoint unreachable, so labels used `Guard`) and layer 1 still landed the
right player.

### Raw `st.tabs` keys are not sticky

Landing on a *sub*-tab (`rk_subtab`) means assigning that key directly, not
through the mirror — `st.tabs` reads its own key. Legal in a callback, same
as `active_tab`.

---

## 5. Clickable chart points

**The dot is the affordance.** A chip strip under a chart is a second,
indirect control for the same games; if the chart plots games, clicking the
point is the gesture. (A strip is still right under a *table*, which has no
dots — Player Search keeps one.)

### What not to do

- **`<a>` inside the SVG** — destroys the session (§0.2).
- **A Vega/Altair chart with `on_select`** — gives native point selection,
  but only by replacing the hand-built SVG charts and losing their
  reference line, per-point coloring and corner badges.

### What works

`render_trend_with_point_links(render_chart, entries, season, key_suffix, chart_height)`

The chart and a row of **transparent `st.button`s** go into one
relatively-positioned container; the button row is absolutely positioned
over the chart, one column per data point. Each dot sits on its own
invisible hit strip, a click fires an ordinary callback, and the chart
itself is untouched.

```python
render_trend_with_point_links(
    lambda: render_trend_line(dates, values, avg=avg, height=150, ...),
    [link_by_date.get(str(d)) for d in dates], season,
    key_suffix=f"plr_{stat}", chart_height=150,
)
```

### The alignment is arithmetic, not eyeballing

`render_trend_line` places point *i* at `i/(n-1)` of the plot width; column
*i* spans `[i/n, (i+1)/n]`. The point is inside its own column for every
*i* and every *n*, since `i/(n-1) ≤ (i+1)/n` reduces to `i ≤ n-1`.

Two consequences:

- **Column gaps must be zeroed in CSS**, or the bands stop being flush.
- **An unresolvable point still consumes its column.** Skipping it slides
  every later strip onto the wrong dot.

### Height comes from `padding-bottom`, as a percentage of *width*

The chart is `width:100%; height:auto` over a fixed `viewBox`, so its
rendered height is `width × H/860` — not knowable in Python. Percentage
padding resolves against the containing block's **width**, so the overlay
emits a one-line `<style>` scoped to its own key class:

```python
f"<style>.st-key-{row_key}{{padding-bottom:{chart_height / 860 * 100:.4f}%;}}</style>"
```

An absolutely positioned child then uses `inset: 0` — **not**
`height: 100%`, which resolves against *content* height (zero) while an
absolutely positioned box resolves against the **padding** box.

### Three DOM facts you cannot guess

Getting this to land required walking the real DOM. All three were wrong in
my first attempt, and each one silently collapsed the strips back to
button height:

1. **The keyed container IS the vertical block**, not a parent of one.
2. **Streamlit inserts a `stLayoutWrapper`** between it and the column row.
3. **An unnamed `<div>` plus two tooltip spans** sit between `.stButton`
   and the `<button>` — the same wrappers that break `.stButton > button`
   selectors elsewhere. Any one of them left at its natural height kills
   it.

Hence the subtree selector rather than a list of testids a Streamlit
upgrade could rename:

```css
div[class*="st-key-cpl_row_"] .stButton,
div[class*="st-key-cpl_row_"] .stButton * {
    height: 100% !important;
    min-height: 0 !important;
}
```

**Verify functionally, not visually.** The check that matters is: click at
each dot's exact coordinates and confirm *that dot's* game fires. Measured
10/10 dots covered, clicks firing the right game, and tooltips still
working.

---

## 6. Back

One control, rendered in `app.py` **above the tab bar** — a browser back
button, not a per-tab one, so it's in the same place regardless of which
jump got you there.

```python
sync_nav_history()      # both MUST run before st.tabs()
render_back_button()
```

### An entry is not just a tab name

A jump seeds the destination's pickers *and* clears the origin's filters,
so Back has to restore the exact values it overwrote. Returning to a tab
whose controls have silently moved is worse than offering no Back at all.

Each navigation therefore snapshots the keys it is **about to** touch:

```python
_SLATE_NAV_KEYS = [
    'gs_box_game',
    'gs_season', '_sticky__gs_season',
    'gs_date', '_sticky__gs_date',
    'gs_conferences', '_sticky__gs_conferences',
    'gs_ranked_only', '_sticky__gs_ranked_only',
    'gs_page', '_sticky__gs_page',
]
```

Both the mirror **and** the raw widget key, since `seed_sticky_value`
writes one and pops the other.

### A key that did not exist is deleted again, not set to `None`

A `None` left behind reads as a real remembered value to the sticky
wrappers, which check membership rather than nullness. Hence the `_Absent`
sentinel in the snapshot.

### The stack drops on a manual tab change

A Back that outlives hand navigation sends someone somewhere they never
asked to go. Each jump sets `_nav_marker` in its callback; `sync_nav_history`
treats a tab change with no marker as manual and clears the stack. This is
why it must run before `st.tabs()`.

### One click, one entry

`open_box_score` delegates to `switch_tab`, so exactly one of them may
push — hence `switch_tab(..., _record=False)`. Two entries would mean two
Backs to undo one click. Depth is capped at 20.

**Session-state keys used:** `_nav_stack`, `_nav_marker`, `_nav_last_tab`.

---

## 7. Gotchas — every one was a real bug

### 7.1 `game_id` types don't match across sources

`int32` in the files, `str` in the slate frame. The naive comparison
returns an empty box **with no error**. Cast both sides.

### 7.2 Team totals ≠ the sum of the player rows

Team rebounds and team turnovers belong to no player. See §1.2 for the
measured discrepancy. The panel's caption says this out loud, so the
numbers not tying out doesn't read as a bug.

### 7.3 The box panel must not depend on what's on screen

Resolve against the whole season and render before the empty-day early
return, or every cross-tab link fails whenever the target game falls
outside the slate's current date, filters or page.

### 7.4 Clear the origin's filters on arrival

Someone arriving via a link asked for **one game**. A stale conference
filter left on shows the box above a baffling empty slate. `open_box_score`
clears conferences, ranked-only and paging — but leaves `gs_di_only`, which
is on by default and can't hide a game this app has stats for.

### 7.5 A player-name button is not a link, so style it like one

Scope the appearance rules to the panel's keyed container, or you restyle
every button in the app. `!important` is required — Streamlit injects its
button styles with emotion **at runtime, after** the app's `<style>` block,
so an equally specific override silently loses the cascade.

### 7.6 Per-widget `st-key-` classes are real but undocumented

Streamlit stamps `st-key-<key>` on each widget's element container, which
is the only handle for styling **one** button differently from its
neighbours (the win/loss tint keys off a `gl_<tone>_` token baked into the
button's key). It is not documented API — **verify with `getComputedStyle`
in a real browser** before depending on it, and keep a test asserting the
key format so a rename can't silently kill the tint.

### 7.7 Screenshots lie about CSS

Both §7.5 and §7.6 look completely fine in a screenshot while being dead in
the DOM. Read computed styles.

### 7.8 Watch what you name scratch files

A probe script named `click.py` on `sys.path` shadowed the `click` package
Streamlit imports, and every test run died with an unrelated-looking
traceback. Not a code bug, but it cost real time.

---

## 8. Tests worth porting

`tests/test_game_links.py` (27 cases) and the box-score section of
`tests/test_game_slate.py`. The ones that earn their keep:

**Resolver** — resolves by ESPN id; falls back to date+team for a foreign
id namespace; the date fallback *requires* a team; a CBBD-spelled team
still resolves; unresolvable rows are dropped, never emitted with a null
id; duplicates collapse; `limit` keeps the most recent.

**Labels** — away uses `@ABBR`, home uses `vs ABBR` (with the space —
`vsOAK` is unreadable); a neutral site is never an away game; win/loss is
from the subject team's point of view; an unplayed game has no win flag;
the label never contains `nan`.

**Navigation** — Back restores the tab *and* the overwritten values; a key
that didn't exist is deleted, not set to `None`; a box jump records exactly
one entry; history nests and pops in order; Back on an empty stack is a
no-op; depth is capped; a manual tab change drops the stack; an ordinary
rerun does not.

**Overlay** — one strip per resolvable point, each opening its own game; an
unresolvable point still consumes its column; the chart renders even when
nothing resolves; the height is emitted as a percentage of the viewBox
width.

**Box rendering** — shooting bars compare percentage not makes; equal
values split the track evenly; 0-0 doesn't collapse it; a missing stat
renders a dash and the chip is skipped entirely; a DNP row never prints
`nan`; the heat bar scales to the game's top scorer; a malformed color
can't reach the bar's `style` attribute.

Assert on **rendered HTML** for the visual pieces. These requirements fail
silently — a card printing `nan` where a score goes still renders fine and
raises nothing.

---

## 9. Port checklist

1. [ ] Port the Game Slate first (`PORTING_GAME_SLATE.md`). Everything here
       links *into* it.
2. [ ] Find the box-score files in the target sport's data source; confirm
       they join to a schedule row and check the join rate.
3. [ ] Check whether the app **already downloads** the player box for
       something else. In CBB it did, which made half the feature free.
4. [ ] Implement `load_game_box`; cast the game id to `str` on both sides;
       read the raw frame, not the name-resolved one; pull team totals from
       the team file rather than summing rows.
5. [ ] Build the box panel full width, above the grid.
6. [ ] Implement the resolver with **both** paths (§3), and a test that the
       two agree on a real season log.
7. [ ] Audit the app for every per-game display. In CBB: a game-log table,
       three trend charts, and a defense trend that only knew dates.
8. [ ] Decide seeding per destination (§4). Check each destination's label
       format; seed defensively where it's ambiguous; **disable** a button
       whose target can't be resolved.
9. [ ] Add the overlay for charts (§5). Walk the DOM before writing the
       CSS; verify by clicking at dot coordinates.
10. [ ] Add `sync_nav_history()` + `render_back_button()` to `app.py`
        **above** `st.tabs()`.
11. [ ] Snapshot the full key set each navigation touches, mirrors and
        widget keys both.
12. [ ] Port the tests from §8.
13. [ ] Verify in a real browser: hover a dot, click a dot, follow a player
        name, Back twice, and toggle light/dark.

---

## 10. Deliberate decisions — don't "fix" these

| Decision | Why |
|---|---|
| Links are `st.button`s styled as links/strips/overlays | HTML and SVG cannot fire a Python callback (§0.1) |
| No `<a href="?game=…">` anywhere | It destroys the session — measured, not assumed (§0.2) |
| Charts get overlays; tables get chip strips | The dot is the direct gesture; a table has no dots |
| Overlay rather than a Vega/Altair rewrite | Keeps the hand-built charts and their design |
| An unresolvable point keeps its column | Otherwise every later strip lands on the wrong dot |
| Unresolvable rows are dropped, not linked | A wrong destination is worse than no link |
| Cross-tab seeding writes the mirror only | Guarded by a membership check; the raw key raises (§4) |
| Player links seed three layers | The destination's label format is genuinely ambiguous |
| Back restores values, not just the tab | A tab whose controls silently moved is worse than no Back |
| The stack drops on manual tab changes | Otherwise Back sends you somewhere you never asked to go |
| Team totals come from the team file | Player sums undercount rebounds and turnovers, invisibly |
| The box panel ignores the current page | It's a deep-link destination, not a page element |
