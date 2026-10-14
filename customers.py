"""Customers blueprint (Supplier and Customer Management — customer side)."""
from flask import (Blueprint, flash, redirect, render_template, request, url_for)

import db
import services
from security import module_required

customers_bp = Blueprint("customers", __name__)


@customers_bp.route("/", methods=["GET", "POST"])
@module_required("customers")
def index():
    if request.method == "POST":
        cid = (request.form.get("id") or "").strip()
        name = (request.form.get("name") or "").strip()
        if not name:
            flash("Customer name is required.", "error")
            return redirect(url_for("customers.index"))
        payload = {
            "name": name,
            "contact_person": (request.form.get("contact_person") or "").strip(),
            "phone": (request.form.get("phone") or "").strip(),
            "email": (request.form.get("email") or "").strip(),
            "address": (request.form.get("address") or "").strip(),
            "notes": (request.form.get("notes") or "").strip(),
        }
        if cid:
            db.update("customers", cid, payload)
            flash("Customer updated.", "success")
        else:
            payload["created_at"] = services.now_iso()
            db.insert("customers", payload)
            flash("Customer '%s' added." % name, "success")
        return redirect(url_for("customers.index"))

    customers = db.read("customers")
    orders = db.read("sales_orders")
    order_counts = {}
    spend = {}
    for o in orders:
        cid = o.get("customer_id")
        order_counts[cid] = order_counts.get(cid, 0) + 1
        spend[cid] = spend.get(cid, 0.0) + float(o.get("total") or 0)
    return render_template("customers/index.html", customers=customers,
                           order_counts=order_counts, spend=spend)
