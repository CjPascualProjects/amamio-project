"""Purchase-request blueprint: production (BOM shortfall) and material/equipment
requests, plus the BOM auto-calc AJAX endpoint."""
from flask import (Blueprint, abort, flash, jsonify, redirect, render_template,
                   request, url_for)

import db
import services
from security import (current_user, is_admin, module_required,
                      role_required)

requests_bp = Blueprint("requests", __name__)


@requests_bp.route("/")
@module_required("requests")
def index():
    user = current_user()
    all_reqs = db.read("purchase_requests")
    if is_admin(user):
        reqs = all_reqs
    else:
        reqs = [r for r in all_reqs if r.get("requestor_id") == user["id"]]
    reqs = sorted(reqs, key=lambda r: r.get("created_at", ""), reverse=True)
    return render_template("requests/index.html", requests=reqs,
                           users_by_id=services.users_by_id(),
                           status_badge=services.REQUEST_STATUS_BADGE,
                           urgency_badge=services.URGENCY_BADGE)


@requests_bp.route("/bom_calc")
@module_required("requests")
def bom_calc():
    product_id = request.args.get("product_id")
    qty = request.args.get("qty")
    try:
        rows = services.requirements_for(int(product_id), float(qty))
    except (TypeError, ValueError):
        return jsonify({"rows": []})
    return jsonify({"rows": rows})


@requests_bp.route("/new/production", methods=["GET", "POST"])
@role_required("production_head")
def new_production():
    if request.method == "POST":
        product_id = request.form.get("product_id")
        qty = request.form.get("qty")
        remarks = request.form.get("remarks") or ""
        reason = (request.form.get("reason") or "").strip()
        needed_by = request.form.get("needed_by") or ""
        urgency = request.form.get("urgency") or "Normal"
        material_ids = request.form.getlist("material_id")
        requested = request.form.getlist("requested_qty")
        notes = request.form.getlist("note")
        try:
            product_id = int(product_id)
            qty = float(qty)
        except (TypeError, ValueError):
            flash("Choose a product and quantity.", "error")
            return redirect(url_for("requests.new_production"))
        if not reason:
            flash("Say why this request is needed — the approver sees it.",
                  "error")
            return redirect(url_for("requests.new_production"))

        lines = []
        for i, mid in enumerate(material_ids):
            try:
                rq = float(requested[i]) if i < len(requested) else 0
            except ValueError:
                rq = 0
            if rq > 0:
                lines.append({"material_id": int(mid), "requested_qty": rq,
                              "note": notes[i] if i < len(notes) else ""})
        if not lines:
            flash("At least one material must have a request quantity above zero.",
                  "error")
            return redirect(url_for("requests.new_production"))

        req = services.create_production_request(
            current_user()["id"], product_id, qty, lines, reason=reason,
            remarks=remarks, needed_by=needed_by, urgency=urgency)
        flash("Production request #%d submitted for approval." % req["id"], "success")
        return redirect(url_for("requests.index"))

    return render_template("requests/new_production.html",
                           products=db.read("products"),
                           reasons=services.REQUEST_REASONS,
                           urgencies=services.URGENCY_LEVELS,
                           today=services.today_iso())


@requests_bp.route("/new/material", methods=["GET", "POST"])
@role_required("production_head", "assets_head", "packing_head",
               "receiving_head")
def new_material():
    if request.method == "POST":
        category = request.form.get("category") or ""
        name = (request.form.get("name") or "").strip()
        description = request.form.get("description") or ""
        reason = (request.form.get("reason") or "").strip()
        needed_by = request.form.get("needed_by") or ""
        urgency = request.form.get("urgency") or "Normal"
        qty = request.form.get("requested_qty")
        try:
            qty = float(qty)
        except (TypeError, ValueError):
            qty = 0
        if category not in ("cleaning", "asset"):
            flash("Choose a valid category.", "error")
        elif not name or qty <= 0:
            flash("Item name and a positive quantity are required.", "error")
        elif not reason:
            flash("Say why this request is needed — the approver sees it.",
                  "error")
        else:
            req = services.create_material_request(
                current_user()["id"], category, name, qty, description,
                reason=reason, needed_by=needed_by, urgency=urgency)
            flash("Material request #%d submitted for approval." % req["id"],
                  "success")
            return redirect(url_for("requests.index"))
        return redirect(url_for("requests.new_material"))

    return render_template("requests/new_material.html",
                           reasons=services.REQUEST_REASONS,
                           urgencies=services.URGENCY_LEVELS,
                           today=services.today_iso())


@requests_bp.route("/<int:id>")
@module_required("requests")
def detail(id):
    user = current_user()
    req = db.get("purchase_requests", id)
    if not req:
        abort(404)
    if not is_admin(user) and req.get("requestor_id") != user["id"]:
        abort(403)
    requestor = db.get("users", req.get("requestor_id"))
    materials_by_id = {m["id"]: m for m in db.read("raw_materials")}
    return render_template("requests/detail.html", req=req, requestor=requestor,
                           materials_by_id=materials_by_id,
                           status_badge=services.REQUEST_STATUS_BADGE,
                           urgency_badge=services.URGENCY_BADGE)
