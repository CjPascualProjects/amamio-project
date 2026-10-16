"""Domain / business logic for the IMS.

Feature blueprints stay thin: they parse the request, call a helper here, then
flash + render.  ALL inventory math and stock side-effects live in this module
so they are implemented exactly once.

Stock is stored as ``stock_qty`` on the raw_materials / products record and is
moved ONLY through :func:`adjust_stock` (which also writes the ledger).
"""
from datetime import date, datetime, timezone

import db
import security

# --- Status badge maps (shared with templates) -----------------------------
REQUEST_STATUS_BADGE = {
    "Pending Approval": "badge-warn",
    "Approved": "badge-ok",
    "Revised": "badge-warn",
    "Rejected": "badge-danger",
    "Ordered": "badge-warn",
    "Received": "badge-ok",
    "Pending": "badge-muted",
}
SALES_BADGE = {
    "Pending Approval": "badge-warn",
    "Approved": "badge-ok",
    "In Fulfilment": "badge-ok",
    "Fulfilled": "badge-ok",
    "Rejected": "badge-danger",
}
ORDER_BADGE = {
    "Pending": "badge-warn",
    "Confirmed": "badge-ok",
    "Delivered": "badge-ok",
    "Cancelled": "badge-danger",
}
PAYMENT_BADGE = {
    "Unpaid": "badge-danger",
    "Partial": "badge-warn",
    "Paid": "badge-ok",
}
DELIVERY_BADGE = {
    "Scheduled": "badge-warn",
    "In Transit": "badge-warn",
    "Delivered": "badge-ok",
    "Cancelled": "badge-danger",
    "Returned": "badge-danger",
}
RECEIVING_BADGE = {
    "Open": "badge-warn",
    "Completed": "badge-ok",
    "Cancelled": "badge-danger",
}
BOX_BADGE = {
    "Awaiting Inspection": "badge-warn",
    "On Hold": "badge-warn",
    "Accepted": "badge-ok",
    "Rejected": "badge-danger",
}
QC_BADGE = {
    "Pending QC": "badge-warn",
    "Pass": "badge-ok",
    "Failed": "badge-danger",
}
PACKING_BADGE = {
    "In Progress": "badge-warn",
    "Packed": "badge-warn",
    "Disbursed": "badge-ok",
    "Handed to Courier": "badge-ok",
    "Handed Over": "badge-ok",
    "Cancelled": "badge-danger",
}

# --- Client vocabulary -----------------------------------------------------
# How a received item is counted in the receiving area.  Lemons come by piece,
# ginger by weight, so every material declares which applies.
TRACK_MODES = [
    ("weight", "By weight (kg)"),
    ("piece", "By piece (pcs)"),
    ("unit", "By unit / bundle"),
]
TRACK_MODE_LABELS = dict(TRACK_MODES)

# Stocked items, grouped the way the client's month-end reports are.
MATERIAL_CATEGORIES = [
    ("raw", "Raw materials"),
    ("packaging", "Jars, bottles & packaging"),
    ("cleaning", "Production & cleaning supplies"),
    ("office", "Office supplies"),
]
MATERIAL_CATEGORY_LABELS = dict(MATERIAL_CATEGORIES)


def material_category(material):
    """Category key, folding older spellings into the current four."""
    cat = (material.get("category") or "raw").strip().lower()
    return {"ingredient": "raw", "packing": "packaging"}.get(cat, cat)


def stocked_materials(categories=None):
    """Materials sorted by category then name (assets are not materials)."""
    order = [c[0] for c in MATERIAL_CATEGORIES]
    rows = [m for m in db.read("raw_materials")
            if material_category(m) in order
            and (not categories or material_category(m) in categories)]
    rows.sort(key=lambda m: (order.index(material_category(m)),
                             m.get("subcategory") or "", m.get("name") or ""))
    return rows

# Packing channels the client ships through.
PACKING_CHANNELS = ["VIP", "Shopee", "TikTok", "Lazada", "Walk-in"]

# Why a buy is being asked for.  The client requires a reason on every request;
# these are the common ones, and "Other" lets the requester type their own.
REQUEST_REASONS = [
    "Out of stock",
    "Below reorder level",
    "Upcoming production batch",
    "New / larger order to fulfil",
    "Spoilage or damage replacement",
    "Quality rejected on delivery",
    "Equipment repair or maintenance",
    "Other",
]
URGENCY_LEVELS = ["Normal", "Urgent", "Critical"]
URGENCY_BADGE = {
    "Normal": "badge-muted",
    "Urgent": "badge-warn",
    "Critical": "badge-danger",
}

# Honey QC outcome is Pass / Failed only, as the client specified.
QC_RESULTS = ["Pass", "Failed"]
QC_APPEARANCE = ["Clear", "Cloudy", "Crystallized", "With sediment",
                 "Fermented / off-smell"]
# Pass/fail guide applied when the checker does not override it.
MOISTURE_PASS_MAX = 20.0

DISPOSITION_PASS = "For Selling"
DISPOSITION_FAIL = "For Other Products"


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def today_iso():
    """Local calendar date — every transaction is stamped for monitoring."""
    return date.today().isoformat()


def month_start_iso():
    return date.today().replace(day=1).isoformat()


def this_month():
    """'2026-10' — the period key used by monthly records."""
    return date.today().strftime("%Y-%m")


def fmt_dt(value, length=16):
    """'2026-10-14T08:30:00+00:00' -> '2026-10-14 08:30' for templates."""
    return (value or "")[:length].replace("T", " ")


def fmt_qty(value, unit=""):
    """12.0 -> '12', 11.4 -> '11.4', None -> '—'; optional unit appended."""
    if value in (None, ""):
        return "—"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    text = ("%.3f" % number).rstrip("0").rstrip(".")
    if text == "-0":
        text = "0"
    if abs(number) >= 1000:
        whole, _, frac = text.partition(".")
        sign = "-" if whole.startswith("-") else ""
        text = sign + "{:,}".format(int(whole.lstrip("-"))) + (("." + frac) if frac else "")
    return ("%s %s" % (text, unit)).strip() if unit else text


def fmt_peso(value):
    """1234.5 -> '₱1,234.50'."""
    try:
        return "₱{:,.2f}".format(float(value or 0))
    except (TypeError, ValueError):
        return "₱0.00"


# --- Item / stock primitives ----------------------------------------------
def _collection_for(item_type):
    return "raw_materials" if item_type == "material" else "products"


def _to_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def get_item(item_type, item_id):
    return db.get(_collection_for(item_type), item_id)


def item_name(item_type, item_id):
    item = get_item(item_type, item_id)
    return item.get("name") if item else ("Item #%s" % item_id)


def item_unit(item_type, item_id):
    item = get_item(item_type, item_id)
    return item.get("unit", "") if item else ""


def current_stock(item_type, item_id):
    """Single source of truth for stock reads (float, 0.0 default)."""
    item = get_item(item_type, item_id)
    return _to_float(item.get("stock_qty", 0)) if item else 0.0


def record_txn(item_type, item_id, change_qty, txn_type,
               reference_id=None, user_id=None):
    """Append an inventory-ledger row.  Does NOT change stock_qty."""
    return db.insert("inventory_transactions", {
        "item_type": item_type,
        "item_id": int(item_id),
        "change_qty": float(change_qty),
        "txn_type": txn_type,
        "reference_id": reference_id,
        "user_id": user_id,
        "timestamp": now_iso(),
    })


def adjust_stock(item_type, item_id, delta, txn_type,
                 reference_id=None, user_id=None):
    """Move stock by ``delta`` AND record a matching ledger txn.

    Returns the updated item (or None if the item does not exist)."""
    collection = _collection_for(item_type)
    item = db.get(collection, item_id)
    if not item:
        return None
    new_qty = _to_float(item.get("stock_qty", 0)) + float(delta)
    item = db.update(collection, item_id, {"stock_qty": new_qty})
    record_txn(item_type, item_id, delta, txn_type,
               reference_id=reference_id, user_id=user_id)
    return item


def record_adjustment(item_type, item_id, new_qty, reason, user_id=None):
    """Set stock to an absolute value; log an Inventory_Adjustment + ledger txn."""
    collection = _collection_for(item_type)
    item = db.get(collection, item_id)
    if not item:
        return None
    old = _to_float(item.get("stock_qty", 0))
    delta = float(new_qty) - old
    if delta == 0:
        return item
    db.insert("inventory_adjustments", {
        "item_type": item_type,
        "item_id": int(item_id),
        "old_qty": old,
        "new_qty": float(new_qty),
        "delta": delta,
        "reason": reason or "Manual adjustment",
        "user_id": user_id,
        "timestamp": now_iso(),
    })
    return adjust_stock(item_type, item_id, delta, "adjusted",
                        reference_id="adjustment", user_id=user_id)


# --- Bill of materials -----------------------------------------------------
def requirements_for(product_id, qty):
    """Per-material requirement rows for producing ``qty`` of a product."""
    qty = _to_float(qty)
    rows = []
    for line in db.query("bill_of_materials", product_id=int(product_id)):
        material = db.get("raw_materials", line.get("material_id"))
        if not material:
            continue
        qty_per_unit = _to_float(line.get("qty_per_unit", 0))
        required = qty_per_unit * qty
        on_hand = current_stock("material", material["id"])
        rows.append({
            "material_id": material["id"],
            "material_name": material.get("name"),
            "unit": material.get("unit"),
            "qty_per_unit": qty_per_unit,
            "required": required,
            "on_hand": on_hand,
            "shortfall": max(0.0, required - on_hand),
        })
    return rows


def can_produce(product_id, qty):
    return all(r["shortfall"] <= 0 for r in requirements_for(product_id, qty))


# --- Production ------------------------------------------------------------
def record_production(product_id, qty, user_id=None, rejected=0.0, damaged=0.0):
    """Consume BOM materials and add finished goods.

    Returns ``(order, None)`` on success or ``(None, message)`` if materials are
    insufficient (no stock is moved in that case)."""
    product = db.get("products", product_id)
    if not product:
        return None, "Product not found."
    qty = _to_float(qty)
    if qty <= 0:
        return None, "Quantity must be greater than zero."

    rows = requirements_for(product_id, qty)
    short = [r for r in rows if r["shortfall"] > 0]
    if short:
        names = ", ".join(r["material_name"] for r in short)
        return None, ("Insufficient materials to produce %g x %s (short: %s)."
                      % (qty, product.get("name"), names))

    order = db.insert("production_orders", {
        "product_id": int(product_id),
        "product_name": product.get("name"),
        "qty": qty,
        "batch_no": "",
        "status": "Completed",
        "output_qty": qty,
        "rejected_qty": _to_float(rejected),
        "damaged_qty": _to_float(damaged),
        "materials_used": [{"material_id": r["material_id"], "qty": r["required"]}
                           for r in rows],
        "user_id": user_id,
        "timestamp": now_iso(),
    })
    order = db.update("production_orders", order["id"],
                      {"batch_no": "BR-%d" % order["id"]})

    for r in rows:
        adjust_stock("material", r["material_id"], -r["required"], "consumed",
                     reference_id=order["id"], user_id=user_id)
    adjust_stock("product", product_id, qty, "produced",
                 reference_id=order["id"], user_id=user_id)
    return order, None


def production_history(limit=None):
    """Newest-first production runs shaped for the production/index template."""
    orders = sorted(db.read("production_orders"),
                    key=lambda o: o.get("timestamp", ""), reverse=True)
    if limit:
        orders = orders[:limit]
    rows = []
    for o in orders:
        rows.append({
            "timestamp": o.get("timestamp"),
            "product": o.get("product_name"),
            "qty": o.get("qty"),
            "user": user_name(o.get("user_id")),
            "reference_id": o.get("batch_no") or o.get("id"),
        })
    return rows


# --- Notifications ---------------------------------------------------------
def notify(user_id, message, link=None):
    if user_id is None:
        return None
    return db.insert("notifications", {
        "user_id": int(user_id),
        "message": message,
        "link": link,
        "is_read": False,
        "created_at": now_iso(),
    })


def notify_role(role, message, link=None):
    created = []
    for user in db.read("users"):
        if not user.get("active", True):
            continue
        if security.normalize_role(user.get("role")) == role:
            created.append(notify(user["id"], message, link=link))
    return created


def notify_admins(message, link=None):
    """Notify every active Super Admin / Admin (the approval queue owners)."""
    created = []
    for user in db.read("users"):
        if user.get("active", True) and security.is_admin(user):
            created.append(notify(user["id"], message, link=link))
    return created


def notify_team(roles, message, link=None, admins=True):
    """One notification to every active user in ``roles`` (and the admins).

    This is how the floor tells the next team something has arrived from a
    given area — e.g. a delivery received at the Receiving Area tells the
    production team there are boxes to inspect."""
    rows, now = [], now_iso()
    for user in db.read("users"):
        if not user.get("active", True):
            continue
        role = security.normalize_role(user.get("role"))
        if role in roles or (admins and security.is_admin(user)):
            rows.append({"user_id": int(user["id"]), "message": message,
                         "link": link, "is_read": False, "created_at": now})
    return db.insert_many("notifications", rows)


def unread_count(user_id):
    if user_id is None:
        return 0
    try:
        uid = int(user_id)
    except (TypeError, ValueError):
        return 0
    return sum(1 for n in db.read("notifications")
               if int(n.get("user_id", 0)) == uid and not n.get("is_read", False))


# --- Users -----------------------------------------------------------------
def user_name(user_id):
    if user_id is None:
        return "—"
    u = db.get("users", user_id)
    return u.get("name") if u else "—"


def users_by_id():
    return {u["id"]: u for u in db.read("users")}


# --- Purchase requests (procurement -> approval -> QR receive) --------------
def qr_token(request_id, item_id):
    return "PR-%s-%s" % (request_id, item_id)


def parse_qr_token(token):
    """Return (request_id, item_id) ints, or (None, None) if malformed."""
    try:
        parts = (token or "").strip().split("-")
        if len(parts) == 3 and parts[0].upper() == "PR":
            return int(parts[1]), int(parts[2])
    except (ValueError, AttributeError):
        pass
    return None, None


def create_production_request(requestor_id, product_id, qty, item_lines,
                              reason="", remarks="", needed_by="",
                              urgency="Normal"):
    """Raise a recipe/ingredient request for a production run.

    ``item_lines``: list of {material_id, requested_qty, note}.  ``reason`` is
    mandatory for the client (why the buy is needed — out of stock, bigger
    batch, spoilage, …) and is shown to the approver."""
    product = db.get("products", product_id)
    items = []
    for i, line in enumerate(item_lines, start=1):
        items.append({
            "item_id": i,
            "material_id": int(line["material_id"]),
            "requested_qty": _to_float(line.get("requested_qty", 0)),
            "approved_qty": None,
            "received_qty": None,
            "status": "Pending",
            "note": (line.get("note") or "").strip(),
            "qr_token": None,
        })
    req = db.insert("purchase_requests", {
        "type": "production",
        "requestor_id": int(requestor_id),
        "product_id": int(product_id),
        "product_name": product.get("name") if product else None,
        "qty": _to_float(qty),
        "reason": (reason or "").strip(),
        "needed_by": (needed_by or "").strip(),
        "urgency": urgency or "Normal",
        "status": "Pending Approval",
        "remarks": (remarks or "").strip(),
        "items": items,
        "created_at": now_iso(),
    })
    notify_admins("New production request #%d awaiting approval — %s."
                  % (req["id"], (reason or "no reason given")[:80]),
                  link="/approvals/%d" % req["id"])
    return req


def create_material_request(requestor_id, category, name, qty, description="",
                            reason="", needed_by="", urgency="Normal"):
    req = db.insert("purchase_requests", {
        "type": "material",
        "requestor_id": int(requestor_id),
        "reason": (reason or "").strip(),
        "needed_by": (needed_by or "").strip(),
        "urgency": urgency or "Normal",
        "status": "Pending Approval",
        "remarks": "",
        "items": [{
            "item_id": 1,
            "name": (name or "").strip(),
            "category": category,
            "description": (description or "").strip(),
            "material_id": None,
            "requested_qty": _to_float(qty),
            "approved_qty": None,
            "received_qty": None,
            "status": "Pending",
            "note": "",
            "qr_token": None,
        }],
        "created_at": now_iso(),
    })
    notify_admins("New material request #%d awaiting approval — %s."
                  % (req["id"], (reason or "no reason given")[:80]),
                  link="/approvals/%d" % req["id"])
    return req


def apply_decision(request_id, decisions, remarks, action, decider_id=None):
    """Apply an approval decision.

    ``decisions``: {item_id: {"reject": bool, "approved_qty": str|None}}.
    ``action``: 'approve' | 'revise' | 'reject'.  No stock changes here.
    Returns the updated request (or None)."""
    req = db.get("purchase_requests", request_id)
    if not req:
        return None
    items = req.get("items", [])
    any_ordered = False
    any_revised = False

    for it in items:
        iid = it["item_id"]
        requested = _to_float(it.get("requested_qty", 0))
        if action == "reject":
            approved = 0.0
        else:
            d = decisions.get(iid, {})
            if d.get("reject"):
                approved = 0.0
            else:
                raw = d.get("approved_qty")
                if raw is None or str(raw).strip() == "":
                    approved = requested
                else:
                    approved = _to_float(raw, requested)
                    if approved < 0:
                        approved = 0.0
        if float(approved).is_integer():
            approved = int(approved)
        it["approved_qty"] = approved
        if approved and approved > 0:
            it["status"] = "Ordered"
            it["qr_token"] = qr_token(req["id"], iid)
            any_ordered = True
            if approved != requested:
                any_revised = True
        else:
            it["status"] = "Rejected"
            it["qr_token"] = None

    if not any_ordered:
        status = "Rejected"
    elif any_revised or action == "revise":
        status = "Revised"
    else:
        status = "Approved"

    req = db.update("purchase_requests", request_id, {
        "items": items,
        "status": status,
        "remarks": (remarks or "").strip(),
        "decided_by": decider_id,
        "decided_at": now_iso(),
    })
    notify(req.get("requestor_id"),
           "Your purchase request #%d was %s." % (request_id, status.lower()),
           link="/requests/%d" % request_id)
    return req


def receive_item(token, received_qty=None, note="", user_id=None):
    """Receive a material against a QR token.  Returns a dict:
    {ok, message, stock?} — ok False on any problem."""
    request_id, item_id = parse_qr_token(token)
    if request_id is None:
        return {"ok": False, "message": "Invalid QR token."}
    req = db.get("purchase_requests", request_id)
    if not req:
        return {"ok": False, "message": "Request %s not found." % request_id}

    items = req.get("items", [])
    target = next((it for it in items if it.get("item_id") == item_id), None)
    if not target:
        return {"ok": False, "message": "Item not found for token %s." % token}
    if target.get("status") == "Received":
        return {"ok": False, "message": "Item already received (token %s)." % token}
    if target.get("status") != "Ordered" or not target.get("qr_token"):
        return {"ok": False,
                "message": "Item is not ordered / has no QR token yet."}

    approved = _to_float(target.get("approved_qty") or target.get("requested_qty"))
    qty = approved if received_qty in (None, "") else _to_float(received_qty, approved)
    if qty <= 0:
        return {"ok": False, "message": "Received quantity must be positive."}

    material_id = target.get("material_id")
    if not material_id:
        # A material/equipment request that was not yet linked to a stock item:
        # create the raw material on the fly so stock can be tracked.
        material_id = _ensure_material_for_item(target)
        target["material_id"] = material_id

    item = adjust_stock("material", material_id, qty, "received",
                        reference_id=request_id, user_id=user_id)
    if item is None:
        return {"ok": False,
                "message": "Stock item %s no longer exists." % material_id}
    target["status"] = "Received"
    target["received_qty"] = qty
    if note:
        target["note"] = ((target.get("note") or "") + " " + note).strip()

    all_received = all(it.get("status") in ("Received", "Rejected") for it in items)
    new_status = "Received" if all_received else req.get("status")
    db.update("purchase_requests", request_id,
              {"items": items, "status": new_status})

    notify_admins(
                "Material received for request #%d (%s)." % (request_id,
                                                             item.get("name")),
                link="/requests/%d" % request_id)
    return {"ok": True,
            "message": "Received %g %s of %s." % (qty, item.get("unit", ""),
                                                  item.get("name")),
            "stock": item.get("stock_qty")}


def _ensure_material_for_item(item):
    """Create a raw_materials record for a material/equipment request item."""
    existing = db.query("raw_materials", name=item.get("name"))
    if existing:
        return existing[0]["id"]
    mat = db.insert("raw_materials", {
        "name": item.get("name") or "Received item",
        "category": item.get("category") or "cleaning",
        "unit": "pc",
        "stock_qty": 0.0,
        "reorder_level": 0,
        "supplier_id": None,
        "unit_cost": 0.0,
        "expiry_date": "",
    })
    return mat["id"]


# --- Internal sales requests (finished-goods release) ----------------------
def create_sales_request(requestor_id, product_id, qty, remarks=""):
    product = db.get("products", product_id)
    if not product:
        return None, "Product not found."
    qty = _to_float(qty)
    if qty <= 0:
        return None, "Quantity must be greater than zero."
    req = db.insert("sales_requests", {
        "product_id": int(product_id),
        "product_name": product.get("name"),
        "product_unit": product.get("unit"),
        "qty": qty,
        "requestor_id": int(requestor_id),
        "requestor_name": user_name(requestor_id),
        "status": "Pending Approval",
        "remarks": (remarks or "").strip(),
        "created_at": now_iso(),
    })
    notify_admins("New sales request #%d awaiting approval." % req["id"],
                link="/sales/")
    return req, None


def decide_sales_request(request_id, decision, remarks, decider_id=None):
    req = db.get("sales_requests", request_id)
    if not req:
        return None
    status = "Approved" if decision == "approve" else "Rejected"
    req = db.update("sales_requests", request_id, {
        "status": status,
        "remarks": (remarks or req.get("remarks") or "").strip(),
        "decided_by": decider_id,
    })
    notify(req.get("requestor_id"),
           "Your sales request #%d was %s." % (request_id, status.lower()),
           link="/sales/")
    if status == "Approved":
        notify_role("production_head",
                    "Sales request #%d approved — ready to fulfil." % request_id,
                    link="/sales/")
    return req


def fulfil_sales_request(request_id, user_id=None):
    req = db.get("sales_requests", request_id)
    if not req:
        return False, "Sales request not found."
    if req.get("status") != "Approved":
        return False, "Only approved requests can be fulfilled."
    qty = _to_float(req.get("qty"))
    stock = current_stock("product", req.get("product_id"))
    if qty > stock:
        return False, ("Cannot fulfil: only %g %s in stock (need %g)."
                       % (stock, req.get("product_unit") or "", qty))
    adjust_stock("product", req.get("product_id"), -qty, "sold",
                 reference_id=request_id, user_id=user_id)
    db.update("sales_requests", request_id,
              {"status": "Fulfilled", "fulfilled_by": user_id})
    notify(req.get("requestor_id"),
           "Your sales request #%d has been fulfilled." % request_id,
           link="/sales/")
    return True, "Sales request #%d fulfilled." % request_id


# --- Customer sales orders (invoice / payment / delivery / return) ---------
def create_sales_order(customer_id, lines, discount=0.0, remarks="", user_id=None):
    """lines: list of {product_id, qty, unit_price}.  Creates a Pending order
    (no stock movement until confirmed)."""
    customer = db.get("customers", customer_id)
    if not customer:
        return None, "Customer not found."
    items = []
    subtotal = 0.0
    for line in lines:
        product = db.get("products", line.get("product_id"))
        if not product:
            continue
        qty = _to_float(line.get("qty"))
        if qty <= 0:
            continue
        price = _to_float(line.get("unit_price"), _to_float(product.get("price")))
        line_total = qty * price
        subtotal += line_total
        items.append({
            "product_id": product["id"],
            "name": product.get("name"),
            "qty": qty,
            "unit_price": price,
            "line_total": line_total,
        })
    if not items:
        return None, "Add at least one product line."
    discount = _to_float(discount)
    total = max(0.0, subtotal - discount)
    order = db.insert("sales_orders", {
        "customer_id": int(customer_id),
        "customer_name": customer.get("name"),
        "status": "Pending",
        "order_date": now_iso(),
        "subtotal": subtotal,
        "discount": discount,
        "total": total,
        "payment_status": "Paid" if total <= 0 else "Unpaid",
        "remarks": (remarks or "").strip(),
        "created_by": user_id,
        "items": items,
    })
    notify_role("packing_head", "Sales order #%d created for %s." %
                (order["id"], customer.get("name")), link="/orders/%d" % order["id"])
    return order, None


def confirm_sales_order(order_id, user_id=None):
    """Deduct finished goods for every line and mark the order Confirmed."""
    order = db.get("sales_orders", order_id)
    if not order:
        return False, "Order not found."
    if order.get("status") != "Pending":
        return False, "Only pending orders can be confirmed."
    # Aggregate demand per product so duplicate lines are checked against stock
    # together (otherwise each line could pass the check independently).
    required = {}
    for it in order.get("items", []):
        pid = it.get("product_id")
        required[pid] = required.get(pid, 0.0) + _to_float(it.get("qty"))
    for pid, need in required.items():
        if need > current_stock("product", pid):
            product = db.get("products", pid)
            return False, ("Cannot confirm: not enough stock of %s."
                           % (product.get("name") if product else pid))
    for pid, need in required.items():
        adjust_stock("product", pid, -need, "sold",
                     reference_id=order_id, user_id=user_id)
    db.update("sales_orders", order_id, {"status": "Confirmed"})
    return True, "Order #%d confirmed and stock released." % order_id


def record_payment(order_id, amount, method="Cash", reference="", user_id=None):
    order = db.get("sales_orders", order_id)
    if not order:
        return False, "Order not found."
    amount = _to_float(amount)
    if amount <= 0:
        return False, "Payment amount must be positive."
    db.insert("payments", {
        "sales_order_id": int(order_id),
        "amount": amount,
        "method": method,
        "reference": (reference or "").strip(),
        "paid_at": now_iso(),
        "recorded_by": user_id,
    })
    paid = sum(_to_float(p.get("amount"))
               for p in db.query("payments", sales_order_id=int(order_id)))
    total = _to_float(order.get("total"))
    if total <= 0 or paid >= total:
        pstatus = "Paid"
    elif paid > 0:
        pstatus = "Partial"
    else:
        pstatus = "Unpaid"
    db.update("sales_orders", order_id, {"payment_status": pstatus})
    return True, "Payment of %.2f recorded (%s)." % (amount, pstatus)


def order_paid_amount(order_id):
    return sum(_to_float(p.get("amount"))
               for p in db.query("payments", sales_order_id=int(order_id)))


def create_delivery(order_id, scheduled_date="", driver="", address="",
                    user_id=None):
    order = db.get("sales_orders", order_id)
    if not order:
        return None, "Order not found."
    delivery = db.insert("deliveries", {
        "sales_order_id": int(order_id),
        "customer_name": order.get("customer_name"),
        "status": "Scheduled",
        "scheduled_date": scheduled_date,
        "driver": (driver or "").strip(),
        "address": (address or "").strip(),
        "delivered_at": None,
        "confirmed_by_customer": False,
        "notes": "",
        "created_by": user_id,
    })
    notify_role("packing_head", "Delivery #%d scheduled for order #%d." %
                (delivery["id"], order_id), link="/deliveries/")
    return delivery, None


def update_delivery(delivery_id, status=None, driver=None, scheduled_date=None,
                    confirmed=None, notes=None):
    delivery = db.get("deliveries", delivery_id)
    if not delivery:
        return None
    changes = {}
    if status:
        changes["status"] = status
        if status == "Delivered":
            changes["delivered_at"] = now_iso()
    if driver is not None:
        changes["driver"] = driver.strip()
    if scheduled_date is not None:
        changes["scheduled_date"] = scheduled_date
    if confirmed is not None:
        changes["confirmed_by_customer"] = bool(confirmed)
    if notes is not None:
        changes["notes"] = notes.strip()
    delivery = db.update("deliveries", delivery_id, changes)
    if changes.get("status") == "Delivered":
        order = db.get("sales_orders", delivery.get("sales_order_id"))
        if order and order.get("status") == "Confirmed":
            db.update("sales_orders", order["id"], {"status": "Delivered"})
    return delivery


def process_return(order_id, product_id, qty, reason, user_id=None):
    order = db.get("sales_orders", order_id)
    if not order:
        return None, "Order not found."
    qty = _to_float(qty)
    if qty <= 0:
        return None, "Return quantity must be positive."
    if order.get("status") not in ("Confirmed", "Delivered"):
        return None, "Only confirmed/delivered orders can have returns."
    line = next((it for it in order.get("items", [])
                 if int(it.get("product_id")) == int(product_id)), None)
    if not line:
        return None, "That product is not on this order."
    sold = _to_float(line.get("qty"))
    already = sum(_to_float(r.get("qty"))
                  for r in db.query("returns", sales_order_id=int(order_id))
                  if int(r.get("product_id")) == int(product_id))
    if qty > sold - already:
        return None, ("Cannot return more than was sold (%g remaining)."
                      % (sold - already))
    product = db.get("products", product_id)
    ret = db.insert("returns", {
        "sales_order_id": int(order_id),
        "product_id": int(product_id),
        "product_name": product.get("name") if product else None,
        "qty": qty,
        "reason": (reason or "").strip(),
        "status": "Received",
        "created_at": now_iso(),
        "handled_by": user_id,
    })
    adjust_stock("product", product_id, qty, "returned",
                 reference_id=order_id, user_id=user_id)
    return ret, None


# --- Shared reporting helpers ---------------------------------------------
def low_stock_materials():
    out = []
    for m in db.read("raw_materials"):
        reorder = _to_float(m.get("reorder_level", 0))
        stock = _to_float(m.get("stock_qty", 0))
        if reorder > 0 and stock <= reorder:
            out.append(m)
    return out


def is_low(material):
    reorder = _to_float(material.get("reorder_level", 0))
    stock = _to_float(material.get("stock_qty", 0))
    return reorder > 0 and stock <= reorder


# --- AI snapshot persistence (AI_Forecasts / AI_Recommendations tables) -----
def save_ai_forecasts(cards):
    """Persist the latest demand-forecast batch (replaces the prior snapshot)."""
    rows = []
    for i, c in enumerate(cards, start=1):
        rows.append({
            "id": i, "product_id": c.get("product_id"),
            "product_name": c.get("product_name"), "generated_at": now_iso(),
            "horizon_weeks": len(c.get("forecast", [])), "model": c.get("model"),
            "forecast": c.get("forecast"), "future_labels": c.get("future_labels"),
        })
    db.write("ai_forecasts", rows)


def save_ai_recommendations(recs):
    """Persist the latest AI recommendations (replaces the prior snapshot)."""
    rows = []
    for i, r in enumerate(recs, start=1):
        row = dict(r)
        row["id"] = i
        row["generated_at"] = now_iso()
        row["acted_on"] = False
        rows.append(row)
    db.write("ai_recommendations", rows)


# ===========================================================================
#  MODULE 1 - RECEIVING AREA, then INSPECTION & CLEANING
# ===========================================================================
# Part 1 (Receiving Team Head): a delivery arrives -> it is recorded once,
#   with every box / crate logged with its item and quantity (kg for ginger,
#   pieces for lemon, units for bottles) -> each box gets its own QR label
#   carrying the code, item, quantity and delivery details -> the production
#   team is notified that boxes are waiting at the Receiving Area.
# Part 2 (inspection & cleaning): the box is scanned, cleaned and checked,
#   and its content is split into USABLE / CAN'T BE USED / DAMAGED.  The
#   decision is Accepted, Rejected or Hold (pending test / document / QA).
#   Only the usable quantity of an accepted box joins stock; the rest goes
#   to the damage ledger with its reason.
# Every box keeps its own stage so stock can be located at any moment.

BOX_STAGES = ["Receiving Area", "Storage Area", "Production Area", "Consumed"]
# The order a box moves through the site — drawn as a track on its page.
BOX_TRACK = ["Received", "Inspected & cleaned", "Storage Area",
             "Production Area", "Consumed"]

BOX_AWAITING = "Awaiting Inspection"
BOX_HOLD = "On Hold"
BOX_ACCEPTED = "Accepted"
BOX_REJECTED = "Rejected"

ACCEPTANCE = ["Accepted", "Rejected", "Hold"]
PACKAGING_CONDITIONS = ["Good / intact", "Slightly dented / torn",
                        "Wet / soiled", "Badly damaged"]
INSPECTION_RESULTS = ["Pass", "Fail", "Not applicable"]
COA_RESULTS = ["Complete", "Incomplete", "Not required"]
SAMPLING_RESULTS = ["Passed", "Failed", "Pending result", "Not required"]

# Statuses written by earlier versions of the system.
_LEGACY_BOX_STATUS = {"Pending Check": BOX_AWAITING, "Checked": BOX_ACCEPTED,
                      "Stored": BOX_ACCEPTED, "Released": BOX_ACCEPTED,
                      "Consumed": BOX_ACCEPTED}
_LEGACY_STAGE = {"Storage": "Storage Area",
                 "Production Floor": "Production Area"}


def box_status(box):
    status = box.get("status")
    return _LEGACY_BOX_STATUS.get(status, status)


def box_stage(box):
    stage = box.get("stage")
    return _LEGACY_STAGE.get(stage, stage)


def box_token(box_id):
    return "RB-%d" % int(box_id)


def container_token(container_id):
    return "HC-%d" % int(container_id)


def packing_token(run_id):
    return "PK-%d" % int(run_id)


def _next_ref(prefix, collection, field="ref_no"):
    """Sequential human reference like RCV-2026-0007 (per calendar year)."""
    year = date.today().year
    stem = "%s-%d-" % (prefix, year)
    highest = 0
    for row in db.read(collection):
        value = str(row.get(field) or "")
        if value.startswith(stem):
            try:
                highest = max(highest, int(value[len(stem):]))
            except ValueError:
                continue
    return "%s%04d" % (stem, highest + 1)


def create_receiving_batch(supplier_id, received_date, user_id,
                           delivery_ref="", remarks="", po_no=""):
    """Open a delivery record.  Boxes are added to it next."""
    supplier = db.get("suppliers", supplier_id) if supplier_id else None
    batch = db.insert("receiving_batches", {
        "ref_no": _next_ref("RCV", "receiving_batches"),
        "supplier_id": int(supplier_id) if supplier_id else None,
        "supplier_name": supplier.get("name") if supplier
                         else "Walk-in / own harvest",
        "po_no": (po_no or "").strip(),
        "delivery_ref": (delivery_ref or "").strip(),
        "received_date": received_date or today_iso(),
        "received_by": user_id,
        "status": "Open",
        "remarks": (remarks or "").strip(),
        "box_count": 0,
        "total_declared": 0.0,
        "total_good": 0.0,
        "total_unusable": 0.0,
        "total_damaged": 0.0,
        "checked_by_name": "",
        "approved_by_name": "",
        "created_at": now_iso(),
        "closed_at": None,
    })
    return batch


def add_receiving_box(batch_id, material_id, declared_qty, user_id,
                      location="Receiving Area", count=1, lot_no="",
                      expiry_date="", packaging_condition="",
                      temperature_c=None):
    """Add ``count`` boxes of one item to a delivery, each with a QR code."""
    batch = db.get("receiving_batches", batch_id)
    if not batch:
        return [], "Delivery not found."
    if batch.get("status") != "Open":
        return [], "This delivery is already closed."
    material = db.get("raw_materials", material_id)
    if not material:
        return [], "Choose the item that arrived."
    declared = _to_float(declared_qty)
    if declared <= 0:
        return [], "The quantity per box must be greater than zero."
    try:
        count = max(1, min(int(count), 100))
    except (TypeError, ValueError):
        count = 1
    temp = None
    if temperature_c not in (None, ""):
        temp = _to_float(temperature_c, None)

    existing = len(db.query("receiving_boxes", batch_id=int(batch_id)))
    created = []
    for i in range(count):
        box = db.insert("receiving_boxes", {
            "batch_id": int(batch_id),
            "box_code": "",
            "seq": existing + i + 1,
            "material_id": material["id"],
            "material_name": material.get("name"),
            "unit": material.get("unit"),
            "track_mode": material.get("track_mode") or "weight",
            "declared_qty": declared,
            "lot_no": (lot_no or "").strip(),
            "expiry_date": (expiry_date or "").strip(),
            "packaging_condition": (packaging_condition or "").strip(),
            "temperature_c": temp,
            "good_qty": None,
            "unusable_qty": 0.0,
            "unusable_reason": "",
            "damaged_qty": 0.0,
            "damage_reason": "",
            "cleaned": False,
            "visual_inspection": "",
            "coa_check": "",
            "sampling_test": "",
            "acceptance_status": "",
            "nonconformity": "",
            "action_taken": "",
            "verified_by_name": "",
            "checked_by": None,
            "checked_at": None,
            "status": BOX_AWAITING,
            "stage": "Receiving Area",
            "location": location,
            "released_to": "",
            "released_at": None,
            "received_by": user_id,
            "created_at": now_iso(),
        })
        box = db.update("receiving_boxes", box["id"],
                        {"box_code": box_token(box["id"])})
        created.append(box)
    _refresh_batch_totals(batch_id)
    return created, None


def receive_delivery(user_id, supplier_id, received_date, lines, po_no="",
                     delivery_ref="", remarks=""):
    """Part 1 in one go: the delivery, its boxes, their QR codes, and a
    notification to the team that inspects them.

    lines: [{material_id, qty_per_box, boxes, lot_no, expiry_date,
             packaging_condition, temperature_c}]
    Returns ``(batch, boxes, None)`` or ``(None, [], message)``."""
    clean = []
    for line in lines:
        if not line.get("material_id"):
            continue
        material = db.get("raw_materials", line.get("material_id"))
        if not material:
            return None, [], "One of the items no longer exists."
        if _to_float(line.get("qty_per_box")) <= 0:
            return None, [], ("Enter how much is in each box of %s."
                              % material.get("name"))
        clean.append((material, line))
    if not clean:
        return None, [], "Add at least one item that arrived."

    batch = create_receiving_batch(supplier_id, received_date, user_id,
                                   delivery_ref=delivery_ref, remarks=remarks,
                                   po_no=po_no)
    boxes = []
    for material, line in clean:
        created, err = add_receiving_box(
            batch["id"], material["id"], line.get("qty_per_box"), user_id,
            count=line.get("boxes") or 1, lot_no=line.get("lot_no") or "",
            expiry_date=line.get("expiry_date") or "",
            packaging_condition=line.get("packaging_condition") or "",
            temperature_c=line.get("temperature_c"))
        if err:
            return None, [], err
        boxes.extend(created)

    batch = db.get("receiving_batches", batch["id"])
    summary = "; ".join(
        "%s %s in %d box(es)" % (
            material.get("name"),
            fmt_qty(_to_float(line.get("qty_per_box"))
                    * max(1, int(_to_float(line.get("boxes"), 1))),
                    material.get("unit") or ""),
            max(1, int(_to_float(line.get("boxes"), 1))))
        for material, line in clean)
    notify_team({"production_head", "receiving_head"},
                "Received at the Receiving Area — %s from %s: %s. Ready for "
                "inspection & cleaning."
                % (batch.get("ref_no"), batch.get("supplier_name"), summary),
                link="/receiving/%d" % batch["id"])
    return batch, boxes, None


def _refresh_batch_totals(batch_id):
    boxes = db.query("receiving_boxes", batch_id=int(batch_id))
    accepted = [b for b in boxes if box_status(b) == BOX_ACCEPTED]
    open_boxes = [b for b in boxes if box_status(b) in (BOX_AWAITING, BOX_HOLD)]
    changes = {
        "box_count": len(boxes),
        "total_declared": round(sum(_to_float(b.get("declared_qty"))
                                    for b in boxes), 3),
        "total_good": round(sum(_to_float(b.get("good_qty"))
                                for b in accepted), 3),
        "total_unusable": round(sum(_to_float(b.get("unusable_qty"))
                                    for b in boxes), 3),
        "total_damaged": round(sum(_to_float(b.get("damaged_qty"))
                                   for b in boxes), 3),
    }
    batch = db.get("receiving_batches", batch_id) or {}
    # A delivery completes itself once every box has a final decision.
    if boxes and not open_boxes and batch.get("status") == "Open":
        changes.update({"status": "Completed", "closed_at": now_iso()})
    return db.update("receiving_batches", batch_id, changes)


def _post_box_decision(box, material, user_id):
    """Move stock / write damage for a box whose decision is final."""
    status = box_status(box)
    good = _to_float(box.get("good_qty"))
    unusable = _to_float(box.get("unusable_qty"))
    damaged = _to_float(box.get("damaged_qty"))
    code = box.get("box_code")
    unit = material.get("unit")
    if status == BOX_ACCEPTED and good > 0:
        adjust_stock("material", material["id"], good, "received",
                     reference_id=code, user_id=user_id)
    if unusable > 0:
        record_damage("inspection", code, "material", material["id"],
                      material.get("name"), unusable, unit,
                      "Can't be used: %s" % (box.get("unusable_reason") or "-"),
                      stage="Inspection & Cleaning", user_id=user_id)
    if damaged > 0:
        record_damage("inspection", code, "material", material["id"],
                      material.get("name"), damaged, unit,
                      "Damaged: %s" % (box.get("damage_reason") or "-"),
                      stage="Inspection & Cleaning", user_id=user_id)


def inspect_receiving_box(box_id, user_id, usable_qty, unusable_qty=0,
                          damaged_qty=0, unusable_reason="", damage_reason="",
                          cleaned=False, visual_inspection="", coa_check="",
                          sampling_test="", acceptance="Accepted",
                          nonconformity="", action_taken="",
                          verified_by_name=""):
    """Part 2: record the inspection & cleaning of one box.

    Returns ``(box, None)`` or ``(None, message)``."""
    box = db.get("receiving_boxes", box_id)
    if not box:
        return None, "Box not found."
    if box_status(box) != BOX_AWAITING:
        return None, ("Box %s was already inspected (%s)."
                      % (box.get("box_code"), box_status(box)))
    usable = _to_float(usable_qty)
    unusable = _to_float(unusable_qty)
    damaged = _to_float(damaged_qty)
    if min(usable, unusable, damaged) < 0:
        return None, "Quantities cannot be negative."
    if usable + unusable + damaged <= 0:
        return None, "Enter how much is usable, can't be used or damaged."
    if unusable > 0 and not (unusable_reason or "").strip():
        return None, "Say why part of the box can't be used."
    if damaged > 0 and not (damage_reason or "").strip():
        return None, "Say what the damage is."
    if acceptance not in ACCEPTANCE:
        return None, "Choose Accepted, Rejected or Hold."
    if acceptance in ("Rejected", "Hold") and not (nonconformity or "").strip():
        return None, "Describe the nonconformity behind this decision."

    material = db.get("raw_materials", box.get("material_id"))
    if not material:
        return None, "The item in this box no longer exists."

    status = {"Accepted": BOX_ACCEPTED, "Rejected": BOX_REJECTED,
              "Hold": BOX_HOLD}[acceptance]
    stage = {"Accepted": "Storage Area", "Rejected": "Receiving Area",
             "Hold": "Receiving Area"}[acceptance]
    box = db.update("receiving_boxes", box_id, {
        "good_qty": usable,
        "unusable_qty": unusable,
        "unusable_reason": (unusable_reason or "").strip(),
        "damaged_qty": damaged,
        "damage_reason": (damage_reason or "").strip(),
        "cleaned": bool(cleaned),
        "visual_inspection": visual_inspection or "",
        "coa_check": coa_check or "",
        "sampling_test": sampling_test or "",
        "acceptance_status": acceptance,
        "nonconformity": (nonconformity or "").strip(),
        "action_taken": (action_taken or "").strip(),
        "verified_by_name": (verified_by_name or "").strip(),
        "status": status,
        "stage": stage,
        "checked_by": user_id,
        "checked_at": now_iso(),
    })
    if status != BOX_HOLD:
        _post_box_decision(box, material, user_id)
    _refresh_batch_totals(box.get("batch_id"))

    unit = material.get("unit") or ""
    message = ("Inspected %s (%s): %s usable, %s can't be used, %s damaged — %s."
               % (box.get("box_code"), material.get("name"),
                  fmt_qty(usable, unit), fmt_qty(unusable, unit),
                  fmt_qty(damaged, unit), acceptance))
    if status == BOX_ACCEPTED:
        message += " Moved to the Storage Area."
    notify_team({"receiving_head", "production_head"}, message,
                link="/receiving/box/%d" % int(box_id))
    return box, None


def decide_held_box(box_id, decision, user_id, note=""):
    """Close a box that was put on Hold: Accepted or Rejected."""
    box = db.get("receiving_boxes", box_id)
    if not box:
        return None, "Box not found."
    if box_status(box) != BOX_HOLD:
        return None, "Only a box on hold waits for this decision."
    if decision not in ("Accepted", "Rejected"):
        return None, "Choose Accepted or Rejected."
    material = db.get("raw_materials", box.get("material_id"))
    if not material:
        return None, "The item in this box no longer exists."
    action = (box.get("action_taken") or "").strip()
    if (note or "").strip():
        action = ("%s\n%s" % (action, note.strip())).strip()
    box = db.update("receiving_boxes", box_id, {
        "acceptance_status": decision,
        "status": BOX_ACCEPTED if decision == "Accepted" else BOX_REJECTED,
        "stage": "Storage Area" if decision == "Accepted" else "Receiving Area",
        "action_taken": action,
        "checked_by": user_id,
        "checked_at": now_iso(),
    })
    _post_box_decision(box, material, user_id)
    _refresh_batch_totals(box.get("batch_id"))
    notify_team({"receiving_head", "production_head"},
                "Box %s on hold is now %s." % (box.get("box_code"), decision),
                link="/receiving/box/%d" % int(box_id))
    return box, None


def move_receiving_box(box_id, stage, user_id=None, released_to=""):
    """Move an accepted box along the floor so its location is always known."""
    box = db.get("receiving_boxes", box_id)
    if not box:
        return None, "Box not found."
    if stage not in BOX_STAGES[1:]:
        return None, "Unknown area."
    if box_status(box) != BOX_ACCEPTED:
        return None, "Only an accepted box can be moved."
    box = db.update("receiving_boxes", box_id, {
        "stage": stage,
        "status": BOX_ACCEPTED,
        "released_to": (released_to or box.get("released_to") or "").strip(),
        "released_at": now_iso() if stage in ("Production Area", "Consumed")
                       else box.get("released_at"),
    })
    return box, None


def close_receiving_batch(batch_id, user_id=None):
    batch = db.get("receiving_batches", batch_id)
    if not batch:
        return None, "Delivery not found."
    boxes = db.query("receiving_boxes", batch_id=int(batch_id))
    if not boxes:
        return None, "Add at least one box before closing the delivery."
    pending = [b for b in boxes if box_status(b) in (BOX_AWAITING, BOX_HOLD)]
    if pending:
        return None, ("%d box(es) still need a decision before this delivery "
                      "can be closed." % len(pending))
    _refresh_batch_totals(batch_id)
    batch = db.update("receiving_batches", batch_id,
                      {"status": "Completed", "closed_at": now_iso()})
    return batch, None


def box_qr_text(box, batch=None):
    """What a box's QR code carries: the code first (so any scanner finds it),
    then the item, quantity and delivery details, all on one line."""
    batch = batch or db.get("receiving_batches", box.get("batch_id")) or {}
    parts = [box.get("box_code") or box_token(box["id"]),
             box.get("material_name") or "",
             fmt_qty(box.get("declared_qty"), box.get("unit") or "")]
    if box.get("lot_no"):
        parts.append("Lot %s" % box.get("lot_no"))
    if box.get("expiry_date"):
        parts.append("Exp %s" % box.get("expiry_date"))
    parts += [batch.get("ref_no") or "",
              "Rcvd %s" % (batch.get("received_date") or ""),
              batch.get("supplier_name") or "",
              "Amamio Farm Products - Receiving Area"]
    return " | ".join(p for p in parts if p)


def box_track(box):
    """[(label, state)] for the flow track on a box's page."""
    status, stage = box_status(box), box_stage(box)
    if status == BOX_AWAITING:
        reached = 0
    elif status in (BOX_HOLD, BOX_REJECTED):
        reached = 1
    else:
        reached = {"Storage Area": 2, "Production Area": 3,
                   "Consumed": 4}.get(stage, 2)
    steps = []
    for i, label in enumerate(BOX_TRACK):
        if status == BOX_REJECTED and i > 1:
            break
        state = "done" if i < reached else ("now" if i == reached else "")
        steps.append((label, state))
    return steps


def receiving_box_rows(batch_id=None, status=None, limit=None):
    """Boxes shaped for the receiving templates."""
    boxes = db.read("receiving_boxes")
    if batch_id is not None:
        boxes = [b for b in boxes if b.get("batch_id") == int(batch_id)]
    if status:
        wanted = status if isinstance(status, (list, tuple, set)) else [status]
        boxes = [b for b in boxes if box_status(b) in wanted]
    boxes.sort(key=lambda b: (b.get("batch_id") or 0, b.get("seq") or 0))
    batches = {b["id"]: b for b in db.read("receiving_batches")}
    rows = []
    for b in boxes:
        batch = batches.get(b.get("batch_id"), {})
        status_now = box_status(b)
        rows.append({
            "id": b["id"], "box_code": b.get("box_code"), "seq": b.get("seq"),
            "material_id": b.get("material_id"),
            "material_name": b.get("material_name"), "unit": b.get("unit"),
            "track_mode": b.get("track_mode"),
            "track_label": TRACK_MODE_LABELS.get(b.get("track_mode"), ""),
            "declared_qty": b.get("declared_qty"),
            "lot_no": b.get("lot_no"), "expiry_date": b.get("expiry_date"),
            "packaging_condition": b.get("packaging_condition"),
            "temperature_c": b.get("temperature_c"),
            "good_qty": b.get("good_qty"),
            "unusable_qty": b.get("unusable_qty"),
            "unusable_reason": b.get("unusable_reason"),
            "damaged_qty": b.get("damaged_qty"),
            "damage_reason": b.get("damage_reason"),
            "cleaned": b.get("cleaned"),
            "visual_inspection": b.get("visual_inspection"),
            "coa_check": b.get("coa_check"),
            "sampling_test": b.get("sampling_test"),
            "acceptance_status": b.get("acceptance_status"),
            "nonconformity": b.get("nonconformity"),
            "action_taken": b.get("action_taken"),
            "verified_by_name": b.get("verified_by_name"),
            "status": status_now, "stage": box_stage(b),
            "badge": BOX_BADGE.get(status_now, "badge-muted"),
            "checked_by": user_name(b.get("checked_by")),
            "checked_at": fmt_dt(b.get("checked_at")),
            "received_at": fmt_dt(b.get("created_at")),
            "batch_ref": batch.get("ref_no"),
            "batch_id": b.get("batch_id"),
            "po_no": batch.get("po_no"),
            "delivery_ref": batch.get("delivery_ref"),
            "supplier_name": batch.get("supplier_name"),
            "received_date": batch.get("received_date"),
        })
    if limit:
        rows = rows[-limit:]
    return rows


# --- Damage ledger ---------------------------------------------------------
def record_damage(source, reference, item_type, item_id, item_name, qty, unit,
                  reason, stage="", user_id=None):
    """One row per damage event, wherever in the flow it was spotted."""
    return db.insert("damage_records", {
        "source": source,
        "reference": reference,
        "item_type": item_type,
        "item_id": int(item_id) if item_id else None,
        "item_name": item_name,
        "qty": _to_float(qty),
        "unit": unit,
        "stage": stage,
        "reason": (reason or "").strip(),
        "recorded_by": user_id,
        "recorded_at": now_iso(),
    })


def damage_summary():
    """Totals per item and per source for the reports page."""
    by_item, by_source = {}, {}
    for d in db.read("damage_records"):
        qty = _to_float(d.get("qty"))
        key = (d.get("item_name") or "-", d.get("unit") or "")
        by_item[key] = by_item.get(key, 0.0) + qty
        src = d.get("source") or "other"
        by_source[src] = by_source.get(src, 0.0) + qty
    rows = [{"name": k[0], "unit": k[1], "qty": round(v, 3)}
            for k, v in by_item.items()]
    rows.sort(key=lambda r: r["qty"], reverse=True)
    return rows, by_source


# ===========================================================================
#  MODULE 2 - HONEY: containers, moisture / appearance QC, PASS or FAILED
# ===========================================================================
# Each honey container carries a QR code.  QC records moisture content and
# appearance; the result is PASS or FAILED only.
#   PASS   -> joins sellable honey stock and goes to the PASS products.
#   FAILED -> is never discarded: it is kept as "honey for processing" and
#             goes to the products that can still use it.
# Each container's honey is then allocated (in kg) to the products it went
# into, so every kilo can be traced.

# --- PLACEHOLDER product routing ------------------------------------------
# The client will confirm which products each kind of honey goes into; until
# then these are stand-ins taken from the product catalog.  Replace the two
# lists below (nothing else needs to change).
HONEY_PASS_PRODUCTS = [
    "Pure Honey",
    "RFH (Raw Forest Honey) with Comb",
]
HONEY_FAIL_PRODUCTS = [
    "Honey Lemon Ginger Concentrate",
    "Honey Calamansi Concentrate",
    "Honey Infused Turmeric Ginger",
    "Honey Infused Ginger",
    "Honey Vinegar",
]

HONEY_TRACK = ["Received", "Quality checked", "Routed", "Used in products"]
PROCESSING_HONEY = "Honey for Processing (QC failed)"


def honey_products_for(result):
    return HONEY_PASS_PRODUCTS if result == "Pass" else HONEY_FAIL_PRODUCTS


def create_honey_container(net_weight_kg, user_id, supplier_id=None,
                           source="Own harvest", harvest_date="",
                           received_date="", batch_ref="", gross_weight_kg=None,
                           tare_weight_kg=None, material_id=None):
    net = _to_float(net_weight_kg)
    if net <= 0:
        return None, "Net weight must be greater than zero."
    supplier = db.get("suppliers", supplier_id) if supplier_id else None
    container = db.insert("honey_containers", {
        "container_code": "",
        "batch_ref": (batch_ref or "").strip() or _next_ref(
            "HNY", "honey_containers", field="batch_ref"),
        "source": source,
        "supplier_id": int(supplier_id) if supplier_id else None,
        "supplier_name": supplier.get("name") if supplier else source,
        "harvest_date": harvest_date or "",
        "received_date": received_date or today_iso(),
        "gross_weight_kg": _to_float(gross_weight_kg) or None,
        "tare_weight_kg": _to_float(tare_weight_kg) or None,
        "net_weight_kg": net,
        "status": "Pending QC",
        "moisture_pct": None,
        "appearance": "",
        "qc_notes": "",
        "qc_by": None,
        "qc_at": None,
        "disposition": "",
        "allocated_to": "",
        "allocated_at": None,
        "allocated_kg": 0.0,
        "remaining_kg": net,
        "allocations": [],
        "material_id": int(material_id) if material_id else None,
        "created_by": user_id,
        "created_at": now_iso(),
    })
    container = db.update("honey_containers", container["id"],
                          {"container_code": container_token(container["id"])})
    return container, None


def log_honey_containers(count, net_weight_kg, user_id, **details):
    """Log ``count`` containers of the same weight in one go; one shared batch
    reference so they can be traced together.  Notifies production."""
    try:
        count = max(1, min(int(count), 50))
    except (TypeError, ValueError):
        count = 1
    if _to_float(net_weight_kg) <= 0:
        return [], "Net weight must be greater than zero."
    if not (details.get("batch_ref") or "").strip():
        details["batch_ref"] = _next_ref("HNY", "honey_containers",
                                         field="batch_ref")
    created = []
    for _ in range(count):
        container, err = create_honey_container(net_weight_kg, user_id,
                                                **details)
        if err:
            return created, err
        created.append(container)
    notify_team({"production_head"},
                "Honey received — %d container(s), %s kg in total (%s). "
                "Ready for moisture & appearance check."
                % (len(created), fmt_qty(_to_float(net_weight_kg) * len(created)),
                   details["batch_ref"]),
                link="/honey/")
    return created, None


def suggested_qc_result(moisture_pct, appearance):
    """The guide the checker sees before they confirm - never auto-applied."""
    moisture = _to_float(moisture_pct, -1)
    if moisture < 0:
        return ""
    if moisture > MOISTURE_PASS_MAX:
        return "Failed"
    if appearance in ("Fermented / off-smell", "With sediment"):
        return "Failed"
    return "Pass"


def record_honey_qc(container_id, result, moisture_pct, appearance, notes="",
                    user_id=None):
    """Apply the Pass/Failed decision and route the container accordingly."""
    container = db.get("honey_containers", container_id)
    if not container:
        return None, "Container not found."
    if container.get("status") in QC_RESULTS:
        return None, ("Container %s was already checked (%s)."
                      % (container.get("container_code"),
                         container.get("status")))
    if result not in QC_RESULTS:
        return None, "The QC result must be Pass or Failed."
    moisture = _to_float(moisture_pct, -1)
    if moisture < 0 or moisture > 100:
        return None, "Enter a moisture content between 0 and 100 %."
    if not appearance:
        return None, "Select the appearance observed."

    disposition = DISPOSITION_PASS if result == "Pass" else DISPOSITION_FAIL
    container = db.update("honey_containers", container_id, {
        "status": result,
        "moisture_pct": moisture,
        "appearance": appearance,
        "qc_notes": (notes or "").strip(),
        "qc_by": user_id,
        "qc_at": now_iso(),
        "disposition": disposition,
    })

    # Passed honey joins sellable raw-honey stock; failed honey is kept as its
    # own stock line for processing and is NOT added to the sellable pool.
    kg = _to_float(container.get("net_weight_kg"))
    if result == "Pass":
        material_id = container.get("material_id") or _honey_material_id()
        txn = "qc_passed"
    else:
        material_id = _processing_honey_id()
        txn = "qc_failed"
    if material_id:
        adjust_stock("material", material_id, kg, txn,
                     reference_id=container.get("container_code"),
                     user_id=user_id)
        db.update("honey_containers", container_id, {"material_id": material_id})

    notify_team({"production_head", "receiving_head"},
                "Honey container %s %s QC (%.1f%% moisture, %s) — %s."
                % (container.get("container_code"),
                   "PASSED" if result == "Pass" else "FAILED", moisture,
                   appearance.lower(), disposition.lower()),
                link="/honey/%d" % int(container_id))
    return container, None


def _honey_material_id():
    """The raw material that sellable honey accumulates into."""
    for name in ("Raw Honey", "Honey"):
        found = db.query("raw_materials", name=name)
        if found:
            return found[0]["id"]
    return None


def _processing_honey_id():
    """Stock line for failed honey, created the first time it is needed."""
    found = db.query("raw_materials", name=PROCESSING_HONEY)
    if found:
        return found[0]["id"]
    return db.insert("raw_materials", {
        "name": PROCESSING_HONEY, "category": "raw", "subcategory": "Honey",
        "unit": "kg", "track_mode": "weight", "stock_qty": 0.0,
        "reorder_level": 0, "supplier_id": None, "unit_cost": 0.0,
        "expiry_date": "", "storage_location": "Production Area",
        "created_at": now_iso(),
    })["id"]


def allocate_honey_container(container_id, product, kg, user_id=None):
    """Record how many kg of a checked container went into which product.

    A PASS container can only go to PASS products and a FAILED container to
    FAILED products.  Several allocations may be made until it is empty."""
    container = db.get("honey_containers", container_id)
    if not container:
        return None, "Container not found."
    result = container.get("status")
    if result not in QC_RESULTS:
        return None, "Run the quality check before using this container."
    product = (product or "").strip()
    if product not in honey_products_for(result):
        return None, ("Choose one of the products %s honey goes into."
                      % ("passed" if result == "Pass" else "failed"))
    remaining = _to_float(container.get("remaining_kg",
                                        container.get("net_weight_kg")))
    amount = _to_float(kg)
    if amount <= 0:
        return None, "Enter how many kg were used."
    if amount > remaining + 1e-9:
        return None, "Only %s kg is left in this container." % fmt_qty(remaining)

    allocations = list(container.get("allocations") or [])
    allocations.append({"product": product, "kg": amount,
                        "allocated_by": user_id, "allocated_at": now_iso()})
    used = round(sum(_to_float(a.get("kg")) for a in allocations), 3)
    names = []
    for a in allocations:
        if a["product"] not in names:
            names.append(a["product"])
    return db.update("honey_containers", container_id, {
        "allocations": allocations,
        "allocated_kg": used,
        "remaining_kg": round(max(0.0, remaining - amount), 3),
        "allocated_to": ", ".join(names),
        "allocated_at": now_iso(),
    }), None


def honey_track(container):
    status = container.get("status")
    remaining = _to_float(container.get("remaining_kg",
                                        container.get("net_weight_kg")))
    if status not in QC_RESULTS:
        reached = 1
    elif not container.get("allocations"):
        reached = 2
    else:
        reached = 3 if remaining > 0 else 4
    labels = list(HONEY_TRACK)
    if status in QC_RESULTS:
        labels[2] = "Routed: %s" % container.get("disposition")
    return [(label, "done" if i < reached else ("now" if i == reached else ""))
            for i, label in enumerate(labels)]


def honey_qr_text(container):
    parts = [container.get("container_code") or container_token(container["id"]),
             "Honey", fmt_qty(container.get("net_weight_kg"), "kg"),
             container.get("batch_ref") or "",
             "Rcvd %s" % (container.get("received_date") or ""),
             container.get("supplier_name") or container.get("source") or "",
             "Amamio Farm Products - Honey"]
    return " | ".join(p for p in parts if p)


def honey_summary():
    containers = db.read("honey_containers")

    def _kg(rows):
        return round(sum(_to_float(c.get("net_weight_kg")) for c in rows), 2)

    pending = [c for c in containers if c.get("status") == "Pending QC"]
    passed = [c for c in containers if c.get("status") == "Pass"]
    failed = [c for c in containers if c.get("status") == "Failed"]
    checked = len(passed) + len(failed)
    to_allocate = [c for c in passed + failed
                   if _to_float(c.get("remaining_kg",
                                      c.get("net_weight_kg"))) > 0]
    return {
        "total": len(containers), "pending": len(pending),
        "passed": len(passed), "failed": len(failed),
        "pending_kg": _kg(pending), "passed_kg": _kg(passed),
        "failed_kg": _kg(failed),
        "to_allocate": len(to_allocate),
        "pass_rate": round(100.0 * len(passed) / checked, 1) if checked else 0.0,
        "avg_moisture": round(
            sum(_to_float(c.get("moisture_pct")) for c in passed + failed)
            / checked, 2) if checked else 0.0,
    }


def honey_product_totals():
    """kg of honey per destination product, split PASS / FAILED."""
    totals = {}
    for c in db.read("honey_containers"):
        for a in c.get("allocations") or []:
            key = (c.get("status"), a.get("product"))
            totals[key] = totals.get(key, 0.0) + _to_float(a.get("kg"))
    rows = [{"result": k[0], "product": k[1], "kg": round(v, 3)}
            for k, v in totals.items()]
    rows.sort(key=lambda r: (r["result"] != "Pass", -r["kg"]))
    return rows


# ===========================================================================
#  MODULE 4 - PACKING AREA: packed, then disbursed or handed to the courier
# ===========================================================================
# The packing team records, per run and channel (VIP / Shopee / TikTok /
# Lazada / Walk-in), how many items were PACKED, then whether the parcels
# were DISBURSED (handed straight to the customer, VIP buyer, walk-in or an
# internal requester) or DELIVERED TO THE LOGISTICS / COURIER (with the
# courier name and tracking number).
# A run that is NOT tied to an internal sales order releases finished-goods
# stock when packed; a run tied to a sales order does not, because confirming
# that order already moved the stock.

DISPATCH_DISBURSED = "Disbursed"
DISPATCH_COURIER = "Handed to Courier"
DISPATCH_TYPES = [
    (DISPATCH_DISBURSED, "Disbursed",
     "Handed straight to the customer, VIP buyer, walk-in or another team"),
    (DISPATCH_COURIER, "Delivered to logistics / courier",
     "Picked up by J&T, SPX, Flash, LBC… with a tracking number"),
]
COURIERS = ["SPX Express (Shopee)", "J&T Express", "Flash Express", "LBC",
            "Ninja Van", "Lalamove", "Grab Express", "Own delivery", "Other"]
PACKING_FLOW = ["Packing", "Packed", "Disbursed / with courier"]
_LEGACY_PACKING_STATUS = {"Handed Over": DISPATCH_COURIER}


def packing_status(run):
    status = run.get("status")
    return _LEGACY_PACKING_STATUS.get(status, status)


def is_dispatched(run):
    return packing_status(run) in (DISPATCH_DISBURSED, DISPATCH_COURIER)


def create_packing_run(channel, packer_id, lines, user_id, pack_date="",
                       order_ref="", sales_order_id=None, remarks="",
                       courier="", tracking_no=""):
    """lines: list of {product_id, qty, damaged_qty, notes}."""
    if channel not in PACKING_CHANNELS:
        return None, "Choose a packing channel."
    packer = db.get("users", packer_id) if packer_id else None
    items, total, damaged_total = [], 0.0, 0.0
    for line in lines:
        product = db.get("products", line.get("product_id"))
        if not product:
            continue
        qty = _to_float(line.get("qty"))
        if qty <= 0:
            continue
        dmg = _to_float(line.get("damaged_qty"))
        if dmg < 0:
            return None, "Damaged quantities cannot be negative."
        total += qty
        damaged_total += dmg
        items.append({
            "product_id": product["id"],
            "name": product.get("name"),
            "qty": qty,
            "unit": product.get("unit"),
            "damaged_qty": dmg,
            "notes": (line.get("notes") or "").strip(),
        })
    if not items:
        return None, "Add at least one product with the quantity packed."

    run = db.insert("packing_runs", {
        "run_code": "",
        "channel": channel,
        "packer_id": int(packer_id) if packer_id else None,
        "packer_name": packer.get("name") if packer else "",
        "pack_date": pack_date or today_iso(),
        "order_ref": (order_ref or "").strip(),
        "sales_order_id": int(sales_order_id) if sales_order_id else None,
        "status": "In Progress",
        "total_qty": total,
        "damaged_qty": damaged_total,
        "stock_released": False,
        "dispatch_type": "",
        "handed_to": "",
        "handed_at": None,
        "courier": (courier or "").strip(),
        "tracking_no": (tracking_no or "").strip(),
        "parcel_count": None,
        "dispatch_notes": "",
        "dispatched_by": None,
        "remarks": (remarks or "").strip(),
        "items": items,
        "created_by": user_id,
        "created_at": now_iso(),
        "packed_at": None,
    })
    run = db.update("packing_runs", run["id"],
                    {"run_code": packing_token(run["id"])})
    return run, None


def mark_packed(run_id, user_id=None):
    """Confirm the run is packed; release finished goods when appropriate."""
    run = db.get("packing_runs", run_id)
    if not run:
        return None, "Packing run not found."
    if run.get("status") != "In Progress":
        return None, "Only a run in progress can be marked packed."

    linked_order = run.get("sales_order_id")
    if not linked_order:
        # Standalone run (platform / walk-in): check stock before releasing.
        needed = {}
        for item in run.get("items", []):
            pid = item.get("product_id")
            needed[pid] = needed.get(pid, 0.0) + _to_float(item.get("qty"))
        for pid, qty in needed.items():
            if qty > current_stock("product", pid):
                product = db.get("products", pid)
                return None, ("Not enough %s in stock to pack this run (%s on "
                              "hand)." % (product.get("name") if product else pid,
                                          fmt_qty(current_stock("product", pid))))
        for pid, qty in needed.items():
            adjust_stock("product", pid, -qty, "packed",
                         reference_id=run.get("run_code"), user_id=user_id)

    for item in run.get("items", []):
        dmg = _to_float(item.get("damaged_qty"))
        if dmg > 0:
            record_damage("packing", run.get("run_code"), "product",
                          item.get("product_id"), item.get("name"), dmg,
                          item.get("unit"),
                          item.get("notes") or "Damaged during packing",
                          stage="Packing Area", user_id=user_id)

    run = db.update("packing_runs", run_id, {
        "status": "Packed",
        "stock_released": not linked_order,
        "packed_at": now_iso(),
    })
    return run, None


def pack_now(channel, packer_id, lines, user_id, **details):
    """Create a run and mark it packed in one step — the usual case on the
    floor, where the record is made once the parcels are ready."""
    run, err = create_packing_run(channel, packer_id, lines, user_id, **details)
    if err:
        return None, err
    packed, err = mark_packed(run["id"], user_id=user_id)
    if err:
        # Keep the run so nothing typed is lost; it stays In Progress.
        return run, err
    return packed, None


def dispatch_packing_run(run_id, dispatch_type, handed_to, user_id=None,
                         courier="", tracking_no="", parcel_count=None,
                         notes=""):
    """Record where packed parcels went: disbursed, or to the courier."""
    run = db.get("packing_runs", run_id)
    if not run:
        return None, "Packing run not found."
    if run.get("status") != "Packed":
        return None, "Only a packed run can be disbursed or handed over."
    if dispatch_type not in (DISPATCH_DISBURSED, DISPATCH_COURIER):
        return None, "Choose disbursed or delivered to the courier."
    if not (handed_to or "").strip():
        return None, ("Record who received the parcels."
                      if dispatch_type == DISPATCH_DISBURSED
                      else "Record the rider / courier staff who picked up.")
    if dispatch_type == DISPATCH_COURIER and not (courier or "").strip():
        return None, "Choose the courier."
    count = None
    if parcel_count not in (None, ""):
        try:
            count = max(0, int(parcel_count))
        except (TypeError, ValueError):
            return None, "The number of parcels must be a whole number."
    run = db.update("packing_runs", run_id, {
        "status": dispatch_type,
        "dispatch_type": dispatch_type,
        "handed_to": handed_to.strip(),
        "handed_at": now_iso(),
        "courier": (courier or "").strip() if dispatch_type == DISPATCH_COURIER
                   else "",
        "tracking_no": (tracking_no or run.get("tracking_no") or "").strip(),
        "parcel_count": count,
        "dispatch_notes": (notes or "").strip(),
        "dispatched_by": user_id,
    })
    where = ("disbursed to %s" % handed_to.strip()
             if dispatch_type == DISPATCH_DISBURSED
             else "handed to %s (%s)" % (courier.strip(), handed_to.strip()))
    notify_team({"packing_head"},
                "Packing run %s (%s, %s item(s)) %s."
                % (run.get("run_code"), run.get("channel"),
                   fmt_qty(run.get("total_qty")), where),
                link="/packing/%d" % int(run_id))
    return run, None


def hand_over_packing_run(run_id, handed_to, courier="", tracking_no="",
                          user_id=None):
    """Older entry point: a hand-over is a delivery to the courier."""
    return dispatch_packing_run(run_id, DISPATCH_COURIER, handed_to,
                                user_id=user_id, courier=courier or "Other",
                                tracking_no=tracking_no)


def cancel_packing_run(run_id, user_id=None):
    """Cancel a run, returning any stock it had already released."""
    run = db.get("packing_runs", run_id)
    if not run:
        return None, "Packing run not found."
    if is_dispatched(run):
        return None, "A run that has left the packing area can't be cancelled."
    if run.get("status") == "Cancelled":
        return None, "This run is already cancelled."
    if run.get("stock_released"):
        for item in run.get("items", []):
            adjust_stock("product", item.get("product_id"),
                         _to_float(item.get("qty")), "returned",
                         reference_id=run.get("run_code"), user_id=user_id)
    return db.update("packing_runs", run_id,
                     {"status": "Cancelled", "stock_released": False}), None


def packing_track(run):
    status = packing_status(run)
    reached = {"In Progress": 0, "Packed": 1}.get(status, 2)
    labels = list(PACKING_FLOW)
    if is_dispatched(run):
        labels[2] = status
    return [(label, "done" if i < reached else ("now" if i == reached else ""))
            for i, label in enumerate(labels)]


def packing_qr_text(run):
    parts = [run.get("run_code") or packing_token(run["id"]),
             "Packed for %s" % (run.get("channel") or ""),
             "%s item(s)" % fmt_qty(run.get("total_qty")),
             run.get("order_ref") or "",
             run.get("pack_date") or "",
             "Packer %s" % (run.get("packer_name") or "-"),
             "Amamio Farm Products - Packing Area"]
    return " | ".join(p for p in parts if p)


def packing_summary(runs=None, date_from="", date_to=""):
    """Packed / disbursed / with-courier totals, per channel and overall."""
    runs = db.read("packing_runs") if runs is None else runs
    live = [r for r in runs if r.get("status") != "Cancelled"]
    if date_from:
        live = [r for r in live if (r.get("pack_date") or "") >= date_from]
    if date_to:
        live = [r for r in live if (r.get("pack_date") or "") <= date_to]

    def _qty(rows):
        return round(sum(_to_float(r.get("total_qty")) for r in rows), 2)

    def _split(rows):
        packed = [r for r in rows if r.get("status") != "In Progress"]
        disbursed = [r for r in rows if packing_status(r) == DISPATCH_DISBURSED]
        courier = [r for r in rows if packing_status(r) == DISPATCH_COURIER]
        waiting = [r for r in rows if r.get("status") == "Packed"]
        return {
            "runs": len(rows),
            "packed_qty": _qty(packed),
            "disbursed_qty": _qty(disbursed),
            "courier_qty": _qty(courier),
            "waiting_qty": _qty(waiting),
            "damaged": round(sum(_to_float(r.get("damaged_qty")) for r in rows), 2),
            "open": len([r for r in rows if r.get("status") == "In Progress"]),
            "waiting": len(waiting),
        }

    per_channel = []
    for channel in PACKING_CHANNELS:
        row = _split([r for r in live if r.get("channel") == channel])
        row["channel"] = channel
        row["qty"] = row["packed_qty"]
        per_channel.append(row)
    overall = _split(live)
    return {
        "per_channel": per_channel,
        "total_runs": len(live),
        "total_qty": overall["packed_qty"],
        "packed_qty": overall["packed_qty"],
        "disbursed_qty": overall["disbursed_qty"],
        "courier_qty": overall["courier_qty"],
        "waiting_qty": overall["waiting_qty"],
        "open_runs": overall["open"],
        "packed_runs": overall["waiting"],
        "damaged": overall["damaged"],
    }


def packer_leaderboard(limit=10):
    """Who packed how much - the client monitors packers per channel."""
    totals = {}
    for run in db.read("packing_runs"):
        if run.get("status") == "Cancelled":
            continue
        key = (run.get("packer_id"), run.get("packer_name") or "-")
        entry = totals.setdefault(key, {"name": key[1], "runs": 0, "qty": 0.0,
                                        "channels": set()})
        entry["runs"] += 1
        entry["qty"] += _to_float(run.get("total_qty"))
        entry["channels"].add(run.get("channel"))
    rows = []
    for entry in totals.values():
        rows.append({"name": entry["name"], "runs": entry["runs"],
                     "qty": round(entry["qty"], 2),
                     "channels": ", ".join(sorted(c for c in entry["channels"]
                                                  if c))})
    rows.sort(key=lambda r: r["qty"], reverse=True)
    return rows[:limit]


def qr_payload(token):
    """The full text a printed QR label carries for a code."""
    token = (token or "").strip().upper()
    prefix, _, rest = token.partition("-")
    try:
        if prefix == "RB":
            box = db.get("receiving_boxes", int(rest))
            return box_qr_text(box) if box else token
        if prefix == "HC":
            container = db.get("honey_containers", int(rest))
            return honey_qr_text(container) if container else token
        if prefix == "PK":
            run = db.get("packing_runs", int(rest))
            return packing_qr_text(run) if run else token
    except (TypeError, ValueError):
        pass
    return token


# ===========================================================================
#  ASSETS & MAINTENANCE
# ===========================================================================
MAINTENANCE_TYPES = ["Preventive", "Repair", "Inspection", "Calibration",
                     "Cleaning"]
MAINTENANCE_STATUS = ["Scheduled", "In Progress", "Completed", "Overdue"]
MAINTENANCE_BADGE = {
    "Scheduled": "badge-warn",
    "In Progress": "badge-warn",
    "Completed": "badge-ok",
    "Overdue": "badge-danger",
}
# Recording maintenance and what falls due live in assets_service.
