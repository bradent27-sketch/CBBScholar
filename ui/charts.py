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
                f"<rect x='{x0:.1f}' y='{cy - bar_h / 2:.1f}' width='{bar_len:.1f}' height='{bar_h}' rx='3' "
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
            f"<span title='{_esc(tooltip)}' style='display:inline-flex; flex-direction:column; align-items:center; "
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
                parts.append(f"<circle cx='{x:.1f}' cy='{yv:.1f}' r='3' fill='{color}'/>")
            else:
                d = " ".join(f"{x:.1f},{yv:.1f}" for x, yv in seg)
                parts.append(f"<polyline points='{d}' fill='none' stroke='{color}' stroke-width='2.2' stroke-linejoin='round' stroke-linecap='round' opacity='0.9'/>")
        for o, v in series.items():
            if pd.isna(v):
                continue
            parts.append(
                f"<circle cx='{xs[o]:.1f}' cy='{y_for(v):.1f}' r='3.4' fill='{color}' stroke='{C['surface']}' stroke-width='1'>"
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
            f"<rect x='{x:.1f}' y='{y:.1f}' width='{bar_w:.1f}' height='{h:.1f}' rx='3' fill='{fill}' "
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
    parts.append(
        f"<text x='{W - MR - 4}' y='{MT + 14}' text-anchor='end' font-size='10.5' font-weight='700' "
        f"letter-spacing='0.06em' fill='{C['on_surface_variant']}' opacity='0.8'>ELITE BOTH WAYS ↗</text>"
    )
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
            f"<circle cx='{px(row[x_col]):.1f}' cy='{py(row[y_col]):.1f}' r='4.2' fill='{color}' "
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
            f"<circle cx='{x:.1f}' cy='{yv:.1f}' r='7' fill='{color}' stroke='#ffffff' stroke-width='1.6'>"
            f"<title>{_esc(team)} — {x_col}: {row[x_col]:.1f}, {y_col}: {row[y_col]:.1f}</title></circle>"
        )
        parts.append(
            f"<text x='{x + 10:.1f}' y='{yv + 4:.1f}' font-size='11.5' font-weight='700' fill='#ffffff' "
            f"style='paint-order:stroke; stroke:{C['surface']}; stroke-width:3px;'>{_esc(team)}</text>"
        )
    parts.append("</svg>")
    st.markdown("".join(parts), unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Statistical-identity radar ("shape" of a team/player across N dimensions)
# ---------------------------------------------------------------------------

def render_radar_chart(labels, series, help_texts=None):
    """
    Multi-axis percentile radar, up to a few overlaid series. `labels`: N
    axis names around the ring. `series`: [{'name', 'color', 'values'}, ...]
    - `values` are 0-100 (percentiles), same order/length as `labels`, so
    every axis shares one scale regardless of the underlying stat's own
    units. `help_texts`: optional per-axis tooltip strings (same order as
    `labels`). Sport-agnostic like every other chart here - which stats
    become axes, and what "100" means for each, is entirely the caller's
    call (see data/transforms.py's profile builder).
    """
    n = len(labels)
    if n < 3 or not series:
        return
    help_texts = help_texts or [''] * n
    W, H = 860, 520
    cx, cy = W / 2, H / 2 - 6
    R = 185

    def angle(i):
        return -math.pi / 2 + i * 2 * math.pi / n

    def point(i, val):
        r = R * max(0.0, min(100.0, val)) / 100.0
        a = angle(i)
        return cx + r * math.cos(a), cy + r * math.sin(a)

    parts = [
        f"<svg viewBox='0 0 {W} {H}' xmlns='http://www.w3.org/2000/svg' "
        f"style='width:100%; height:auto; font-family:{_BODY_FONT};'>"
    ]
    # Grid rings (25/50/75/100) + spokes
    for ring in (25, 50, 75, 100):
        pts = " ".join(f"{point(i, ring)[0]:.1f},{point(i, ring)[1]:.1f}" for i in range(n))
        dash = "none" if ring == 100 else "3,4"
        parts.append(f"<polygon points='{pts}' fill='none' stroke='{C['outline_variant']}' stroke-width='1' stroke-dasharray='{dash}'/>")
    for i in range(n):
        ex, ey = point(i, 100)
        parts.append(f"<line x1='{cx:.1f}' y1='{cy:.1f}' x2='{ex:.1f}' y2='{ey:.1f}' stroke='{C['outline_variant']}' stroke-width='1'/>")
        lx, ly = point(i, 118)
        anchor = 'middle' if abs(lx - cx) < 8 else ('start' if lx > cx else 'end')
        baseline = ly + (10 if ly > cy + 8 else (-4 if ly < cy - 8 else 4))
        parts.append(
            f"<text x='{lx:.1f}' y='{baseline:.1f}' text-anchor='{anchor}' font-size='11' font-weight='600' "
            f"fill='{C['on_surface_variant']}'>{_esc(labels[i])}"
            f"<title>{_esc(help_texts[i] if i < len(help_texts) else '')}</title></text>"
        )
    # Series polygons (drawn after the grid so they sit on top)
    for s in series:
        color = s.get('color') or C['primary']
        vals = s['values']
        pts = [point(i, vals[i]) for i in range(n) if vals[i] is not None and not pd.isna(vals[i])]
        if len(pts) < 3:
            continue
        d = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
        parts.append(f"<polygon points='{d}' fill='{color}' fill-opacity='0.16' stroke='{color}' stroke-width='2.2' stroke-linejoin='round'/>")
        for i in range(n):
            v = vals[i]
            if v is None or pd.isna(v):
                continue
            x, y = point(i, v)
            parts.append(
                f"<circle cx='{x:.1f}' cy='{y:.1f}' r='3.6' fill='{color}' stroke='{C['surface']}' stroke-width='1'>"
                f"<title>{_esc(s.get('name', ''))} — {_esc(labels[i])}: {v:.0f}th percentile</title></circle>"
            )
    # Legend
    if len(series) > 1:
        lx = cx - (len(series) - 1) * 70
        for s in series:
            color = s.get('color') or C['primary']
            parts.append(f"<circle cx='{lx:.1f}' cy='{H - 14}' r='5' fill='{color}'/>")
            parts.append(f"<text x='{lx + 10:.1f}' y='{H - 10}' font-size='12' font-weight='600' fill='{C['on_surface']}'>{_esc(s.get('name', ''))}</text>")
            lx += 140
    parts.append("</svg>")
    st.markdown("".join(parts), unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Signed correlation bars ("what actually correlates with winning")
# ---------------------------------------------------------------------------

def render_correlation_bars(rows):
    """
    Horizontal bars diverging from a center zero-line - one row per stat,
    bar length/direction = its correlation with the season's Net Rating
    (see data/transforms.stat_win_correlations). `rows`: [{'label', 'help',
    'display_r', 'neutral', 'n'}, ...]. `display_r` in [-1, 1]: positive
    (green) = being GOOD at this stat associates with winning this season;
    negative (red) = counterintuitively associates with losing. `neutral`
    rows (style/tempo stats with no inherent good direction, e.g. pace) get
    a neutral color instead of green/red since sign there means direction
    of correlation, not good/bad.
    """
    if not rows:
        return
    W, ROW_H, LABEL_W = 860, 32, 190
    half = (W - 40) / 2
    cx = LABEL_W + half
    H = ROW_H * len(rows) + 20
    parts = [
        f"<svg viewBox='0 0 {W} {H}' xmlns='http://www.w3.org/2000/svg' "
        f"style='width:100%; height:auto; font-family:{_BODY_FONT};'>"
    ]
    parts.append(f"<line x1='{cx:.1f}' y1='4' x2='{cx:.1f}' y2='{H - 4}' stroke='{C['outline_variant']}' stroke-width='1'/>")
    max_bar = half - 46
    y = 0
    for r in rows:
        cy = y + ROW_H / 2
        val = r.get('display_r') or 0.0
        bar_len = max_bar * min(abs(val), 1.0)
        if r.get('neutral'):
            color = C['tertiary']
        else:
            color = C['positive'] if val >= 0 else C['negative']
        x0 = cx if val >= 0 else cx - bar_len
        tooltip = f"{r['label']}: r = {val:+.2f} (n={r.get('n', '?')} teams) — {r.get('help', '')}"
        parts.append(
            f"<text x='{LABEL_W - 10}' y='{cy + 4:.1f}' text-anchor='end' font-size='11.5' font-weight='600' "
            f"fill='{C['on_surface']}'>{_esc(r['label'])}<title>{_esc(tooltip)}</title></text>"
        )
        parts.append(
            f"<rect x='{x0:.1f}' y='{cy - 9:.1f}' width='{max(bar_len, 2.0):.1f}' height='18' rx='3' fill='{color}'>"
            f"<title>{_esc(tooltip)}</title></rect>"
        )
        label_x = x0 + bar_len + 8 if val >= 0 else x0 - 8
        anchor = 'start' if val >= 0 else 'end'
        parts.append(
            f"<text x='{label_x:.1f}' y='{cy + 4:.1f}' text-anchor='{anchor}' font-size='10.5' "
            f"font-family='{_MONO_FONT}' fill='{C['on_surface_variant']}'>{val:+.2f}</text>"
        )
        y += ROW_H
    parts.append("</svg>")
    st.markdown("".join(parts), unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Season margin trend (win/loss margin per game, zero-centered)
# ---------------------------------------------------------------------------

def render_margin_chart(games):
    """
    One bar per completed game (season order), height/direction = scoring
    margin, split at a zero baseline (win margin up in `positive`, loss
    margin down in `negative`) so a season's shape - steady vs. streaky,
    building vs. fading - reads at a glance. `games`: [{'margin',
    'tooltip'}, ...] in chronological order.
    """
    if not games:
        return
    W, H, MB, MT = 860, 220, 22, 16
    plot_h = H - MB - MT
    zero_y = MT + plot_h / 2
    n = len(games)
    slot = W / n
    bar_w = min(40.0, slot * 0.62)
    vmax = max(abs(g['margin']) for g in games) or 1
    scale = (plot_h / 2) / vmax
    parts = [
        f"<svg viewBox='0 0 {W} {H}' xmlns='http://www.w3.org/2000/svg' "
        f"style='width:100%; height:auto; font-family:{_BODY_FONT};'>"
    ]
    parts.append(f"<line x1='0' y1='{zero_y:.1f}' x2='{W}' y2='{zero_y:.1f}' stroke='{C['outline_variant']}' stroke-width='1.2'/>")
    for i, g in enumerate(games):
        margin = g['margin']
        h = abs(margin) * scale
        x = slot * i + (slot - bar_w) / 2
        is_win = margin > 0
        y = zero_y - h if is_win else zero_y
        color = C['positive'] if is_win else C['negative']
        parts.append(
            f"<rect x='{x:.1f}' y='{y:.1f}' width='{bar_w:.1f}' height='{max(h, 1.5):.1f}' rx='2.5' fill='{color}' opacity='0.85'>"
            f"<title>{_esc(g['tooltip'])}</title></rect>"
        )
    parts.append("</svg>")
    st.markdown("".join(parts), unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Role/tendency badges (see data.transforms.classify_player_role)
# ---------------------------------------------------------------------------

def render_role_badges(primary_role, secondary_badges=None, primary_color=None):
    """
    Primary role pill (filled, accent-colored) + secondary tendency badges
    (outlined) - see data.transforms.classify_player_role for what feeds
    this. `primary_color`: optional override (e.g. team color) for the
    filled pill; defaults to THEME's primary accent.
    """
    if not primary_role:
        st.caption("Not enough minutes this season to classify a role.")
        return
    color = primary_color or C['primary']
    chips = [
        f"<span style='display:inline-flex; align-items:center; padding:4px 12px; border-radius:999px; "
        f"background:{color}; color:{C['on_primary']}; font-size:11.5px; font-weight:800; "
        f"text-transform:uppercase; letter-spacing:0.04em; margin-right:6px;'>{_esc(primary_role)}</span>"
    ]
    for b in (secondary_badges or []):
        chips.append(
            f"<span style='display:inline-flex; align-items:center; padding:4px 11px; border-radius:999px; "
            f"background:transparent; border:1px solid {C['outline_variant']}; color:{C['on_surface_variant']}; "
            f"font-size:11px; font-weight:600; margin-right:6px;'>{_esc(b)}</span>"
        )
    st.markdown(f"<div style='margin:6px 0 10px 0;'>{''.join(chips)}</div>", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Rate-stat / allowed-by-role trend (game-by-game + trailing rolling avg)
# ---------------------------------------------------------------------------

def render_trend_line(labels, values, window=5, unit=''):
    """
    Game-by-game dots plus a trailing `window`-game rolling-average line and
    a dashed season-average reference - the shape that makes a mid-season
    role/scheme change visible (the rolling line breaks away from the
    season-average dashes) before it moves the season number itself. Used
    for both a player's rate-stat trend (Usage%, 3PA Rate) and a defense's
    allowed-by-role trend (data.transforms.defense_role_game_series).
    `labels`: per-game hover text (e.g. dates); `values`: same-length
    numeric series, None for a game with no data.
    """
    n = len(values)
    if n < 2:
        return
    finite = [v for v in values if v is not None and not pd.isna(v)]
    if len(finite) < 2:
        return
    W, H = 860, 190
    ML, MR, MT, MB = 42, 12, 14, 24
    plot_w, plot_h = W - ML - MR, H - MT - MB
    vmin, vmax = min(finite), max(finite)
    vmin = min(vmin, 0)
    pad = (vmax - vmin) * 0.12 or 1
    vmin, vmax = vmin - pad, vmax + pad

    def px(i):
        return ML + plot_w * i / max(n - 1, 1)

    def py(v):
        return MT + plot_h * (1 - (v - vmin) / (vmax - vmin))

    roll = []
    for i in range(n):
        lo = max(0, i - window + 1)
        window_vals = [v for v in values[lo:i + 1] if v is not None and not pd.isna(v)]
        roll.append(sum(window_vals) / len(window_vals) if window_vals else None)

    season_avg = sum(finite) / len(finite)

    parts = [
        f"<svg viewBox='0 0 {W} {H}' xmlns='http://www.w3.org/2000/svg' "
        f"style='width:100%; height:auto; font-family:{_BODY_FONT};'>"
    ]
    ay = py(season_avg)
    parts.append(f"<line x1='{ML}' y1='{ay:.1f}' x2='{W - MR}' y2='{ay:.1f}' stroke='{C['on_surface_variant']}' stroke-width='1' stroke-dasharray='4,4' opacity='0.7'/>")
    parts.append(
        f"<text x='{W - MR}' y='{ay - 5:.1f}' text-anchor='end' font-size='10' font-family='{_MONO_FONT}' "
        f"fill='{C['on_surface_variant']}'>season avg {season_avg:.1f}{unit}</text>"
    )
    for i, v in enumerate(values):
        if v is None or pd.isna(v):
            continue
        parts.append(
            f"<circle cx='{px(i):.1f}' cy='{py(v):.1f}' r='3' fill='{C['secondary']}' opacity='0.65'>"
            f"<title>{_esc(labels[i] if i < len(labels) else '')}: {v:.1f}{unit}</title></circle>"
        )
    roll_pts = [(px(i), py(r)) for i, r in enumerate(roll) if r is not None]
    if len(roll_pts) >= 2:
        d = " ".join(f"{x:.1f},{y:.1f}" for x, y in roll_pts)
        parts.append(f"<polyline points='{d}' fill='none' stroke='{C['primary']}' stroke-width='2.4' stroke-linejoin='round' stroke-linecap='round'/>")
        lx, ly = roll_pts[-1]
        parts.append(f"<circle cx='{lx:.1f}' cy='{ly:.1f}' r='3.6' fill='{C['primary']}' stroke='{C['surface']}' stroke-width='1'/>")
        parts.append(
            f"<text x='{lx:.1f}' y='{ly - 8:.1f}' text-anchor='end' font-size='10.5' font-weight='700' "
            f"font-family='{_MONO_FONT}' fill='{C['primary']}'>{roll[-1]:.1f}{unit}</text>"
        )
    parts.append(
        f"<text x='{ML}' y='{H - 6}' font-size='10' fill='{C['on_surface_variant']}'>oldest</text>"
        f"<text x='{W - MR}' y='{H - 6}' text-anchor='end' font-size='10' fill='{C['on_surface_variant']}'>most recent</text>"
    )
    parts.append("</svg>")
    st.markdown("".join(parts), unsafe_allow_html=True)
