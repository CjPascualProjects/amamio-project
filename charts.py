"""Small server-rendered SVG charts for the reports.

Drawn to one set of rules: thin columns (max 24px) with a 4px rounded top
and a square base, a 2px card-coloured gap between stacked segments,
hairline solid gridlines, compact y-axis ticks, and every mark carrying a
``data-tip`` that the shared hover tooltip (static/js/app.js) shows.  Colour
belongs to the series (a platform keeps its colour everywhere); text always
uses the text colours, never the series colour.
"""
from markupsafe import Markup, escape

# Theme variables (static/css/style.css), so charts follow light / dark.
GRID = "var(--viz-grid)"
AXIS = "var(--viz-axis)"
MUTED = "var(--viz-text)"
OTHER = "var(--plat-other)"


def _nice_max(value):
    """Round an axis maximum up to 1, 2, 2.5 or 5 x 10^n."""
    if value <= 0:
        return 1.0
    magnitude = 10 ** (len(str(int(value))) - 1)
    for step in (1, 2, 2.5, 5, 10):
        if value <= step * magnitude:
            return step * magnitude
    return 10 * magnitude


def _compact(value):
    value = float(value)
    if abs(value) >= 1_000_000:
        return ("%.1fM" % (value / 1_000_000)).replace(".0M", "M")
    if abs(value) >= 1000:
        return ("%.1fK" % (value / 1000)).replace(".0K", "K")
    return "%g" % round(value, 1)


def _peso(value):
    return "₱{:,.2f}".format(float(value or 0))


def _top_rounded_rect(x, y, w, h, r, fill, tip):
    """A column segment with rounded top corners and a square bottom."""
    r = min(r, w / 2.0, h)
    path = ("M{x0},{yb} L{x0},{yr} Q{x0},{yt} {xr0},{yt} L{xr1},{yt} "
            "Q{x1},{yt} {x1},{yr} L{x1},{yb} Z").format(
        x0=x, x1=x + w, yt=y, yb=y + h, yr=y + r, xr0=x + r, xr1=x + w - r)
    return ('<path d="%s" style="fill:%s" data-tip="%s" class="viz-mark"/>'
            % (path, fill, escape(tip)))


def stacked_columns(periods, series, colors, height=260, money=True):
    """periods: [{"label", "net", "by_platform": {series: value}}]
    series: ordered series names (fixed order, so colours never move)."""
    if not periods:
        return Markup("")
    left, right, top, bottom = 56, 12, 14, 34
    # A fixed drawing width: few periods keep thin columns rather than being
    # stretched; many periods get narrower slots (and a wider drawing).
    width = max(820, left + right + 22 * len(periods))
    slot = min(72.0, (width - left - right) / float(max(1, len(periods))))
    plot_h = height - top - bottom
    peak = _nice_max(max(p["net"] for p in periods))
    bar_w = min(24.0, slot * 0.6)
    fmt = _peso if money else (lambda v: "%g" % v)

    out = ['<svg viewBox="0 0 %d %d" role="img" aria-label="Net sales per period" '
           'preserveAspectRatio="xMinYMin meet" class="viz">' % (width, height)]
    # Gridlines + y ticks (4 steps).
    for i in range(5):
        value = peak * i / 4.0
        y = top + plot_h - plot_h * value / peak
        out.append('<line x1="%d" x2="%d" y1="%.1f" y2="%.1f" style="stroke:%s" '
                   'stroke-width="1"/>' % (left, width - right, y, y,
                                           AXIS if i == 0 else GRID))
        out.append('<text x="%d" y="%.1f" text-anchor="end" font-size="11" '
                   'style="fill:%s" dominant-baseline="middle">%s</text>'
                   % (left - 8, y, MUTED, ("₱" if money else "") + _compact(value)))
    # Label every period when they fit, otherwise every n-th.
    every = max(1, int(len(periods) / max(1, (width - left) / 70.0)) + 1)
    for i, p in enumerate(periods):
        cx = left + slot * i + slot / 2.0
        x = cx - bar_w / 2.0
        y_cursor = top + plot_h
        stack = [(s, p["by_platform"].get(s, 0.0)) for s in series
                 if p["by_platform"].get(s, 0.0) > 0]
        for j, (name, value) in enumerate(stack):
            h = plot_h * value / peak
            is_top = j == len(stack) - 1
            gap = 0 if j == 0 else 2          # surface gap between segments
            seg_h = max(0.0, h - gap)
            y = y_cursor - h
            tip = "%s · %s: %s" % (p["label"], name, fmt(value))
            if is_top:
                out.append(_top_rounded_rect(x, y, bar_w, seg_h, 4,
                                             colors.get(name, OTHER), tip))
            else:
                out.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" '
                           'style="fill:%s" data-tip="%s" class="viz-mark"/>'
                           % (x, y, bar_w, seg_h, colors.get(name, OTHER),
                              escape(tip)))
            y_cursor -= h
        # Whole-column hit target, larger than the mark, with the total.
        out.append('<rect x="%.1f" y="%d" width="%.1f" height="%d" fill="transparent" '
                   'data-tip="%s" class="viz-hit"/>'
                   % (left + slot * i, top, slot, plot_h,
                      escape("%s — total %s" % (p["label"], fmt(p["net"])))))
        if i % every == 0:
            out.append('<text x="%.1f" y="%d" text-anchor="middle" font-size="11" '
                       'style="fill:%s">%s</text>' % (cx, height - 12, MUTED,
                                                escape(p["label"])))
    out.append("</svg>")
    return Markup("".join(out))


def hbars(rows, label_key, value_key, color_key=None, color="var(--gold)",
          money=True, limit=10, wide_labels=False):
    """Horizontal bars as HTML (label · bar · value), one colour per row
    when ``color_key`` is given, else a single colour."""
    rows = [r for r in rows if float(r.get(value_key) or 0) > 0][:limit]
    if not rows:
        return Markup("")
    top = max(float(r[value_key]) for r in rows)
    fmt = _peso if money else (lambda v: "{:,.0f}".format(v))
    parts = ['<div class="bars%s">' % (" bars-wide" if wide_labels else "")]
    for r in rows:
        value = float(r[value_key])
        fill = r.get(color_key) if color_key else color
        parts.append(
            '<div class="bar-row" data-tip="%s"><span class="bar-label" title="%s">%s</span>'
            '<span class="bar-track"><span class="bar-fill" style="width:%.1f%%;'
            'background:%s"></span></span><span class="bar-value">%s</span></div>'
            % (escape("%s: %s" % (r[label_key], fmt(value))), escape(r[label_key]),
               escape(r[label_key]), 100.0 * value / top, fill, fmt(value)))
    parts.append("</div>")
    return Markup("".join(parts))
