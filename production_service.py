"""Production records — the client's three paper forms, as guided flows.

* Batch Manufacturing Record (BMR)  -> ``batch_records`` (children
  ``dispensing`` and ``steps``).  A batch moves Dispensing -> Procedure ->
  Yield & QA -> Done; finishing it is the only place stock moves.
* Daily Production Report           -> computed from ``inventory_transactions``
  (item_type "product"): positive change = IN, negative = OUT.
* Retention Record                  -> ``retention_samples``.

All stock changes go through ``services.adjust_stock`` so the ledger stays the
single source of truth.
"""
import calendar
import sys
import traceback
from datetime import date, datetime, timedelta, timezone

import db
import services
from services import _to_float, now_iso, today_iso

# --- Constants -------------------------------------------------------------
IN_PROGRESS = "In Progress"
COMPLETED = "Completed"
CANCELLED = "Cancelled"
APPROVED = "APPROVED"
DISAPPROVED = "DISAPPROVED"
DISPOSITIONS = [APPROVED, DISAPPROVED]

RETAINED = "Retained"
DISPOSED = "Disposed"

GROUP_ORDER = ["Honey Products", "Cacao Products", "Coffee Products",
               "Powder", "Others"]

TRACK = ["Dispensing", "Procedure", "Yield & QA", "Done"]
STAGE_INDEX = {"dispensing": 0, "procedure": 1, "finish": 2, "done": 3}

SHELF_LIFE_MONTHS = 12

# Procedure templates, as the client writes them on the BMR (upper case).
MORINGA_STEPS = [
    "QUALITY INSPECTION", "WASHING OF MORINGA LEAVES",
    "DEHYDRATING MORINGA LEAVES", "GRINDING", "SIFTING", "OVEN HEATING",
    "PACKAGING", "LABELING & MARKING", "FINISHED PRODUCT",
]
_TAIL = ["LABELING & MARKING", "FINISHED PRODUCT"]
PROCEDURES = {
    "moringa": MORINGA_STEPS,
    "powder": ["QUALITY INSPECTION", "WASHING OF RAW MATERIALS",
               "PEELING & SLICING", "DEHYDRATING", "GRINDING", "SIFTING",
               "OVEN HEATING", "PACKAGING"] + _TAIL,
    "concentrate": ["QUALITY INSPECTION", "WASHING OF RAW MATERIALS",
                    "PEELING & SLICING", "EXTRACTION / JUICING",
                    "MIXING WITH HONEY", "HEATING / PASTEURIZATION", "COOLING",
                    "BOTTLE SANITATION", "FILLING / BOTTLING",
                    "CAPPING & SEALING"] + _TAIL,
    "pure_honey": ["QUALITY INSPECTION (MOISTURE & APPEARANCE)",
                   "STRAINING / FILTERING", "SETTLING", "BOTTLE SANITATION",
                   "FILLING", "CAPPING & SEALING"] + _TAIL,
    "comb_honey": ["QUALITY INSPECTION (MOISTURE & APPEARANCE)",
                   "STRAINING / FILTERING", "COMB CUTTING", "JAR SANITATION",
                   "PLACING OF COMB & FILLING", "CAPPING & SEALING"] + _TAIL,
    "vinegar": ["QUALITY INSPECTION", "MIXING", "FERMENTATION", "FILTERING",
                "BOTTLE SANITATION", "BOTTLING", "CAPPING & SEALING"] + _TAIL,
    "tableya": ["QUALITY INSPECTION OF CACAO BEANS", "SORTING", "ROASTING",
                "COOLING", "WINNOWING (DEHULLING)", "GRINDING", "MOLDING",
                "COOLING & SETTING", "PACKAGING"] + _TAIL,
    "cacao_powder": ["QUALITY INSPECTION OF CACAO BEANS", "SORTING", "ROASTING",
                     "COOLING", "WINNOWING (DEHULLING)", "GRINDING", "PRESSING",
                     "SIFTING", "PACKAGING"] + _TAIL,
    "cacao_nibs": ["QUALITY INSPECTION OF CACAO BEANS", "SORTING", "ROASTING",
                   "COOLING", "CRACKING & WINNOWING", "PACKAGING"] + _TAIL,
    "cacao_butter": ["QUALITY INSPECTION OF CACAO BEANS", "ROASTING",
                     "WINNOWING (DEHULLING)", "GRINDING", "PRESSING",
                     "FILTERING", "FILLING", "COOLING & SETTING"] + _TAIL,
    "coffee": ["QUALITY INSPECTION OF GREEN BEANS", "SORTING", "ROASTING",
               "COOLING", "GRINDING", "PACKAGING"] + _TAIL,
    "corn_coffee": ["QUALITY INSPECTION OF CORN", "WASHING", "SUN DRYING",
                    "ROASTING", "COOLING", "GRINDING", "SIFTING",
                    "PACKAGING"] + _TAIL,
    "chips": ["QUALITY INSPECTION", "PEELING & SLICING", "FRYING",
              "DRAINING & COOLING", "PACKAGING"] + _TAIL,
    "oil": ["QUALITY INSPECTION", "MIXING", "BOTTLE SANITATION", "FILLING",
            "CAPPING & SEALING"] + _TAIL,
    "lip": ["QUALITY INSPECTION", "MELTING OF BASE", "MIXING", "FILLING",
            "COOLING & SETTING", "CAPPING"] + _TAIL,
    "generic": ["QUALITY INSPECTION", "PREPARATION OF RAW MATERIALS",
                "PROCESSING", "PACKAGING"] + _TAIL,
}


def procedure_key(product):
    """Which procedure template fits this product (by family / name)."""
    if not product:
        return "generic"
    text = ("%s %s" % (product.get("family") or "", product.get("name") or "")).lower()
    group = (product.get("product_group") or "").lower()
    rules = [
        ("moringa", "moringa"),
        ("concentrate", "concentrate"), ("infused", "concentrate"),
        ("vinegar", "vinegar"), ("comb", "comb_honey"),
        ("tableya", "tableya"), ("nibs", "cacao_nibs"),
        ("cacao butter", "cacao_butter"), ("cacao powder", "cacao_powder"),
        ("corn coffee", "corn_coffee"), ("coffee", "coffee"),
        ("chips", "chips"), ("liniment", "oil"), ("lip", "lip"),
        ("powder", "powder"), ("honey", "pure_honey"),
    ]
    for needle, key in rules:
        if needle in text:
            return key
    if "honey" in group:
        return "pure_honey"
    if "coffee" in group:
        return "coffee"
    return "generic"


def procedure_for(product):
    return list(PROCEDURES[procedure_key(product)])


# --- Small helpers -----------------------------------------------------------
def _clean(value, limit=200):
    return (value or "").strip()[:limit]


def _date_or_blank(value):
    value = (value or "").strip()[:10]
    if not value:
        return ""
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        return ""


def _dt_or_blank(value):
    """'2026-10-16T08:30' (datetime-local) or '' if unparseable."""
    value = (value or "").strip()[:16]
    if not value:
        return ""
    try:
        return datetime.fromisoformat(value).strftime("%Y-%m-%dT%H:%M")
    except ValueError:
        return ""


def add_months(day, months):
    """Same day ``months`` later (clamped to the month's last day)."""
    if isinstance(day, str):
        day = date.fromisoformat(day)
    month0 = day.month - 1 + months
    year = day.year + month0 // 12
    month = month0 % 12 + 1
    return day.replace(year=year, month=month,
                       day=min(day.day, calendar.monthrange(year, month)[1]))


def default_expiry(production_date=None):
    base = production_date or today_iso()
    try:
        return add_months(base, SHELF_LIFE_MONTHS).isoformat()
    except ValueError:
        return add_months(date.today(), SHELF_LIFE_MONTHS).isoformat()


def local_date(timestamp):
    """Ledger timestamps are UTC ISO strings; report them on the local day."""
    if not timestamp:
        return ""
    try:
        moment = datetime.fromisoformat(str(timestamp))
    except ValueError:
        return str(timestamp)[:10]
    if moment.tzinfo is not None:
        moment = moment.astimezone()
    return moment.date().isoformat()


def fmt_local(value):
    """'2026-10-16T08:30' -> '2026-10-16 08:30'."""
    return (value or "")[:16].replace("T", " ")


# --- Catalog for the start wizard ---------------------------------------------
def _sorted_products():
    return sorted(db.read("products"),
                  key=lambda p: (int(p.get("sort_order") or 9999), p.get("name") or ""))


def product_groups():
    """[(group, [product, ...]), ...] in Daily Production Report order."""
    groups = {}
    for p in _sorted_products():
        groups.setdefault(p.get("product_group") or "Others", []).append(p)
    ordered = [g for g in GROUP_ORDER if g in groups]
    ordered += sorted(g for g in groups if g not in GROUP_ORDER)
    return [(g, groups[g]) for g in ordered]


def ingredient_materials():
    """Materials that can be dispensed into a batch (raw + packaging first)."""
    rank = {"raw": 0, "packaging": 1}
    rows = [m for m in db.read("raw_materials")
            if m.get("category") in ("raw", "packaging", "cleaning", None, "")]
    return sorted(rows, key=lambda m: (rank.get(m.get("category"), 2),
                                       m.get("name") or ""))


def wizard_data():
    """What the start wizard's page script needs to pre-fill lines and steps."""
    boms = {}
    for line in db.read("bill_of_materials"):
        boms.setdefault(str(line.get("product_id")), []).append({
            "material_id": line.get("material_id"),
            "qty_per_unit": _to_float(line.get("qty_per_unit")),
        })
    materials = {str(m["id"]): {"name": m.get("name"), "unit": m.get("unit") or "",
                                "stock": _to_float(m.get("stock_qty"))}
                 for m in db.read("raw_materials")}
    products = {str(p["id"]): {"name": p.get("name"), "unit": p.get("unit") or "unit",
                               "steps": procedure_for(p)}
                for p in db.read("products")}
    return {"boms": boms, "materials": materials, "products": products}


def default_dispensing(product_id, batch_size):
    """BOM x batch size as editable dispensing lines."""
    rows = []
    for r in services.requirements_for(product_id, batch_size):
        rows.append({"material_id": r["material_id"], "ingredient": r["material_name"],
                     "lot_no": "", "expiry_date": "",
                     "theoretical_qty": round(r["required"], 3), "unit": r["unit"] or ""})
    return rows


# --- Batch records -------------------------------------------------------------
def stage(rec):
    """dispensing -> procedure -> finish -> done."""
    if rec.get("status") in (COMPLETED, CANCELLED):
        return "done"
    lines = rec.get("dispensing") or []
    if any(not (l.get("conducted_by") and l.get("checked_by")) for l in lines):
        return "dispensing"
    if any(not s.get("done") for s in rec.get("steps") or []):
        return "procedure"
    return "finish"


def current_step_index(rec):
    for i, s in enumerate(rec.get("steps") or []):
        if not s.get("done"):
            return i
    return None


def track(rec):
    now = STAGE_INDEX[stage(rec)]
    out = []
    for i, label in enumerate(TRACK):
        if rec.get("status") in (COMPLETED, CANCELLED):
            state = "done"
        else:
            state = "done" if i < now else ("now" if i == now else "todo")
        out.append((label, state))
    return out


def next_label(rec):
    """Short 'what to do next' line for queues."""
    st = stage(rec)
    if st == "dispensing":
        return "Sign off dispensing & weighing"
    if st == "procedure":
        i = current_step_index(rec)
        steps = rec.get("steps") or []
        return "Step %d of %d: %s" % (i + 1, len(steps), (steps[i].get("process") or "").title())
    if st == "finish":
        return "Record yield & QA disposition"
    return rec.get("disposition") or rec.get("status") or ""


def disposition_badge(rec):
    if rec.get("status") == CANCELLED:
        return "badge-muted"
    if rec.get("status") == IN_PROGRESS:
        return "badge-warn"
    return "badge-ok" if rec.get("disposition") == APPROVED else "badge-danger"


def status_label(rec):
    if rec.get("status") == COMPLETED:
        return rec.get("disposition") or COMPLETED
    return rec.get("status") or IN_PROGRESS


def product_unit(rec):
    product = db.get("products", rec.get("product_id")) if rec.get("product_id") else None
    return (product or {}).get("unit") or "unit"


def get_batch(batch_id):
    return db.get("batch_records", batch_id)


def find_batch_by_no(batch_no):
    batch_no = (batch_no or "").strip().upper()
    for r in db.read("batch_records"):
        if (r.get("batch_no") or "").upper() == batch_no:
            return r
    return None


def next_batch_no():
    return services._next_ref("BMR", "batch_records", "batch_no")


def material_shortages(lines):
    """Lines whose material does not have enough stock right now.

    Same material on several lines is added up first."""
    need = {}
    for l in lines:
        mid = l.get("material_id")
        if mid in (None, ""):
            continue
        need[int(mid)] = need.get(int(mid), 0.0) + _to_float(l.get("theoretical_qty"))
    short = []
    for mid, qty in need.items():
        material = db.get("raw_materials", mid)
        if not material:
            continue
        have = _to_float(material.get("stock_qty"))
        if qty > have + 1e-9:
            short.append({"material_id": mid, "name": material.get("name"),
                          "unit": material.get("unit") or "", "required": qty,
                          "available": have, "shortfall": qty - have})
    return short


def shortage_message(short):
    return "Not enough stock: " + "; ".join(
        "%s needs %s, only %s on hand" % (s["name"], services.fmt_qty(s["required"], s["unit"]),
                                          services.fmt_qty(s["available"], s["unit"]))
        for s in short) + "."


def parse_dispensing(form):
    """Line arrays from the start wizard -> dispensing dicts (blank lines dropped)."""
    mids = form.getlist("d_material_id")
    names = form.getlist("d_ingredient")
    lots = form.getlist("d_lot_no")
    exps = form.getlist("d_expiry")
    qtys = form.getlist("d_qty")
    units = form.getlist("d_unit")
    lines = []
    for i in range(len(names)):
        def at(seq, default=""):
            return seq[i] if i < len(seq) else default
        mid = (at(mids) or "").strip()
        material = db.get("raw_materials", mid) if mid else None
        name = _clean(at(names), 120) or (material or {}).get("name", "")
        qty = _to_float(at(qtys), 0.0)
        if not name and qty <= 0:
            continue
        lines.append({
            "material_id": int(material["id"]) if material else None,
            "ingredient": name,
            "lot_no": _clean(at(lots), 60),
            "expiry_date": _date_or_blank(at(exps)),
            "theoretical_qty": qty,
            "unit": _clean(at(units), 20) or (material or {}).get("unit", ""),
            "conducted_by": "", "checked_by": "",
        })
    return lines


def start_batch(user_id, product_id, batch_size, production_date, expiry_date,
                start_at, dispensing, steps, batch_no=""):
    """Create a BMR in progress.  Returns (record, error)."""
    product = db.get("products", product_id) if product_id else None
    if not product:
        return None, "Choose the product for this batch."
    size = _to_float(batch_size)
    if size <= 0:
        return None, "Batch size must be more than zero."
    production_date = _date_or_blank(production_date)
    if not production_date:
        return None, "Enter the production date."
    expiry_date = _date_or_blank(expiry_date) or default_expiry(production_date)
    if expiry_date <= production_date:
        return None, "The expiry date must be after the production date."
    start_at = _dt_or_blank(start_at)
    if not start_at:
        return None, "Enter when the batch started."
    if not dispensing:
        return None, "Add at least one ingredient to dispense."
    for l in dispensing:
        if not l.get("ingredient"):
            return None, "Every dispensing line needs an ingredient."
        if _to_float(l.get("theoretical_qty")) <= 0:
            return None, "Enter the weight / volume for %s." % l["ingredient"]
    steps = [_clean(s, 120).upper() for s in steps if _clean(s)]
    if not steps:
        return None, "Add at least one procedure step."
    batch_no = _clean(batch_no, 40).upper()
    with db._lock:
        if batch_no and find_batch_by_no(batch_no):
            return None, "Batch number %s is already used." % batch_no
        rec = db.insert("batch_records", {
            "batch_no": batch_no or next_batch_no(),
            "product_id": int(product["id"]),
            "product_name": product.get("name"),
            "batch_size": size,
            "production_date": production_date,
            "expiry_date": expiry_date,
            "start_at": start_at,
            "end_at": "",
            "theoretical_yield": size,
            "actual_yield": None,
            "test_date": "", "test_result_date": "",
            "disposition": "", "qa_name": "", "qa_date": "", "remarks": "",
            "status": IN_PROGRESS,
            "stock_posted": False,
            "dispensing": dispensing,
            "steps": [{"process": s, "conducted_by": "", "checked_by": "",
                       "done": False, "done_at": ""} for s in steps],
            "created_by": user_id,
            "created_at": now_iso(),
            "completed_at": "",
        })
    return rec, None


def sign_dispensing(batch_id, signers, user_id=None):
    """signers: [(conducted_by, checked_by), ...] one per dispensing line."""
    rec = get_batch(batch_id)
    if not rec or rec.get("status") != IN_PROGRESS:
        return None, "This batch is not in progress."
    lines = [dict(l) for l in rec.get("dispensing") or []]
    if len(signers) != len(lines):
        return None, "Sign every dispensing line."
    for line, (conducted, checked) in zip(lines, signers):
        conducted, checked = _clean(conducted, 80), _clean(checked, 80)
        if not conducted or not checked:
            return None, "Each line needs who weighed it and who checked it."
        line["conducted_by"], line["checked_by"] = conducted, checked
    return db.update("batch_records", rec["id"], {"dispensing": lines}), None


def sign_step(batch_id, index, conducted_by, checked_by, user_id=None):
    """Tick off the current procedure step (steps are done in order)."""
    rec = get_batch(batch_id)
    if not rec or rec.get("status") != IN_PROGRESS:
        return None, "This batch is not in progress."
    if stage(rec) != "procedure":
        return None, "Sign off dispensing first." if stage(rec) == "dispensing" \
            else "All procedure steps are already done."
    current = current_step_index(rec)
    try:
        index = int(index)
    except (TypeError, ValueError):
        index = -1
    if index != current:
        return None, "That step was already signed — showing the current one."
    conducted_by, checked_by = _clean(conducted_by, 80), _clean(checked_by, 80)
    if not conducted_by or not checked_by:
        return None, "Enter who conducted and who checked this step."
    steps = [dict(s) for s in rec.get("steps") or []]
    steps[index].update({"conducted_by": conducted_by, "checked_by": checked_by,
                         "done": True, "done_at": now_iso()})
    return db.update("batch_records", rec["id"], {"steps": steps}), None


def undo_last_step(batch_id):
    """Re-open the most recently ticked step (before the batch is finished)."""
    rec = get_batch(batch_id)
    if not rec or rec.get("status") != IN_PROGRESS:
        return None, "This batch is not in progress."
    steps = [dict(s) for s in rec.get("steps") or []]
    done = [i for i, s in enumerate(steps) if s.get("done")]
    if not done:
        return None, "No step has been signed yet."
    steps[done[-1]].update({"done": False, "done_at": ""})
    return db.update("batch_records", rec["id"], {"steps": steps}), None


def cancel_batch(batch_id, user_id=None):
    rec = get_batch(batch_id)
    if not rec or rec.get("status") != IN_PROGRESS:
        return None, "Only a batch in progress can be cancelled."
    return db.update("batch_records", rec["id"], {
        "status": CANCELLED, "completed_at": now_iso()}), None


def finish_batch(batch_id, user_id, end_at, actual_yield, disposition, qa_name,
                 qa_date="", test_date="", test_result_date="", remarks="",
                 yield_conducted_by="", yield_checked_by="",
                 test_conducted_by="", test_checked_by=""):
    """Record yield & QA and post stock — exactly once.  Returns (rec, error).

    APPROVED: finished goods +actual yield, dispensed materials consumed.
    DISAPPROVED: materials still consumed, no finished goods; the yield is
    logged as damage at the Production Area."""
    with db._lock:
        rec = get_batch(batch_id)
        if not rec:
            return None, "Batch record not found."
        if rec.get("stock_posted") or rec.get("status") != IN_PROGRESS:
            return None, "This batch is already finished."
        if stage(rec) != "finish":
            return None, "Finish the dispensing sign-off and every procedure step first."
        end_at = _dt_or_blank(end_at)
        if not end_at:
            return None, "Enter when the batch ended."
        if rec.get("start_at") and end_at < rec["start_at"]:
            return None, "The end must be after the start (%s)." % fmt_local(rec["start_at"])
        try:
            yield_qty = float(actual_yield)
        except (TypeError, ValueError):
            return None, "Enter the actual yield."
        if yield_qty < 0:
            return None, "The actual yield cannot be negative."
        disposition = (disposition or "").strip().upper()
        if disposition not in DISPOSITIONS:
            return None, "Choose APPROVED or DISAPPROVED."
        qa_name = _clean(qa_name, 80)
        if not qa_name:
            return None, "Enter the name of the QA."
        remarks = _clean(remarks, 500)
        if disposition == DISAPPROVED and not remarks:
            return None, "Say why the batch was disapproved (remarks)."
        test_date = _date_or_blank(test_date)
        test_result_date = _date_or_blank(test_result_date)
        if test_date and test_result_date and test_result_date < test_date:
            return None, "The test result date cannot be before the test date."
        lines = rec.get("dispensing") or []
        short = material_shortages(lines)
        if short:
            return None, shortage_message(short) + " Receive more stock before finishing this batch."

        product = db.get("products", rec.get("product_id"))
        unit = (product or {}).get("unit") or "unit"
        batch_no = rec["batch_no"]
        approved = disposition == APPROVED

        rec = db.update("batch_records", rec["id"], {
            "end_at": end_at, "actual_yield": yield_qty,
            "test_date": test_date, "test_result_date": test_result_date,
            "disposition": disposition, "qa_name": qa_name,
            "qa_date": _date_or_blank(qa_date) or today_iso(),
            "remarks": remarks, "status": COMPLETED, "stock_posted": True,
            "yield_conducted_by": _clean(yield_conducted_by, 80),
            "yield_checked_by": _clean(yield_checked_by, 80),
            "test_conducted_by": _clean(test_conducted_by, 80),
            "test_checked_by": _clean(test_checked_by, 80),
            "completed_at": now_iso(),
        })

        used = []
        for l in lines:
            if l.get("material_id") in (None, ""):
                continue
            qty = _to_float(l.get("theoretical_qty"))
            if qty <= 0:
                continue
            services.adjust_stock("material", l["material_id"], -qty, "consumed",
                                  reference_id=batch_no, user_id=user_id)
            used.append({"material_id": int(l["material_id"]), "qty": qty})
        if approved and product and yield_qty > 0:
            services.adjust_stock("product", product["id"], yield_qty, "produced",
                                  reference_id=batch_no, user_id=user_id)
        if not approved and yield_qty > 0:
            services.record_damage("production", batch_no, "product",
                                   rec.get("product_id"), rec.get("product_name"),
                                   yield_qty, unit, "Batch disapproved: %s" % remarks,
                                   stage="Production Area", user_id=user_id)

        db.insert("production_orders", {
            "product_id": rec.get("product_id"),
            "product_name": rec.get("product_name"),
            "qty": yield_qty, "batch_no": batch_no,
            "status": "Completed" if approved else "Rejected",
            "output_qty": yield_qty if approved else 0.0,
            "rejected_qty": 0.0 if approved else yield_qty,
            "damaged_qty": 0.0,
            "notes": "BMR %s · %s%s" % (batch_no, disposition,
                                        (" · " + remarks) if remarks else ""),
            "materials_used": used, "user_id": user_id, "timestamp": now_iso(),
        })

    services.notify_team(
        {"production_head"},
        "Batch %s (%s) finished — %s, %s %s." % (
            batch_no, rec.get("product_name"), disposition,
            services.fmt_qty(yield_qty), unit),
        link="/production/batch/%d" % rec["id"])
    return rec, None


def batch_rows(status=None):
    rows = sorted(db.read("batch_records"),
                  key=lambda r: (r.get("completed_at") or r.get("created_at") or ""),
                  reverse=True)
    if status:
        rows = [r for r in rows if r.get("status") == status]
    return rows


def decorate(rec):
    """Add display-only keys used by templates."""
    row = dict(rec)
    row["stage"] = stage(rec)
    row["next_label"] = next_label(rec)
    row["badge"] = disposition_badge(rec)
    row["status_label"] = status_label(rec)
    row["unit"] = product_unit(rec)
    steps = rec.get("steps") or []
    row["steps_done"] = sum(1 for s in steps if s.get("done"))
    row["steps_total"] = len(steps)
    return row


def batch_summary():
    month = services.this_month()
    rows = db.read("batch_records")
    done_month = [r for r in rows if r.get("status") == COMPLETED
                  and local_date(r.get("completed_at")).startswith(month)]
    return {
        "in_progress": sum(1 for r in rows if r.get("status") == IN_PROGRESS),
        "completed_month": len(done_month),
        "approved": sum(1 for r in done_month if r.get("disposition") == APPROVED),
        "disapproved": sum(1 for r in done_month if r.get("disposition") == DISAPPROVED),
    }


def last_signers(rec):
    """Names most recently used on this batch, to pre-fill the next sign-off."""
    conducted = checked = ""
    for l in rec.get("dispensing") or []:
        conducted = l.get("conducted_by") or conducted
        checked = l.get("checked_by") or checked
    for s in rec.get("steps") or []:
        if s.get("done"):
            conducted = s.get("conducted_by") or conducted
            checked = s.get("checked_by") or checked
    return conducted, checked


# --- Daily Production Report ---------------------------------------------------
def _month_bounds(month):
    try:
        year, mon = (int(x) for x in (month or "").split("-")[:2])
        first = date(year, mon, 1)
    except (TypeError, ValueError):
        first = date.today().replace(day=1)
    last = first.replace(day=calendar.monthrange(first.year, first.month)[1])
    return first, last


def report_periods(first, last, view="week"):
    """[(label, start, end), ...] — weeks are days 1–7, 8–14, … of the month."""
    periods = []
    if view == "day":
        d = first
        while d <= last:
            periods.append(("%d" % d.day, d, d))
            d += timedelta(days=1)
        return periods
    start = first
    n = 1
    while start <= last:
        end = min(start + timedelta(days=6), last)
        periods.append(("Week %d · %d–%d" % (n, start.day, end.day), start, end))
        start = end + timedelta(days=1)
        n += 1
    return periods


def daily_report(month=None, view="week", show_all=False):
    """Rows exactly like the paper Daily Production Report.

    Bal. Fwd = stock at the start of the month = current stock minus every
    ledger change since then.  Each period shows IN / OUT / BAL."""
    first, last = _month_bounds(month)
    view = "day" if view == "day" else "week"
    periods = report_periods(first, last, view)
    today = date.today()
    first_iso = first.isoformat()

    moves = {}       # product_id -> [(day_iso, change)]
    since = {}       # product_id -> total change since month start (to now)
    for t in db.read("inventory_transactions"):
        if t.get("item_type") != "product":
            continue
        day = local_date(t.get("timestamp"))
        if day < first_iso:
            continue
        pid = int(t.get("item_id") or 0)
        change = _to_float(t.get("change_qty"))
        since[pid] = since.get(pid, 0.0) + change
        if day <= last.isoformat():
            moves.setdefault(pid, []).append((day, change))

    groups = []
    for group, products in product_groups():
        families = []
        by_family = {}
        for p in products:
            fam = p.get("family") or p.get("name")
            if fam not in by_family:
                by_family[fam] = {"family": fam, "rows": [], "active": False}
                families.append(by_family[fam])
            pid = int(p["id"])
            fwd = _to_float(p.get("stock_qty")) - since.get(pid, 0.0)
            bal = fwd
            cells = []
            total_in = total_out = 0.0
            pmoves = moves.get(pid, [])
            for label, start, end in periods:
                s, e = start.isoformat(), end.isoformat()
                qin = sum(c for d, c in pmoves if s <= d <= e and c > 0)
                qout = -sum(c for d, c in pmoves if s <= d <= e and c < 0)
                bal += qin - qout
                total_in += qin
                total_out += qout
                cells.append({"in": qin, "out": qout, "bal": bal,
                              "future": start > today})
            row = {"product": p, "label": p.get("variant") or p.get("name"),
                   "fwd": fwd, "cells": cells, "total_in": total_in,
                   "total_out": total_out, "bal": bal,
                   "moved": bool(pmoves)}
            if pmoves or abs(fwd) > 1e-9 or abs(bal) > 1e-9:
                by_family[fam]["active"] = True
            by_family[fam]["rows"].append(row)
        shown = [f for f in families if show_all or f["active"]]
        for f in shown:
            # A family with one unnamed size is a single row on the paper.
            f["single"] = len(f["rows"]) == 1 and not f["rows"][0]["product"].get("variant")
        if shown:
            groups.append({"group": group, "families": shown})
    return {"first": first, "last": last, "month": first.strftime("%Y-%m"),
            "month_label": first.strftime("%B %Y"), "view": view,
            "periods": periods, "groups": groups, "show_all": show_all}


# --- Retention samples -----------------------------------------------------------
def retention_due(sample):
    return (sample.get("status") != DISPOSED and bool(sample.get("exp_date"))
            and sample["exp_date"] < today_iso())


def retention_rows(show="retained"):
    rows = sorted(db.read("retention_samples"),
                  key=lambda r: (r.get("prod_date") or "", r.get("id") or 0), reverse=True)
    out = []
    for r in rows:
        row = dict(r)
        row["due"] = retention_due(r)
        product = db.get("products", r.get("product_id")) if r.get("product_id") else None
        row["unit"] = (product or {}).get("unit") or ""
        out.append(row)
    if show == "due":
        return [r for r in out if r["due"]]
    if show == "disposed":
        return [r for r in out if r.get("status") == DISPOSED]
    if show == "all":
        return out
    return [r for r in out if r.get("status") != DISPOSED]


def retention_summary():
    rows = db.read("retention_samples")
    return {
        "retained": sum(1 for r in rows if r.get("status") != DISPOSED),
        "due": sum(1 for r in rows if retention_due(r)),
        "disposed": sum(1 for r in rows if r.get("status") == DISPOSED),
    }


def add_retention(user_id, qty, prod_date, exp_date, batch_record_id=None,
                  batch_no="", product_id=None, description="", remarks="",
                  inspected_by="", approved_by=""):
    """Keep a retention sample.  Returns (sample, error)."""
    batch = get_batch(batch_record_id) if batch_record_id else None
    if batch_record_id and not batch:
        return None, "Choose a batch record."
    if batch:
        batch_no = batch.get("batch_no")
        product_id = batch.get("product_id")
    batch_no = _clean(batch_no, 40).upper()
    if not batch_no:
        return None, "Enter the batch number."
    product = db.get("products", product_id) if product_id else None
    if not product:
        return None, "Choose the product."
    qty = _to_float(qty)
    if qty <= 0:
        return None, "Enter how many units are kept as a sample."
    prod_date = _date_or_blank(prod_date)
    exp_date = _date_or_blank(exp_date)
    if not prod_date or not exp_date:
        return None, "Enter the production and expiry dates."
    if exp_date <= prod_date:
        return None, "The expiry date must be after the production date."
    inspected_by, approved_by = _clean(inspected_by, 80), _clean(approved_by, 80)
    if not inspected_by or not approved_by:
        return None, "Enter who inspected and who approved the sample."
    sample = db.insert("retention_samples", {
        "batch_no": batch_no,
        "batch_record_id": int(batch["id"]) if batch else None,
        "product_id": int(product["id"]),
        "product_name": product.get("name"),
        "description": _clean(description, 300),
        "prod_date": prod_date, "exp_date": exp_date, "qty": qty,
        "disposal_date": "", "status": RETAINED,
        "remarks": _clean(remarks, 500),
        "inspected_by": inspected_by, "approved_by": approved_by,
        "created_by": user_id, "created_at": now_iso(),
    })
    return sample, None


def dispose_retention(sample_id, disposal_date, remarks="", user_id=None):
    sample = db.get("retention_samples", sample_id)
    if not sample:
        return None, "Retention sample not found."
    if sample.get("status") == DISPOSED:
        return None, "This sample was already disposed."
    disposal_date = _date_or_blank(disposal_date)
    if not disposal_date:
        return None, "Enter the disposal date."
    if sample.get("prod_date") and disposal_date < sample["prod_date"]:
        return None, "The disposal date cannot be before the production date."
    note = _clean(remarks, 300)
    merged = sample.get("remarks") or ""
    if note:
        merged = (merged + "\n" if merged else "") + "Disposal: " + note
    return db.update("retention_samples", sample["id"], {
        "status": DISPOSED, "disposal_date": disposal_date, "remarks": merged}), None


# --- Demo data -------------------------------------------------------------------
def _fit_size(product_id, wanted):
    """Largest batch size <= wanted that the materials on hand allow."""
    size = int(wanted)
    while size > 1:
        if all(r["shortfall"] <= 0 for r in services.requirements_for(product_id, size)):
            return size
        size -= 1
    return size


def _backdate(rec, when):
    """Move a seeded batch's timestamps (and its ledger rows) into the past."""
    stamp = when.astimezone(timezone.utc).isoformat()
    db.update("batch_records", rec["id"], {"created_at": stamp, "completed_at": stamp})
    txns = db.read("inventory_transactions")
    changed = False
    for t in txns:
        if t.get("reference_id") == rec["batch_no"]:
            t["timestamp"] = stamp
            changed = True
    if changed:
        db.write("inventory_transactions", txns)
    orders = db.read("production_orders")
    for o in orders:
        if o.get("batch_no") == rec["batch_no"]:
            o["timestamp"] = stamp
    db.write("production_orders", orders)
    damages = db.read("damage_records")
    for d in damages:
        if d.get("reference") == rec["batch_no"]:
            d["recorded_at"] = stamp
    if damages:
        db.write("damage_records", damages)


def _seed_batch(products, name, size, days_ago, conducted, checked, qa, uid,
                lots=None, finish=True, steps_done=None):
    product = products.get(name)
    if not product:
        return None
    size = _fit_size(product["id"], size)
    day = date.today() - timedelta(days=days_ago)
    lines = default_dispensing(product["id"], size)
    for i, l in enumerate(lines):
        if lots and i < len(lots):
            l["lot_no"], l["expiry_date"] = lots[i]
        l["conducted_by"] = l["checked_by"] = ""
    rec, err = start_batch(uid, product["id"], size, day.isoformat(),
                           default_expiry(day.isoformat()),
                           "%sT08:00" % day.isoformat(), lines, procedure_for(product))
    if err:
        print("production_service.seed_demo: %s — %s" % (name, err), file=sys.stderr)
        return None
    sign_dispensing(rec["id"], [(conducted, checked)] * len(lines), uid)
    steps = rec.get("steps") or []
    upto = len(steps) if steps_done is None else min(steps_done, len(steps))
    for i in range(upto):
        sign_step(rec["id"], i, conducted, checked, uid)
    if finish:
        rec, err = finish_batch(
            rec["id"], uid, "%sT16:30" % day.isoformat(), size, APPROVED, qa,
            qa_date=(day + timedelta(days=3)).isoformat(),
            test_date=(day + timedelta(days=1)).isoformat(),
            test_result_date=(day + timedelta(days=3)).isoformat(),
            remarks="Passed QA — released for selling.",
            yield_conducted_by=conducted, yield_checked_by=checked,
            test_conducted_by=conducted, test_checked_by=qa)
        if err:
            print("production_service.seed_demo: %s — %s" % (name, err), file=sys.stderr)
            return get_batch_by_name(products, name)
        _backdate(rec, datetime.combine(day, datetime.min.time()).astimezone()
                  + timedelta(hours=16, minutes=30))
        rec = get_batch(rec["id"])
    else:
        db.update("batch_records", rec["id"], {
            "created_at": datetime.combine(day, datetime.min.time()).astimezone()
            .astimezone(timezone.utc).isoformat()})
        rec = get_batch(rec["id"])
    return rec


def get_batch_by_name(products, name):
    product = products.get(name)
    if not product:
        return None
    rows = [r for r in db.read("batch_records") if r.get("product_id") == product["id"]]
    return rows[-1] if rows else None


def seed_demo(users):
    """Example BMRs and retention samples (called by seed.py on a fresh install)."""
    try:
        _seed_demo(users)
    except Exception:  # demo data must never stop the app from starting
        traceback.print_exc()


def _seed_demo(users):
    if db.read("batch_records"):
        return
    head = users.get("production_head") or users.get("admin") or {}
    admin = users.get("admin") or users.get("super_admin") or head
    uid = head.get("id")
    conducted = head.get("name") or "Production Team Head"
    checked = admin.get("name") or "Amamio Admin"
    qa = checked
    products = {p.get("name"): p for p in db.read("products")}

    moringa = _seed_batch(products, "Moringa Powder 100 g", 12, 10, conducted,
                          checked, qa, uid,
                          lots=[("MOR-1009", ""), ("PCH-W-0412", "")])
    hlgc = _seed_batch(products, "Honey Lemon Ginger Concentrate 300 mL", 24, 6,
                       conducted, checked, qa, uid,
                       lots=[("RH-1003", ""), ("LEM-1016", ""), ("GIN-1004", ""),
                             ("SQB-0920", "")])
    _seed_batch(products, "Pure Tableya 200 g", 20, 0, conducted, checked, qa, uid,
                lots=[("CAC-0930", "")], finish=False, steps_done=2)

    for rec, qty, past in ((moringa, 2, False), (hlgc, 1, True)):
        if not rec or rec.get("status") != COMPLETED:
            continue
        exp = rec.get("expiry_date")
        remarks = "Kept in the retention cabinet."
        if past:
            exp = (date.today() - timedelta(days=2)).isoformat()
            remarks = "Opened-bottle stability sample — keep until test is closed."
        add_retention(uid, qty, rec.get("production_date"), exp,
                      batch_record_id=rec["id"],
                      description="%s, sealed as sold" % (rec.get("product_name") or ""),
                      remarks=remarks, inspected_by=conducted, approved_by=checked)
