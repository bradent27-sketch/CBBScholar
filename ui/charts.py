"""
Inline-SVG chart components shared by tabs. Deliberately hand-rolled SVG
(rendered via st.markdown) instead of a charting library: every color/font
comes straight from config.THEME so charts are pixel-consistent with the
rest of the design system, there's no new dependency, native <title>
elements give hover tooltips for free, and the file is byte-identical
between CFB Scholar and CBB Scholar (sport-agnostic by design - keep it
that way; sport-specific logic belongs in the calling tab or transforms).
"""
import html
import math

import pandas as pd
import streamlit as st

from config import THEME
from ui.styling import get_grade_color

C = THEME['colors']
F = THEME['fonts']

# THEME's font stacks quote family names with SINGLE quotes ("'Inter',
# sans-serif") - embedded inside this module's single-quoted style/
# font-family attributes that terminates the attribute early, and the
# resulting malformed opening tag makes Streamlit's markdown refuse to
# treat the block as raw HTML at all (it renders as escaped text - hit
# live during verification). Double-quoted family names inside
# single-quoted attributes are valid HTML+CSS.
_BODY_FONT = F['body'].replace("'", '"')
_MONO_FONT = F['mono'].replace("'", '"')


def _esc(s):
    return html.escape(str(s), quote=True)


# ---------------------------------------------------------------------------
# Mirrored matchup bars (unit-vs-unit comparisons)
# ---------------------------------------------------------------------------

def render_mirror_bars(header_left, header_right, rows):
    """
    Center-labeled mirrored percentile bars - the matchup workhorse. Each
    row: {'label', 'help', 'left_val_str', 'left_pct', 'right_val_str',
    'right_pct'}. Bars grow outward from the center label, length AND color
    driven by league percentile (get_grade_color's diverging scale), so on
    both sides "long + violet/blue = that unit is winning its side."
    Percentile of None renders a neutral stub instead of a lying zero-bar.
    """
    W, ROW_H, LABEL_W = 860, 34, 170
    half = (W - LABEL_W) / 2
    H = ROW_H * len(rows) + 26
    parts = [
        f"<svg viewBox='0 0 {W} {H}' xmlns='http://www.w3.org/2000/svg' "
        f"style='width:100%; height:auto; font-family:{_BODY_FONT};'>"
    ]
    # Column headers
    parts.append(
        f"<text x='{half - 6}' y='14' text-anchor='end' font-size='11' font-weight='700' "
        f"letter-spacing='0.08em' fill='{C['on_surface_variant']}'>{_esc(header_left.upper())}</text>"
    )
    parts.append(
        f"<text x='{half + LABEL_W + 6}' y='14' text-anchor='start' font-size='11' font-weight='700' "
        f"letter-spacing='0.08em' fill='{C['on_surface_variant']}'>{_esc(header_right.upper())}</text>"
    )
    y = 26
    max_bar = half - 78  # room for the value label beyond the bar tip
    for r in rows:
        cy = y + ROW_H / 2
        bar_h = 12
        # center label (with tooltip)
        parts.append(
            f"<text x='{half + LABEL_W / 2}' y='{cy + 4}' text-anchor='middle' font-size='11.5' "
            f"font-weight='600' fill='{C['on_surface']}'>{_esc(r['label'])}"
            f"<title>{_esc(r.get('help', ''))}</title></text>"
        )
        for side in ('left', 'right'):
            pct = r.get(f'{side}_pct')
            val_str = r.get(f'{side}_val_str', '--')
            if pct is None or pd.isna(pct):
                bar_len, color = 4, C['surface_container_high']
                pct_label = ''
            else:
                bar_len = max(4.0, max_bar * float(pct) / 100.0)
                color = get_grade_color(pct)
                pct_label = f" · {pct:.0f}th pctl"
            if side == 'left':
                x0 = half - bar_len
                tx, anchor = x0 - 8, 'end'
            else:
                x0 = half + LABEL_W
                tx, anchor = x0 + bar_len + 8, 'start'
            tooltip = f"{r['label']}: {val_str}{pct_label}"
            parts.append(
                f"<rect class='hz-bar' x='{x0:.1f}' y='{cy - bar_h / 2:.1f}' width='{bar_len:.1f}' height='{bar_h}' rx='3' "
                f"fill='{color}'><title>{_esc(tooltip)}</title></rect>"
            )
            parts.append(
                f"<text x='{tx:.1f}' y='{cy + 4}' text-anchor='{anchor}' font-size='11' "
                f"font-family='{_MONO_FONT}' fill='{C['on_surface']}'>{_esc(val_str)}</text>"
            )
        y += ROW_H
    parts.append("</svg>")
    st.markdown("".join(parts), unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Recent-form strip (last-n results as chips)
# ---------------------------------------------------------------------------

def render_form_strip(team_label, chips, elo_delta=None):
    """W/L chips (oldest -> newest) with score + opponent tooltips, plus an
    optional Elo-trend readout. `chips`: [{'result','margin','opponent',
    'venue','score'}, ...] from transforms.recent_form."""
    if not chips:
        st.caption(f"{team_label}: no completed games yet.")
        return
    chip_html = []
    for ch in chips:
        is_win = ch['result'] == 'W'
        bg = C['positive'] if is_win else C['negative']
        tooltip = f"{ch['result']} {ch['score']} {ch['venue']} {ch['opponent']}"
        chip_html.append(
            f"<span class='form-chip' title='{_esc(tooltip)}' style='display:inline-flex; flex-direction:column; align-items:center; "
            f"min-width:34px; padding:4px 6px; border-radius:6px; background:{bg}22; "
            f"border:1px solid {bg}66;'>"
            f"<span style='font-weight:800; font-size:12px; color:{bg};'>{ch['result']}</span>"
            f"<span style='font-family:{_MONO_FONT}; font-size:10px; color:{C['on_surface_variant']};'>"
            f"{'+' if ch['margin'] > 0 else ''}{ch['margin']}</span></span>"
        )
    elo_html = ""
    if elo_delta is not None:
        up = elo_delta >= 0
        color = C['positive'] if up else C['negative']
        elo_html = (
            f"<span style='margin-left:10px; font-family:{_MONO_FONT}; font-size:11px; color:{color};' "
            f"title='Elo rating change across these games'>{'▲' if up else '▼'} {abs(elo_delta):.0f} Elo</span>"
        )
    st.markdown(
        f"<div style='display:flex; align-items:center; gap:5px; margin:2px 0 10px 0;'>"
        f"<span style='font-size:11px; font-weight:700; text-transform:uppercase; letter-spacing:0.07em; "
        f"color:{C['on_surface_variant']}; margin-right:6px;'>{_esc(team_label)}</span>"
        f"{''.join(chip_html)}{elo_html}</div>",
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# Rank trajectory (poll position over weeks; rank 1 at the top)
# ---------------------------------------------------------------------------

def render_rank_trajectory(pivot, week_labels, color_map, max_rank=26):
    """
    Multi-team rank-over-time lines. `pivot`: index = week order, columns =
    teams, values = rank (NaN = unranked, drawn as a gap). `week_labels`:
    {week_order: 'W5'/'Final'}. Y axis inverted (rank 1 on top). Team lines
    use official team colors with an end-of-line label; hover any point for
    'team - W5: #12'.
    """
    if pivot.empty:
        return
    W, H = 860, 360
    ML, MR, MT, MB = 34, 130, 14, 30
    plot_w, plot_h = W - ML - MR, H - MT - MB
    orders = list(pivot.index)
    n = len(orders)
    xs = {o: ML + (plot_w * i / max(n - 1, 1)) for i, o in enumerate(orders)}

    def y_for(rank):
        return MT + plot_h * (rank - 1) / (max_rank - 1)

    parts = [
        f"<svg viewBox='0 0 {W} {H}' xmlns='http://www.w3.org/2000/svg' "
        f"style='width:100%; height:auto; font-family:{_BODY_FONT};'>"
    ]
    # Grid + rank axis
    for r in (1, 5, 10, 15, 20, 25):
        gy = y_for(r)
        parts.append(f"<line x1='{ML}' y1='{gy:.1f}' x2='{W - MR}' y2='{gy:.1f}' stroke='{C['outline_variant']}' stroke-width='1' stroke-dasharray='3,4'/>")
        parts.append(f"<text x='{ML - 6}' y='{gy + 4:.1f}' text-anchor='end' font-size='10.5' font-family='{_MONO_FONT}' fill='{C['on_surface_variant']}'>{r}</text>")
    # Week axis labels (thin out if crowded)
    step = max(1, n // 12)
    for i, o in enumerate(orders):
        if i % step and i != n - 1:
            continue
        parts.append(
            f"<text x='{xs[o]:.1f}' y='{H - 8}' text-anchor='middle' font-size='10.5' "
            f"font-family='{_MONO_FONT}' fill='{C['on_surface_variant']}'>{_esc(week_labels.get(o, o))}</text>"
        )
    # Team lines - draw in reverse final-rank order so better teams paint last (on top)
    final_ranks = pivot.iloc[-1]
    ordered_teams = final_ranks.sort_values(ascending=False, na_position='first').index.tolist()
    label_ys = []
    for team in ordered_teams:
        series = pivot[team]
        color = color_map.get(team) or C['primary']
        pts = [(xs[o], y_for(v)) for o, v in series.items() if pd.notna(v)]
        if not pts:
            continue
        # polyline segments broken at unranked gaps
        segs, cur = [], []
        for o in orders:
            v = series.get(o)
            if pd.notna(v):
                cur.append((xs[o], y_for(v)))
            elif cur:
                segs.append(cur)
                cur = []
        if cur:
            segs.append(cur)
        for seg in segs:
            if len(seg) == 1:
                x, yv = seg[0]
                parts.append(f"<circle class='hz-dot' cx='{x:.1f}' cy='{yv:.1f}' r='3' fill='{color}'/>")
            else:
                d = " ".join(f"{x:.1f},{yv:.1f}" for x, yv in seg)
                parts.append(f"<polyline points='{d}' fill='none' stroke='{color}' stroke-width='2.2' stroke-linejoin='round' stroke-linecap='round' opacity='0.9'/>")
        for o, v in series.items():
            if pd.isna(v):
                continue
            parts.append(
                f"<circle class='hz-dot' cx='{xs[o]:.1f}' cy='{y_for(v):.1f}' r='3.4' fill='{color}' stroke='{C['surface']}' stroke-width='1'>"
                f"<title>{_esc(team)} — {_esc(week_labels.get(o, o))}: #{int(v)}</title></circle>"
            )
        # End label, nudged to avoid overlaps
        last_y = next((y_for(series[o]) for o in reversed(orders) if pd.notna(series.get(o))), None)
        if last_y is not None:
            while any(abs(last_y - ly) < 13 for ly in label_ys):
                last_y += 13
            label_ys.append(last_y)
            parts.append(
                f"<text x='{W - MR + 8}' y='{last_y + 4:.1f}' font-size='11' font-weight='600' "
                f"fill='{color}'>{_esc(team)}</text>"
            )
    parts.append("</svg>")
    st.markdown("".join(parts), unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Game-log bars (per-game values with season-average line + breakout flags)
# ---------------------------------------------------------------------------

def render_game_log_bars(values, tooltips, breakout, avg=None, avg_label="season avg"):
    """
    One bar per game (season order), season-average dashed reference line,
    breakout games (see transforms.breakout_flags) drawn in the primary
    accent with a ★ marker. `tooltips` supplies the per-bar hover text.
    """
    if not values:
        return
    W, H, MB, MT = 860, 190, 24, 18
    plot_h = H - MB - MT
    n = len(values)
    slot = W / n
    bar_w = min(46.0, slot * 0.62)
    vmax = max(max(values), (avg or 0)) or 1
    parts = [
        f"<svg viewBox='0 0 {W} {H}' xmlns='http://www.w3.org/2000/svg' "
        f"style='width:100%; height:auto; font-family:{_BODY_FONT};'>"
    ]
    for i, v in enumerate(values):
        h = max(2.0, plot_h * float(v) / vmax)
        x = slot * i + (slot - bar_w) / 2
        y = MT + plot_h - h
        is_star = bool(breakout[i]) if i < len(breakout) else False
        fill = C['primary'] if is_star else C['secondary']
        parts.append(
            f"<rect class='hz-bar' x='{x:.1f}' y='{y:.1f}' width='{bar_w:.1f}' height='{h:.1f}' rx='3' fill='{fill}' "
            f"opacity='{1.0 if is_star else 0.75}'><title>{_esc(tooltips[i])}</title></rect>"
        )
        if is_star:
            parts.append(
                f"<text x='{x + bar_w / 2:.1f}' y='{y - 5:.1f}' text-anchor='middle' font-size='12' "
                f"fill='{C['primary']}'>★<title>{_esc(tooltips[i])}</title></text>"
            )
        parts.append(
            f"<text x='{x + bar_w / 2:.1f}' y='{H - 8}' text-anchor='middle' font-size='9.5' "
            f"font-family='{_MONO_FONT}' fill='{C['on_surface_variant']}'>{i + 1}</text>"
        )
    if avg is not None and vmax:
        ay = MT + plot_h - plot_h * float(avg) / vmax
        parts.append(f"<line x1='0' y1='{ay:.1f}' x2='{W}' y2='{ay:.1f}' stroke='{C['on_surface_variant']}' stroke-width='1.2' stroke-dasharray='5,5' opacity='0.8'/>")
        parts.append(
            f"<text x='{W - 4}' y='{ay - 5:.1f}' text-anchor='end' font-size='10' font-family='{_MONO_FONT}' "
            f"fill='{C['on_surface_variant']}'>{avg_label} {avg:.1f}</text>"
        )
    parts.append("</svg>")
    st.markdown("".join(parts), unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Trend line (single series over chronological game order, vs a flat
# reference average) - "is this trending up or down" at a glance. Shared by
# the Matchup Analyzer's positional-defense-over-time chart (data.transforms
# .positional_defense_trend) and Player Trends' last-N-games chart (data.
# transforms.player_trend_series).
# ---------------------------------------------------------------------------

def render_trend_line(dates, values, avg=None, avg_label="season avg", y_suffix='', color=None, height=170):
    """
    Per-point trend line, oldest-to-newest, with an optional flat dashed
    reference line (season/baseline average) so "trending up" or "trending
    down" reads as a shape, not a column of numbers you have to scan.
    Points above the reference render green, below render red (no
    reference line: neutral accent color throughout). Hover any point for
    the exact date/value/delta-from-reference.
    """
    if not values:
        return
    W, MB, MT, ML, MR = 860, 26, 16, 8, 8
    H = height
    plot_w = W - ML - MR
    plot_h = H - MT - MB
    n = len(values)
    color = color or C['primary']
    lo_candidates = [v for v in values if v is not None]
    if avg is not None:
        lo_candidates.append(avg)
    vmin, vmax = min(lo_candidates), max(lo_candidates)
    pad = (vmax - vmin) * 0.2 or 1
    vmin, vmax = vmin - pad, vmax + pad

    def px(i):
        return ML + (plot_w * i / (n - 1)) if n > 1 else ML + plot_w / 2

    def py(v):
        return MT + plot_h * (1 - (v - vmin) / (vmax - vmin))

    parts = [
        f"<svg viewBox='0 0 {W} {H}' xmlns='http://www.w3.org/2000/svg' "
        f"style='width:100%; height:auto; font-family:{_BODY_FONT};'>"
    ]
    if avg is not None:
        ay = py(avg)
        parts.append(
            f"<line x1='{ML}' y1='{ay:.1f}' x2='{ML + plot_w}' y2='{ay:.1f}' stroke='{C['on_surface_variant']}' "
            f"stroke-width='1.2' stroke-dasharray='5,5' opacity='0.8'/>"
        )
        parts.append(
            f"<text x='{ML + plot_w}' y='{ay - 5:.1f}' text-anchor='end' font-size='10' font-family='{_MONO_FONT}' "
            f"fill='{C['on_surface_variant']}'>{_esc(avg_label)} {avg:.1f}{y_suffix}</text>"
        )
    pts = [(px(i), py(v)) for i, v in enumerate(values)]
    if n > 1:
        d = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
        parts.append(f"<polyline points='{d}' fill='none' stroke='{color}' stroke-width='2.4' stroke-linejoin='round' stroke-linecap='round' opacity='0.85'/>")
    for i, (x, y) in enumerate(pts):
        v = values[i]
        dt = dates[i] if i < len(dates) else ''
        delta_txt = f" ({v - avg:+.1f} vs {avg_label})" if avg is not None else ""
        tooltip = f"{dt}: {v:.1f}{y_suffix}{delta_txt}"
        if avg is not None:
            dot_color = C['positive'] if v >= avg else C['negative']
        else:
            dot_color = color
        parts.append(
            f"<circle class='hz-dot' cx='{x:.1f}' cy='{y:.1f}' r='4' fill='{dot_color}' stroke='{C['surface']}' stroke-width='1.2'>"
            f"<title>{_esc(tooltip)}</title></circle>"
        )
    step = max(1, n // 8)
    for i, dt in enumerate(dates):
        if i % step and i != n - 1:
            continue
        label = str(dt)[5:] if len(str(dt)) > 5 else str(dt)
        parts.append(
            f"<text x='{px(i):.1f}' y='{H - 6}' text-anchor='middle' font-size='9.5' font-family='{_MONO_FONT}' "
            f"fill='{C['on_surface_variant']}'>{_esc(label)}</text>"
        )
    parts.append("</svg>")
    st.markdown("".join(parts), unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Efficiency landscape scatter (offense vs defense, quadrant-annotated)
# ---------------------------------------------------------------------------

def render_efficiency_scatter(df, x_col, y_col, color_map, invert_y=False,
                              highlight=None, x_label=None, y_label=None):
    """
    Full-league scatter with team-colored dots and hover tooltips.
    `invert_y=True` for metrics where lower = better (defensive ratings),
    so 'good' is always up-and-right. `highlight`: iterable of team names
    drawn larger with a name label.
    """
    data = df[['Team', x_col, y_col]].dropna()
    if data.empty:
        return
    W, H = 860, 420
    ML, MR, MT, MB = 52, 18, 16, 40
    plot_w, plot_h = W - ML - MR, H - MT - MB
    xs_ = pd.to_numeric(data[x_col])
    ys_ = pd.to_numeric(data[y_col])
    x_min, x_max = xs_.min(), xs_.max()
    y_min, y_max = ys_.min(), ys_.max()
    x_pad = (x_max - x_min) * 0.05 or 1
    y_pad = (y_max - y_min) * 0.05 or 1
    x_min, x_max = x_min - x_pad, x_max + x_pad
    y_min, y_max = y_min - y_pad, y_max + y_pad

    def px(v):
        return ML + plot_w * (v - x_min) / (x_max - x_min)

    def py(v):
        frac = (v - y_min) / (y_max - y_min)
        if not invert_y:
            frac = 1 - frac
        return MT + plot_h * frac

    highlight = set(highlight or [])
    parts = [
        f"<svg viewBox='0 0 {W} {H}' xmlns='http://www.w3.org/2000/svg' "
        f"style='width:100%; height:auto; font-family:{_BODY_FONT};'>"
    ]
    # Median crosshairs -> four quadrants
    mx, my = px(xs_.median()), py(ys_.median())
    parts.append(f"<line x1='{mx:.1f}' y1='{MT}' x2='{mx:.1f}' y2='{MT + plot_h}' stroke='{C['outline_variant']}' stroke-width='1' stroke-dasharray='4,4'/>")
    parts.append(f"<line x1='{ML}' y1='{my:.1f}' x2='{ML + plot_w}' y2='{my:.1f}' stroke='{C['outline_variant']}' stroke-width='1' stroke-dasharray='4,4'/>")
    if x_label:
        parts.append(f"<text x='{ML + plot_w / 2}' y='{H - 8}' text-anchor='middle' font-size='11' fill='{C['on_surface_variant']}'>{_esc(x_label)}</text>")
    if y_label:
        parts.append(
            f"<text x='14' y='{MT + plot_h / 2}' text-anchor='middle' font-size='11' fill='{C['on_surface_variant']}' "
            f"transform='rotate(-90 14 {MT + plot_h / 2})'>{_esc(y_label)}</text>"
        )
    # Dots: non-highlighted first so highlights paint on top
    for _, row in data.iterrows():
        team = row['Team']
        if team in highlight:
            continue
        color = color_map.get(team) or C['secondary']
        parts.append(
            f"<circle class='hz-dot' cx='{px(row[x_col]):.1f}' cy='{py(row[y_col]):.1f}' r='4.2' fill='{color}' "
            f"opacity='0.75' stroke='{C['surface']}' stroke-width='0.8'>"
            f"<title>{_esc(team)} — {x_col}: {row[x_col]:.1f}, {y_col}: {row[y_col]:.1f}</title></circle>"
        )
    for _, row in data.iterrows():
        team = row['Team']
        if team not in highlight:
            continue
        color = color_map.get(team) or C['primary']
        x, yv = px(row[x_col]), py(row[y_col])
        parts.append(
            f"<circle class='hz-dot' cx='{x:.1f}' cy='{yv:.1f}' r='7' fill='{color}' stroke='#ffffff' stroke-width='1.6'>"
            f"<title>{_esc(team)} — {x_col}: {row[x_col]:.1f}, {y_col}: {row[y_col]:.1f}</title></circle>"
        )
        parts.append(
            f"<text x='{x + 10:.1f}' y='{yv + 4:.1f}' font-size='11.5' font-weight='700' fill='#ffffff' "
            f"style='paint-order:stroke; stroke:{C['surface']}; stroke-width:3px;'>{_esc(team)}</text>"
        )
    parts.append("</svg>")
    st.markdown("".join(parts), unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Relative stat bars (Savant-style: value positioned against a comparison
# group's distribution, average marked - deliberately no percentile NUMBER
# shown, just the relative position, per how this was asked for)
# ---------------------------------------------------------------------------

def render_relative_bars(rows):
    """
    One horizontal bar per stat, the player's value positioned along the
    comparison group's distribution - bar length and color driven by
    percentile (get_grade_color's diverging scale, the same treatment
    every other grade-like number in this app gets), with a tick marking
    where the group's average sits, so "about average" reads as a mark
    near the middle without ever printing a percentile digit. `rows`:
    [{'label', 'help', 'value_str', 'pct', 'avg_pct'}] - pct/avg_pct
    already 0-100 from data.transforms.pct_rank (None renders a neutral
    stub instead of a lying zero-bar).
    """
    if not rows:
        return
    W, ROW_H, LABEL_W, VAL_W = 860, 32, 108, 60
    track_w = W - LABEL_W - VAL_W - 16
    H = ROW_H * len(rows) + 10
    parts = [
        f"<svg viewBox='0 0 {W} {H}' xmlns='http://www.w3.org/2000/svg' "
        f"style='width:100%; height:auto; font-family:{_BODY_FONT};'>"
    ]
    y = 6
    for r in rows:
        cy = y + ROW_H / 2
        x0 = LABEL_W
        pct, avg_pct = r.get('pct'), r.get('avg_pct')
        parts.append(
            f"<text x='{LABEL_W - 10}' y='{cy + 4:.1f}' text-anchor='end' font-size='11.5' font-weight='700' "
            f"fill='{C['on_surface']}'>{_esc(r['label'])}<title>{_esc(r.get('help', ''))}</title></text>"
        )
        parts.append(f"<rect x='{x0}' y='{cy - 6:.1f}' width='{track_w}' height='12' rx='6' fill='{C['surface_container_high']}'/>")
        if pct is not None and pd.notna(pct):
            bar_w = max(4.0, track_w * max(0.0, min(100.0, float(pct))) / 100.0)
            color = get_grade_color(pct)
            parts.append(
                f"<rect class='hz-bar' x='{x0}' y='{cy - 6:.1f}' width='{bar_w:.1f}' height='12' rx='6' fill='{color}'>"
                f"<title>{_esc(r['label'])}: {_esc(r.get('value_str', ''))}</title></rect>"
            )
        if avg_pct is not None and pd.notna(avg_pct):
            ax = x0 + track_w * max(0.0, min(100.0, float(avg_pct))) / 100.0
            parts.append(
                f"<line x1='{ax:.1f}' y1='{cy - 10:.1f}' x2='{ax:.1f}' y2='{cy + 10:.1f}' "
                f"stroke='{C['on_surface_variant']}' stroke-width='2'><title>Group average</title></line>"
            )
        parts.append(
            f"<text x='{x0 + track_w + 14}' y='{cy + 4:.1f}' font-size='12' font-family='{_MONO_FONT}' "
            f"font-weight='600' fill='{C['on_surface']}'>{_esc(r.get('value_str', '--'))}</text>"
        )
        y += ROW_H
    parts.append("</svg>")
    st.markdown("".join(parts), unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Radar / spider chart (multi-axis two-entity comparison)
# ---------------------------------------------------------------------------

def render_radar(axes, values_a, values_b, name_a, name_b, color_a=None, color_b=None):
    """
    Inline-SVG radar/spider chart overlaying two entities (e.g. two
    players) across N axes. `axes`: ordered list of axis labels.
    `values_a`/`values_b`: {axis_label: raw_value} dicts for each entity -
    a missing/None/NaN value is treated as 0. Each axis is scaled
    independently to whichever of the two values is larger on THAT axis
    (plus headroom) - a relative shape comparison between these two
    entities only, not a league percentile (no full-D-I player-level
    percentile source exists yet - see HANDOFF.md's parked items). Hover
    any vertex for the raw value.
    """
    n = len(axes)
    if n < 3:
        return
    W = H = 460
    cx, cy = W / 2, H / 2 + 2
    radius = 158
    color_a = color_a or C['primary']
    color_b = color_b or C['secondary']

    def _v(values, label):
        val = values.get(label)
        return 0.0 if val is None or pd.isna(val) else float(val)

    a_vals = [_v(values_a, ax) for ax in axes]
    b_vals = [_v(values_b, ax) for ax in axes]
    peaks = [max(a_vals[i], b_vals[i], 1e-9) * 1.15 for i in range(n)]

    def point(i, frac):
        angle = -math.pi / 2 + 2 * math.pi * i / n
        r = radius * max(0.0, min(1.0, frac))
        return cx + r * math.cos(angle), cy + r * math.sin(angle)

    parts = [
        f"<svg viewBox='0 0 {W} {H}' xmlns='http://www.w3.org/2000/svg' "
        f"style='width:100%; max-width:460px; height:auto; font-family:{_BODY_FONT}; display:block; margin:0 auto;'>"
    ]
    for frac in (0.33, 0.66, 1.0):
        ring = " ".join(f"{point(i, frac)[0]:.1f},{point(i, frac)[1]:.1f}" for i in range(n))
        parts.append(f"<polygon points='{ring}' fill='none' stroke='{C['outline_variant']}' stroke-width='1'/>")
    for i in range(n):
        x, y = point(i, 1.0)
        parts.append(f"<line x1='{cx:.1f}' y1='{cy:.1f}' x2='{x:.1f}' y2='{y:.1f}' stroke='{C['outline_variant']}' stroke-width='1'/>")

    for i, label in enumerate(axes):
        lx, ly = point(i, 1.22)
        angle = -math.pi / 2 + 2 * math.pi * i / n
        anchor = 'start' if math.cos(angle) > 0.3 else 'end' if math.cos(angle) < -0.3 else 'middle'
        parts.append(
            f"<text x='{lx:.1f}' y='{ly:.1f}' text-anchor='{anchor}' dominant-baseline='middle' "
            f"font-size='11' font-weight='600' fill='{C['on_surface_variant']}'>{_esc(label)}</text>"
        )

    def draw_entity(vals, color, name):
        pts, dots = [], []
        for i in range(n):
            frac = vals[i] / peaks[i] if peaks[i] else 0.0
            x, y = point(i, frac)
            pts.append(f"{x:.1f},{y:.1f}")
            dots.append((x, y, axes[i], vals[i]))
        parts.append(
            f"<polygon points='{' '.join(pts)}' fill='{color}' fill-opacity='0.16' "
            f"stroke='{color}' stroke-width='2.2' stroke-linejoin='round'/>"
        )
        for x, y, label, v in dots:
            parts.append(
                f"<circle class='hz-dot' cx='{x:.1f}' cy='{y:.1f}' r='3.6' fill='{color}' stroke='{C['surface']}' stroke-width='1'>"
                f"<title>{_esc(name)} — {_esc(label)}: {v:.1f}</title></circle>"
            )

    draw_entity(a_vals, color_a, name_a)
    draw_entity(b_vals, color_b, name_b)

    parts.append(f"<text x='4' y='{H - 6}' font-size='12' font-weight='700' fill='{color_a}'>● {_esc(name_a)}</text>")
    parts.append(f"<text x='{W - 4}' y='{H - 6}' text-anchor='end' font-size='12' font-weight='700' fill='{color_b}'>● {_esc(name_b)}</text>")
    parts.append("</svg>")
    st.markdown("".join(parts), unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Percentile heatmap (team x stat grid, D-I percentile-colored)
# ---------------------------------------------------------------------------

def render_percentile_heatmap(pct_df, raw_df, cols, col_labels=None, sort_by_avg=True, show_values=True):
    """
    Team x stat-column percentile grid - each cell colored by D-I percentile
    (get_grade_color's diverging scale) for a "whole league at a glance"
    tiering view. `pct_df`/`raw_df`: same-shape DataFrames sharing a 'Team'
    column plus `cols` (see data.transforms.four_factors_percentile_grid) -
    pct_df drives cell color, raw_df drives the tooltip's raw value.
    `col_labels`: optional {col: shorter_display_label} override.
    `sort_by_avg`: rank rows by mean percentile (best profile first) rather
    than whatever order the input arrived in. `show_values=True` prints the
    actual stat number inside each cell (not just color) - the color alone
    tells you good/bad but not the number behind it, which was hard to
    reconstruct without hovering every cell one at a time.
    """
    if pct_df is None or pct_df.empty or not cols:
        return
    col_labels = col_labels or {}
    work = pct_df.copy()
    work['_avg'] = work[cols].mean(axis=1, skipna=True)
    if sort_by_avg:
        work = work.sort_values('_avg', ascending=False)
    raw_by_team = raw_df.set_index('Team') if raw_df is not None and not raw_df.empty else pd.DataFrame()

    n_rows, n_cols = len(work), len(cols)
    ROW_H, CELL_W, LABEL_W, HEADER_H, MR = 26, 74, 132, 78, 60
    W = LABEL_W + CELL_W * n_cols + MR  # MR: room for the last rotated column header's overhang
    H = HEADER_H + ROW_H * n_rows + 6

    parts = [
        f"<svg viewBox='0 0 {W} {H}' xmlns='http://www.w3.org/2000/svg' "
        f"style='width:100%; height:auto; font-family:{_BODY_FONT};'>"
    ]
    for j, col in enumerate(cols):
        col_x = LABEL_W + CELL_W * j + CELL_W / 2
        label = col_labels.get(col, col)
        parts.append(
            f"<text x='{col_x:.1f}' y='{HEADER_H - 14}' text-anchor='start' font-size='10.5' font-weight='700' "
            f"letter-spacing='0.02em' fill='{C['on_surface_variant']}' "
            f"transform='rotate(-28 {col_x:.1f} {HEADER_H - 14})'>{_esc(label)}</text>"
        )
    for i, (_, row) in enumerate(work.iterrows()):
        team = row['Team']
        y = HEADER_H + ROW_H * i
        parts.append(
            f"<text x='{LABEL_W - 8}' y='{y + ROW_H / 2 + 4:.1f}' text-anchor='end' font-size='11' "
            f"font-weight='600' fill='{C['on_surface']}'>{_esc(team)}</text>"
        )
        raw_row = raw_by_team.loc[team] if team in raw_by_team.index else None
        for j, col in enumerate(cols):
            pct = row[col]
            x = LABEL_W + CELL_W * j
            color = get_grade_color(pct) if pd.notna(pct) else C['surface_container_high']
            raw_val = raw_row[col] if raw_row is not None else None
            if raw_val is not None and pd.notna(raw_val):
                tooltip = f"{team} — {col_labels.get(col, col)}: {raw_val:.1f}"
            else:
                tooltip = f"{team} — {col_labels.get(col, col)}: --"
            if pd.notna(pct):
                tooltip += f" ({pct:.0f}th pctl)"
            parts.append(
                f"<rect class='hz-cell' x='{x + 2:.1f}' y='{y + 3:.1f}' width='{CELL_W - 4:.1f}' height='{ROW_H - 6:.1f}' rx='3' "
                f"fill='{color}'><title>{_esc(tooltip)}</title></rect>"
            )
            if show_values and raw_val is not None and pd.notna(raw_val):
                decimals = 2 if 'TO' in col else 1
                parts.append(
                    f"<text x='{x + CELL_W / 2:.1f}' y='{y + ROW_H / 2 + 4:.1f}' text-anchor='middle' "
                    f"font-size='10.5' font-weight='700' font-family='{_MONO_FONT}' fill='#ffffff' "
                    # pointer-events:none so hovering the printed number
                    # still resolves to the cell rect underneath it (drawn
                    # first, so it'd otherwise be occluded by this text and
                    # never receive the :hover highlight when the mouse is
                    # directly over the digits).
                    f"style='paint-order:stroke; stroke:rgba(0,0,0,0.35); stroke-width:2px; pointer-events:none;'>"
                    f"{raw_val:.{decimals}f}<title>{_esc(tooltip)}</title></text>"
                )
    parts.append("</svg>")
    st.markdown("".join(parts), unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Prop line-shopping strip (per-book price/line comparison for one bet)
# ---------------------------------------------------------------------------

def render_prop_line_shop(rows):
    """
    Horizontal book-by-book comparison for ONE prop bet (a single Market +
    Player + Selection combo, already filtered to that by the caller - see
    ui/tabs/live_odds.py). `rows`: list of {'book', 'line', 'odds'} dicts.
    Sorted best-price-first (for American odds, numerically larger is
    always the better price for the bettor - true whether the price is
    positive or negative) with the best price highlighted, so "which book
    has the number" reads at a glance without cross-referencing the wide
    comparison table by hand.
    """
    valid = [r for r in rows if r.get('odds') is not None and pd.notna(r.get('odds'))]
    if not valid:
        return
    valid.sort(key=lambda r: r['odds'], reverse=True)
    best_odds = valid[0]['odds']

    ROW_H, W = 30, 860
    H = ROW_H * len(valid) + 14
    label_w, bar_zone_w = 160, 300
    max_abs = max(abs(r['odds']) for r in valid) or 1
    parts = [
        f"<svg viewBox='0 0 {W} {H}' xmlns='http://www.w3.org/2000/svg' "
        f"style='width:100%; height:auto; font-family:{_BODY_FONT};'>"
    ]
    for i, r in enumerate(valid):
        y = 8 + ROW_H * i
        cy = y + ROW_H / 2
        is_best = r['odds'] == best_odds
        color = C['primary'] if is_best else C['secondary']
        bar_len = max(6.0, bar_zone_w * abs(r['odds']) / max_abs)
        has_line = r.get('line') is not None and pd.notna(r.get('line'))
        line_txt = f" ({r['line']:g})" if has_line else ""
        odds_txt = f"{int(r['odds']):+d}"
        parts.append(
            f"<text x='{label_w - 8}' y='{cy + 4:.1f}' text-anchor='end' font-size='11.5' "
            f"font-weight='{700 if is_best else 500}' fill='{C['on_surface'] if is_best else C['on_surface_variant']}'>"
            f"{_esc(r['book'])}{' ★' if is_best else ''}</text>"
        )
        parts.append(
            f"<rect class='hz-bar' x='{label_w}' y='{cy - 7:.1f}' width='{bar_len:.1f}' height='14' rx='3' fill='{color}' "
            f"opacity='{1.0 if is_best else 0.55}'><title>{_esc(r['book'])}: {odds_txt}{line_txt}</title></rect>"
        )
        parts.append(
            f"<text x='{label_w + bar_len + 8:.1f}' y='{cy + 4:.1f}' font-size='11' font-family='{_MONO_FONT}' "
            f"font-weight='{700 if is_best else 400}' fill='{C['on_surface']}'>{odds_txt}{line_txt}</text>"
        )
    parts.append("</svg>")
    st.markdown("".join(parts), unsafe_allow_html=True)
