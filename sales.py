"""Sales blueprint: internal finished-goods release requests.

Sales staff request finished goods, admin approves, production fulfils (which
deducts finished-goods stock)."""
from flask import (Blueprint, abort, flash, redirect, render_template, request,
                   url_for)

import db
import services
from security import (current_user, is_admin, module_required,
                      normalize_role, role_required)

sales_bp = Blueprint("sales", __name__)


@sales_bp.route("/")
@module_required("sales")
def index():
    user = current_user()
    role = normalize_role(user.get("role"))
    all_reqs = sorted(db.read("sales_requests"),
                      key=lambda r: r.get("created_at", ""), reverse=True)
    if role == "packing_head":
        reqs = [r for r in all_reqs if r.get("requestor_id") == user["id"]]
    elif role == "production_head":
        reqs = [r for r in all_reqs
                if r.get("status") in ("Approved", "In Fulfilment")]
    else:
        reqs = all_reqs

    rows = []
    for r in reqs:
        stock = services.current_stock("product", r.get("product_id"))
        qty = float(r.get("qty") or 0)
        rows.append({
            "id": r["id"], "product_name": r.get("product_name"),
            "qty": ("%g" % qty), "product_unit": r.get("product_unit"),
            "requestor_name": r.get("requestor_name"),
            "status": r.get("status"),
            "badge": services.SALES_BADGE.get(r.get("status"), "badge-muted"),
            "remarks": r.get("remarks"),
            "created_at": (r.get("created_at") or "")[:16].replace("T", " "),
            "product_stock": ("%g" % stock),
            "can_fulfil": (role in ("production_head", "super_admin", "admin")
                           and r.get("status") == "Approved"
                           and stock >= qty),
        })
    return render_template("sales/index.html", role=role,
                           is_manager=is_admin(user), requests=rows)


@sales_bp.route("/new", methods=["GET", "POST"])
@role_required("packing_head")
def new():
    if request.method == "POST":
        product_id = request.form.get("product_id")
        qty = request.form.get("qty")
        remarks = request.form.get("remarks") or ""
        try:
            product_id = int(product_id)
            qty = float(qty)
        except (TypeError, ValueError):
            flash("Choose a product and quantity.", "error")
            return redirect(url_for("sales.new"))
        req, err = services.create_sales_request(current_user()["id"], product_id,
                                                 qty, remarks)
        if err:
            flash(err, "error")
            return redirect(url_for("sales.new"))
        flash("Sales request #%d submitted for approval." % req["id"], "success")
        return redirect(url_for("sales.index"))

    return render_template("sales/new.html", products=db.read("products"))


@sales_bp.route("/<int:id>/decide", methods=["POST"])
@role_required("admin")
def decide(id):
    req = db.get("sales_requests", id)
    if not req:
        abort(404)
    decision = request.form.get("decision") or "approve"
    remarks = request.form.get("remarks") or ""
    services.decide_sales_request(id, decision, remarks,
                                  decider_id=current_user()["id"])
    flash("Sales request #%d %s." % (id, "approved" if decision == "approve"
                                     else "rejected"), "success")
    return redirect(url_for("sales.index"))


@sales_bp.route("/<int:id>/fulfil", methods=["POST"])
@role_required("production_head")
def fulfil(id):
    ok, message = services.fulfil_sales_request(id, user_id=current_user()["id"])
    flash(message, "success" if ok else "error")
    return redirect(url_for("sales.index"))
