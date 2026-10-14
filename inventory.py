"""Inventory blueprint: read-only stock view and the transaction ledger."""
from flask import Blueprint, render_template

import db
import services
from security import module_required

inventory_bp = Blueprint("inventory", __name__)


@inventory_bp.route("/")
@module_required("inventory")
def index():
    materials = []
    for m in db.read("raw_materials"):
        row = dict(m)
        row["low"] = services.is_low(m)
        materials.append(row)
    return render_template("inventory/index.html", materials=materials,
                           products=db.read("products"))


@inventory_bp.route("/transactions")
@module_required("inventory")
def transactions():
    txns = sorted(db.read("inventory_transactions"),
                  key=lambda t: t.get("timestamp", ""), reverse=True)
    rows = []
    for t in txns:
        change = float(t.get("change_qty") or 0)
        rows.append({
            "timestamp": (t.get("timestamp") or "")[:19].replace("T", " "),
            "item_name": services.item_name(t.get("item_type"), t.get("item_id")),
            "item_type": t.get("item_type"),
            "item_unit": services.item_unit(t.get("item_type"), t.get("item_id")),
            "txn_type": t.get("txn_type"),
            "change_qty": ("%g" % change),
            "change_positive": change >= 0,
            "reference_id": t.get("reference_id"),
            "user_name": services.user_name(t.get("user_id")),
        })
    return render_template("inventory/transactions.html", rows=rows)
