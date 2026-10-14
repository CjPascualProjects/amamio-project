"""Offline, dependency-free AI/analytics engine for the IMS.

Everything here is pure Python (no numpy / scikit-learn / network) so the system
runs fully offline.  It provides:

  * server-rendered inline-SVG charts (no JS chart libraries),
  * heuristic weekly demand forecasting with confidence bands,
  * material stockout-risk projection through the BOM,
  * reorder / production / stockout-overstock / trend / anomaly recommendations,
  * a keyword-routed natural-language chatbot over live data.

Weekly series use ISO year-week labels ('YYYY-Www') and are gap-filled with 0.
"""
import math
from datetime import date, datetime

import db

# --- Palette (Amamio brand: black and white, gold as the accent) ----------
# Charts sit on near-black cards.  Series use gold, white and muted golds only
# — no other hues — so the charts read as part of the brand, not a rainbow.
PALETTE = ["#d4af37", "#f5f5f5", "#8a7330", "#e9d9a6", "#b8892a", "#a3a3a3",
           "#f0d27a"]
GREEN = "#d4af37"          # default line accent (gold)
AMBER = "#e9d9a6"
VIOLET = "#8a7330"         # production series (deep gold)
BLUE = "#f0d27a"
MAGENTA = "#e9d9a6"
GRID = "rgba(255,255,255,.06)"
AXIS = "#8a8a8a"
BAND_FILL = "rgba(212,175,55,.16)"
DANGER = "#e5735f"
WARN = "#e9d9a6"
OK = "#d4af37"

PERIODS = 4          # forecast horizon (weeks)
Z = 1.96             # 95% confidence


def model_backend():
    return "heuristic (naive / moving-average / linear-trend)"


# ==========================================================================
#  Small helpers
# ==========================================================================
def _f(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _esc(s):
    return (str("" if s is None else s)
            .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


def _fmt(n):
    n = _f(n)
    r = round(n, 3)
    return ("%g" % r)


def _parse_dt(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        try:
            return datetime.fromisoformat(str(s)[:19])
        except ValueError:
            return None


def _week_monday(dt):
    y, w, _ = dt.isocalendar()
    return date.fromisocalendar(y, w, 1)


def _week_label(d):
    y, w, _ = d.isocalendar()
    return "%04d-W%02d" % (y, w)


def _weekly_series(records, date_key, value_fn):
    """Bucket records into gap-filled weekly (label, value) pairs."""
    buckets = {}
    for r in records:
        dt = _parse_dt(r.get(date_key))
        if dt is None:
            continue
        monday = _week_monday(dt)
        buckets[monday] = buckets.get(monday, 0.0) + _f(value_fn(r))
    if not buckets:
        return []
    start, end = min(buckets), max(buckets)
    series = []
    cur = start
    guard = 0
    while cur <= end and guard < 5000:
        series.append((_week_label(cur), round(buckets.get(cur, 0.0), 6)))
        cur = date.fromordinal(cur.toordinal() + 7)
        guard += 1
    return series


def _next_week_labels(last_label, periods):
    try:
        y, w = last_label.split("-W")
        d = date.fromisocalendar(int(y), int(w), 1)
    except (ValueError, AttributeError):
        return ["W+%d" % k for k in range(1, periods + 1)]
    out = []
    for _ in range(periods):
        d = date.fromordinal(d.toordinal() + 7)
        out.append(_week_label(d))
    return out


# ==========================================================================
#  Data series
# ==========================================================================
def weekly_demand(product_id):
    """Weekly demand for a product from sales_requests (non-rejected); falls
    back to negated 'sold' inventory transactions if there are no requests."""
    reqs = [r for r in db.read("sales_requests")
            if r.get("product_id") == product_id and r.get("status") != "Rejected"]
    if reqs:
        return _weekly_series(reqs, "created_at", lambda r: r.get("qty", 0))
    sold = [t for t in db.read("inventory_transactions")
            if t.get("item_type") == "product" and t.get("item_id") == product_id
            and t.get("txn_type") == "sold"]
    return _weekly_series(sold, "timestamp", lambda t: -_f(t.get("change_qty")))


def demand_series():
    reqs = [r for r in db.read("sales_requests") if r.get("status") != "Rejected"]
    return _weekly_series(reqs, "created_at", lambda r: r.get("qty", 0))


def production_series():
    prod = [t for t in db.read("inventory_transactions")
            if t.get("item_type") == "product" and t.get("txn_type") == "produced"]
    return _weekly_series(prod, "timestamp", lambda t: _f(t.get("change_qty")))


def movement_totals():
    totals = {"Received": 0.0, "Consumed": 0.0, "Produced": 0.0, "Sold": 0.0}
    key = {"received": "Received", "consumed": "Consumed",
           "produced": "Produced", "sold": "Sold"}
    for t in db.read("inventory_transactions"):
        label = key.get(t.get("txn_type"))
        if label:
            totals[label] += abs(_f(t.get("change_qty")))
    return totals


def top_products_by_demand(n=6):
    pairs = []
    for p in db.read("products"):
        total = sum(v for _, v in weekly_demand(p["id"]))
        pairs.append((p.get("name"), round(total, 3)))
    pairs.sort(key=lambda x: x[1], reverse=True)
    return pairs[:n]


def category_breakdown():
    counts = {}
    for m in db.read("raw_materials"):
        c = m.get("category") or "other"
        counts[c] = counts.get(c, 0) + 1
    order = {"raw": 0, "cleaning": 1, "asset": 2, "other": 3}
    return sorted(counts.items(), key=lambda kv: (order.get(kv[0], 9), kv[0]))


def material_stock_pairs():
    return [(m.get("name"), round(_f(m.get("stock_qty")), 3))
            for m in db.read("raw_materials")]


# ==========================================================================
#  KPIs
# ==========================================================================
def kpis():
    products = db.read("products")
    materials = db.read("raw_materials")
    txns = db.read("inventory_transactions")
    sreqs = db.read("sales_requests")
    preqs = db.read("purchase_requests")

    def low(m):
        r = _f(m.get("reorder_level"))
        return r > 0 and _f(m.get("stock_qty")) <= r

    sold = sum(abs(_f(t.get("change_qty"))) for t in txns
               if t.get("item_type") == "product" and t.get("txn_type") == "sold")
    produced = [t for t in txns if t.get("item_type") == "product"
                and t.get("txn_type") == "produced"]
    return {
        "products": len(products),
        "materials": len(materials),
        "low_stock": sum(1 for m in materials if low(m)),
        "finished_units_in_stock": round(sum(_f(p.get("stock_qty"))
                                             for p in products), 3),
        "total_units_produced": round(sum(_f(t.get("change_qty"))
                                          for t in produced), 3),
        "total_units_sold": round(sold, 3),
        "total_sales_requests": len(sreqs),
        "fulfilled_sales": sum(1 for r in sreqs if r.get("status") == "Fulfilled"),
        "pending_sales_approvals": sum(1 for r in sreqs
                                       if r.get("status") == "Pending Approval"),
        "pending_purchase_approvals": sum(1 for r in preqs
                                          if r.get("status") == "Pending Approval"),
        "production_runs": len(db.read("production_orders")) or len(produced),
    }


# ==========================================================================
#  SVG charts
# ==========================================================================
_W = 640


def _placeholder(height, msg="No data yet"):
    return (
        '<svg viewBox="0 0 %d %d" width="100%%" role="img" aria-label="%s" '
        'xmlns="http://www.w3.org/2000/svg">'
        '<rect x="1" y="1" width="%d" height="%d" rx="10" fill="#141414" '
        'stroke="%s"/>'
        '<text x="%d" y="%d" text-anchor="middle" fill="%s" font-size="14" '
        'font-family="Montserrat,Century Gothic,Segoe UI,sans-serif">%s</text></svg>'
        % (_W, height, _esc(msg), _W - 2, height - 2, GRID,
           _W // 2, height // 2, AXIS, _esc(msg))
    )


def _axis_grid(x0, y0, x1, y1, vmax, vmin=0.0):
    parts = []
    steps = 4
    for i in range(steps + 1):
        y = y1 - (y1 - y0) * i / steps
        val = vmin + (vmax - vmin) * i / steps
        parts.append('<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" stroke="%s"/>'
                     % (x0, y, x1, y, GRID))
        parts.append('<text x="%d" y="%.1f" text-anchor="end" fill="%s" '
                     'font-size="10" font-family="Montserrat,Century Gothic,Segoe UI,sans-serif">%s</text>'
                     % (x0 - 6, y + 3, AXIS, _fmt(val)))
    return "".join(parts)


def svg_line_chart(series, color=GREEN, label="", height=260):
    if not series:
        return _placeholder(height)
    pad_l, pad_r, pad_t, pad_b = 44, 16, 16, 30
    x0, y0, x1, y1 = pad_l, pad_t, _W - pad_r, height - pad_b
    vals = [v for _, v in series]
    vmax = max(vals + [1.0]) * 1.15
    n = len(series)

    def px(i):
        return x0 if n == 1 else x0 + (x1 - x0) * i / (n - 1)

    def py(v):
        return y1 - (y1 - y0) * (v / vmax if vmax else 0)

    pts = " ".join("%.1f,%.1f" % (px(i), py(v)) for i, (_, v) in enumerate(series))
    dots = "".join(
        '<circle cx="%.1f" cy="%.1f" r="3" fill="%s"><title>%s: %s</title></circle>'
        % (px(i), py(v), color, _esc(lbl), _fmt(v))
        for i, (lbl, v) in enumerate(series))
    step = max(1, n // 8)
    xlabels = "".join(
        '<text x="%.1f" y="%d" text-anchor="middle" fill="%s" font-size="9" '
        'font-family="Montserrat,Century Gothic,Segoe UI,sans-serif">%s</text>'
        % (px(i), height - 10, AXIS, _esc(series[i][0]))
        for i in range(0, n, step))
    # Area under the line, fading from translucent gold to nothing.  The
    # gradient id is unique per chart so several charts can share a page.
    grad_id = "area%d" % (abs(hash((label, pts))) % 10 ** 8)
    area = "%.1f,%.1f %s %.1f,%.1f" % (px(0), y1, pts, px(n - 1), y1)
    return (
        '<svg viewBox="0 0 %d %d" width="100%%" role="img" aria-label="%s" '
        'xmlns="http://www.w3.org/2000/svg">'
        '<defs><linearGradient id="%s" x1="0" y1="0" x2="0" y2="1">'
        '<stop offset="0" stop-color="%s" stop-opacity=".38"/>'
        '<stop offset="1" stop-color="%s" stop-opacity="0"/>'
        '</linearGradient></defs>%s'
        '<polygon fill="url(#%s)" stroke="none" points="%s"/>'
        '<polyline fill="none" stroke="%s" stroke-width="2.5" '
        'stroke-linejoin="round" stroke-linecap="round" points="%s"/>'
        '%s%s</svg>'
        % (_W, height, _esc(label or "line chart"), grad_id, color, color,
           _axis_grid(x0, y0, x1, y1, vmax), grad_id, area, color, pts,
           dots, xlabels)
    )


def svg_bar_chart(pairs, colors=None, height=260, value_suffix=""):
    if not pairs:
        return _placeholder(height)
    pad_l, pad_r, pad_t, pad_b = 44, 16, 16, 34
    x0, y0, x1, y1 = pad_l, pad_t, _W - pad_r, height - pad_b
    vals = [v for _, v in pairs]
    vmax = max(vals + [1.0])
    vmin = min(vals + [0.0])
    span = (vmax - vmin) or 1.0
    n = len(pairs)
    gap = 10
    bw = (x1 - x0 - gap * (n + 1)) / n

    def zero_y():
        return y1 - (y1 - y0) * (0 - vmin) / span

    zy = zero_y()
    bars = []
    for i, (lbl, v) in enumerate(pairs):
        bx = x0 + gap + i * (bw + gap)
        vy = y1 - (y1 - y0) * (v - vmin) / span
        top = min(vy, zy)
        h = abs(vy - zy)
        if isinstance(colors, list):
            col = colors[i] if i < len(colors) else PALETTE[i % len(PALETTE)]
        elif isinstance(colors, str):
            col = colors
        else:
            col = GREEN
        if v < 0:
            col = DANGER
        bars.append(
            '<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" rx="4" fill="%s">'
            '<title>%s: %s%s</title></rect>'
            % (bx, top, bw, max(1.0, h), col, _esc(lbl), _fmt(v), value_suffix))
        bars.append(
            '<text x="%.1f" y="%d" text-anchor="middle" fill="%s" font-size="9" '
            'font-family="Montserrat,Century Gothic,Segoe UI,sans-serif">%s</text>'
            % (bx + bw / 2, height - 12, AXIS, _esc(lbl)))
    baseline = ('<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" stroke="%s"/>'
                % (x0, zy, x1, zy, AXIS))
    return (
        '<svg viewBox="0 0 %d %d" width="100%%" role="img" aria-label="bar chart" '
        'xmlns="http://www.w3.org/2000/svg">%s%s%s</svg>'
        % (_W, height, _axis_grid(x0, y0, x1, y1, vmax, vmin), "".join(bars),
           baseline)
    )


def svg_forecast_chart(history, future_labels, forecast, lower, upper, height=280):
    combined = list(history) + list(zip(future_labels, forecast))
    if not combined:
        return _placeholder(height)
    pad_l, pad_r, pad_t, pad_b = 44, 16, 16, 30
    x0, y0, x1, y1 = pad_l, pad_t, _W - pad_r, height - pad_b
    allvals = [v for _, v in history] + list(forecast) + list(upper)
    vmax = (max(allvals + [1.0])) * 1.15
    n = len(combined)

    def px(i):
        return x0 if n == 1 else x0 + (x1 - x0) * i / (n - 1)

    def py(v):
        return y1 - (y1 - y0) * (v / vmax if vmax else 0)

    hlen = len(history)
    band_pts = []
    for k in range(len(forecast)):
        band_pts.append((px(hlen + k), py(upper[k])))
    for k in range(len(forecast) - 1, -1, -1):
        band_pts.append((px(hlen + k), py(lower[k])))
    band = ""
    if band_pts:
        band = ('<polygon points="%s" fill="%s" stroke="none"/>'
                % (" ".join("%.1f,%.1f" % p for p in band_pts), BAND_FILL))
    hist_pts = " ".join("%.1f,%.1f" % (px(i), py(v))
                        for i, (_, v) in enumerate(history))
    fc_pairs = [(px(hlen - 1), py(history[-1][1]))] if history else []
    fc_pairs += [(px(hlen + k), py(forecast[k])) for k in range(len(forecast))]
    fc_pts = " ".join("%.1f,%.1f" % p for p in fc_pairs)
    dots = "".join(
        '<circle cx="%.1f" cy="%.1f" r="3" fill="%s"><title>%s: %s</title></circle>'
        % (px(hlen + k), py(forecast[k]), GREEN, _esc(future_labels[k]),
           _fmt(forecast[k]))
        for k in range(len(forecast)))
    step = max(1, n // 8)
    xlabels = "".join(
        '<text x="%.1f" y="%d" text-anchor="middle" fill="%s" font-size="9" '
        'font-family="Montserrat,Century Gothic,Segoe UI,sans-serif">%s</text>'
        % (px(i), height - 10, AXIS, _esc(combined[i][0]))
        for i in range(0, n, step))
    hist_line = ('<polyline fill="none" stroke="%s" stroke-width="2.5" points="%s"/>'
                 % (VIOLET, hist_pts)) if hist_pts else ""
    fc_line = ('<polyline fill="none" stroke="%s" stroke-width="2.5" '
               'stroke-dasharray="6 4" points="%s"/>' % (GREEN, fc_pts)) if fc_pts else ""
    return (
        '<svg viewBox="0 0 %d %d" width="100%%" role="img" '
        'aria-label="forecast chart" xmlns="http://www.w3.org/2000/svg">%s%s%s%s%s%s</svg>'
        % (_W, height, _axis_grid(x0, y0, x1, y1, vmax), band, hist_line,
           fc_line, dots, xlabels)
    )


def stock_status_colors():
    cols = []
    for m in db.read("raw_materials"):
        stock = _f(m.get("stock_qty"))
        reorder = _f(m.get("reorder_level"))
        if reorder > 0:
            cols.append(DANGER if stock <= reorder
                        else WARN if stock <= reorder * 1.5 else OK)
        else:
            cols.append(DANGER if stock <= 0 else OK)
    return cols


def threshold_colors(values, low=0.34, mid=0.67):
    vmax = max(values) if values else 0
    out = []
    for v in values:
        if vmax <= 0:
            out.append(OK)
        else:
            frac = v / vmax
            out.append(DANGER if frac < low else WARN if frac < mid else OK)
    return out


def overview_charts():
    top = top_products_by_demand()
    mats = material_stock_pairs()
    mv = movement_totals()
    return {
        "demand": svg_line_chart(demand_series(), label="Units requested / week"),
        "production": svg_line_chart(production_series(), color=VIOLET,
                                     label="Units produced / week"),
        "movements": svg_bar_chart(list(mv.items()),
                                   colors=[OK, WARN, VIOLET, MAGENTA]),
        "top_products": svg_bar_chart(top,
                                      colors=threshold_colors([v for _, v in top])),
        "materials": svg_bar_chart(mats, colors=stock_status_colors()),
        "categories": svg_bar_chart(category_breakdown(), colors=PALETTE),
    }


# ==========================================================================
#  Forecasting core (pure, never raises)
# ==========================================================================
def _mean(xs):
    return sum(xs) / len(xs) if xs else 0.0


def _linfit(values):
    """Least-squares slope/intercept over index 0..n-1."""
    n = len(values)
    xs = list(range(n))
    mx, my = _mean(xs), _mean(values)
    denom = sum((x - mx) ** 2 for x in xs)
    if denom == 0:
        return 0.0, my
    slope = sum((xs[i] - mx) * (values[i] - my) for i in range(n)) / denom
    return slope, my - slope * mx


def _errors(actual, fitted):
    n = len(actual)
    if n == 0:
        return 0.0, 0.0
    mae = sum(abs(actual[i] - fitted[i]) for i in range(n)) / n
    pcts = [abs(actual[i] - fitted[i]) / actual[i] for i in range(n) if actual[i]]
    mape = (sum(pcts) / len(pcts) * 100.0) if pcts else 0.0
    return mae, mape


def _forecast_series(values, periods=PERIODS):
    """Pure heuristic forecast.  Never raises; always returns a dict with
    forecast/lower/upper (len == periods, clamped >= 0), model, mae, mape, n,
    low_data."""
    values = [_f(v) for v in values]
    n = len(values)
    if n == 0:
        return {"forecast": [0.0] * periods, "lower": [0.0] * periods,
                "upper": [0.0] * periods, "model": "naive-mean", "mae": 0.0,
                "mape": 0.0, "n": 0, "low_data": True}
    if n < 2:
        base = max(0.0, values[-1])
        return {"forecast": [base] * periods, "lower": [base] * periods,
                "upper": [base] * periods, "model": "naive-mean", "mae": 0.0,
                "mape": 0.0, "n": n, "low_data": True}

    # Candidate 1: naive mean
    mean = _mean(values)
    fit_mean = [mean] * n

    # Candidate 2: moving average (window up to 4)
    w = min(4, n)
    fit_ma = []
    for i in range(n):
        window = values[max(0, i - w):i] or values[:1]
        fit_ma.append(_mean(window))
    ma_next = _mean(values[-w:])

    # Candidate 3: linear trend
    slope, intercept = _linfit(values)
    fit_lin = [intercept + slope * i for i in range(n)]

    candidates = {
        "naive-mean": (fit_mean, [mean] * periods),
        "moving-average": (fit_ma, [ma_next] * periods),
        "linear-trend": (fit_lin, [intercept + slope * (n - 1 + k)
                                   for k in range(1, periods + 1)]),
    }
    scored = {}
    for name, (fitted, fut) in candidates.items():
        mae, mape = _errors(values, fitted)
        scored[name] = (mae, mape, fitted, fut)

    variance = sum((v - mean) ** 2 for v in values) / n
    if variance == 0:
        best = "naive-mean"
        model_label = "constant"
    else:
        # prefer lowest MAPE, break ties on MAE
        best = min(scored, key=lambda k: (scored[k][1], scored[k][0]))
        model_label = best

    mae, mape, fitted, fut = scored[best]
    resid = [values[i] - fitted[i] for i in range(n)]
    std = math.sqrt(sum(r * r for r in resid) / n) if n else 0.0
    band = Z * std
    forecast = [max(0.0, round(v, 6)) for v in fut]
    lower = [max(0.0, round(v - band, 6)) for v in fut]
    upper = [round(v + band, 6) for v in fut]
    return {"forecast": forecast, "lower": lower, "upper": upper,
            "model": model_label, "mae": round(mae, 3), "mape": round(mape, 1),
            "n": n, "low_data": n < 4}


def forecast_demand(product_id, periods=PERIODS):
    product = db.get("products", product_id)
    history = weekly_demand(product_id)
    values = [v for _, v in history]
    res = _forecast_series(values, periods)
    last_label = history[-1][0] if history else _week_label(date.today())
    future_labels = _next_week_labels(last_label, periods)
    res.update({
        "product_id": product_id,
        "product_name": product.get("name") if product else "Product #%s" % product_id,
        "history": history,
        "future_labels": future_labels,
    })
    if res["n"] == 0:
        res["note"] = "No sales history yet — forecast is a flat baseline."
    elif res["low_data"]:
        res["note"] = ("Limited history (%d week%s) — treat the forecast as indicative."
                       % (res["n"], "" if res["n"] == 1 else "s"))
    else:
        res["note"] = ""
    return res


def forecast_all_products(periods=PERIODS):
    cards = [forecast_demand(p["id"], periods) for p in db.read("products")]
    cards.sort(key=lambda c: sum(c["forecast"]), reverse=True)
    return cards


def forecast_cards_from(cards):
    """Shape already-computed forecast dicts for the analytics/forecast template."""
    out = []
    for c in cards:
        out.append({
            "product_name": c["product_name"],
            "chart": svg_forecast_chart(c["history"], c["future_labels"],
                                        c["forecast"], c["lower"], c["upper"]),
            "model": c["model"], "mae": c["mae"], "mape": c["mape"],
            "n": c["n"], "low_data": c["low_data"], "note": c["note"],
        })
    return out


def forecast_cards(periods=PERIODS):
    """Shaped for the analytics/forecast template."""
    return forecast_cards_from(forecast_all_products(periods))


def material_risk(periods=PERIODS):
    # forecast every product once, keep per-week list
    fc = {c["product_id"]: c["forecast"] for c in forecast_all_products(periods)}
    boms = db.read("bill_of_materials")
    rows = []
    for m in db.read("raw_materials"):
        per_week_total = 0.0
        for line in boms:
            if line.get("material_id") != m["id"]:
                continue
            weekly = fc.get(line.get("product_id"))
            if not weekly:
                continue
            qpu = _f(line.get("qty_per_unit"))
            per_week_total += qpu * (sum(weekly) / periods)
        horizon = per_week_total * periods
        stock = _f(m.get("stock_qty"))
        reorder = _f(m.get("reorder_level"))
        weeks_to = (stock / per_week_total) if per_week_total > 1e-9 else None
        recommended = max(0.0, horizon + reorder - stock)
        if (weeks_to is not None and weeks_to <= 1) or (reorder > 0 and stock <= reorder):
            risk = "high"
        elif weeks_to is not None and weeks_to <= periods:
            risk = "medium"
        else:
            risk = "low"
        rows.append({
            "name": m.get("name"), "category": m.get("category"),
            "unit": m.get("unit"), "current_stock": round(stock, 3),
            "reorder_level": round(reorder, 3),
            "per_week_consumption": round(per_week_total, 3),
            "horizon_consumption": round(horizon, 3),
            "weeks_to_stockout": (round(weeks_to, 2) if weeks_to is not None else None),
            "recommended_reorder": round(recommended, 3), "risk": risk,
        })
    order = {"high": 0, "medium": 1, "low": 2}
    rows.sort(key=lambda r: (order[r["risk"]], -r["horizon_consumption"]))
    return rows


# ==========================================================================
#  Recommendations (AI insights)
# ==========================================================================
def reorder_recommendations(periods=PERIODS):
    out = []
    for r in material_risk(periods):
        if r["risk"] in ("high", "medium") and r["recommended_reorder"] > 0:
            weeks = ("~%g weeks" % r["weeks_to_stockout"]
                     if r["weeks_to_stockout"] is not None else "soon")
            out.append({
                "type": "reorder", "severity": r["risk"], "subject": r["name"],
                "message": ("%s may run low in %s. Recommended reorder: %g %s."
                            % (r["name"], weeks, r["recommended_reorder"],
                               r["unit"] or "units")),
            })
    return out


def production_plan_suggestions(periods=PERIODS):
    out = []
    for c in forecast_all_products(periods):
        nxt = c["forecast"][0] if c["forecast"] else 0
        if nxt <= 0:
            continue
        out.append({
            "type": "production", "severity": "info", "subject": c["product_name"],
            "message": ("Based on recent demand, plan to produce ~%g units of %s next week."
                        % (round(nxt), c["product_name"])),
        })
    return out


def stockout_overstock_predictions(periods=PERIODS):
    out = []
    for c in forecast_all_products(periods):
        product = db.get("products", c["product_id"])
        stock = _f(product.get("stock_qty")) if product else 0.0
        horizon_demand = sum(c["forecast"])
        if horizon_demand > stock and horizon_demand > 0:
            out.append({
                "type": "stockout", "severity": "high", "subject": c["product_name"],
                "message": ("%s may stock out within %d weeks — projected demand %g > %g in stock."
                            % (c["product_name"], periods, round(horizon_demand, 1),
                               round(stock, 1))),
            })
        elif stock > 0 and horizon_demand < stock * 0.25:
            out.append({
                "type": "overstock", "severity": "low", "subject": c["product_name"],
                "message": ("%s is slow moving — %g in stock vs only %g projected demand over %d weeks."
                            % (c["product_name"], round(stock, 1),
                               round(horizon_demand, 1), periods)),
            })
    return out


def sales_trend():
    out = []
    for p in db.read("products"):
        hist = weekly_demand(p["id"])
        if len(hist) < 4:
            continue
        recent = sum(v for _, v in hist[-2:]) / 2
        prev = sum(v for _, v in hist[-4:-2]) / 2
        if prev <= 0:
            continue
        change = (recent - prev) / prev * 100
        if change >= 15:
            out.append({"type": "trend", "severity": "info", "subject": p.get("name"),
                        "message": "%s demand up %.0f%% recently — fast-moving item."
                        % (p.get("name"), change)})
        elif change <= -15:
            out.append({"type": "trend", "severity": "low", "subject": p.get("name"),
                        "message": "%s demand down %.0f%% recently — slow-moving item."
                        % (p.get("name"), abs(change))})
    return out


def anomaly_detection():
    out = []
    adjustments = db.read("inventory_adjustments")
    deltas = [abs(_f(a.get("delta"))) for a in adjustments]
    if len(deltas) >= 3:
        avg = _mean(deltas)
        for a in adjustments:
            if abs(_f(a.get("delta"))) > max(3 * avg, 1) and avg > 0:
                out.append({
                    "type": "anomaly", "severity": "high",
                    "subject": item_label(a.get("item_type"), a.get("item_id")),
                    "message": ("Unusual stock adjustment of %g for %s — please verify."
                                % (_f(a.get("delta")),
                                   item_label(a.get("item_type"), a.get("item_id")))),
                })
    # abnormally large single transactions
    txns = db.read("inventory_transactions")
    mags = [abs(_f(t.get("change_qty"))) for t in txns] or [0]
    avg_t = _mean(mags)
    for t in txns:
        if avg_t > 0 and abs(_f(t.get("change_qty"))) > 6 * avg_t:
            out.append({
                "type": "anomaly", "severity": "medium",
                "subject": item_label(t.get("item_type"), t.get("item_id")),
                "message": ("Large %s movement of %g detected — verify the transaction."
                            % (t.get("txn_type"), _f(t.get("change_qty")))),
            })
    return out[:8]


def item_label(item_type, item_id):
    coll = "raw_materials" if item_type == "material" else "products"
    it = db.get(coll, item_id)
    return it.get("name") if it else "%s #%s" % (item_type, item_id)


def all_recommendations(periods=PERIODS):
    recs = (reorder_recommendations(periods) + production_plan_suggestions(periods)
            + stockout_overstock_predictions(periods) + sales_trend()
            + anomaly_detection())
    return recs


# ==========================================================================
#  Chatbot (keyword routing over live data)
# ==========================================================================
def chatbot_answer(question):
    q = (question or "").lower().strip()
    if not q:
        return "Ask me about stock, low materials, sales, forecasts or reorders."

    # low stock / reorder
    if any(k in q for k in ("low", "reorder", "run out", "restock")):
        lows = [m for m in db.read("raw_materials")
                if _f(m.get("reorder_level")) > 0
                and _f(m.get("stock_qty")) <= _f(m.get("reorder_level"))]
        if not lows:
            return "Good news — no materials are at or below their reorder level."
        lines = ["Materials at/below reorder level:"]
        for m in lows:
            lines.append("• %s — %g %s (reorder at %g)"
                         % (m.get("name"), _f(m.get("stock_qty")), m.get("unit") or "",
                            _f(m.get("reorder_level"))))
        recs = reorder_recommendations()
        for r in recs[:5]:
            lines.append("↳ %s" % r["message"])
        return "\n".join(lines)

    # best-selling / top products
    if any(k in q for k in ("best", "top", "fast-moving", "fast moving", "popular")):
        top = top_products_by_demand()
        if not top or all(v == 0 for _, v in top):
            return "No sales demand recorded yet."
        return "Top products by demand:\n" + "\n".join(
            "• %s — %g units" % (n, v) for n, v in top if v > 0)

    # forecast / demand
    if any(k in q for k in ("forecast", "demand", "predict", "next week", "next month")):
        cards = forecast_all_products()
        if not cards:
            return "No products to forecast yet."
        lines = ["Demand forecast (next %d weeks):" % PERIODS]
        for c in cards[:6]:
            lines.append("• %s — ~%g units next week (%s model)"
                         % (c["product_name"], round(c["forecast"][0]), c["model"]))
        return "\n".join(lines)

    # production plan
    if any(k in q for k in ("produce", "production", "make", "manufacture")):
        plan = production_plan_suggestions()
        if not plan:
            return "No production suggestions — not enough demand history yet."
        return "Production suggestions:\n" + "\n".join("• " + p["message"] for p in plan)

    # sold this month/week
    if "sold" in q or ("how many" in q and "sold" in q) or "sales" in q:
        txns = [t for t in db.read("inventory_transactions")
                if t.get("item_type") == "product" and t.get("txn_type") == "sold"]
        # try to match a product name
        for p in db.read("products"):
            if p.get("name", "").lower() in q:
                units = sum(abs(_f(t.get("change_qty"))) for t in txns
                            if t.get("item_id") == p["id"])
                return "%s: %g units sold in total." % (p.get("name"), units)
        total = sum(abs(_f(t.get("change_qty"))) for t in txns)
        return "Total units sold across all products: %g." % total

    # stock of a named product/material
    if "stock" in q or "how many" in q or "available" in q:
        for coll, kind in (("products", "product"), ("raw_materials", "material")):
            for it in db.read(coll):
                if it.get("name", "").lower() in q:
                    return ("%s: %g %s in stock."
                            % (it.get("name"), _f(it.get("stock_qty")),
                               it.get("unit") or ""))
        # otherwise summarize
        pcount = len(db.read("products"))
        mcount = len(db.read("raw_materials"))
        return ("I track %d products and %d materials. Ask e.g. \"stock of Honey 100 mL\" "
                "or \"what's low in stock?\"." % (pcount, mcount))

    # anomalies
    if any(k in q for k in ("anomaly", "unusual", "suspicious", "wrong")):
        anoms = anomaly_detection()
        if not anoms:
            return "No unusual inventory or sales activity detected."
        return "Possible anomalies:\n" + "\n".join("• " + a["message"] for a in anoms)

    return ("I can answer questions like:\n"
            "• What products are low in stock?\n"
            "• How many units of Honey 100 mL were sold?\n"
            "• What raw materials need to be reordered?\n"
            "• Show the best-selling products.\n"
            "• What's the demand forecast?")
