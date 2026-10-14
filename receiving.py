"""Receiving-area blueprint.

Deliveries arrive as cage boxes / crates.  A batch is opened per delivery, each
box is logged and labelled with its own QR code, and the checker records the
GOOD and DAMAGED quantity per box — in kilos for ginger, pieces for lemon, or
whole units, according to how the material is tracked.  Only the good quantity
joins raw-material stock; damage is kept in its own ledger.
"""
from flask import (Blueprint, abort, flash, jsonify, redirect, render_template,
                   request, url_for)

import db
import services
from security import current_user, module_required

receiving_bp = Blueprint("receiving", __name__)


def _back_to(box):
    """Where to return after acting on a box.

    The forms post a ``next``; falling back on the box's own batch keeps a
    direct POST (or a failed action on a missing box) off a dead URL."""
    target = (request.form.get("next") or "").strip()
    if target.startswith("/"):
        return target
    if box and box.get("batch_id"):
        return url_for("receiving.batch", batch_id=box["batch_id"])
    return url_for("receiving.index")


def _batch_rows(batches):
    rows = []
    for b in sorted(batches, key=lambda x: x.get("created_at", ""), reverse=True):
        rows.append({
            "id": b["id"], "ref_no": b.get("ref_no"),
            "supplier_name": b.get("supplier_name"),
            "delivery_ref": b.get("delivery_ref"),
            "received_date": b.get("received_date"),
            "received_by": services.user_name(b.get("received_by")),
            "status": b.get("status"),
            "badge": services.RECEIVING_BADGE.get(b.get("status"), "badge-muted"),
            "box_count": b.get("box_count") or 0,
            "total_good": b.get("total_good") or 0,
            "total_damaged": b.get("total_damaged") or 0,
            "created_at": services.fmt_dt(b.get("created_at")),
        })
    return rows


@receiving_bp.route("/")
@module_required("receiving")
def index():
    batches = db.read("receiving_batches")
    boxes = db.read("receiving_boxes")
    pending = [b for b in boxes if b.get("status") == "Pending Check"]
    stats = {
        "open_batches": len([b for b in batches if b.get("status") == "Open"]),
        "pending_boxes": len(pending),
        "boxes_today": len([b for b in boxes
                            if (b.get("created_at") or "")[:10]
                            == services.today_iso()]),
        "damaged_total": round(sum(services._to_float(b.get("damaged_qty"))
                                   for b in boxes), 2),
    }
    return render_template("receiving/index.html",
                           batches=_batch_rows(batches), stats=stats,
                           recent_boxes=services.receiving_box_rows(limit=12))


@receiving_bp.route("/new", methods=["GET", "POST"])
@module_required("receiving")
def new():
    if request.method == "POST":
        supplier_raw = (request.form.get("supplier_id") or "").strip()
        try:
            supplier_id = int(supplier_raw) if supplier_raw else None
        except ValueError:
            supplier_id = None
        batch = services.create_receiving_batch(
            supplier_id,
            request.form.get("received_date") or services.today_iso(),
            current_user()["id"],
            delivery_ref=request.form.get("delivery_ref") or "",
            remarks=request.form.get("remarks") or "")
        flash("Receiving batch %s opened — add the boxes now."
              % batch.get("ref_no"), "success")
        return redirect(url_for("receiving.batch", batch_id=batch["id"]))

    return render_template("receiving/new.html", suppliers=db.read("suppliers"),
                           today=services.today_iso())


@receiving_bp.route("/<int:batch_id>")
@module_required("receiving")
def batch(batch_id):
    record = db.get("receiving_batches", batch_id)
    if not record:
        abort(404)
    materials = [m for m in db.read("raw_materials")
                 if m.get("category") in (None, "", "raw", "ingredient")]
    return render_template(
        "receiving/batch.html", batch=record,
        badge=services.RECEIVING_BADGE.get(record.get("status"), "badge-muted"),
        received_by=services.user_name(record.get("received_by")),
        boxes=services.receiving_box_rows(batch_id=batch_id),
        materials=materials or db.read("raw_materials"),
        track_labels=services.TRACK_MODE_LABELS, stages=services.BOX_STAGES)


@receiving_bp.route("/<int:batch_id>/boxes", methods=["POST"])
@module_required("receiving")
def add_boxes(batch_id):
    boxes, err = services.add_receiving_box(
        batch_id, request.form.get("material_id"),
        request.form.get("declared_qty"), current_user()["id"],
        location=request.form.get("location") or "Receiving Area",
        count=request.form.get("count") or 1)
    if err:
        flash(err, "error")
    else:
        flash("%d box(es) added — print the QR labels before they leave the "
              "receiving area." % len(boxes), "success")
    return redirect(url_for("receiving.batch", batch_id=batch_id))


@receiving_bp.route("/box/<int:box_id>/check", methods=["POST"])
@module_required("receiving")
def check_box(box_id):
    box, err = services.check_receiving_box(
        box_id, request.form.get("good_qty"), request.form.get("damaged_qty"),
        request.form.get("damage_reason") or "", user_id=current_user()["id"])
    if request.is_json or request.args.get("ajax"):
        if err:
            return jsonify({"message": err}), 400
        return jsonify({"message": "Box %s checked." % box.get("box_code"),
                        "box_code": box.get("box_code"),
                        "good_qty": box.get("good_qty"),
                        "damaged_qty": box.get("damaged_qty")})
    if err:
        flash(err, "error")
    else:
        flash("Box %s checked — %g %s good, %g damaged."
              % (box.get("box_code"), services._to_float(box.get("good_qty")),
                 box.get("unit") or "",
                 services._to_float(box.get("damaged_qty"))), "success")
    return redirect(_back_to(box))


@receiving_bp.route("/box/<int:box_id>/move", methods=["POST"])
@module_required("receiving")
def move_box(box_id):
    box, err = services.move_receiving_box(
        box_id, request.form.get("stage") or "",
        user_id=current_user()["id"],
        released_to=request.form.get("released_to") or "")
    if err:
        flash(err, "error")
    else:
        flash("Box %s moved to %s." % (box.get("box_code"), box.get("stage")),
              "success")
    return redirect(_back_to(box))


@receiving_bp.route("/<int:batch_id>/close", methods=["POST"])
@module_required("receiving")
def close(batch_id):
    record, err = services.close_receiving_batch(batch_id,
                                                 current_user()["id"])
    if err:
        flash(err, "error")
    else:
        flash("Batch %s closed — %g good, %g damaged across %d box(es)."
              % (record.get("ref_no"), record.get("total_good") or 0,
                 record.get("total_damaged") or 0, record.get("box_count") or 0),
              "success")
    return redirect(url_for("receiving.batch", batch_id=batch_id))


@receiving_bp.route("/<int:batch_id>/labels")
@module_required("receiving")
def labels(batch_id):
    record = db.get("receiving_batches", batch_id)
    if not record:
        abort(404)
    return render_template("receiving/labels.html", batch=record,
                           boxes=services.receiving_box_rows(batch_id=batch_id))


@receiving_bp.route("/damage")
@module_required("receiving")
def damage():
    records = sorted(db.read("damage_records"),
                     key=lambda d: d.get("recorded_at", ""), reverse=True)
    rows = [{
        "recorded_at": services.fmt_dt(d.get("recorded_at")),
        "source": d.get("source"), "reference": d.get("reference"),
        "item_name": d.get("item_name"), "qty": d.get("qty"),
        "unit": d.get("unit"), "stage": d.get("stage"),
        "reason": d.get("reason"),
        "recorded_by": services.user_name(d.get("recorded_by")),
    } for d in records]
    totals, by_source = services.damage_summary()
    return render_template("receiving/damage.html", rows=rows, totals=totals,
                           by_source=by_source)
