"""
Game Slate tab: one card per game on a chosen date, each one a launchpad
into the Matchup Analyzer with both teams already filled in.

It answers the first question of a real prep session - who is playing -
and then hands a chosen game to the app's other tools. It is a LAUNCHPAD,
NOT A REPORT: nothing here analyzes anything, it routes.

WHY CARDS AND NOT AN st.dataframe (don't undo this). Two structural
reasons, both already established elsewhere in this app:

1. Streamlit's dataframe is a <canvas> widget - confirmed repeatedly in
   this codebase (see ui.styling.render_responsive_table's docstring and
   the chart-hover comment in inject_theme). It cannot hold a button, a
   link, or any per-row control. Acting on a game from a table would mean
   re-picking it from a SEPARATE dropdown underneath - the visitor selects
   a row visually, then re-selects the same game in a second widget. That
   second selection is exactly what this design deletes.
2. A table gives every column equal visual weight, so each game becomes a
   horizontal scan. A card can rank information: teams and score big,
   metadata small.

Ported from CFB Scholar's weekly_slate.py, with the sport-specific parts
rebuilt rather than translated - college basketball has no "weeks" (147
game DATES in a real season, not 15 weeks), and its slates are far bigger
than football's (the 2026 season peaked at 169 games on a single day,
against CFB Scholar's worst case of 46), which is why the filters and
paging below are load-bearing rather than decorative.
"""
import datetime
import html

import pandas as pd
import streamlit as st

from config import AVAILABLE_SEASONS, TAB_MATCHUP, TAB_PLAYER_SEARCH
from data.loaders import (
    current_cbb_season, load_slate, slate_dates, default_slate_date, slate_source,
    refresh_slate, slate_team_bridge, load_game_box,
)
from ui.components import (
    switch_tab, set_sticky_value, sticky_date_input,
    sticky_selectbox, sticky_multiselect, sticky_checkbox,
)

# Two per row: wide enough for full school names plus a two-button row,
# and it halves the scroll on a slate this size.
_CARDS_PER_ROW = 2

# A big CBB date really is ~170 games. Rendering all of them is ~340
# buttons and a very long page, so the slate pages. This is a display
# cap only - every filter below applies to the WHOLE day first, so paging
# never hides a game a filter was supposed to surface.
_CARDS_PER_PAGE = 24


def _abbrev(row, side):
    """Short label for a card button. Prefers the source's own
    abbreviation; falls back to trimming the school name at a WORD
    boundary, never mid-word - a hard character slice turned "Delaware
    State" into "Delaware Sta", which reads as a typo rather than an
    abbreviation."""
    abbr = row.get(f'{side} Abbr')
    if abbr and pd.notna(abbr) and len(str(abbr)) <= 5:
        return str(abbr).upper()
    name = str(row.get(side) or '')
    if len(name) <= 12:
        return name
    words = name.split()
    out = ''
    for w in words:
        if out and len(out) + 1 + len(w) > 12:
            break
        out = f"{out} {w}".strip()
    return out or name[:12]


def _logo_for(row, side, dark_mode):
    """This app has BOTH a dark and a light theme, so the logo variant is
    chosen here rather than baked into the data (CFB Scholar, where this
    came from, could hardcode the dark mark precisely because every surface
    in it is dark). ESPN's `500-dark` mark is designed FOR dark backgrounds
    and reads as a smudge on a pale one; the standard mark is the right
    choice in light mode. Falls back to the standard mark whenever a dark
    variant couldn't be derived."""
    if dark_mode:
        return row.get(f'{side} Logo Dark') or row.get(f'{side} Logo')
    return row.get(f'{side} Logo')


def _team_row_html(row, side, is_winner, show_score, dark_mode):
    """
    One team's row inside a card.

    `is_winner` is deliberately three-valued: True / False / None. It must
    stay None when there's no winner rather than collapsing to False -
    passing False marks BOTH teams as losers, which is what a tie, an
    unplayed game and a postponement would all render as.

    Everything interpolated here is escaped. Real school and venue names
    contain ampersands (Texas A&M, M&T Bank Stadium), and the color and
    logo values land inside quoted HTML attributes.
    """
    state_cls = ''
    if is_winner is True:
        state_cls = ' gs-won'
    elif is_winner is False:
        state_cls = ' gs-lost'

    color = row.get(f'{side} Color')
    style = f" style='--gs-color:{html.escape(str(color), quote=True)};'" if color else ''

    logo = _logo_for(row, side, dark_mode)
    logo_html = (
        f"<img class='gs-logo' src='{html.escape(str(logo), quote=True)}' alt=''>"
        if logo and pd.notna(logo) else ''
    )

    rank = row.get(f'{side} Rank')
    rank_html = f"<span class='gs-rank'>#{int(rank)}</span>" if pd.notna(rank) else ''

    conf = row.get(f'{side} Conf')
    conf_html = f"<span class='gs-conf'>{html.escape(str(conf))}</span>" if conf and pd.notna(conf) else ''

    # An unplayed game emits NO score node at all - not '--', not 'NA', not
    # an empty span. A blank right edge is the honest reading of "hasn't
    # happened yet"; a placeholder reads as missing data. This is also the
    # NaN trap: pandas promotes an int column holding any missing value to
    # float64 and turns None into NaN, and `NaN is not None` is True - so an
    # `is not None` guard here would print the literal string "nan" as the
    # score of every upcoming game.
    pts = row.get(f'{side} Pts')
    score_html = ''
    flag_html = ''
    if show_score and pd.notna(pts):
        score_html = f"<span class='gs-score'>{int(pts)}</span>"
        if is_winner is True:
            flag_html = "<span class='gs-win-flag'>W</span>"

    return (
        f"<div class='gs-team{state_cls}'{style}>"
        f"<span class='gs-side'>{side.upper()}</span>"
        f"{logo_html}{rank_html}"
        f"<span class='gs-name'>{html.escape(str(row.get(side) or ''))}</span>"
        f"{conf_html}{score_html}{flag_html}"
        f"</div>"
    )


def _card_html(idx, row, dark_mode):
    """The card's non-interactive body. The buttons are real Streamlit
    widgets rendered separately inside the same keyed container - see
    _render_card."""
    away_color = row.get('Away Color')
    home_color = row.get('Home Color')
    # A one-line <style> scoped to this card's own key class, declaring the
    # custom properties the stylesheet's ::before gradient reads. This is
    # the only way to get per-card values onto a Streamlit-OWNED element:
    # the container has no inline style attribute to set. Only the thin top
    # bar depends on it - each team row also carries its color inline, so
    # the per-row accents survive even if the container class ever changes.
    decls = []
    if away_color:
        decls.append(f"--gs-a:{html.escape(str(away_color), quote=True)};")
    if home_color:
        decls.append(f"--gs-b:{html.escape(str(home_color), quote=True)};")
    style_tag = f"<style>.st-key-gs_card_{idx}{{{''.join(decls)}}}</style>" if decls else ''

    played = bool(row.get('Played'))
    live = bool(row.get('Live'))
    winner = row.get('Winner')
    winner = winner if (winner is not None and pd.notna(winner)) else None

    meta = [f"<span class='gs-date'>{html.escape(str(row.get('Date Display') or ''))}</span>"]
    if live:
        detail = row.get('Status Detail')
        label = str(detail) if detail and pd.notna(detail) else 'Live'
        meta.append(f"<span class='gs-live'>{html.escape(label)}</span>")
    else:
        tip = row.get('Tipoff Long')
        # A game that never happened says so where the tip time would go,
        # rather than advertising a start time it will never have.
        if not played and str(row.get('Status Detail') or '') in ('Postponed', 'Canceled', 'Cancelled'):
            tip = row.get('Status Detail')
        if tip and pd.notna(tip):
            meta.append(f"<span>{html.escape(str(tip))}</span>")

    venue = row.get('Venue')
    if venue and pd.notna(venue):
        venue_txt = f"{venue} (neutral)" if row.get('Neutral Site') else str(venue)
        meta.append(f"<span>{html.escape(venue_txt)}</span>")

    tv = row.get('Broadcast')
    if tv and pd.notna(tv):
        meta.append(f"<span class='gs-tv'>{html.escape(str(tv))}</span>")

    dot = "<span class='gs-dot'>·</span>"
    meta_html = f"<div class='gs-meta'>{dot.join(meta)}</div>"

    headline = row.get('Headline')
    headline_html = (
        f"<div class='gs-headline'>{html.escape(str(headline))}</div>"
        if headline and pd.notna(headline) else ''
    )

    show_score = played or live
    away_win = (winner == row.get('Away')) if winner else None
    home_win = (winner == row.get('Home')) if winner else None

    return (
        f"{style_tag}{meta_html}{headline_html}"
        f"{_team_row_html(row, 'Away', away_win, show_score, dark_mode)}"
        f"{_team_row_html(row, 'Home', home_win, show_score, dark_mode)}"
    )


def _render_card(idx, row, season, bridge, dark_mode):
    """
    One matchup card: a KEYED st.container (so CSS can style it - see the
    .gs-* block in ui/styling.py) holding the markup above plus two real
    buttons.

    The two buttons are the point of the tab. Each one opens the Matchup
    Analyzer with THAT team's players in the PLAYER panel and the OTHER
    team in TEAM DEFENSE - i.e. "show me Duke's guys against what North
    Carolina's defense does" - with the mirror button for the same game
    from the opposite side.

    Streamlit allows exactly ONE level of column nesting, and this design
    spends it: the outer slate grid column, then this button row. Nothing
    inside a card may open further columns.
    """
    away, home = row.get('Away'), row.get('Home')
    # The destination's pickers are keyed on CBBD's school names; every
    # name here is ESPN's. A team that doesn't bridge gets a disabled
    # button saying so, rather than a live button that silently opens the
    # Matchup Analyzer on the wrong team (or its default one).
    away_cbbd, home_cbbd = bridge.get(away), bridge.get(home)

    # A completed game gets a third control. Deliberately only when the
    # schedule row says a box actually exists (`Has Box`) - a button that
    # opens an empty panel is worse than no button.
    has_box = bool(row.get('Played')) and bool(row.get('Has Box', True))
    with st.container(key=f"gs_card_{idx}"):
        st.markdown(_card_html(idx, row, dark_mode), unsafe_allow_html=True)
        cols = st.columns(3 if has_box else 2)
        b1, b2 = cols[0], cols[1]
        if has_box:
            with cols[2]:
                st.button(
                    "Box score", key=f"gs_box_{idx}", width="stretch",
                    help=f"Full box score for {away} {'vs' if row.get('Neutral Site') else '@'} {home}",
                    on_click=_open_box, args=(row.get('GameId'),),
                )
        for col, (team, opp, team_cbbd, opp_cbbd, side) in zip(
            (b1, b2),
            ((away, home, away_cbbd, home_cbbd, 'away'), (home, away, home_cbbd, away_cbbd, 'home')),
        ):
            with col:
                ready = bool(team_cbbd and opp_cbbd)
                if ready:
                    help_text = f"Open Matchup Analyzer: {team}'s players vs {opp}'s defense"
                else:
                    missing = team if not team_cbbd else opp
                    help_text = (
                        f"Couldn't match {missing} to a CollegeBasketballData.com team"
                        if bridge else
                        "Needs a CollegeBasketballData.com API key — see DATA_SOURCES.md"
                    )
                st.button(
                    f"{_abbrev(row, side.capitalize())} players",
                    key=f"gs_go_{side}_{idx}",
                    width="stretch",
                    disabled=not ready,
                    help=help_text,
                    # switch_tab MUST be an on_click callback, never called
                    # from this render body - see its docstring for the
                    # StreamlitAPIException that makes that a hard rule, and
                    # for why it's the reason this card is a keyed container
                    # rather than one block of raw HTML.
                    on_click=switch_tab if ready else None,
                    args=(TAB_MATCHUP,) if ready else None,
                    kwargs={
                        'ma_season': season,
                        'ma_player_team': team_cbbd,
                        'ma_def_team': opp_cbbd,
                    } if ready else None,
                )


# ---------------------------------------------------------------------------
# Box score panel (completed games only). Rendered FULL WIDTH above the card
# grid rather than inside a card: Streamlit's single level of column nesting
# is already spent inside a card (grid column -> button row), and a two-team
# box is unreadable at half width anyway.
# ---------------------------------------------------------------------------

# (label, made-column, attempted-column) for the shooting comparison rows,
# then (label, column, lower_is_better) for the counting ones.
_CMP_SHOOTING = [('FG', 'FGM', 'FGA', 'FG%'), ('3PT', '3PM', '3PA', '3P%'), ('FT', 'FTM', 'FTA', 'FT%')]
_CMP_COUNTS = [('Rebounds', 'REB', False), ('Assists', 'AST', False), ('Turnovers', 'TOV', True)]

_BOX_COLUMNS = [
    ('MIN', 'Minutes', False), ('PTS', 'Points', False), ('REB', 'Rebounds', False),
    ('AST', 'Assists', False), ('STL', 'Steals', True), ('BLK', 'Blocks', True),
    ('TO', 'Turnovers', False), ('PF', 'Fouls', True),
]


def _esc(value):
    return html.escape(str(value)) if value is not None and pd.notna(value) else ''


def _num(value, dash='—'):
    """Integer display for a stat, or an em dash. Never 'nan' - the same
    NaN-is-not-None trap the cards guard against (pandas promotes any
    column with a missing value to float64)."""
    return str(int(value)) if pd.notna(value) else dash


def _split_bar(a, b, color_a, color_b):
    """One head-to-head track. Each side takes its share of the pair, so
    the bar answers 'who won this category' at a glance. Equal values (and
    the 0-0 case) split evenly rather than collapsing to an empty track."""
    a = float(a) if pd.notna(a) else 0.0
    b = float(b) if pd.notna(b) else 0.0
    total = a + b
    share_a = 50.0 if total <= 0 else a / total * 100
    lead_a = ' bs-lead' if a > b else ''
    lead_b = ' bs-lead' if b > a else ''
    ca = html.escape(str(color_a or '#565d8c'), quote=True)
    cb = html.escape(str(color_b or '#565d8c'), quote=True)
    return (
        "<div class='bs-cmp-track'>"
        f"<div class='bs-cmp-bar{lead_a}' style='width:{share_a:.1f}%;background:{ca};'></div>"
        "<div class='bs-cmp-gap'></div>"
        f"<div class='bs-cmp-bar{lead_b}' style='width:{100 - share_a:.1f}%;background:{cb};'></div>"
        "</div>"
    )


def _comparison_html(away_row, home_row, away_color, home_color):
    rows = []
    for label, made, att, pct in _CMP_SHOOTING:
        av, ap = away_row.get(made), away_row.get(att)
        hv, hp = home_row.get(made), home_row.get(att)
        a_txt = f"{_num(av, '0')}-{_num(ap, '0')}"
        h_txt = f"{_num(hv, '0')}-{_num(hp, '0')}"
        a_pct, h_pct = away_row.get(pct), home_row.get(pct)
        if pd.notna(a_pct):
            a_txt += f"  {a_pct:.0f}%"
        if pd.notna(h_pct):
            h_txt = f"{h_pct:.0f}%  " + h_txt
        rows.append(
            "<div class='bs-cmp-row'>"
            f"<div class='bs-cmp-vals'><span>{html.escape(a_txt)}</span>"
            f"<span class='bs-cmp-label'>{label}</span>"
            f"<span>{html.escape(h_txt)}</span></div>"
            # Shooting bars compare PERCENTAGE, not makes: 21-68 and 21-55
            # are the same makes and very different games.
            + _split_bar(a_pct, h_pct, away_color, home_color) + "</div>"
        )
    for label, col, lower_better in _CMP_COUNTS:
        av, hv = away_row.get(col), home_row.get(col)
        suffix = " (fewer is better)" if lower_better else ""
        rows.append(
            "<div class='bs-cmp-row'>"
            f"<div class='bs-cmp-vals'><span>{_num(av)}</span>"
            f"<span class='bs-cmp-label'>{html.escape(label + suffix)}</span>"
            f"<span>{_num(hv)}</span></div>"
            + _split_bar(av, hv, away_color, home_color) + "</div>"
        )
    return f"<div class='bs-cmp'>{''.join(rows)}</div>"


def _chips_html(away_row, home_row, away_abbr, home_abbr):
    """Extras the team box carries that nothing else in this app can
    derive - points in paint, fast-break points, points off turnovers,
    largest lead, lead changes. Silently skipped for a season whose file
    doesn't carry them (the schema drifts - see loaders._num_col)."""
    chips = []
    for label, col in (('Paint', 'PIP'), ('Fast break', 'Fast Break'), ('Off TOs', 'Off TO'),
                       ('Largest lead', 'Largest Lead')):
        a, h = away_row.get(col), home_row.get(col)
        if pd.isna(a) and pd.isna(h):
            continue
        chips.append(
            f"<span class='bs-chip'>{html.escape(label)} "
            f"<b>{_num(a)}</b>–<b>{_num(h)}</b> "
            f"<span style='opacity:.7'>{_esc(away_abbr)}/{_esc(home_abbr)}</span></span>"
        )
    lc = away_row.get('Lead Changes')
    if pd.notna(lc):
        chips.append(f"<span class='bs-chip'>Lead changes <b>{_num(lc)}</b></span>")
    return f"<div class='bs-chips'>{''.join(chips)}</div>" if chips else ''


def _box_header_html(row, teams_df, dark_mode):
    away, home = row.get('Away'), row.get('Home')
    sides = []
    for side, team, align in (('Away', away, 'bs-away'), ('Home', home, 'bs-home')):
        logo = _logo_for(row, side, dark_mode)
        logo_html = (
            f"<img class='bs-logo' src='{html.escape(str(logo), quote=True)}' alt=''>"
            if logo and pd.notna(logo) else ''
        )
        conf = row.get(f'{side} Conf')
        rank = row.get(f'{side} Rank')
        meta = " · ".join(x for x in [
            f"#{int(rank)}" if pd.notna(rank) else '',
            str(conf) if conf and pd.notna(conf) else '',
            side.upper(),
        ] if x)
        pts = row.get(f'{side} Pts')
        won = ' bs-w' if (row.get('Winner') == team) else ''
        sides.append(
            f"<div class='bs-side {align}'>{logo_html}"
            f"<div><div class='bs-name'>{_esc(team)}</div>"
            f"<div class='bs-rec'>{html.escape(meta)}</div></div>"
            f"<div class='bs-pts{won}'>{_num(pts)}</div></div>"
        )
    joiner = "vs" if row.get('Neutral Site') else "@"
    sub_bits = [x for x in [
        row.get('Date Display'), row.get('Status Detail'),
        (f"{row.get('Venue')} (neutral)" if row.get('Neutral Site') else row.get('Venue')),
        row.get('Broadcast'),
    ] if x and pd.notna(x)]
    return (
        f"<div class='bs-head'>{sides[0]}<span class='bs-vs'>{joiner}</span>{sides[1]}</div>"
        f"<div class='bs-sub'>{html.escape(' · '.join(str(b) for b in sub_bits))}</div>"
    )


def _strip_html(cells, extra_class='', style=''):
    return f"<div class='bs-strip {extra_class}'{style}>{''.join(cells)}</div>"


def _column_header_html():
    cells = ["<span class='bs-c bs-pos'></span>"]
    for label, _, optional in _BOX_COLUMNS:
        cells.append(f"<span class='bs-c{' bs-opt' if optional else ''}'>{label}</span>")
    for label in ('FG', '3PT', 'FT'):
        cells.append(f"<span class='bs-c bs-wide'>{label}</span>")
    return _strip_html(cells, extra_class='bs-strip-head')


def _player_strip_html(p, max_points, accent):
    """One player's numbers, with a subtle points heat bar behind the row so
    the scoring line reads without scanning a column."""
    pts = p.get('Points')
    pct = (float(pts) / max_points * 100) if (pd.notna(pts) and max_points) else 0
    tint = html.escape(str(accent or '#565d8c'), quote=True)
    style = (
        f" style=\"background:linear-gradient(90deg,{tint}22 0%,{tint}22 {pct:.0f}%,transparent {pct:.0f}%);\""
        if pct > 0 else ''
    )
    cells = [f"<span class='bs-c bs-pos'>{_esc(p.get('PosAbbr'))}</span>"]
    for _, col, optional in _BOX_COLUMNS:
        cells.append(f"<span class='bs-c{' bs-opt' if optional else ''}'>{_num(p.get(col), '0')}</span>")
    for made, att in (('FGM', 'FGA'), ('3PM', '3PA'), ('FTM', 'FTA')):
        cells.append(f"<span class='bs-c bs-wide bs-dim'>{_num(p.get(made), '0')}-{_num(p.get(att), '0')}</span>")
    return _strip_html(cells, extra_class='bs-heat', style=style)


def _render_team_box(row, side, box, season, dark_mode, key_prefix):
    team = row.get(side)
    players = box['players']
    squad = players[players['TeamRaw'] == team] if not players.empty else pd.DataFrame()
    color = row.get(f'{side} Color')

    totals = pd.Series(dtype='object')
    if box['team_totals']:
        match = box['teams'][box['teams']['Team'] == team]
        if not match.empty:
            totals = match.iloc[0]

    logo = _logo_for(row, side, dark_mode)
    logo_html = f"<img src='{html.escape(str(logo), quote=True)}' alt=''>" if logo and pd.notna(logo) else ''
    line = ''
    if not totals.empty:
        line = (
            f"{_num(totals.get('FGM'),'0')}-{_num(totals.get('FGA'),'0')} FG · "
            f"{_num(totals.get('3PM'),'0')}-{_num(totals.get('3PA'),'0')} 3PT · "
            f"{_num(totals.get('FTM'),'0')}-{_num(totals.get('FTA'),'0')} FT · "
            f"{_num(totals.get('REB'))} REB · {_num(totals.get('AST'))} AST · {_num(totals.get('TOV'))} TO"
        )
    style = f" style='--bs-color:{html.escape(str(color), quote=True)};'" if color else ''
    st.markdown(
        f"<div class='bs-team-head'{style}>{logo_html}"
        f"<span class='bs-t-name'>{_esc(team)}</span>"
        f"<span class='bs-t-line'>{html.escape(line)}</span></div>",
        unsafe_allow_html=True,
    )

    if squad.empty:
        st.caption("No player box score published for this team yet.")
        return

    played = squad[~squad['DNP']]
    dnp = squad[squad['DNP']]
    max_points = pd.to_numeric(played['Points'], errors='coerce').max() if not played.empty else 0
    max_points = float(max_points) if pd.notna(max_points) else 0

    hc1, hc2 = st.columns([3.1, 6.9])
    hc1.markdown(
        "<div class='bs-strip bs-strip-head'><span class='bs-c' style='text-align:left'>PLAYER</span></div>",
        unsafe_allow_html=True,
    )
    hc2.markdown(_column_header_html(), unsafe_allow_html=True)

    for i, (_, p) in enumerate(played.iterrows()):
        c1, c2 = st.columns([3.1, 6.9])
        with c1:
            name = str(p.get('name') or '')
            starter = '● ' if p.get('Starter') else ''
            _player_button(f"{starter}{name}", name, p, row, side, season, f"{key_prefix}_{i}")
        with c2:
            st.markdown(_player_strip_html(p, max_points, color), unsafe_allow_html=True)

    if not dnp.empty:
        names = ", ".join(f"<b>{_esc(n)}</b>" for n in dnp['name'].dropna())
        st.markdown(f"<div class='bs-dnp'>Did not play: {names}</div>", unsafe_allow_html=True)


def _player_button(label, name, p, row, side, season, key):
    """
    A player's name, as a real button that opens Player Search already on
    that player. Has to be a widget, not an <a>: switch_tab only works as
    an on_click callback (see ui.components.switch_tab).

    Seeding is THREE layers deep on purpose, because Player Search resolves
    a player through two different widget paths and an exact-label match is
    not guaranteed:

      1. `ps_team` + `ps_player_query_team` narrow the team-mode roster
         list to this one player. `fuzzy_filter_names` ranks a full
         substring hit above everything else, so the player is first even
         if layer 2 misses.
      2. `ps_player_select` is the exact label Player Search builds,
         `"Name (POS)"`. POS uses ESPN's ABBREVIATION ('G'), which is what
         load_espn_roster emits - the box file's full 'Guard' would never
         match. If this hits, it's exact; if it misses, the sticky wrapper
         falls back to the narrowed list's first entry, which is layer 1.
      3. `ps_player_query` covers the case where the TEAM itself doesn't
         resolve and Player Search opens in All Teams mode - that mode
         needs a non-empty query before it shows anything at all, so
         without this the visitor would land on an empty search box.

    Every one of those degrades to "the right player, found a slightly
    different way" rather than to a wrong player, because the sticky
    mirrors are all membership-checked (see ui.components.seed_sticky_value).
    """
    team = row.get(side)
    pos = p.get('PosAbbr')
    exact_label = f"{name} ({pos})" if pos and pd.notna(pos) else f"{name} (?)"
    st.button(
        label, key=key, width="stretch",
        help=f"Open {name}'s season profile in Player Search",
        on_click=switch_tab, args=(TAB_PLAYER_SEARCH,),
        kwargs={
            'ps_season': season,
            'ps_team': team,
            'ps_player_query_team': name,
            'ps_player_select': exact_label,
            'ps_player_query': name,
        },
    )


def _close_box():
    st.session_state.pop('gs_box_game', None)


def _open_box(game_id):
    st.session_state['gs_box_game'] = str(game_id)


def _render_box_panel(games, season, dark_mode):
    """Renders the open box score, if any. `games` is the CURRENT page, so
    a box stays open only while its game is on screen - closing the panel
    implicitly when the date or filters move off it, rather than showing a
    box for a game the visitor can no longer see."""
    gid = st.session_state.get('gs_box_game')
    if not gid:
        return
    match = games[games['GameId'].astype(str) == str(gid)]
    if match.empty:
        return
    row = match.iloc[0]

    with st.container(key="bs_panel"):
        head, close = st.columns([9, 1])
        with head:
            st.markdown(_box_header_html(row, None, dark_mode), unsafe_allow_html=True)
        with close:
            st.button("✕", key="bs_close", help="Close box score", on_click=_close_box)

        with st.spinner("Loading box score..."):
            box = load_game_box(row['GameId'], season)

        if box['players'].empty and not box['team_totals']:
            st.info(
                "No box score published for this game yet. This source is a bulk file rebuilt "
                "daily, so a game that just finished can lag — try **Refresh slate** below."
            )
            return

        if box['team_totals'] and len(box['teams']) == 2:
            teams = box['teams']
            away_t = teams[teams['Team'] == row.get('Away')]
            home_t = teams[teams['Team'] == row.get('Home')]
            if not away_t.empty and not home_t.empty:
                st.markdown(
                    _comparison_html(away_t.iloc[0], home_t.iloc[0],
                                     row.get('Away Color'), row.get('Home Color')),
                    unsafe_allow_html=True,
                )
                st.markdown(
                    _chips_html(away_t.iloc[0], home_t.iloc[0],
                                _abbrev(row, 'Away'), _abbrev(row, 'Home')),
                    unsafe_allow_html=True,
                )

        _render_team_box(row, 'Away', box, season, dark_mode, 'bs_a')
        _render_team_box(row, 'Home', box, season, dark_mode, 'bs_h')
        st.caption(
            "● starter. Team totals include team rebounds and team turnovers, which belong to no "
            "player — so they can exceed the sum of the rows above. Click a player to open their "
            "season profile."
        )


def _shift_date(key, current, days):
    """on_click callback for the prev/next-day arrows. Drives the date
    picker on THIS tab, which is open and therefore instantiated - so the
    widget key has to be written too, not just the sticky mirror (see
    ui.components.set_sticky_value)."""
    set_sticky_value(key, current + datetime.timedelta(days=days))


def render():
    st.markdown("<div class='custom-section-header'>GAME SLATE</div>", unsafe_allow_html=True)

    default_season = current_cbb_season()
    seasons = AVAILABLE_SEASONS if default_season in AVAILABLE_SEASONS else [default_season] + AVAILABLE_SEASONS
    c_season, c_prev, c_date, c_next = st.columns([2, 1, 3, 1])
    with c_season:
        season = sticky_selectbox(
            "Season", seasons, key="gs_season", default_index=seasons.index(default_season),
            format_func=lambda y: f"{y - 1}-{str(y)[2:]}",
        )

    dates = slate_dates(season)
    default_date = default_slate_date(season, dates)
    # Read the date BEFORE the arrows render, so an arrow click this run
    # shifts from the date currently shown rather than from a stale one.
    current = st.session_state.get("_sticky__gs_date", default_date)
    if isinstance(current, datetime.datetime):
        current = current.date()
    if not isinstance(current, datetime.date):
        current = default_date

    with c_prev:
        st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
        st.button("◀", key="gs_prev_day", width="stretch", help="Previous day",
                  on_click=_shift_date, args=("gs_date", current, -1))
    with c_date:
        picked = sticky_date_input("Date", key="gs_date", default_value=default_date)
    with c_next:
        st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
        st.button("▶", key="gs_next_day", width="stretch", help="Next day",
                  on_click=_shift_date, args=("gs_date", current, 1))

    date_iso = picked.isoformat() if isinstance(picked, (datetime.date, datetime.datetime)) else str(picked)

    f1, f2 = st.columns([3, 2])
    with f1:
        di_only = sticky_checkbox(
            "Division I matchups only", key="gs_di_only", default_value=True,
            help=(
                "Hides games against non-Division I opponents. This app has no stats for those "
                "teams from any of its sources, so a card for one can't be acted on — about 9% of "
                "a real season's games."
            ),
        )
    with f2:
        ranked_only = sticky_checkbox(
            "Ranked teams only", key="gs_ranked_only", default_value=False,
            help="Only games with at least one AP Top 25 team.",
        )

    with st.spinner("Loading slate..."):
        games = load_slate(season, date_iso, di_only=di_only)

    if games.empty:
        source = slate_source(season, date_iso)
        if source is None:
            st.info(
                f"{date_iso} falls outside the {season - 1}-{str(season)[2:]} season, so there's "
                "nothing scheduled. Pick a date between early November and early April."
            )
        else:
            st.info(
                f"No {'Division I ' if di_only else ''}games found for {date_iso}. "
                "College basketball has real off-days mid-week — try the next day, or clear the "
                "filters above."
            )
        return

    total_today = len(games)

    conf_values = sorted(
        {c for c in pd.concat([games['Away Conf'], games['Home Conf']]).dropna().unique()}
    )
    if conf_values:
        picked_confs = sticky_multiselect(
            "Conferences", conf_values, key="gs_conferences", default=[],
            help="Leave empty for every conference. A game shows if EITHER team is in one you pick.",
        )
        if picked_confs:
            games = games[
                games['Away Conf'].isin(picked_confs) | games['Home Conf'].isin(picked_confs)
            ]

    if ranked_only:
        games = games[games['Away Rank'].notna() | games['Home Rank'].notna()]

    if games.empty:
        st.info(f"No games on {date_iso} match those filters — {total_today} played that day in total.")
        return

    games = games.reset_index(drop=True)
    filtered_total = len(games)

    page_count = (filtered_total + _CARDS_PER_PAGE - 1) // _CARDS_PER_PAGE
    if page_count > 1:
        page_labels = [
            f"{i * _CARDS_PER_PAGE + 1}–{min((i + 1) * _CARDS_PER_PAGE, filtered_total)} of {filtered_total}"
            for i in range(page_count)
        ]
        page_label = sticky_selectbox("Showing", page_labels, key="gs_page", default_index=0)
        # Guard the index rather than trusting the remembered label: a
        # filter change can shrink the list under a remembered page. The
        # sticky wrapper already falls back to index 0 when the exact label
        # is gone, but the labels are value-derived, so a same-length page
        # set could match a label that no longer means the same range.
        page = page_labels.index(page_label) if page_label in page_labels else 0
        games = games.iloc[page * _CARDS_PER_PAGE:(page + 1) * _CARDS_PER_PAGE].reset_index(drop=True)

    bridge = slate_team_bridge(games, season)
    dark_mode = st.session_state.get('theme_mode', 'dark') != 'light'

    # Above the grid: clicking a card's "Box score" reruns and scrolls to
    # the top, so the panel has to be where the eye lands.
    _render_box_panel(games, season, dark_mode)

    # Row by row, NOT column by column. Filling column 0 with the first half
    # of the slate and column 1 with the second half makes the two halves of
    # the screen scroll out of chronological order.
    for start in range(0, len(games), _CARDS_PER_ROW):
        cols = st.columns(_CARDS_PER_ROW)
        for offset, col in enumerate(cols):
            idx = start + offset
            if idx >= len(games):
                continue
            with col:
                _render_card(idx, games.iloc[idx], season, bridge, dark_mode)

    _render_footer(season, date_iso, games, total_today, filtered_total)


def _render_footer(season, date_iso, games, total_today, filtered_total):
    source = slate_source(season, date_iso)
    if source == 'local':
        detail = (
            "Source: SportsDataverse/hoopR published season schedule (free, no API key). "
            "Rebuilt daily upstream and cached here for a day."
        )
    elif source == 'espn':
        detail = (
            "Source: ESPN's public scoreboard (free, no API key), cached one hour — short on "
            "purpose, since tip times move late and a live score changes by the minute."
        )
    else:
        detail = "Source: unavailable for this date."

    shown = len(games)
    counts = f"Showing {shown} of {filtered_total} filtered"
    if filtered_total != total_today:
        counts += f" ({total_today} on this date)"

    tbd = int(games['Time TBD'].sum()) if 'Time TBD' in games.columns else 0
    tbd_note = f" · {tbd} tip time{'s' if tbd != 1 else ''} not announced yet" if tbd else ""

    st.caption(f"{counts}{tbd_note}. {detail}")
    if st.button("🔄 Refresh slate", key="gs_refresh", help="Re-pull this date's games now."):
        refresh_slate()
        st.rerun()
