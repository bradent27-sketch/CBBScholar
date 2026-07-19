"""
Live Odds tab: refresh-on-demand game lines (moneyline/spread/total across
every bookmaker) and player props for a selected game, pivoted so the same
bet's price can be compared across every book at a glance. Ported from NFL
Scholar's live_odds.py / CFB Scholar's, adapted for basketball's market keys.
"""
import datetime
import pandas as pd
import streamlit as st

from config import ODDS_API_PLAYER_PROP_MARKETS
from data.loaders import fetch_ncaab_odds, fetch_ncaab_player_props
from ui.components import render_coming_soon
from ui.styling import style_plain_dataframe, df_auto_height


def _fmt_tipoff(iso_str):
    try:
        dt = datetime.datetime.fromisoformat(iso_str.replace('Z', '+00:00'))
        return dt.strftime('%a %b %d, %I:%M %p UTC')
    except Exception:
        return iso_str


def _pt(val):
    return round(float(val), 1) if val is not None else None


def _build_lines_table(game):
    home, away = game.get('home_team'), game.get('away_team')
    rows = []
    for book in game.get('bookmakers', []):
        row = {'Book': book.get('title', book.get('key', '?'))}
        for market in book.get('markets', []):
            if market['key'] == 'h2h':
                for o in market['outcomes']:
                    if o['name'] == home: row['Home ML'] = o['price']
                    if o['name'] == away: row['Away ML'] = o['price']
            elif market['key'] == 'spreads':
                for o in market['outcomes']:
                    if o['name'] == home: row['Home Spread'] = _pt(o.get('point'))
                    if o['name'] == away: row['Away Spread'] = _pt(o.get('point'))
            elif market['key'] == 'totals':
                for o in market['outcomes']:
                    if o['name'] == 'Over': row['Total (O/U)'] = _pt(o.get('point'))
        rows.append(row)
    return pd.DataFrame(rows)


def _build_props_long_table(props_data):
    rows = []
    for book in props_data.get('bookmakers', []):
        for market in book.get('markets', []):
            for o in market.get('outcomes', []):
                rows.append({
                    'Market': market.get('key', '').replace('player_', '').replace('_', ' ').title(),
                    'Player': o.get('description') or o.get('name'),
                    'Selection': o.get('name'),
                    'Line': o.get('point'),
                    'Odds': o.get('price'),
                    'Book': book.get('title', book.get('key', '?')),
                })
    return pd.DataFrame(rows)


def _build_props_comparison_table(props_long_df):
    if props_long_df.empty:
        return pd.DataFrame()

    def fmt_cell(r):
        try:
            odds_txt = f"{int(r['Odds']):+d}"
        except (TypeError, ValueError):
            return ''
        if pd.notna(r['Line']):
            return f"{odds_txt} ({r['Line']:g})"
        return odds_txt

    work = props_long_df.copy()
    work['_cell'] = work.apply(fmt_cell, axis=1)
    pivot = work.pivot_table(
        index=['Market', 'Player', 'Selection'], columns='Book', values='_cell', aggfunc='first'
    ).reset_index()
    pivot.columns.name = None
    return pivot


def render():
    st.markdown("<div class='custom-section-header'>LIVE ODDS</div>", unsafe_allow_html=True)

    oc1, oc2 = st.columns([1, 3])
    with oc1:
        if st.button("🔄 Refresh Odds"):
            fetch_ncaab_odds.clear()
            fetch_ncaab_player_props.clear()
            st.session_state.pop('odds_props_game_id', None)
            st.session_state.pop('odds_props_data', None)
            st.rerun()

    with st.spinner("Fetching odds..."):
        odds_data, odds_err, requests_left = fetch_ncaab_odds()

    if odds_err:
        render_coming_soon(
            eyebrow="NEEDS SETUP" if "key configured" in odds_err else "ERROR",
            blurb=odds_err,
            data_sources=["The Odds API — basketball_ncaab"],
        )
        return
    if not odds_data:
        st.info("No upcoming NCAAB games with posted odds right now.")
        return

    if requests_left:
        st.caption(f"API requests remaining this period: {requests_left}")

    game_labels = {}
    for g in odds_data:
        label = f"{g.get('away_team','?')} @ {g.get('home_team','?')} — {_fmt_tipoff(g.get('commence_time',''))}"
        game_labels[label] = g
    sel_label = st.selectbox("Select a game", list(game_labels.keys()), key="odds_game_select")
    game = game_labels[sel_label]

    st.markdown(f"<div class='custom-section-header'>{game.get('away_team')} @ {game.get('home_team')}</div>", unsafe_allow_html=True)
    st.caption(f"Tip-off: {_fmt_tipoff(game.get('commence_time',''))}")

    lines_df = _build_lines_table(game)
    if not lines_df.empty:
        st.markdown("**Game Lines — Moneyline / Spread / Total (every bookmaker, click a header to sort)**")
        st.dataframe(style_plain_dataframe(lines_df.set_index('Book')), width="stretch", height=df_auto_height(len(lines_df)))
    else:
        st.info("No bookmakers have posted lines for this game yet.")

    st.markdown("**Player Props**")

    if st.button("Load player props for this game") or st.session_state.get('odds_props_game_id') == game['id']:
        if st.session_state.get('odds_props_game_id') != game['id']:
            with st.spinner("Fetching player props..."):
                props_data, props_err = fetch_ncaab_player_props(
                    game['id'], markets=','.join(ODDS_API_PLAYER_PROP_MARKETS)
                )
            st.session_state['odds_props_game_id'] = game['id']
            st.session_state['odds_props_data'] = props_data
            st.session_state['odds_props_err'] = props_err

        props_err = st.session_state.get('odds_props_err')
        props_data = st.session_state.get('odds_props_data')

        if props_err:
            st.warning(f"Player props unavailable: {props_err}")
        elif props_data:
            props_long = _build_props_long_table(props_data)
            if not props_long.empty:
                markets_found = sorted(props_long['Market'].unique().tolist())
                books_found = sorted(props_long['Book'].unique().tolist())
                st.caption(f"Markets posted for this game: {', '.join(markets_found)} — across {len(books_found)} book(s): {', '.join(books_found)}")
                market_filter = st.multiselect("Filter by market", markets_found, default=[], key="odds_market_filter")
                filtered_long = props_long[props_long['Market'].isin(market_filter)] if market_filter else props_long

                comparison_df = _build_props_comparison_table(filtered_long)
                st.markdown("**Cross-book comparison** — one row per bet, one column per bookmaker (odds shown as `price (line)`; click a column header to sort)")
                st.dataframe(
                    style_plain_dataframe(comparison_df.set_index('Player')),
                    width="stretch", height=df_auto_height(min(len(comparison_df), 30))
                )
            else:
                st.info("No player props posted for this game yet by any tracked bookmaker.")
