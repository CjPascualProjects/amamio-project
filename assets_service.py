"""Module 3 — equipment, supplies and every movement in and out.

Two registers, one rule: nothing moves without a record.

* **Equipment & assets** (``assets``) follow the paper "Inventory of Assets"
  (AFP-001 …).  Every unit that leaves (borrowed, sent for repair, lent to
  another site, disposed) or comes back / is bought is an ``asset_movements``
  row; ``qty_out`` on the asset says how many are away right now.  Service
  history is the paper "Equipment Maintenance Log" (``maintenance_logs``).
* **Supplies** are ``raw_materials`` rows (raw / packaging / cleaning /
  office).  Each IN / OUT is a ``stock_movements`` row and moves stock only
  through :func:`services.adjust_stock`, so the inventory ledger stays the
  single source of truth.  The paper "Month-End Report" is rebuilt from that
  ledger plus the physical count saved in ``month_end_counts``.

Public helpers other modules may call:
    maintenance_due(within_days=14)   assets whose next service is due / overdue
    assets_out()                      what is out right now, with who / since
    asset_summary()                   figures for dashboards
    low_supplies()                    supplies at / below their reorder level
"""
from datetime import date, datetime, timedelta, timezone

import db
import services
from services import _to_float

try:  # The paper register's category order (Appliances, Machines, …).
    from seed_catalog import ASSET_CATEGORIES as _CATALOG_CATEGORIES
except Exception:  # pragma: no cover - catalog is optional
    _CATALOG_CATEGORIES = []


# ===========================================================================
#  Constants
# ===========================================================================
ASSET_CONDITIONS = ["Serviceable", "Under repair", "Non-serviceable"]
CONDITION_BADGE = {
    "Serviceable": "badge-ok",
    "Under repair": "badge-warn",
    "Non-serviceable": "badge-danger",
}

# Why an item leaves / comes back: (value, short explanation)
OUT_BORROWED = "Borrowed / used elsewhere"
OUT_REPAIR = "Sent for repair"
OUT_LENT = "Lent to another site"
OUT_DISPOSED = "Disposed / condemned"
IN_RETURNED = "Returned"
IN_REPAIRED = "Back from repair"
IN_PURCHASE = "New purchase / acquisition"

ASSET_OUT_REASONS = [
    (OUT_BORROWED, "Taken to another area or team, coming back"),
    (OUT_REPAIR, "Out to a repair shop or technician"),
    (OUT_LENT, "Lent to another site or partner"),
    (OUT_DISPOSED, "Broken beyond repair — removed from the register"),
]
ASSET_IN_REASONS = [
    (IN_RETURNED, "Something that was borrowed or lent came back"),
    (IN_REPAIRED, "Fixed and back on site"),
    (IN_PURCHASE, "Newly bought or donated units"),
]
# OUT reasons that expect the item back (they raise qty_out).
RETURNABLE_OUT = (OUT_BORROWED, OUT_REPAIR, OUT_LENT)
# IN reasons that close an earlier OUT (they lower qty_out).
RETURN_IN = (IN_RETURNED, IN_REPAIRED)

SUPPLY_IN_REASONS = ["Delivery / purchase", "Returned unused", "Count correction"]
SUPPLY_OUT_REASONS = ["Used in production", "Issued to a team", "Used for cleaning",
                      "Office use", "Damaged / expired", "Count correction"]

MONTH_NAMES = ["JANUARY", "FEBRUARY", "MARCH", "APRIL", "MAY", "JUNE", "JULY",
               "AUGUST", "SEPTEMBER", "OCTOBER", "NOVEMBER", "DECEMBER"]

# Paper report titles per supplies category.
REPORT_TITLES = {
    "raw": "Raw Materials",
    "packaging": "Jars / Bottles / Packaging Supplies",
    "cleaning": "Production Supplies (Cleaning Supplies)",
    "office": "Office Supplies",
}


# ===========================================================================
#  Small helpers
# ===========================================================================
def _int(value):
    try:
        return int(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _clean(value, limit=200):
    return (value or "").strip()[:limit]


def _iso_date(value):
    """'2026-10-16' or '' — rejects anything that is not a real date."""
    value = (value or "").strip()[:10]
    if not value:
        return ""
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        return None


def _days_until(iso):
    try:
        return (date.fromisoformat((iso or "")[:10]) - date.today()).days
    except ValueError:
        return None


def period_label(period):
    """'2026-10' -> 'OCTOBER 2026'."""
    try:
        year, month = period.split("-")
        return "%s %s" % (MONTH_NAMES[int(month) - 1], year)
    except (ValueError, IndexError, AttributeError):
        return period or ""


def valid_period(period):
    try:
        year, month = (period or "").split("-")
        return 2000 <= int(year) <= 2100 and 1 <= int(month) <= 12 \
            and len(month) == 2
    except ValueError:
        return False


def recent_periods(count=6):
    """This month and the ``count - 1`` before it, newest first."""
    today = date.today()
    year, month = today.year, today.month
    out = []
    for _ in range(count):
        out.append("%04d-%02d" % (year, month))
        month -= 1
        if month == 0:
            year, month = year - 1, 12
    return out


def previous_period():
    return recent_periods(2)[1]


# ===========================================================================
#  Equipment & assets — the register
# ===========================================================================
def active_assets():
    return [a for a in db.read("assets") if a.get("active", True)]


def asset_categories(assets=None):
    """Categories in paper-register order, then any new ones A–Z."""
    used = {a.get("category") or "Uncategorised"
            for a in (assets if assets is not None else active_assets())}
    order = [c for c in _CATALOG_CATEGORIES if c in used]
    order += sorted(c for c in used if c not in order)
    return order


def available(asset):
    return max(_to_float(asset.get("quantity")) - _to_float(asset.get("qty_out")), 0.0)


def _latest_logs():
    latest = {}
    for log in db.read("maintenance_logs"):
        key = log.get("asset_id")
        stamp = (log.get("performed_on") or "", log.get("id") or 0)
        if key not in latest or stamp > latest[key][0]:
            latest[key] = (stamp, log)
    return {k: v[1] for k, v in latest.items()}


def asset_row(asset, latest_log=None, due_within=14):
    """An asset plus the figures every page needs."""
    qty = _to_float(asset.get("quantity"))
    out = _to_float(asset.get("qty_out"))
    condition = asset.get("condition") or "Serviceable"
    next_due = (latest_log or {}).get("next_due") or ""
    days = _days_until(next_due) if next_due else None
    row = dict(asset)
    row.update({
        "quantity": qty, "qty_out": out, "available": max(qty - out, 0.0),
        "condition": condition,
        "badge": CONDITION_BADGE.get(condition, "badge-muted"),
        "next_due": next_due[:10], "due_days": days,
        "due_soon": days is not None and days <= due_within,
        "overdue": days is not None and days < 0,
        "last_service": (latest_log or {}).get("performed_on") or "",
    })
    row["needs_attention"] = (condition != "Serviceable" or row["due_soon"])
    return row


def asset_rows(show="all"):
    latest = _latest_logs()
    rows = [asset_row(a, latest.get(a["id"])) for a in active_assets()]
    if show == "out":
        rows = [r for r in rows if r["qty_out"] > 0]
    elif show == "attention":
        rows = [r for r in rows if r["needs_attention"]]
    return rows


def group_assets(rows):
    """[(category, [rows sorted by item no])] in register order."""
    groups = []
    for cat in asset_categories(rows):
        members = [r for r in rows if (r.get("category") or "Uncategorised") == cat]
        if members:
            members.sort(key=lambda r: (r.get("item_no") or "", r.get("name") or ""))
            groups.append((cat, members))
    return groups


def asset_summary():
    rows = asset_rows()
    return {
        "items": len(rows),
        "units": sum(r["quantity"] for r in rows),
        "out": sum(r["qty_out"] for r in rows),
        "out_items": len([r for r in rows if r["qty_out"] > 0]),
        "repair": len([r for r in rows if r["condition"] != "Serviceable"]),
        "due": len(maintenance_due()),
        "attention": len([r for r in rows if r["needs_attention"]]),
    }


def next_item_no():
    """Next free AFP-### number."""
    used = set()
    for a in db.read("assets"):
        code = (a.get("item_no") or "").upper()
        if code.startswith("AFP-") and code[4:].isdigit():
            used.add(int(code[4:]))
    n = 1
    while n in used:
        n += 1
    return "AFP-%03d" % n


ASSET_FIELDS = ("name", "category", "quantity", "unit", "condition",
                "serial_number", "model", "manufacturer", "date_of_purchase",
                "location", "contact_details", "cost_per_item", "years_in_use",
                "remarks")


def save_asset(data, user_id=None, asset_id=None):
    """Create or update an asset from form data.  Returns (asset, error)."""
    name = _clean(data.get("name"), 120)
    category = _clean(data.get("category"), 80)
    if category == "__new__" or not category:
        category = _clean(data.get("new_category"), 80)
    if not name:
        return None, "Enter the equipment name."
    if not category or category == "__new__":
        return None, "Choose a category or type a new one."
    condition = data.get("condition") or "Serviceable"
    if condition not in ASSET_CONDITIONS:
        return None, "Choose the condition."
    purchase = _iso_date(data.get("date_of_purchase"))
    if purchase is None:
        return None, "The date of purchase is not a valid date."
    existing = db.get("assets", asset_id) if asset_id else None
    if asset_id and not existing:
        return None, "Equipment not found."

    record = {
        "name": name, "category": category,
        "unit": _clean(data.get("unit"), 20) or "unit",
        "condition": condition,
        "serial_number": _clean(data.get("serial_number"), 60),
        "model": _clean(data.get("model"), 60),
        "manufacturer": _clean(data.get("manufacturer"), 120),
        "date_of_purchase": purchase,
        "location": _clean(data.get("location"), 120),
        "contact_details": _clean(data.get("contact_details"), 160),
        "cost_per_item": (_to_float(data.get("cost_per_item"))
                          if data.get("cost_per_item") not in (None, "") else None),
        "years_in_use": (_to_float(data.get("years_in_use"))
                         if data.get("years_in_use") not in (None, "") else None),
        "remarks": _clean(data.get("remarks"), 300),
    }
    if record["cost_per_item"] is not None and record["cost_per_item"] < 0:
        return None, "The cost cannot be negative."

    if existing:
        # Quantity is changed through IN / OUT so every change is on record.
        return db.update("assets", asset_id, record), None

    qty = _to_float(data.get("quantity"), -1)
    if qty <= 0:
        return None, "Enter how many units there are (at least 1)."
    record.update({
        "item_no": next_item_no(), "quantity": qty, "qty_out": 0.0,
        "active": True, "created_at": services.now_iso(),
    })
    asset = db.insert("assets", record)
    db.insert("asset_movements", {
        "asset_id": asset["id"], "asset_name": asset["name"], "direction": "IN",
        "qty": qty, "reason": "Added to the register", "person": "",
        "destination": record["location"], "expected_return": "",
        "notes": "", "recorded_by": user_id, "moved_at": services.now_iso(),
    })
    return asset, None


# ===========================================================================
#  Equipment IN / OUT
# ===========================================================================
def record_movement(asset_id, direction, reason, qty, person="", destination="",
                    expected_return="", notes="", condition="", user_id=None,
                    moved_at=None, notify=True):
    """Record one equipment movement and apply it.  Returns (movement, error).

    OUT:  borrowed / repair / lent raise ``qty_out``; disposed lowers
          ``quantity`` (the unit leaves the register).
    IN:   returned / back from repair lower ``qty_out``; a new purchase
          raises ``quantity``.
    """
    asset = db.get("assets", asset_id)
    if not asset or not asset.get("active", True):
        return None, "Choose the equipment."
    direction = (direction or "").upper()
    if direction not in ("IN", "OUT"):
        return None, "Choose IN or OUT."
    reasons = [r[0] for r in (ASSET_OUT_REASONS if direction == "OUT"
                              else ASSET_IN_REASONS)]
    if reason not in reasons:
        return None, "Choose why it is going %s." % direction.lower()
    qty = _to_float(qty)
    if qty <= 0:
        return None, "Enter how many (at least 1)."
    expected = _iso_date(expected_return)
    if expected is None:
        return None, "The expected return date is not a valid date."
    if condition and condition not in ASSET_CONDITIONS:
        return None, "Choose a valid condition."

    total = _to_float(asset.get("quantity"))
    out = _to_float(asset.get("qty_out"))
    avail = max(total - out, 0.0)
    unit = asset.get("unit") or "unit"
    changes = {}
    if direction == "OUT":
        if qty > avail:
            return None, "Only %s on site — you can't take out %s." % (
                services.fmt_qty(avail, unit), services.fmt_qty(qty, unit))
        if reason == OUT_DISPOSED:
            changes["quantity"] = total - qty
        else:
            changes["qty_out"] = out + qty
        if reason == OUT_REPAIR:
            changes["condition"] = condition or "Under repair"
        elif reason == OUT_DISPOSED and condition:
            changes["condition"] = condition
    else:
        if reason in RETURN_IN:
            if out <= 0:
                return None, "None of this item is out right now."
            if qty > out:
                return None, "Only %s is out — you can't bring back %s." % (
                    services.fmt_qty(out, unit), services.fmt_qty(qty, unit))
            changes["qty_out"] = out - qty
            if reason == IN_REPAIRED:
                changes["condition"] = condition or "Serviceable"
            elif condition:
                changes["condition"] = condition
        else:
            changes["quantity"] = total + qty
            if condition:
                changes["condition"] = condition

    if direction == "OUT" and reason not in RETURNABLE_OUT:
        expected = ""
    if direction == "IN":
        expected = ""
    movement = db.insert("asset_movements", {
        "asset_id": asset["id"], "asset_name": asset.get("name"),
        "direction": direction, "qty": qty, "reason": reason,
        "person": _clean(person, 120), "destination": _clean(destination, 160),
        "expected_return": expected, "notes": _clean(notes, 400),
        "recorded_by": user_id, "moved_at": moved_at or services.now_iso(),
    })
    asset = db.update("assets", asset["id"], changes)

    if notify and direction == "OUT":
        label = "%s %s" % (asset.get("item_no") or "", asset.get("name"))
        if reason == OUT_DISPOSED:
            msg = "%s × %s disposed / condemned%s." % (
                services.fmt_qty(qty), label.strip(),
                (" — " + movement["notes"]) if movement["notes"] else "")
        else:
            msg = "%s × %s went OUT (%s)%s%s." % (
                services.fmt_qty(qty), label.strip(), reason.lower(),
                (" with " + movement["person"]) if movement["person"] else "",
                (", back by " + expected) if expected else "")
        try:
            from flask import url_for
            link = url_for("assets.detail", asset_id=asset["id"])
        except Exception:
            link = "/assets/%d" % asset["id"]
        services.notify_team(set(), msg, link)
    return movement, None


def movement_rows(asset_id=None, limit=None, direction=None):
    rows = db.read("asset_movements")
    if asset_id is not None:
        rows = [m for m in rows if m.get("asset_id") == int(asset_id)]
    if direction:
        rows = [m for m in rows if m.get("direction") == direction]
    rows.sort(key=lambda m: (m.get("moved_at") or "", m.get("id") or 0),
              reverse=True)
    if limit:
        rows = rows[:limit]
    names = {}
    out = []
    for m in rows:
        uid = m.get("recorded_by")
        if uid not in names:
            names[uid] = services.user_name(uid)
        row = dict(m)
        row["when"] = services.fmt_dt(m.get("moved_at"))
        row["day"] = (m.get("moved_at") or "")[:10]
        row["recorded_by_name"] = names[uid]
        out.append(row)
    return out


def _outstanding(asset, moves):
    """Open OUT entries for one asset (FIFO, matched against returns)."""
    open_list = []
    for m in sorted(moves, key=lambda x: (x.get("moved_at") or "", x.get("id") or 0)):
        qty = _to_float(m.get("qty"))
        if m.get("direction") == "OUT" and m.get("reason") in RETURNABLE_OUT:
            open_list.append({"qty": qty, "move": m})
        elif m.get("direction") == "IN" and m.get("reason") in RETURN_IN:
            want = OUT_REPAIR if m.get("reason") == IN_REPAIRED else None
            who = (m.get("person") or "").strip().lower()

            # Close the same person's entry first, then the same kind (a
            # repair return closes a repair), then the oldest.
            def rank(o):
                same_person = bool(who) and (o["move"].get("person") or "").strip().lower() == who
                same_kind = bool(want) and o["move"].get("reason") == want
                return (not same_person, not same_kind)
            ordered = sorted(open_list, key=rank)   # stable: oldest first within a rank
            for o in ordered:
                if qty <= 0:
                    break
                take = min(qty, o["qty"])
                o["qty"] -= take
                qty -= take
            open_list = [o for o in open_list if o["qty"] > 1e-9]
    return open_list


def assets_out():
    """Everything away from site right now: one row per open OUT.

    Each row: asset_id, item_no, asset_name, unit, qty, reason, person,
    destination, since (date), days_out, expected_return, overdue."""
    moves_by = {}
    for m in db.read("asset_movements"):
        moves_by.setdefault(m.get("asset_id"), []).append(m)
    today = date.today()
    rows = []
    for asset in active_assets():
        qty_out = _to_float(asset.get("qty_out"))
        if qty_out <= 0:
            continue
        opens = _outstanding(asset, moves_by.get(asset["id"], []))
        covered = 0.0
        for o in opens:
            m = o["move"]
            since = (m.get("moved_at") or "")[:10]
            try:
                days_out = (today - date.fromisoformat(since)).days
            except ValueError:
                days_out = None
            exp = m.get("expected_return") or ""
            exp_days = _days_until(exp) if exp else None
            rows.append({
                "asset_id": asset["id"], "item_no": asset.get("item_no"),
                "asset_name": asset.get("name"), "unit": asset.get("unit") or "unit",
                "qty": o["qty"], "reason": m.get("reason"),
                "person": m.get("person") or "", "destination": m.get("destination") or "",
                "since": since, "days_out": days_out, "expected_return": exp,
                "overdue": exp_days is not None and exp_days < 0,
                "movement_id": m.get("id"),
            })
            covered += o["qty"]
        if qty_out - covered > 1e-9:   # out before records were kept
            rows.append({
                "asset_id": asset["id"], "item_no": asset.get("item_no"),
                "asset_name": asset.get("name"), "unit": asset.get("unit") or "unit",
                "qty": qty_out - covered, "reason": "Out (no record)", "person": "",
                "destination": "", "since": "", "days_out": None,
                "expected_return": "", "overdue": False, "movement_id": None,
            })
    rows.sort(key=lambda r: (not r["overdue"], r["since"] or "9999"))
    return rows


# ===========================================================================
#  Maintenance (the Equipment Maintenance Log)
# ===========================================================================
MAINTENANCE_TYPES = services.MAINTENANCE_TYPES
MAINTENANCE_STATUS = services.MAINTENANCE_STATUS
MAINTENANCE_BADGE = services.MAINTENANCE_BADGE


def record_maintenance(asset_id, mtype, performed_on, performed_by, status,
                       description="", performed_time="", cost=0.0, next_due="",
                       downtime_hours=0.0, notes="", user_id=None):
    """One row of the Equipment Maintenance Log.  Returns (log, error)."""
    asset = db.get("assets", asset_id)
    if not asset:
        return None, "Choose the equipment."
    if mtype not in MAINTENANCE_TYPES:
        return None, "Choose what kind of maintenance it was."
    if status not in MAINTENANCE_STATUS:
        return None, "Choose the status."
    done = _iso_date(performed_on)
    nxt = _iso_date(next_due)
    if done is None or nxt is None:
        return None, "Check the dates."
    if nxt and done and nxt < done:
        return None, "The next maintenance date must be after the service date."
    if not _clean(description) and not _clean(notes):
        return None, "Describe what was done."
    if _to_float(cost) < 0 or _to_float(downtime_hours) < 0:
        return None, "Cost and downtime cannot be negative."
    time_ = _clean(performed_time, 5)
    log = db.insert("maintenance_logs", {
        "asset_id": asset["id"], "asset_name": asset.get("name"),
        "type": mtype, "description": _clean(description, 400),
        "performed_on": done or services.today_iso(),
        "performed_time": time_,
        "performed_by": _clean(performed_by, 120),
        "cost": _to_float(cost), "next_due": nxt, "status": status,
        "downtime_hours": _to_float(downtime_hours),
        "notes": _clean(notes, 400), "recorded_by": user_id,
        "created_at": services.now_iso(),
    })
    return log, None


def maintenance_rows(asset_id=None, limit=None):
    logs = db.read("maintenance_logs")
    if asset_id is not None:
        logs = [l for l in logs if l.get("asset_id") == int(asset_id)]
    logs.sort(key=lambda l: (l.get("performed_on") or "", l.get("performed_time") or "",
                             l.get("id") or 0), reverse=True)
    if limit:
        logs = logs[:limit]
    rows = []
    for l in logs:
        row = dict(l)
        row["description"] = l.get("description") or ""
        row["badge"] = MAINTENANCE_BADGE.get(l.get("status"), "badge-muted")
        row["recorded_by_name"] = services.user_name(l.get("recorded_by"))
        rows.append(row)
    return rows


def maintenance_due(within_days=14):
    """Assets whose next service falls due within ``within_days`` (or is
    overdue).  Only each asset's most recent log counts.  Same row shape as
    ``services.maintenance_due`` plus asset_id / item_no."""
    assets = {a["id"]: a for a in active_assets()}
    rows = []
    for asset_id, log in _latest_logs().items():
        asset = assets.get(asset_id)
        if not asset:
            continue
        due = (log.get("next_due") or "").strip()[:10]
        days = _days_until(due) if due else None
        if days is None or days > within_days:
            continue
        rows.append({"asset_id": asset_id, "item_no": asset.get("item_no"),
                     "asset_name": asset.get("name"), "due": due, "days": days,
                     "type": log.get("type"), "overdue": days < 0})
    rows.sort(key=lambda r: r["days"])
    return rows


# ===========================================================================
#  Supplies IN / OUT
# ===========================================================================
def supplies(category=None):
    """Stocked supplies in paper-report order: category, then sub-heading in
    the order it was first entered (Jars / Bottles, Pouches, Cap Seals,
    Packing Supplies …), then the order the items were entered."""
    rows = services.stocked_materials([category] if category else None)
    order = [c[0] for c in services.MATERIAL_CATEGORIES]
    first = {}
    for m in rows:
        key = (services.material_category(m), m.get("subcategory") or "")
        first[key] = min(first.get(key, m["id"]), m["id"])
    rows.sort(key=lambda m: (order.index(services.material_category(m)),
                             first[(services.material_category(m), m.get("subcategory") or "")],
                             m["id"]))
    return rows


def group_supplies(rows):
    """[(subcategory, [materials])] keeping the catalog order."""
    groups, index = [], {}
    for m in rows:
        sub = m.get("subcategory") or services.MATERIAL_CATEGORY_LABELS.get(
            services.material_category(m), "Other")
        if sub not in index:
            index[sub] = len(groups)
            groups.append((sub, []))
        groups[index[sub]][1].append(m)
    return groups


def low_supplies():
    return [m for m in supplies() if services.is_low(m)]


def record_supply_movement(material_id, direction, qty, reason, person="",
                           reference="", notes="", user_id=None, moved_at=None,
                           notify=True):
    """Take a supply IN or issue it OUT.  Returns (movement, error)."""
    material = db.get("raw_materials", material_id)
    if not material or services.material_category(material) not in \
            services.MATERIAL_CATEGORY_LABELS:
        return None, "Choose the item."
    direction = (direction or "").upper()
    if direction not in ("IN", "OUT"):
        return None, "Choose IN or OUT."
    reasons = SUPPLY_IN_REASONS if direction == "IN" else SUPPLY_OUT_REASONS
    if reason not in reasons:
        return None, "Choose the reason."
    qty = _to_float(qty)
    if qty <= 0:
        return None, "Enter a quantity above zero."
    stock = _to_float(material.get("stock_qty"))
    unit = material.get("unit") or ""
    if direction == "OUT" and qty > stock + 1e-9:
        return None, "Only %s in stock — you can't issue %s." % (
            services.fmt_qty(stock, unit), services.fmt_qty(qty, unit))
    delta = qty if direction == "IN" else -qty
    was_low = services.is_low(material)
    movement = db.insert("stock_movements", {
        "material_id": material["id"], "material_name": material.get("name"),
        "category": services.material_category(material),
        "direction": direction, "qty": qty, "unit": unit, "reason": reason,
        "person": _clean(person, 120), "reference": _clean(reference, 60),
        "notes": _clean(notes, 400), "balance_after": round(stock + delta, 6),
        "recorded_by": user_id, "moved_at": moved_at or services.now_iso(),
    })
    ref = "SM-%d" % movement["id"]
    services.adjust_stock("material", material["id"], delta,
                          "stock_in" if direction == "IN" else "stock_out",
                          reference_id=ref, user_id=user_id)
    if moved_at:   # back-dated entry: keep the ledger on the same day
        for t in db.query("inventory_transactions", reference_id=ref):
            db.update("inventory_transactions", t["id"], {"timestamp": moved_at})
    material = db.get("raw_materials", material["id"])
    if notify and direction == "OUT" and not was_low and services.is_low(material):
        try:
            from flask import url_for
            link = url_for("supplies.item", material_id=material["id"])
        except Exception:
            link = "/supplies/%d" % material["id"]
        services.notify_team(set(), "%s is low: %s left (reorder level %s)." % (
            material.get("name"), services.fmt_qty(material.get("stock_qty"), unit),
            services.fmt_qty(material.get("reorder_level"))), link)
    return movement, None


def supply_movement_rows(material_id=None, category=None, limit=None):
    rows = db.read("stock_movements")
    if material_id is not None:
        rows = [m for m in rows if m.get("material_id") == int(material_id)]
    if category:
        rows = [m for m in rows if m.get("category") == category]
    rows.sort(key=lambda m: (m.get("moved_at") or "", m.get("id") or 0),
              reverse=True)
    if limit:
        rows = rows[:limit]
    names, out = {}, []
    for m in rows:
        uid = m.get("recorded_by")
        if uid not in names:
            names[uid] = services.user_name(uid)
        row = dict(m)
        row["when"] = services.fmt_dt(m.get("moved_at"))
        row["recorded_by_name"] = names[uid]
        out.append(row)
    return out


# ===========================================================================
#  Month-end count & report
# ===========================================================================
def _material_changes():
    """{material_id: [(timestamp, change_qty)]} from the inventory ledger."""
    by = {}
    for t in db.read("inventory_transactions"):
        if t.get("item_type") != "material":
            continue
        by.setdefault(t.get("item_id"), []).append(
            ((t.get("timestamp") or "")[:7], _to_float(t.get("change_qty"))))
    return by


def period_figures(material, period, changes=None):
    """Opening / IN / OUT / closing for one material and month, from the ledger:
    closing = current stock − changes after the month;
    opening = closing − net change within the month."""
    changes = changes if changes is not None else _material_changes()
    rows = changes.get(material["id"], [])
    after = sum(c for p, c in rows if p > period)
    within_in = sum(c for p, c in rows if p == period and c > 0)
    within_out = -sum(c for p, c in rows if p == period and c < 0)
    closing = _to_float(material.get("stock_qty")) - after
    opening = closing - (within_in - within_out)
    return {"opening": round(opening, 6), "in": round(within_in, 6),
            "out": round(within_out, 6), "closing": round(closing, 6)}


def system_closing(materials, periods):
    """{material_id: {period: closing qty}} — what the system says was on
    hand at each month end (used to pre-show the count wizard)."""
    changes = _material_changes()
    return {m["id"]: {p: period_figures(m, p, changes)["closing"] for p in periods}
            for m in materials}


def latest_count(category, period):
    found = [c for c in db.read("month_end_counts")
             if c.get("category") == category and c.get("period") == period]
    found.sort(key=lambda c: (c.get("counted_at") or "", c.get("id") or 0))
    return found[-1] if found else None


def month_end_report(category, period):
    """Everything the printable Month-End Report needs."""
    materials = supplies(category)
    changes = _material_changes()
    count = latest_count(category, period)
    counted = {l.get("material_id"): l for l in (count or {}).get("lines", [])}
    groups = []
    n = 0
    for sub, items in group_supplies(materials):
        lines = []
        for m in items:
            n += 1
            fig = period_figures(m, period, changes)
            line = counted.get(m["id"])
            lines.append({
                "no": n, "id": m["id"], "name": m.get("name"),
                "unit": m.get("unit") or "", **fig,
                "physical": line.get("physical_qty") if line else None,
                "variance": line.get("variance") if line else None,
            })
        groups.append((sub, lines))
    return {
        "category": category,
        "title": REPORT_TITLES.get(category, category),
        "period": period, "period_label": period_label(period),
        "groups": groups, "count": count,
        "counted_by": services.user_name(count.get("counted_by")) if count else "",
    }


def save_month_end_count(category, period, counts, user_id=None, notes="",
                         adjust=False, counted_at=None):
    """Save a physical count.  ``counts`` maps material id -> counted qty
    (blank = not counted).  Returns (count, error)."""
    if category not in services.MATERIAL_CATEGORY_LABELS:
        return None, "Choose which report you are counting."
    if not valid_period(period):
        return None, "Choose the month."
    if period > services.this_month():
        return None, "You can't count a month that hasn't started."
    if adjust and period != services.this_month():
        return None, "Stock can only be adjusted for this month's count."
    materials = supplies(category)
    changes = _material_changes()
    lines = []
    for m in materials:
        raw = counts.get(str(m["id"]), counts.get(m["id"]))
        if raw in (None, ""):
            continue
        physical = _to_float(raw, -1)
        if physical < 0:
            return None, "Counted quantities must be zero or more (%s)." % m.get("name")
        system = (_to_float(m.get("stock_qty")) if period == services.this_month()
                  else period_figures(m, period, changes)["closing"])
        lines.append({
            "material_id": m["id"], "name": m.get("name"),
            "unit": m.get("unit") or "", "system_qty": round(system, 6),
            "physical_qty": physical, "variance": round(physical - system, 6),
        })
    if not lines:
        return None, "Enter the counted quantity of at least one item."
    for i, line in enumerate(lines, start=1):
        line["id"] = i
    count = db.insert("month_end_counts", {
        "period": period, "category": category, "counted_by": user_id,
        "counted_at": counted_at or services.now_iso(),
        "notes": _clean(notes, 400), "adjusted": bool(adjust), "lines": lines,
    })
    for line in lines:
        line["month_end_count_id"] = count["id"]
    db.update("month_end_counts", count["id"], {"lines": lines})
    if adjust:
        for line in lines:
            if abs(line["variance"]) > 1e-9:
                services.record_adjustment(
                    "material", line["material_id"], line["physical_qty"],
                    "Month-end count %s" % period, user_id)
    return count, None


def count_rows(limit=None):
    rows = sorted(db.read("month_end_counts"),
                  key=lambda c: (c.get("counted_at") or ""), reverse=True)
    if limit:
        rows = rows[:limit]
    out = []
    for c in rows:
        lines = c.get("lines") or []
        out.append({
            "id": c["id"], "period": c.get("period"),
            "period_label": period_label(c.get("period")),
            "category": c.get("category"),
            "category_label": services.MATERIAL_CATEGORY_LABELS.get(c.get("category"), c.get("category")),
            "items": len(lines),
            "variances": len([l for l in lines if abs(_to_float(l.get("variance"))) > 1e-9]),
            "adjusted": c.get("adjusted"),
            "counted_by": services.user_name(c.get("counted_by")),
            "when": services.fmt_dt(c.get("counted_at")),
        })
    return out


# ===========================================================================
#  Demo data
# ===========================================================================
def seed_demo(users):
    """Realistic Module 3 records for the demo.  Safe on a fresh seed; each
    part is skipped if that collection already holds data, and missing
    assets / materials are simply passed over."""
    def uid(*keys):
        for k in keys:
            u = (users or {}).get(k)
            if u:
                return u.get("id")
        return None

    head = uid("assets_head", "assets", "admin", "super_admin")
    packing_name = ((users or {}).get("packing_head") or {}).get("name") or "Packing Team"
    by_name = {a.get("name"): a for a in db.read("assets")}
    mats = {m.get("name"): m for m in db.read("raw_materials")}
    now = datetime.now(timezone.utc)

    def day(n):
        return (date.today() + timedelta(days=n)).isoformat()

    def stamp(days_ago, hour=9):
        return (now - timedelta(days=days_ago)).replace(
            hour=hour, minute=15, second=0, microsecond=0).isoformat()

    # --- Maintenance log ----------------------------------------------------
    if not db.read("maintenance_logs"):
        logs = [
            ("Roaster", "Preventive", "Cleaned the drum, checked the burner and thermostat",
             -95, "08:30", "Rodel (maintenance)", "Completed", 450, -5, 2, ""),
            ("Filling Machine", "Calibration", "Calibrated nozzles to 250 mL and 300 mL",
             -27, "14:00", "Rodel (maintenance)", "Completed", 0, 3, 1,
             "Re-check after the next big honey run"),
            ("Melanger", "Cleaning", "Deep clean of stones and bowl after cacao batch",
             -12, "16:00", "Production team", "Completed", 0, 48, 1.5, ""),
            ("Dehydrator 4 Doors", "Inspection", "Checked fans, heating elements and door seals",
             -20, "10:00", "Rodel (maintenance)", "Completed", 0, 70, 0.5,
             "Door 3 seal slightly worn — watch it"),
            ("Pressure Washer", "Repair", "Pump losing pressure — sent to the shop",
             -6, "11:00", "Davao Machine Works", "In Progress", 1800, 8, 0,
             "Waiting for a replacement pump seal"),
            ("Automatic Sealer", "Preventive", "Replaced the heating strip and teflon tape",
             -40, "09:00", "Rodel (maintenance)", "Completed", 650, 50, 1, ""),
        ]
        for name, mtype, desc, done, tm, by, status, cost, nxt, down, notes in logs:
            asset = by_name.get(name)
            if not asset:
                continue
            record_maintenance(asset["id"], mtype, day(done), by, status,
                               description=desc, performed_time=tm, cost=cost,
                               next_due=day(nxt), downtime_hours=down,
                               notes=notes, user_id=head)

    # --- Equipment movements -------------------------------------------------
    if not db.read("asset_movements"):
        moves = [
            ("Plastic Chairs", "OUT", OUT_LENT, 4, "Brgy. Kinabjangan Hall",
             "Barangay assembly", day(-10), "", 12),
            ("Plastic Chairs", "IN", IN_RETURNED, 4, "Brgy. Kinabjangan Hall",
             "Barangay assembly", "", "All 4 back, no damage", 9),
            ("Pressure Washer", "OUT", OUT_REPAIR, 1, "Davao Machine Works",
             "Bajada, Davao City", day(4), "Pump losing pressure", 6),
            ("Round Tub", "IN", IN_PURCHASE, 2, "Assets Maintenance Head",
             "Production Area", "", "Bought at Gaisano, OR 55102", 5),
            ("Heat Gun", "OUT", OUT_BORROWED, 1, packing_name,
             "Packing Area", day(1), "For shrink-sealing gift boxes", 2),
        ]
        for name, direction, reason, qty, person, dest, exp, notes, ago in moves:
            asset = by_name.get(name)
            if not asset:
                continue
            record_movement(asset["id"], direction, reason, qty, person=person,
                            destination=dest, expected_return=exp, notes=notes,
                            user_id=head, moved_at=stamp(ago, 10), notify=False)

    # --- Supplies in / out ---------------------------------------------------
    if not db.read("stock_movements"):
        supply = [
            ("Matte Kraft Pouch (white) 13x21 cm", "IN", "Delivery / purchase", 300,
             "Easyhome 168", "DR-55821", 20),
            ("Hexagonal Jar 250 mL", "OUT", "Issued to a team", 120,
             packing_name, "REQ-0412", 18),
            ("Gloves", "OUT", "Used for cleaning", 2, "Production team", "", 15),
            ("A4 Bond Paper", "OUT", "Office use", 2, "Admin office", "", 13),
            ("Packaging Tape", "IN", "Delivery / purchase", 12,
             "CBPH Packing Supplies", "DR-10233", 11),
            ("63 mm Seal (250 mL)", "OUT", "Used in production", 150,
             "Production team", "BMR-HP250", 9),
            ("Dishwashing Liquid 3.78 L", "OUT", "Used for cleaning", 1,
             "Utility", "", 7),
            ("Ginger", "OUT", "Used in production", 8, "Production team",
             "BMR-HLG-1012", 5),
            ("Square Bottle 300 mL", "OUT", "Damaged / expired", 6,
             "Packing Area", "", 3),
            ("Bubble Wrap", "OUT", "Issued to a team", 2, packing_name, "REQ-0420", 1),
        ]
        for name, direction, reason, qty, person, ref, ago in supply:
            m = mats.get(name)
            if not m:
                continue
            if direction == "OUT" and _to_float(m.get("stock_qty")) < qty:
                continue
            record_supply_movement(m["id"], direction, qty, reason, person=person,
                                   reference=ref, user_id=head,
                                   moved_at=stamp(ago, 14), notify=False)
            mats[name] = db.get("raw_materials", m["id"])

    # --- Last month's packaging count ----------------------------------------
    if not db.read("month_end_counts"):
        period = previous_period()
        changes = _material_changes()
        counts = {}
        short = {"Hexagonal Jar 250 mL": -3, "Square Bottle 300 mL": -2,
                 "Packaging Tape": 1, "Cookie Pouch 5.5x8.5 cm": -10}
        for m in supplies("packaging"):
            closing = period_figures(m, period, changes)["closing"]
            counts[str(m["id"])] = max(closing + short.get(m.get("name"), 0), 0)
        if counts:
            first = date.today().replace(day=1)
            at = datetime(first.year, first.month, first.day, 1, 30,
                          tzinfo=timezone.utc).isoformat()
            save_month_end_count("packaging", period, counts, user_id=head,
                                 notes="Counted at the packing area storage.",
                                 counted_at=at)
