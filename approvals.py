"""Approvals blueprint: admin decisions on purchase requests.

Approving items sets them to 'Ordered' and mints a QR token; NO stock moves here
(stock only changes when materials are received via QR scan)."""
from flask import (Blueprint, abort, flash, redirect, render_template, request,
                   url_for)

import db
import services
from security import current_user, module_required

approvals_bp = Blueprint("approvals", __name__)


def _requestor_name(req):
    return services.user_name(req.get("requestor_id"))


@approvals_bp.route("/")
@module_required("approvals")
def index():
    pending = [r for r in db.read("purchase_requests")
               if r.get("status") == "Pending Approval"]
    pending = sorted(pending, key=lambda r: r.get("created_at", ""))
    for r in pending:
        r["requestor_name"] = _requestor_name(r)
    return render_template("approvals/index.html", requests=pending,
                           urgency_badge=services.URGENCY_BADGE)


@approvals_bp.route("/<int:request_id>", methods=["GET", "POST"])
@module_required("approvals")
def decide(request_id):
    req = db.get("purchase_requests", request_id)
    if not req:
        abort(404)
    if req.get("status") != "Pending Approval":
        flash("Request #%d has already been decided." % request_id, "error")
        return redirect(url_for("approvals.index"))

    materials_by_id = {m["id"]: m for m in db.read("raw_materials")}

    if request.method == "POST":
        action = request.form.get("action") or "approve"
        remarks = request.form.get("remarks") or ""
        decisions = {}
        for it in req.get("items", []):
            iid = it["item_id"]
            decisions[iid] = {
                "reject": request.form.get("reject_%d" % iid) == "1",
                "approved_qty": request.form.get("approved_qty_%d" % iid),
            }
        updated = services.apply_decision(request_id, decisions, remarks, action,
                                          decider_id=current_user()["id"])
        flash("Request #%d marked %s." % (request_id, updated.get("status")),
              "success")
        return redirect(url_for("approvals.index"))

    # GET — enrich items for display
    view = dict(req)
    view["requestor_name"] = _requestor_name(req)
    items = []
    for it in req.get("items", []):
        row = dict(it)
        if req.get("type") == "production":
            mat = materials_by_id.get(it.get("material_id"), {})
            row["display_name"] = mat.get("name", "Material #%s" % it.get("material_id"))
            row["display_unit"] = mat.get("unit", "")
        else:
            row["display_name"] = it.get("name")
            row["display_unit"] = "pc"
        items.append(row)
    view["items"] = items
    return render_template("approvals/decide.html", req=view,
                           urgency_badge=services.URGENCY_BADGE)
