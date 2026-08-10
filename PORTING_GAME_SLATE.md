# Porting the Game Slate tab to NFL Scholar

**Revision 2. Written after actually shipping this tab into CBB Scholar,
which is what makes it different from revision 1.** The original document
was written from CFB Scholar looking outward and had to guess at the other
two sports. This one has been through a second real port, so the guesses
are now either confirmed, corrected, or replaced with a measured number —
and several sections exist only because a "obviously fine" assumption in
revision 1 turned out to cost debugging time in CBB.

**Audience: an agent wiring this tab into NFL Scholar (`C:\FantasyF`).**

Read §0 first — it is new, it is short, and it will save you the two
mistakes that cost the most in the CBB port. Then §1 and §2. §2 is the
porting contract: build the adapter functions it lists and the rest of the
tab drops in essentially unchanged.

**Source files this tab lives in, in CBB Scholar** (the more recent and
more directly reusable of the two implementations):

| File | What it holds |
|---|---|
| `ui/tabs/game_slate.py` | The whole tab. ~380 lines, no other tab imports it. |
| `ui/styling.py` | The `.gs-*` CSS block (search `GAME SLATE matchup cards`). |
| `data/loaders.py` | The slate section (search `GAME SLATE`): `load_slate`, `slate_dates`, `default_slate_date`, `slate_source`, `refresh_slate`, `slate_team_bridge`, `format_tipoff`, `_local_date`, `_normalize_slate_frame`, `_scoreboard_raw_rows`. |
| `ui/components.py` | `switch_tab`, `set_sticky_value`, `seed_sticky_value`, `sticky_date_input`. |
| `tests/test_game_slate.py` | 54 tests. Port these — see §9. |

CFB Scholar's original lives in `ui/tabs/weekly_slate.py`. Prefer CBB's
version as the base: it is newer, it carries the fixes below, and its
two-source design is closer to what NFL needs.

---

## 0. Read this first: the three things revision 1 got wrong

### 0.1 "Use whatever the target app already uses for schedules" was bad advice

Revision 1 said to reuse the target app's existing schedule source rather
than adding a dependency. Reasonable-sounding, and in CBB it would have
been the wrong call: the app already had a CBBD `/games` loader, and using
it would have burned a metered API quota on the single most-viewed screen
in the app, for data that turned out to be available free.

**Do the source survey before assuming.** In CBB the winning source was a
free, keyless, already-published bulk file that nothing in the app had ever
touched — sitting in the *same* GitHub Releases namespace the app was
already downloading box scores from. Nobody had looked.

For NFL, the equivalent question is: does `nfl_data_py`'s schedule frame
(or the underlying `nflverse-data` release asset) carry everything in
§2.1? It almost certainly does, it is free and keyless, and it is one
download rather than a per-week call. **Check what is already published
before wiring a live per-request API.**

### 0.2 One source is probably not enough, and the split is not where you'd guess

Revision 1 treated the slate as one source with a fallback. The real
shape, learned the hard way, is that **past and future games are different
data problems**:

- A published bulk file is a rebuild of games that have *happened*. It is
  rich, free, and cheap, and it may not contain the games you most want.
- A live endpoint has today and tomorrow, and is the only thing that has
  kickoff times that moved this week.

CBB ended up with a two-source ladder behind one normalized frame: the
published file serves past dates, a live endpoint serves today and
forward. **NFL may genuinely not need this** — `nflverse`'s schedule file
carries the full season's fixtures from the start, because the NFL
schedule is published in May and doesn't change. Verify that before
building the ladder; if the file really does carry future games with
kickoff times, delete the live path entirely and save yourself §3.

The test: download the file mid-season and check whether any row has a
future date and a null score.

### 0.3 Verify against real data, not against review

Both of the genuinely bad bugs in the CBB port survived a careful read of
the code and died within seconds of running the loader against a real
downloaded file. Neither was subtle in hindsight:

- Dates came off the raw UTC timestamp, so the national championship
  rendered as `04/07/2026 · Monday at 7:50 PM` — and 04/07 was a Tuesday.
  Every evening game in the file had it. See §8.1.
- Games sorted on the kickoff *display string*, so "Mon 9:00 AM" sorted
  after "Mon 10:00 AM". See §8.6.

**Before writing the UI, download one real season file and print ten
rows.** Everything in §2.1 that this document states as a number was
measured that way, and three of the four CBB-specific gotchas in §8 were
found that way rather than reasoned about.

---

## 1. What the tab is, and why it looks like this

It answers the first question of a real prep session — *who is playing* —
and then hands a chosen game to the app's other tools with both teams
already filled in. It is a **launchpad, not a report**.

Layout: a season / date (or week) / filter row, then **one card per game**
laid out two-up, then a data-freshness footer.

Each card shows the date, kickoff, venue, both teams with their own colors
and logos, each team's score when the game has been played, and buttons
that jump to other tabs pre-loaded with this matchup.

### Why cards instead of a table (don't undo this)

The tab shipped first as an `st.dataframe`. Two problems, both structural:

1. **Streamlit's dataframe is a `<canvas>` widget.** It cannot hold a
   button, a link, or any per-row control. Acting on a game therefore
   meant re-picking it from a *separate dropdown underneath the table* —
   the user selects a row visually, then re-selects the same game in a
   second widget. That is the interaction the card design deletes.
2. A table gave six columns equal visual weight, so every game was a
   horizontal scan. A card can rank information: teams and score big,
   metadata small.

If the target app already has a schedule table, this replaces it.

---

## 2. The porting contract

Everything sport-specific is behind these functions. Implement them for
the new sport and the tab body needs almost no edits.

### 2.1 `load_slate(season, period) -> DataFrame`

One row per game. **These column names are load-bearing** — the card
renderer indexes them directly.

| Column | Type | Notes |
|---|---|---|
| `Away`, `Home` | str | **Raw, joinable team identifiers**, not display strings. See §2.4 — this is the single most common silent failure in the whole port. |
| `Away Pts`, `Home Pts` | float / **NaN** | NaN for an unplayed game. See §8.2. |
| `Winner` | str / None | The winning team's identifier, `None` for unplayed **and for a tie**. |
| `Date` | str | ISO `YYYY-MM-DD` **in the display timezone**, kept for sorting and filtering. See §8.1. |
| `Date Display` | str | `MM/DD/YYYY`. Never sort on this. |
| `Kickoff`, `Kickoff Long` | str | `"Sat 12:00 PM CT"` / `"Saturday at 8:00 PM CT"`. |
| `Time TBD` | bool | Drives the footer's count of unannounced kickoffs. |
| `Status` | `'pre'`/`'in'`/`'post'` | **Add this.** Revision 1 didn't have it and it turns out to be what score rendering must gate on — see §8.3. |
| `Status Detail` | str | `"Final"`, `"Postponed"`, `"4th 2:11"`. |
| `Played`, `Live` | bool | Derived from `Status` + the status *name*, not from score presence. |
| `Away Conf`, `Home Conf` | str / None | Division for NFL (`AFC North`). Optional — omit and the row renders without it. |
| `Away Color`, `Home Color` | str / None | `#rrggbb`, **validated** — see §8.5. |
| `Away Logo`, `Home Logo` | str / None | Plus `… Logo Dark` if the league has dark variants — see §5. |
| `Away Rank`, `Home Rank` | float / NaN | Skip for NFL; there is no poll. |
| `Venue` | str / None | |
| `Neutral Site` | bool | Appends `(neutral)` to the venue. |
| `Broadcast` | str / None | **Worth carrying.** Free in both CBB sources, and "which game is on TV" is a real prep question. |
| `Headline` | str / None | Tournament/round label. For NFL: the playoff round. |
| `Matchup` | str | `"Away @ Home"` / `"Away vs Home"` for neutral sites. |
| `Analyzable` | bool | **Rename per sport.** "Is this a game the app can actually analyze". See §2.5 — **for NFL, delete it.** |
| `_source` | str | Which source served this row; drives the footer. |

> CFB Scholar also had `Result` as a pre-joined display string (`"Texas 24
> — 31 Ohio State"`). **Don't build it.** It cannot be split back apart
> safely — team names contain spaces and the separator characters — which
> is exactly why the per-team score fields exist.

### 2.2 The period selector: weeks vs dates

**This is the biggest structural fork in the port, and revision 1 assumed
weeks.**

- **CFB / NFL: weeks.** `slate_weeks(season) -> [{'week', 'season_type',
  'label', 'completed', 'games', …}]`, ordered so the most relevant week
  is last. A selectbox.
- **CBB: dates.** There are no weeks — a real season is 147 game *dates*.
  The selector became a `st.date_input` plus prev/next-day arrow buttons,
  and `slate_weeks` became `slate_dates(season) -> [{'date', 'games',
  'di_games'}]`.

**NFL keeps weeks**, so you get CFB's version nearly unchanged, and you
skip the arrow-button machinery and `sticky_date_input` entirely. But keep
the two-level default fallback from §2.5 — the reason it exists survives
the weeks-vs-dates change.

### 2.3 `slate_source(season, period)` and `refresh_slate()`

`slate_source` returns which source will actually serve this view
(`'local'` / a live-source name / `None`), so the footer can tell a static
published snapshot from a live pull. `refresh_slate` clears **every**
cached layer behind the slate — including any normalized/derived cache
downstream of the raw download. Missing one of those was a real bug in
CBB: clearing only the file download left every date view still served
from the stale normalized copy.

### 2.4 Team identifiers — the silent-failure section

Every map (colors, logos, abbreviations) and every cross-tab jump must key
on the **same team identifier** `load_slate` puts in `Away`/`Home`. A
mismatch is silent: colors and logos just don't appear, and the jump
buttons open the destination on its default team, with no error anywhere.

**Revision 1 warned about this abstractly. In CBB it was real and it needed
its own function.** The app has two team-name namespaces — ESPN's
`location` ("UConn") for some tabs and the stats provider's `school`
("Connecticut") for others — so the slate carries ESPN's names and bridges
to the other namespace through the app's existing fuzzy team-name
resolver:

```python
def slate_team_bridge(games, season):
    """{slate_name: destination_name}. A team that doesn't resolve is
    OMITTED, not mapped to None - every call site does .get(name) and
    disables the button on a miss, and a None VALUE would sail straight
    through that check and seed a null."""
```

**Check NFL for this before assuming it's a non-issue.** NFL is the most
likely of the three to be clean (abbreviations are near-universal), but
`nflverse` uses `LA`/`LAR`/`OAK`/`LV`/`SD`/`SDG`-style codes that have
changed over time, and a historical season is exactly where they diverge.
If a bridge is needed, reuse the app's existing resolver rather than
writing a second one.

### 2.5 The "analyzable game" filter — **delete it for NFL**

CFB's schedule feed covers every division, so it contains FBS-vs-FCS games
the app has no stats for. CBB has the same problem, harder: **365 D-I
teams out of 728 distinct names in a real season file**, with 8.7% of
games against non-D-I opponents. CBB solved it by testing whether both
teams carry a conference id, which is a real field rather than a guess.

**NFL has no equivalent. Every game is analyzable. Delete the checkbox and
the column entirely, and let any `analyzable_games` count collapse into
`games`.** Don't port a filter that can never do anything.

**But keep the two-level default fallback anyway.** The bug it exists for
was: the default period was "last completed week", and real postseason
weeks 13–14 were FCS playoff rounds with 24 and 8 games and *zero*
analyzable ones, so the tab opened on an empty screen.

```python
default_idx = max(
    (i for i, w in enumerate(weeks) if w['completed'] and w['analyzable'] > 0),
    default=max((i for i, w in enumerate(weeks) if w['completed']), default=0),
)
```

For NFL the two levels collapse into one, which is fine — write it as one
level, but write it deliberately rather than by accident. A bye week, a
season boundary, or week 22 of an 18-week regular season will still find
the empty-screen case if the default isn't guarded.

---

## 3. Data sourcing

### 3.1 The two-source ladder (skip if NFL's file has future games)

```python
def load_slate(season, period):
    season_df = _season_slate(season)             # published bulk file
    games = season_df[season_df['Date'] == period]
    if games.empty:
        games = _live_slate(period)               # live endpoint
    return games
```

Two properties worth preserving if you do need both:

**Normalize the live path into the file's column names**, so nothing
downstream branches on source. In CBB this was nearly free, because the
published file's columns are a flat rename of the live endpoint's payload
(`status_type_state` ← `status.type.state`, `home_logo` ←
`competitors[].team.logo`). Check whether the same is true for
`nflverse` vs whatever live endpoint you'd pair it with — if it is, you get
one parser for two sources and the second one is derived from a payload
you've actually inspected rather than guessed at.

**Normalize the whole season once, then slice**, rather than re-parsing per
view. In CBB: 6,318 rows in 1.3s cold, 0.006s warm. This also lets the
period list and the period filter key off the *same* derived values, which
is what keeps §8.1 fixed.

### 3.2 Cache TTLs

**One hour for the live path, not the 6–24h used elsewhere in these apps.**
Kickoff times are precisely the field that changes late — a game moves when
a network picks it up — and an in-progress score changes by the minute.

**The published file: daily.** In CBB it's rebuilt daily upstream
(confirmed via the release asset's own `Last-Modified` header, which is a
cheap way to check publish cadence without an API call — worth doing for
`nflverse` too).

**Watch out**: in this family of apps, `st.cache_data(ttl=…,
persist="disk")` **silently ignores `ttl`**. The established workaround is
a hashed bucket argument (`_week_bucket()`, `_daily_bucket()`). Use the
daily one for a schedule; a schedule must not be a week stale.

### 3.3 Dates and kickoff times — now with a timezone that isn't ET

Revision 1 said "ET everywhere, house standard". **CBB Scholar has since
moved to Central**, which turned the timezone from a constant into a knob —
and exposed that the knob has more attached to it than the display string.

```python
SLATE_DISPLAY_TZ = 'America/Chicago'

def _to_display_tz(dt, tz=SLATE_DISPLAY_TZ):
    try:
        from zoneinfo import ZoneInfo
        local = dt.astimezone(ZoneInfo(tz))
        return local, (local.strftime('%Z') or 'CT')   # CST or CDT
    except Exception:
        return dt, 'UTC'                                # say so, don't lie

def format_kickoff(iso_str, tbd=False, tz=SLATE_DISPLAY_TZ, long=False):
    if tbd:
        if long and iso_str:                            # weekday from the RAW DATE
            day = datetime.date.fromisoformat(str(iso_str)[:10])
            return f"{day.strftime('%A')} · time TBD"
        return 'TBD'
    dt = datetime.datetime.fromisoformat(str(iso_str).replace('Z', '+00:00'))
    local, label = _to_display_tz(dt, tz)
    pattern = '%A at %I:%M %p' if long else '%a %I:%M %p'
    return local.strftime(pattern).replace(' 0', ' ') + f' {label}'
```

Five details, each a real bug if dropped. The first three are inherited
from revision 1; **the last two are new and were found in the Central
move**:

1. **A TBD game still carries a placeholder timestamp** (typically
   midnight UTC). Render it raw and you show a confident, wrong kickoff.
   Check the flag first.
2. **For a TBD game, take the weekday from the raw date string, never from
   a timezone conversion.** Midnight UTC converts to the *previous
   evening*, so a Saturday game reads "Friday". This gap is **wider in
   Central than Eastern** — six hours, not five — so moving off ET makes
   this trap easier to hit, not harder.
3. `.replace(' 0', ' ')` strips the leading zero: `08:00 PM` → `8:00 PM`.
   Apply it to the *time* portion, before appending the zone label, so a
   label containing a ` 0` can't be damaged.
4. **Derive the zone abbreviation with `%Z`, don't hardcode it.** A season
   straddles the DST boundary, so one fixed label is wrong for part of
   every season (CBB: November is CST, the March/April tournament is CDT).
   Every game on a given date shares one abbreviation, so a page never
   shows a mix. The NFL season straddles it in the other direction — a
   September kickoff is EDT/CDT, a January playoff game is EST/CST.
5. **Add `tzdata` to `requirements.txt`.** These apps run on Windows,
   which ships no system tz database, so `zoneinfo.ZoneInfo()` *raises*
   there without it. A silent `except: pass` fallback would render every
   kickoff hours off while still labelling it correctly — the worst
   possible failure for a schedule, because nothing about the output looks
   wrong. Make the fallback say `UTC`.

---

## 4. The UI technique: a keyed container as a styled card

**This is the core trick of the whole tab. Understand it before editing.**

The card must contain real `st.button` widgets (§6 explains why), so it
cannot be one raw-HTML block. But Streamlit gives you no handle to style a
container… unless you give it a key:

```python
with st.container(key=f"gs_card_{idx}"):
    st.markdown(_card_html(idx, row, dark_mode), unsafe_allow_html=True)
    b1, b2 = st.columns(2)
    ...
```

`st.container(key="x")` renders with the CSS class **`st-key-x`**
(Streamlit's generator: `"st-key-" + key` with every character outside
`[a-zA-Z0-9_-]` replaced by `-`). So a substring attribute selector styles
every card at once:

```css
div[class*="st-key-gs_card_"] { /* card shell */ }
div[class*="st-key-gs_card_"]:hover { /* lift + accent border */ }
```

Scoping every rule to that prefix keeps it from leaking into other tabs'
containers. Requires Streamlit ≥ 1.44.

### Getting per-card values onto a Streamlit-owned element

The card's top accent bar is a gradient of the *two teams' real colors*.
That lives on the container's `::before`, but the container is
Streamlit-owned — there's no inline `style` attribute to set.

Solution: the card's own markdown emits a one-line `<style>` scoped to its
key class, declaring CSS custom properties the stylesheet reads.

```python
f"<style>.st-key-gs_card_{idx}{{--gs-a:{away_color};--gs-b:{home_color};}}</style>"
```

```css
div[class*="st-key-gs_card_"]::before {
    content: ''; position: absolute; top: 0; left: 0; right: 0; height: 3px;
    background: linear-gradient(90deg, var(--gs-a, #565d8c) 0%, var(--gs-a, #565d8c) 48%,
                                       var(--gs-b, #565d8c) 52%, var(--gs-b, #565d8c) 100%);
}
```

Note the fallback in each `var()` — a team with no color degrades to the
neutral outline instead of rendering an invalid gradient.

**Belt and braces:** each team *row* also carries its color inline
(`style='--gs-color:#BB0000'`), so the per-row accents survive even if the
container class ever changes. Only the thin top bar depends on the keyed
`<style>`.

**Emit the `<style>` tag only when there is at least one real color.** An
empty `.st-key-gs_card_0{}` is harmless but an unvalidated one is not —
see §8.5.

### Card markup structure

```html
<style>.st-key-gs_card_0{--gs-a:#0c2340;--gs-b:#00274c;}</style>
<div class='gs-meta'>
  <span class='gs-date'>04/06/2026</span><span class='gs-dot'>·</span>
  <span>Monday at 7:50 PM CDT</span><span class='gs-dot'>·</span>
  <span>Lucas Oil Stadium (neutral)</span><span class='gs-dot'>·</span>
  <span class='gs-tv'>TBS</span>
</div>
<div class='gs-headline'>National Championship</div>
<div class='gs-team gs-lost' style='--gs-color:#0c2340;'>
  <span class='gs-side'>AWAY</span>
  <img class='gs-logo' src='https://...' alt=''>
  <span class='gs-rank'>#2</span>
  <span class='gs-name'>UConn</span>
  <span class='gs-conf'>Big East</span>
  <span class='gs-score'>63</span>
</div>
<div class='gs-team gs-won' style='--gs-color:#00274c;'>
  … <span class='gs-score'>69</span><span class='gs-win-flag'>W</span>
</div>
```

Row is a flexbox: `.gs-name` takes `flex: 1 1 auto` so it pushes
conference/score/flag to the right edge; everything else is `flex: 0 0`.

**State classes:** `gs-won` (tinted background, accent-colored score, `W`
pill) / `gs-lost` (dimmed name) / neither. **A tie gets neither** — §8.4.

**Escape everything.** Real team and venue names contain ampersands (`Texas
A&M`, `M&T Bank Stadium`). Use `html.escape`, and `quote=True` for
attribute values like the logo `src`.

---

## 5. Logos

### Where they come from

**Look in the schedule data first.** CFB Scholar found logo URLs sitting
unused in its `team_info` parquet. CBB Scholar found them sitting *on every
schedule row* — `home_logo` / `away_logo`, full ESPN CDN URLs, already
`https`, zero nulls on the home side across 6,318 games. That made a
separate `team_logo_map` unnecessary: the logo travels with the game.

Check `nflverse`'s schedule/teams frames the same way before building a map.

### The transform CBB didn't need but you might

CFB's stored URLs were `http://` — 655 of 656 rows. On an HTTPS-served
page, browsers block mixed-content images **silently**: the image never
appears, and there is no error in the console, the logs, or Python. CBB's
were already https (measured: 0 of 6,318 rows), but the rewrite costs
nothing and the failure mode is invisible, so keep it:

```python
str(url).replace('http://', 'https://')
```

Two design points to keep wherever the map lives:

- **A team with no mark is omitted from the map, not mapped to `None`.**
  Every call site does `.get(team)` and renders nothing on a miss; a `None`
  *value* would sail through that check and emit a broken `<img>`.
- **The string `'nan'` is treated as missing.** A parquet round-trip turns
  a missing value into that string, which would otherwise become a literal
  `src='nan'`.

### Dark variants — **and the light-mode correction**

Revision 1 said flatly: *use the dark variant, every surface in these apps
is dark.* **That is now wrong.** CBB Scholar has a light mode. ESPN's
`500-dark` mark is designed *for* dark backgrounds and reads as a smudge on
a pale one.

**Carry both variants and choose at render time from the active theme:**

```python
def dark_logo_variant(url):
    s = str(url or '')
    return s.replace('/500/', '/500-dark/') if '/500/' in s else None

# in the card renderer
logo = row['Away Logo Dark'] if dark_mode else row['Away Logo']
logo = logo or row['Away Logo']          # fall back, never emit a guess
```

Check whether NFL Scholar has a light mode before deciding. If it doesn't,
hardcoding the dark variant is still fine — just leave a comment saying
which assumption you're relying on.

### Sport-specific URL patterns — VERIFY, don't assume

The `ncaa/500-dark/{id}` pattern is verified for college football and
reused for college basketball (ESPN keys both off the same numeric team id
in the same `ncaa` directory). **NFL is different**: logos are keyed by
team abbreviation rather than a numeric id, and the dark-variant path
segment differs. Before wiring them in:

1. Check whether the target app's existing team source already carries
   logo URLs. **Look first — this is free if so.**
2. Otherwise resolve the real pattern by fetching one known team and
   confirming a 200 and an image content-type.
3. Verify the dark variant exists for that league; fall back to the
   standard mark if not.

**A cheap way to check before writing code:** generate a standalone HTML
page rendering both variants for ~16 stress-test teams on the app's real
card background, with a script that counts how many images loaded. It
takes one file, and it distinguishes "didn't load" from "loaded but is
invisible against the background" — the failure mode that would otherwise
fool you. Give failed images a red outline.

### Rendering

```css
.gs-team .gs-logo {
    height: 24px; width: 24px; object-fit: contain; flex: 0 0 24px;
    filter: drop-shadow(0 1px 3px rgba(0, 0, 0, 0.55));
}
```

`object-fit: contain` prevents distortion on non-square marks. `flex: 0 0`
stops a long team name from squeezing it. The drop-shadow lifts marks whose
own edges are near-black off a dark surface — **invert it for light mode**,
where a black halo only smudges. `alt=''` is intentional: the team name is
the very next element, so alt text would read it twice.

**Logo sits beside the color stripe, not instead of it.** Both were mocked
up; keeping both was the explicit choice.

---

## 6. Cross-tab linking — and the constraint that shapes the whole card

Each card carries buttons that switch tabs *and* pre-seed the destination's
own widget state, so the target opens already pointed at this game instead
of asking the user to re-pick both teams.

### 6.1 What the buttons should actually do

Revision 1 described three generic buttons. **CBB's shape is better and is
worth copying**: two buttons, one per team, each seeding *both* sides of
the destination in complementary roles.

```python
st.button(
    f"{abbrev} players", key=f"gs_go_away_{idx}", width="stretch",
    disabled=not ready,
    help=f"Open Matchup Analyzer: {away}'s players vs {home}'s defense",
    on_click=switch_tab, args=(TAB_MATCHUP,),
    kwargs={'ma_season': season,
            'ma_player_team': away_bridged,      # this team's offense
            'ma_def_team': home_bridged},        # the opponent's defense
)
```

…and a mirror button for the same game from the other side. That reads as
a real question ("show me Duke's guys against what UNC's defense does")
rather than a generic "open this matchup", and it uses the fact that the
destination tab has two independent pickers.

**Map this onto NFL Scholar's actual tabs before copying the labels.**

### 6.2 The rule you must not break

**`switch_tab` has to run as an `on_click` callback. It cannot be called
from the main script body.**

The app's top-level tabs are `st.tabs(TAB_LABELS, key="active_tab",
on_change="rerun")`. Streamlit raises `StreamlitAPIException` if
`st.session_state["active_tab"]` is reassigned during the same script run
that already read it to render those tabs — which `app.py` did, before your
tab's `render()` was reached. A callback runs in the *pre-script* phase,
before `st.tabs()` executes for the next run, so the assignment is legal
there.

**This single constraint is why the card is a keyed `st.container` styled
with CSS rather than one block of raw HTML.** Raw HTML cannot fire a Python
callback. If you "simplify" the card into pure HTML with `<a>` tags, you
lose the pre-seeding — which is the entire point of the tab.

### 6.3 Seeding through sticky wrappers — **new, and it has a sharp edge**

Revision 1 said to seed the destination widgets' `key=` values directly,
and warned that the seeded value must be a valid option or Streamlit
raises. **CBB Scholar wraps every widget in "sticky" helpers** (they mirror
each widget's value into a second, non-widget session_state key, because
Streamlit prunes a widget-scoped key whenever its tab isn't rendered), and
that changes the correct move — into two different correct moves with
*opposite* failure modes:

```python
def set_sticky_value(key, value):
    """Target widget is on the CURRENTLY OPEN tab (e.g. prev/next-day
    arrows driving this tab's own date picker). Its widget key still
    exists and Streamlit prefers it over the wrapper's computed
    index=/value=, so BOTH must be written."""
    st.session_state[f"_sticky__{key}"] = value
    st.session_state[key] = value

def seed_sticky_value(key, value):
    """Target widget is on a tab that is NOT open (cross-tab hand-off).
    Write ONLY the mirror and clear any lingering widget key."""
    st.session_state[f"_sticky__{key}"] = value
    st.session_state.pop(key, None)
```

**Why the asymmetry matters:** writing the raw widget key across a tab
boundary makes Streamlit *raise* on the next run whenever the seeded value
isn't a member of the destination selectbox's options — which is not rare,
because seeding a matchup seeds a team, the destination's option list comes
from a different data source's spelling of the league, and the user may
change the season out from under it. The mirror has no such problem: every
sticky wrapper checks `remembered in options` first and falls back to its
own default. A value that doesn't resolve degrades to "opened on the
default" instead of a traceback.

**If NFL Scholar doesn't have sticky wrappers**, seed the widget keys
directly as revision 1 said — but then you must guarantee validity, so
resolve the team name *before* seeding and disable the button if it
doesn't resolve.

### 6.4 Disable, don't guess

If a team can't be bridged to the destination's namespace, **render the
button disabled with a `help=` explaining why**. The alternative —
seeding a best-guess name — opens the destination on the wrong team with
no indication anything went wrong.

### 6.5 Button labels

Buttons share one card row, so labels use the team **abbreviation** (`"BOIS
players"`), with the full name on the line directly above and the full
sentence in `help=`. The fallback for a team with no abbreviation trims at
a **word boundary**, because a hard character slice turned `Delaware State`
into `Delaware Sta`, which reads as a typo.

---

## 7. Layout, scale and performance

```python
_CARDS_PER_ROW = 2

for start in range(0, len(games), _CARDS_PER_ROW):
    cols = st.columns(_CARDS_PER_ROW)
    for offset, col in enumerate(cols):
        idx = start + offset
        if idx >= len(games):
            continue
        with col:
            _render_card(idx, games.iloc[idx], season, bridge, dark_mode)
```

**Row-by-row, not column-by-column.** Filling column 0 with the first half
and column 1 with the second half makes the two halves of the screen scroll
out of chronological order.

**Streamlit allows exactly one level of column nesting**, and this design
spends it: grid column → button row. Nothing inside a card may open further
columns. If you need a third level, restructure — don't nest.

### Measured cost, all three sports

| | Games in view | Render |
|---|---|---|
| CFB | 46 (a full week) | ~1.0s, ~139 buttons |
| CBB | 24 (one page of a 155-game date) | **0.13s warm** |
| NFL | ~16 (a full week) | trivial — no paging needed |

Revision 1 flagged CBB's 300+ game days as untested. **Measured: the real
peak is 169 games on a single date** (2025-11-03), against CFB's worst case
of 46. That needed paging (`_CARDS_PER_PAGE = 24`) and load-bearing filters
(conference, ranked-only, analyzable-only).

**NFL needs none of that.** A full week is ~16 games. Drop the paging, drop
the conference filter, and let the week selector be the only control. If
you keep paging "just in case", you add a widget that can never do anything
— the same mistake §2.5 warns about for the analyzable filter.

---

## 8. Gotchas — every one of these was a real bug

### 8.1 Don't take the date off the raw timestamp — **new, and it bit hard**

Sources stamp games in UTC. A night game in the US is *already the next day*
in UTC, so slicing the first 10 characters attributes every evening game to
the wrong day. Real symptom: `04/07/2026 · Monday at 7:50 PM CDT` — a card
contradicting itself, since 04/07 was a Tuesday. It affected most of the
file, and it survived code review.

```python
def _local_date(iso_str, tbd=False):
    raw = str(iso_str)[:10]
    if tbd:
        return raw            # midnight-UTC placeholder converts BACKWARD
    dt = _slate_timestamp(iso_str)
    local, label = _to_display_tz(dt)
    return raw if label == 'UTC' else local.date().isoformat()
```

**Two corollaries:**

- **A TBD game must keep the raw slice.** Its placeholder timestamp is
  midnight UTC, which converts back to the previous evening — the same trap
  as §3.3 detail 2, one layer down.
- **Filter on the derived date, not on the source's own date column.**
  CBB's file carries an *Eastern* `game_date`; the app displays Central.
  Selecting by one zone's calendar and displaying the other's reintroduces
  exactly the same contradiction, just for fewer games. Cross-check both:
  after fixing, CBB's derived Central date agreed with the file's own
  Eastern date on all 6,318 games (the latest tip all year was 10:59 PM CT),
  which is *why* the bug was invisible — but the coupling is still wrong and
  the fix is one line.

### 8.2 An unplayed game's score is `NaN`, not `None`

The loader writes `None`, but **pandas promotes an int column holding any
missing value to float64 and turns that `None` into `NaN`** — and `NaN is
not None` evaluates `True`. A `is not None` guard therefore prints `nan` as
the score on every upcoming game.

```python
played = bool(pd.notna(away_pts) and pd.notna(home_pts))
winner = row.get('Winner')
winner = winner if (winner is not None and pd.notna(winner)) else None
```

**Requirement: an unplayed game emits no score node at all.** Not `--`, not
`NA`, not an empty span. A blank right edge is the honest reading of
"hasn't happened yet"; a placeholder reads as missing data.

### 8.3 Gate scores on STATUS, never on presence — **new**

The obvious approach ("does this row have a score?") is wrong in both
directions, and revision 1 didn't cover it:

- **ESPN sends `"0"` for a game that hasn't kicked off**, not null. So
  "has a score" is true for every future game on the board.
- **A postponed or canceled game reaches a `post` state carrying 0-0** and
  would otherwise render as a real final. 18 such rows in one CBB season.

```python
played = status_name.eq('STATUS_FINAL')
live   = state.eq('in')
show_score = played | live          # a live running score is real
```

Also render the status where the kickoff time would go for a postponed
game, rather than advertising a start time it will never have.

### 8.4 A tie must not dim both teams

`is_winner` has to stay **`None`** when there's no winner, not collapse to
`False`. Pass `False` and both rows get `gs-lost` and both teams render as
losers.

```python
(winner == away) if winner else None     # None, not False
```

### 8.5 Validate colors before interpolating them into CSS — **new**

Team colors go straight into a `<style>` block and an inline `style`
attribute. Validate to a real 6-digit hex and drop anything else:

```python
def _hex_color(value):
    s = str(value or '').strip().lstrip('#')
    if len(s) != 6 or not re.fullmatch(r'[0-9a-fA-F]{6}', s):
        return None
    return f"#{s.lower()}"
```

A malformed value would otherwise break the card's whole style block
silently — and the `var(…, fallback)` in §4 only saves you if the property
is *absent*, not if it's present and garbage.

### 8.6 Don't sort on a display string

Keep ISO `Date` alongside `Date Display`, **and sort times on the real
timestamp**. `"Mon 9:00 AM"` sorts *after* `"Mon 10:00 AM"` as text,
because `'9' > '1'`. This app has a related scar: sorting star ratings by
their glyph string sorts wrong, because `☆` U+2606 > `★` U+2605.

```python
order = pd.to_datetime(start, errors='coerce', utc=True, format='mixed')
out = out.assign(_order=order).sort_values(['Date', '_order']).drop(columns='_order')
```

### 8.7 Source schemas drift between seasons — **new**

Measured across four published CBB season files: `broadcast`/`highlights`
exist only in 2025–26, `venue_capacity` only in 2023, `away_non_div1_team`
only in 2025. Indexing any of those directly hard-crashes the tab on a
perfectly good season.

```python
def _col(df, name, default=None):
    if name in df.columns:
        return df[name]
    return pd.Series([default] * len(df), index=df.index)
```

`nflverse`'s schedule frame has gained columns over the years too. Use the
accessor everywhere; it costs nothing.

### 8.8 Sentinel values that aren't null — **new**

ESPN publishes **rank 99 for an unranked team** rather than omitting the
field: 5,744 of 6,318 rows. Rendered raw, every card claims both teams are
99th in the country. Not applicable to NFL (no poll), but **the class is**:
check any "rank"/"seed"/"order" field's actual distribution before trusting
it to be null when absent. Print a `value_counts()` — it takes one line.

### 8.9 `.stButton > button` silently matches nothing when the button has `help=`

Streamlit wraps a button that has a tooltip in **two extra `<span>`s**
(`stTooltipHoverTarget` / `stTooltipIcon`), so the common direct-child
selector matches nothing. No error, no warning — the CSS just does nothing.

Especially deceptive because Streamlit's *own* default hover is an
accent-colored border, so the buttons look styled while every custom rule
is dead.

```css
div[class*="st-key-gs_card_"] .stButton button { }   /* descendant, not > */
```

### 8.10 Streamlit's runtime CSS beats an equally-specific rule

Streamlit injects its button styles with emotion **at runtime, after** the
app's injected `<style>` block. An equally-specific override loses the
cascade and silently does nothing. `!important` is required on
`background` / `border-color` / `color`.

**Verify a style override actually landed by reading `getComputedStyle` in
a browser, not by looking at a screenshot.** Both 8.9 and 8.10 looked fine
in a screenshot and were dead in the DOM.

### 8.11 Clear every cache layer, not just the download — **new**

If you cache both the raw download and a normalized derivative,
`refresh_slate()` must clear both. Clearing only the download leaves every
view still served from the stale normalized copy — a refresh button that
visibly does nothing.

### 8.12 Testing this tab with `AppTest`

`streamlit.testing.v1.AppTest` **cannot reliably simulate a tab switch
followed by another widget interaction** with this `key="active_tab"`-bound
tabs pattern — a subsequent `.set_value().run()` silently resets
`active_tab` to index 0. Harness limitation, not a real-user bug.

Workaround: verify button wiring by calling the card renderer directly with
`st.button` monkeypatched to capture its arguments, then assert on the
captured `args`/`kwargs`.

**A single click *does* work**, though, and is worth one end-to-end test:
`at.button[i].click().run()` then assert on `session_state`. That's how
CBB confirmed the whole chain including the name bridge.

**Also new:** when driving a sticky-wrapped widget from a test, set **both**
the widget key and the `_sticky__` mirror. Setting only the mirror looks
like a broken filter and isn't — see §6.3.

Run **one subprocess per tab** when smoke-testing all tabs. Ten `AppTest`
boots back-to-back in one process died partway through inside pyarrow's
reader, which presents as a hang rather than a failure.

---

## 9. Tests worth porting

CBB Scholar's `tests/test_game_slate.py` is 54 tests and asserts on
rendered HTML — unusual for this codebase, and justified: the card's
requirements *are* visual, and the important ones fail silently. A card
printing `nan` where a score goes still renders fine and raises nothing.

Port these cases:

- **Played game:** both scores render; winner marked; loser marked; exactly
  one `W` flag; date is `MM/DD/YYYY`; kickoff names the weekday; each team
  carries its own color; the keyed `<style>` binds both colors.
- **Unplayed game:** no score node at all; **the string `nan` never appears
  anywhere in the output**; neither team marked won/lost. Build the fixture
  with **score `0`, not null** (§8.3).
- **Postponed game:** no score node; says "Postponed" where the kickoff
  would go.
- **Live game:** running score renders; no winner marked.
- **Tie:** both scores render; neither team dimmed.
- **Dates and times:** the date is the *local* day, not the UTC slice
  (§8.1); a TBD game keeps the raw date; games order by real time, not the
  display string; the zone label matches the zone in force (one CST case
  and one CDT case).
- **Markup safety:** `Texas A&M` / `M&T Bank Stadium` escape correctly; a
  missing color falls back to the neutral outline; a malformed color string
  is rejected rather than interpolated; a missing venue is omitted rather
  than printed as `nan`.
- **Schema drift:** dropping optional columns from the fixture doesn't
  crash (§8.7).
- **Button labels:** abbreviation used when available; long name truncated
  at a word boundary; short names untouched.
- **Logos:** both render; the color stripe survives alongside them; a card
  with no logos renders text-only; a map missing one team drops only that
  one; light mode uses the standard mark and dark mode the dark one.
- **Team bridge:** an unresolvable team is omitted, never mapped to `None`;
  an empty destination team list yields an empty bridge.
- **Button wiring:** each button seeds its own team plus the opponent in
  the complementary role; an unbridged team disables both buttons rather
  than seeding a null; seeded names are the *destination's* spelling.
- **`switch_tab`:** seeds the mirror and clears the widget key (§6.3).
- **Two sources agree:** the live parser and the file parser produce the
  same column set. One assert, catches a whole class of drift.

The fixture should build rows with **float/NaN scores**, matching what
pandas actually hands the renderer.

---

## 10. Port checklist

1. [ ] **Survey sources before choosing one** (§0.1). Check what's already
       published free before wiring a metered API.
2. [ ] **Download one real season file and print ten rows** (§0.3). Check
       `value_counts()` on any rank/status/flag field.
3. [ ] Decide whether NFL needs the two-source ladder at all (§0.2) — test
       whether the schedule file carries future games with kickoff times.
4. [ ] Implement `load_slate` returning §2.1's exact column names.
5. [ ] Implement `slate_weeks` / `slate_source` / `refresh_slate`; keep the
       two-level default fallback (§2.5).
6. [ ] Port `format_kickoff` (with `long=`) and the local-date derivation;
       keep **all five** timezone details from §3.3, including `tzdata` in
       `requirements.txt`.
7. [ ] **Delete the "analyzable game" filter** (§2.5) and the paging and
       conference filters (§7). NFL needs none of them.
8. [ ] Check whether the schedule rows already carry logo URLs (§5); decide
       the dark-variant question against whether the app has a light mode.
9. [ ] Verify the NFL logo URL pattern for real — it is **not** the college
       one (§5).
10. [ ] Copy the `.gs-*` CSS block; re-point color tokens at the target
        app's `THEME` (only the accent pair differs between these apps).
11. [ ] Copy `game_slate.py`; adjust the period selector to weeks and the
        button destinations to the target app's real tabs.
12. [ ] Confirm `switch_tab` exists and is used as a callback; check
        whether the app has sticky wrappers and seed accordingly (§6.3).
13. [ ] Build the team-name bridge if the namespaces differ (§2.4); disable
        buttons that can't resolve (§6.4).
14. [ ] Add the tab to `TAB_LABELS` **and** the tab-module list, keeping
        them index-for-index. Decide deliberately where it sits — it's a
        launchpad, which argues for first.
15. [ ] Port the tests from §9.
16. [ ] Verify in a real browser: hover a card, hover a button, click every
        destination, check a week containing unplayed games, and toggle
        light/dark if the app has both.
17. [ ] Confirm with `getComputedStyle` that the button rules actually
        applied (§8.10).

---

## 11. Deliberate design decisions — don't "fix" these

| Decision | Why |
|---|---|
| Unplayed games show **no** score node | A placeholder reads as missing data for a game that hasn't happened. |
| Scores gate on **status**, not presence | ESPN sends `"0"` for unplayed games and 0-0 for postponed ones (§8.3). |
| Logo **beside** the color stripe | Both mocked up; keeping both was the explicit choice. |
| Logo variant chosen at **render** time | The app has light and dark modes; one baked-in variant is wrong in one of them. |
| Buttons quiet until hovered | Dozens of cards × 2 buttons would otherwise read as competing calls to action. |
| Card is a keyed container, not raw HTML | Raw HTML cannot fire the `on_click` callback `switch_tab` requires (§6.2). |
| Cross-tab seeding writes the **mirror** only | Guarded by an `in options` check; the raw widget key raises instead (§6.3). |
| An unbridgeable team **disables** its button | Better than opening the destination on the wrong team silently. |
| Two cards per row | Wide enough for full team names + a button row; halves the scroll. |
| ISO `Date` kept beside `Date Display` | Ordering must never depend on a display choice (§8.6). |
| Zone label derived with `%Z` | A season straddles the DST boundary; one hardcoded label is wrong half the year. |
