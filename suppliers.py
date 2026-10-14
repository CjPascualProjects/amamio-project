"""Suppliers blueprint (Supplier and Customer Management — supplier side)."""
from flask import (Blueprint, flash, redirect, render_template, request, url_for)

import db
import services
from security import module_required

suppliers_bp = Blueprint("suppliers", __name__)


@suppliers_bp.route("/", methods=["GET", "POST"])
@module_required("suppliers")
def index():
    if request.method == "POST":
        sid = (request.form.get("id") or "").strip()
        name = (request.form.get("name") or "").strip()
        if not name:
            flash("Supplier name is required.", "error")
            return redirect(url_for("suppliers.index"))
        try:
            lead = int(request.form.get("lead_time_days") or 0)
        except ValueError:
            lead = 0
        payload = {
            "name": name,
            "contact_person": (request.form.get("contact_person") or "").strip(),
            "phone": (request.form.get("phone") or "").strip(),
            "email": (request.form.get("email") or "").strip(),
            "address": (request.form.get("address") or "").strip(),
            "materials_supplied": (request.form.get("materials_supplied") or "").strip(),
            "lead_time_days": lead,
            "notes": (request.form.get("notes") or "").strip(),
        }
        if sid:
            db.update("suppliers", sid, payload)
            flash("Supplier updated.", "success")
        else:
            payload["created_at"] = services.now_iso()
            db.insert("suppliers", payload)
            flash("Supplier '%s' added." % name, "success")
        return redirect(url_for("suppliers.index"))

    suppliers = db.read("suppliers")
    # transaction history: count of received txns per supplier's materials
    mat_supplier = {m["id"]: m.get("supplier_id") for m in db.read("raw_materials")}
    received = {}
    for t in db.read("inventory_transactions"):
        if t.get("item_type") == "material" and t.get("txn_type") == "received":
            sup = mat_supplier.get(t.get("item_id"))
            if sup is not None:
                received[sup] = received.get(sup, 0) + 1
    return render_template("suppliers/index.html", suppliers=suppliers,
                           received_counts=received)
