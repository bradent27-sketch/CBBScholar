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
| Matchup Analyzer | CollegeBasketballData.com API — `/ratings/adjusted`, `/stats/team/season`, `/games`, `/games/players`, `/teams/roster` | **Live** — simple projection, not a simulation. Team Defense's positional breakdown is built from `/games` + `/games/players` scoped to each team's actual opponents (not a full-D-I pull) — see HANDOFF.md §3 |
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
