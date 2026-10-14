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
    "Pending Check": "badge-warn",
    "Checked": "badge-ok",
    "Stored": "badge-ok",
    "Released": "badge-muted",
    "Consumed": "badge-muted",
    "Rejected": "badge-danger",
}
QC_BADGE = {
    "Pending QC": "badge-warn",
    "Pass": "badge-ok",
    "Failed": "badge-danger",
}
PACKING_BADGE = {
    "In Progress": "badge-warn",
    "Packed": "badge-ok",
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


def fmt_dt(value, length=16):
    """'2026-10-14T08:30:00+00:00' -> '2026-10-14 08:30' for templates."""
    return (value or "")[:length].replace("T", " ")


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
#  RECEIVING AREA - crates / cage boxes, weight or piece, with damage count
# ===========================================================================
# Physical flow the client described:
#   delivery arrives -> a receiving batch is opened for the date/supplier
#   -> each cage box is logged with its material and declared quantity and
#      gets its own QR code
#   -> the checker scans a box, counts GOOD vs DAMAGED (kg for ginger, pcs for
#      lemon, ...) and accepts it; only the good quantity joins stock
#   -> every box keeps its own stage so stock can be located at any moment.

BOX_STAGES = ["Receiving Area", "Storage", "Production Floor", "Consumed"]


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
                           delivery_ref="", remarks=""):
    """Open a receiving session.  Boxes are added to it one by one."""
    supplier = db.get("suppliers", supplier_id) if supplier_id else None
    batch = db.insert("receiving_batches", {
        "ref_no": _next_ref("RCV", "receiving_batches"),
        "supplier_id": int(supplier_id) if supplier_id else None,
        "supplier_name": supplier.get("name") if supplier
                         else "Walk-in / own harvest",
        "delivery_ref": (delivery_ref or "").strip(),
        "received_date": received_date or today_iso(),
        "received_by": user_id,
        "status": "Open",
        "remarks": (remarks or "").strip(),
        "box_count": 0,
        "total_good": 0.0,
        "total_damaged": 0.0,
        "created_at": now_iso(),
        "closed_at": None,
    })
    return batch


def add_receiving_box(batch_id, material_id, declared_qty, user_id,
                      location="Receiving Area", count=1):
    """Add ``count`` cage boxes to a batch, each with its own QR code."""
    batch = db.get("receiving_batches", batch_id)
    if not batch:
        return [], "Receiving batch not found."
    if batch.get("status") != "Open":
        return [], "This batch is already closed."
    material = db.get("raw_materials", material_id)
    if not material:
        return [], "Material not found."
    declared = _to_float(declared_qty)
    if declared <= 0:
        return [], "Declared quantity must be greater than zero."
    try:
        count = max(1, min(int(count), 100))
    except (TypeError, ValueError):
        count = 1

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
            "good_qty": None,
            "damaged_qty": 0.0,
            "damage_reason": "",
            "status": "Pending Check",
            "stage": "Receiving Area",
            "location": location,
            "checked_by": None,
            "checked_at": None,
            "released_to": "",
            "released_at": None,
            "created_at": now_iso(),
        })
        box = db.update("receiving_boxes", box["id"],
                        {"box_code": box_token(box["id"])})
        created.append(box)
    _refresh_batch_totals(batch_id)
    return created, None


def _refresh_batch_totals(batch_id):
    boxes = db.query("receiving_boxes", batch_id=int(batch_id))
    return db.update("receiving_batches", batch_id, {
        "box_count": len(boxes),
        "total_good": round(sum(_to_float(b.get("good_qty")) for b in boxes), 3),
        "total_damaged": round(sum(_to_float(b.get("damaged_qty"))
                                   for b in boxes), 3),
    })


def check_receiving_box(box_id, good_qty, damaged_qty, damage_reason="",
                        user_id=None):
    """Record the good/damaged split for one box and move good stock in.

    Returns ``(box, None)`` or ``(None, message)``.  Stock only ever rises by
    the GOOD quantity; the damaged quantity is logged separately so the client
    can report on spoilage per box, per material and per supplier."""
    box = db.get("receiving_boxes", box_id)
    if not box:
        return None, "Box not found."
    if box.get("status") in ("Checked", "Stored", "Released", "Consumed"):
        return None, "Box %s was already checked." % box.get("box_code")
    good = _to_float(good_qty)
    damaged = _to_float(damaged_qty)
    if good < 0 or damaged < 0:
        return None, "Quantities cannot be negative."
    if good + damaged <= 0:
        return None, "Enter the good and/or damaged quantity."
    if damaged > 0 and not (damage_reason or "").strip():
        return None, "A reason is required when damage is recorded."

    material = db.get("raw_materials", box.get("material_id"))
    if not material:
        return None, "The material for this box no longer exists."

    if good > 0:
        adjust_stock("material", material["id"], good, "received",
                     reference_id=box.get("box_code"), user_id=user_id)
    if damaged > 0:
        record_damage("receiving", box.get("box_code"), "material",
                      material["id"], material.get("name"), damaged,
                      material.get("unit"), damage_reason,
                      stage="Receiving Area", user_id=user_id)

    box = db.update("receiving_boxes", box_id, {
        "good_qty": good,
        "damaged_qty": damaged,
        "damage_reason": (damage_reason or "").strip(),
        "status": "Checked",
        "stage": "Storage",
        "checked_by": user_id,
        "checked_at": now_iso(),
    })
    _refresh_batch_totals(box.get("batch_id"))
    if damaged > 0:
        notify_admins("Damage recorded on box %s - %g %s of %s."
                      % (box.get("box_code"), damaged,
                         material.get("unit") or "", material.get("name")),
                      link="/receiving/")
    return box, None


def move_receiving_box(box_id, stage, user_id=None, released_to=""):
    """Move a box along the floor so its current location is always known."""
    box = db.get("receiving_boxes", box_id)
    if not box:
        return None, "Box not found."
    if stage not in BOX_STAGES:
        return None, "Unknown stage."
    if box.get("status") == "Pending Check":
        return None, "Check the box before moving it."
    status = {"Storage": "Stored", "Production Floor": "Released",
              "Consumed": "Consumed", "Receiving Area": "Checked"}[stage]
    box = db.update("receiving_boxes", box_id, {
        "stage": stage,
        "status": status,
        "released_to": (released_to or box.get("released_to") or "").strip(),
        "released_at": now_iso() if stage in ("Production Floor", "Consumed")
                       else box.get("released_at"),
    })
    return box, None


def close_receiving_batch(batch_id, user_id=None):
    batch = db.get("receiving_batches", batch_id)
    if not batch:
        return None, "Batch not found."
    boxes = db.query("receiving_boxes", batch_id=int(batch_id))
    if not boxes:
        return None, "Add at least one box before closing the batch."
    pending = [b for b in boxes if b.get("status") == "Pending Check"]
    if pending:
        return None, ("%d box(es) still need checking before this batch can be "
                      "closed." % len(pending))
    _refresh_batch_totals(batch_id)
    batch = db.update("receiving_batches", batch_id,
                      {"status": "Completed", "closed_at": now_iso()})
    return batch, None


def receiving_box_rows(batch_id=None, status=None, limit=None):
    """Boxes shaped for the receiving templates."""
    boxes = db.read("receiving_boxes")
    if batch_id is not None:
        boxes = [b for b in boxes if b.get("batch_id") == int(batch_id)]
    if status:
        boxes = [b for b in boxes if b.get("status") == status]
    boxes.sort(key=lambda b: (b.get("batch_id") or 0, b.get("seq") or 0))
    batches = {b["id"]: b for b in db.read("receiving_batches")}
    rows = []
    for b in boxes:
        batch = batches.get(b.get("batch_id"), {})
        rows.append({
            "id": b["id"], "box_code": b.get("box_code"), "seq": b.get("seq"),
            "material_name": b.get("material_name"), "unit": b.get("unit"),
            "track_mode": b.get("track_mode"),
            "track_label": TRACK_MODE_LABELS.get(b.get("track_mode"), ""),
            "declared_qty": b.get("declared_qty"),
            "good_qty": b.get("good_qty"), "damaged_qty": b.get("damaged_qty"),
            "damage_reason": b.get("damage_reason"),
            "status": b.get("status"), "stage": b.get("stage"),
            "badge": BOX_BADGE.get(b.get("status"), "badge-muted"),
            "checked_by": user_name(b.get("checked_by")),
            "checked_at": fmt_dt(b.get("checked_at")),
            "batch_ref": batch.get("ref_no"),
            "batch_id": b.get("batch_id"),
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
#  HONEY PRODUCTION - containers, moisture / appearance QC, Pass or Failed
# ===========================================================================
# Each honey container carries a QR code.  QC records moisture content and
# appearance; the result is Pass or Failed only.  Pass goes to selling stock,
# Failed is routed to other products (never discarded).

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
        "material_id": int(material_id) if material_id else None,
        "created_by": user_id,
        "created_at": now_iso(),
    })
    container = db.update("honey_containers", container["id"],
                          {"container_code": container_token(container["id"])})
    return container, None


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

    # Passed honey joins sellable raw-honey stock; failed honey is held for
    # other products and is NOT added to the sellable pool.
    material_id = container.get("material_id") or _honey_material_id()
    if result == "Pass" and material_id:
        adjust_stock("material", material_id,
                     _to_float(container.get("net_weight_kg")), "qc_passed",
                     reference_id=container.get("container_code"),
                     user_id=user_id)
        db.update("honey_containers", container_id, {"material_id": material_id})
    if result == "Failed":
        notify_admins("Honey container %s FAILED QC (%.1f%% moisture, %s) - "
                      "routed to other products."
                      % (container.get("container_code"), moisture, appearance),
                      link="/honey/")
    return container, None


def _honey_material_id():
    """The raw material that sellable honey accumulates into."""
    for name in ("Raw Honey", "Honey"):
        found = db.query("raw_materials", name=name)
        if found:
            return found[0]["id"]
    return None


def allocate_honey_container(container_id, allocated_to, user_id=None):
    """Note which product a container was drawn into (both Pass and Failed)."""
    container = db.get("honey_containers", container_id)
    if not container:
        return None, "Container not found."
    if container.get("status") not in QC_RESULTS:
        return None, "Run the quality check before allocating this container."
    if not (allocated_to or "").strip():
        return None, "Say where the container was used."
    return db.update("honey_containers", container_id, {
        "allocated_to": allocated_to.strip(),
        "allocated_at": now_iso(),
    }), None


def honey_summary():
    containers = db.read("honey_containers")

    def _kg(rows):
        return round(sum(_to_float(c.get("net_weight_kg")) for c in rows), 2)

    pending = [c for c in containers if c.get("status") == "Pending QC"]
    passed = [c for c in containers if c.get("status") == "Pass"]
    failed = [c for c in containers if c.get("status") == "Failed"]
    checked = len(passed) + len(failed)
    return {
        "total": len(containers), "pending": len(pending),
        "passed": len(passed), "failed": len(failed),
        "pending_kg": _kg(pending), "passed_kg": _kg(passed),
        "failed_kg": _kg(failed),
        "pass_rate": round(100.0 * len(passed) / checked, 1) if checked else 0.0,
        "avg_moisture": round(
            sum(_to_float(c.get("moisture_pct")) for c in passed + failed)
            / checked, 2) if checked else 0.0,
    }


# ===========================================================================
#  PACKING AREA - one run per channel (VIP / Shopee / TikTok / Lazada / Walk-in)
# ===========================================================================
# Packing is the last monitored step before hand-over to the courier.  A run
# that is NOT tied to an internal sales order releases finished-goods stock on
# pack (platform and walk-in sales); a run tied to a sales order does not,
# because confirming that order already moved the stock.

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
        return None, "Add at least one product line with a quantity."

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
        "handed_to": "",
        "handed_at": None,
        "courier": (courier or "").strip(),
        "tracking_no": (tracking_no or "").strip(),
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
                return None, ("Not enough stock of %s to pack this run."
                              % (product.get("name") if product else pid))
        for pid, qty in needed.items():
            adjust_stock("product", pid, -qty, "packed",
                         reference_id=run.get("run_code"), user_id=user_id)

    for item in run.get("items", []):
        dmg = _to_float(item.get("damaged_qty"))
        if dmg > 0:
            record_damage("packing", run.get("run_code"), "product",
                          item.get("product_id"), item.get("name"), dmg,
                          item.get("unit"), "Damaged during packing",
                          stage="Packing Area", user_id=user_id)

    run = db.update("packing_runs", run_id, {
        "status": "Packed",
        "stock_released": not linked_order,
        "packed_at": now_iso(),
    })
    return run, None


def hand_over_packing_run(run_id, handed_to, courier="", tracking_no="",
                          user_id=None):
    run = db.get("packing_runs", run_id)
    if not run:
        return None, "Packing run not found."
    if run.get("status") != "Packed":
        return None, "Mark the run packed before handing it over."
    if not (handed_to or "").strip():
        return None, "Record who the parcels were handed to."
    run = db.update("packing_runs", run_id, {
        "status": "Handed Over",
        "handed_to": handed_to.strip(),
        "handed_at": now_iso(),
        "courier": (courier or run.get("courier") or "").strip(),
        "tracking_no": (tracking_no or run.get("tracking_no") or "").strip(),
    })
    notify_admins("Packing run %s (%s) handed over to %s."
                  % (run.get("run_code"), run.get("channel"),
                     handed_to.strip()),
                  link="/packing/%d" % run_id)
    return run, None


def cancel_packing_run(run_id, user_id=None):
    """Cancel a run, returning any stock it had already released."""
    run = db.get("packing_runs", run_id)
    if not run:
        return None, "Packing run not found."
    if run.get("status") == "Handed Over":
        return None, "A handed-over run can no longer be cancelled."
    if run.get("stock_released"):
        for item in run.get("items", []):
            adjust_stock("product", item.get("product_id"),
                         _to_float(item.get("qty")), "returned",
                         reference_id=run.get("run_code"), user_id=user_id)
    return db.update("packing_runs", run_id,
                     {"status": "Cancelled", "stock_released": False}), None


def packing_summary(runs=None):
    """Per-channel totals for the packing dashboard and reports."""
    runs = db.read("packing_runs") if runs is None else runs
    live = [r for r in runs if r.get("status") != "Cancelled"]
    per_channel = []
    for channel in PACKING_CHANNELS:
        rows = [r for r in live if r.get("channel") == channel]
        per_channel.append({
            "channel": channel,
            "runs": len(rows),
            "qty": round(sum(_to_float(r.get("total_qty")) for r in rows), 2),
            "damaged": round(sum(_to_float(r.get("damaged_qty"))
                                 for r in rows), 2),
            "open": len([r for r in rows if r.get("status") == "In Progress"]),
        })
    return {
        "per_channel": per_channel,
        "total_runs": len(live),
        "total_qty": round(sum(_to_float(r.get("total_qty")) for r in live), 2),
        "open_runs": len([r for r in live if r.get("status") == "In Progress"]),
        "packed_runs": len([r for r in live if r.get("status") == "Packed"]),
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


def record_maintenance(asset_id, mtype, performed_on, performed_by, status,
                       cost=0.0, next_due="", downtime_hours=0.0, notes="",
                       user_id=None):
    asset = db.get("raw_materials", asset_id)
    if not asset:
        return None, "Asset not found."
    if mtype not in MAINTENANCE_TYPES:
        return None, "Choose a maintenance type."
    if status not in MAINTENANCE_STATUS:
        return None, "Choose a status."
    log = db.insert("maintenance_logs", {
        "asset_id": asset["id"],
        "asset_name": asset.get("name"),
        "type": mtype,
        "performed_on": performed_on or today_iso(),
        "performed_by": (performed_by or "").strip(),
        "cost": _to_float(cost),
        "next_due": (next_due or "").strip(),
        "status": status,
        "downtime_hours": _to_float(downtime_hours),
        "notes": (notes or "").strip(),
        "recorded_by": user_id,
        "created_at": now_iso(),
    })
    return log, None


def maintenance_due(within_days=14):
    """Assets whose next service falls due soon (or is already overdue).

    Only each asset's most recent log counts: its next-due date is the
    reminder, whatever that log's own status — a completed service that sets
    the next date is exactly the case that needs reminding."""
    latest = {}
    for log in db.read("maintenance_logs"):
        key = log.get("asset_id")
        stamp = (log.get("performed_on") or "", log.get("id") or 0)
        if key not in latest or stamp > latest[key][0]:
            latest[key] = (stamp, log)

    today = date.today()
    rows = []
    for _, log in latest.values():
        due = (log.get("next_due") or "").strip()
        if not due:
            continue
        try:
            due_date = date.fromisoformat(due[:10])
        except ValueError:
            continue
        days = (due_date - today).days
        if days <= within_days:
            rows.append({"asset_name": log.get("asset_name"), "due": due[:10],
                         "days": days, "type": log.get("type"),
                         "overdue": days < 0})
    rows.sort(key=lambda r: r["days"])
    return rows
