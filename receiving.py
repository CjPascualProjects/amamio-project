"""Module 1 — the receiving area, then inspection & cleaning.

Part 1 (Receiving Team Head): a delivery is recorded once, in a short
step-by-step flow — who it came from, what arrived and in how many boxes.
Every box gets a QR label carrying its code, item, quantity and delivery
details, and the production team is notified that boxes are waiting.

Part 2 (inspection & cleaning): a box is scanned, cleaned and checked, and
its content split into usable / can't be used / damaged, then Accepted,
Rejected or put on Hold.  Only the usable part of an accepted box joins
stock.  The printable "Raw Materials Receiving and Inspection Report" is
built from these records.
"""
from flask import (Blueprint, abort, flash, g, redirect, render_template,
                   request, url_for)

import db
import services
from security import can, current_user, module_required

receiving_bp = Blueprint("receiving", __name__)


def _int(value):
    try:
        return int(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _batch_rows(batches):
    rows = []
    for b in sorted(batches, key=lambda x: x.get("created_at", ""), reverse=True):
        rows.append({
            "id": b["id"], "ref_no": b.get("ref_no"),
            "supplier_name": b.get("supplier_name"),
            "po_no": b.get("po_no"), "delivery_ref": b.get("delivery_ref"),
            "received_date": b.get("received_date"),
            "received_by": services.user_name(b.get("received_by")),
            "status": b.get("status"),
            "badge": services.RECEIVING_BADGE.get(b.get("status"), "badge-muted"),
            "box_count": b.get("box_count") or 0,
            "created_at": services.fmt_dt(b.get("created_at")),
        })
    return rows


def _lines_from_form(form):
    """The repeating item cards of the receive wizard -> list of dicts."""
    keys = ("material_id", "qty_per_box", "boxes", "lot_no", "expiry_date",
            "packaging_condition", "temperature_c")
    columns = {k: form.getlist(k) for k in keys}
    lines = []
    for i in range(len(columns["material_id"])):
        line = {k: (columns[k][i] if i < len(columns[k]) else "") for k in keys}
        if line["material_id"]:
            lines.append(line)
    return lines


# --- Part 1: receiving --------------------------------------------------------
@receiving_bp.route("/")
@module_required("receiving")
def index():
    show = request.args.get("show") or "open"
    batches = db.read("receiving_batches")
    if show == "open":
        listed = [b for b in batches if b.get("status") == "Open"]
    else:
        listed = batches
    boxes = db.read("receiving_boxes")
    stats = {
        "open": len([b for b in batches if b.get("status") == "Open"]),
        "awaiting": len([b for b in boxes if services.box_status(b)
                         == services.BOX_AWAITING]),
        "today": len([b for b in batches
                      if b.get("received_date") == services.today_iso()]),
    }
    return render_template("receiving/index.html", batches=_batch_rows(listed),
                           stats=stats, show=show)


@receiving_bp.route("/new", methods=["GET", "POST"])
@module_required("receiving")
def new():
    form = request.form
    if request.method == "POST":
        batch, boxes, err = services.receive_delivery(
            current_user()["id"], _int(form.get("supplier_id")),
            form.get("received_date") or services.today_iso(),
            _lines_from_form(form), po_no=form.get("po_no") or "",
            delivery_ref=form.get("delivery_ref") or "",
            remarks=form.get("remarks") or "")
        if not err:
            flash("Delivery %s recorded — %d box(es) labelled. Print the QR "
                  "labels and stick one on each box." % (batch.get("ref_no"),
                                                         len(boxes)), "success")
            return redirect(url_for("receiving.labels", batch_id=batch["id"],
                                    fresh=1))
        flash(err, "error")

    return render_template(
        "receiving/new.html", suppliers=sorted(db.read("suppliers"),
                                               key=lambda s: s.get("name") or ""),
        materials=services.stocked_materials(),
        categories=services.MATERIAL_CATEGORIES,
        category_of=services.material_category,
        track_labels=services.TRACK_MODE_LABELS,
        conditions=services.PACKAGING_CONDITIONS,
        today=services.today_iso(), form=form,
        lines=_lines_from_form(form) if request.method == "POST" else [],
        start=1 if request.method == "POST" else 0)


@receiving_bp.route("/<int:batch_id>")
@module_required("receiving")
def batch(batch_id):
    record = db.get("receiving_batches", batch_id)
    if not record:
        abort(404)
    boxes = services.receiving_box_rows(batch_id=batch_id)
    return render_template(
        "receiving/batch.html", batch=record, boxes=boxes,
        badge=services.RECEIVING_BADGE.get(record.get("status"), "badge-muted"),
        received_by=services.user_name(record.get("received_by")),
        awaiting=[b for b in boxes if b["status"] == services.BOX_AWAITING])


@receiving_bp.route("/<int:batch_id>/add", methods=["GET", "POST"])
@module_required("receiving")
def add_boxes(batch_id):
    """Add boxes that were missed to a delivery that is still open."""
    record = db.get("receiving_batches", batch_id)
    if not record:
        abort(404)
    if request.method == "POST":
        boxes, err = services.add_receiving_box(
            batch_id, request.form.get("material_id"),
            request.form.get("qty_per_box"), current_user()["id"],
            count=request.form.get("boxes") or 1,
            lot_no=request.form.get("lot_no") or "",
            expiry_date=request.form.get("expiry_date") or "",
            packaging_condition=request.form.get("packaging_condition") or "",
            temperature_c=request.form.get("temperature_c"))
        if err:
            flash(err, "error")
            return redirect(url_for("receiving.add_boxes", batch_id=batch_id))
        flash("%d box(es) added to %s." % (len(boxes), record.get("ref_no")),
              "success")
        return redirect(url_for("receiving.labels", batch_id=batch_id,
                                only=",".join(str(b["id"]) for b in boxes)))
    return render_template(
        "receiving/add.html", batch=record,
        materials=services.stocked_materials(),
        categories=services.MATERIAL_CATEGORIES,
        category_of=services.material_category,
        track_labels=services.TRACK_MODE_LABELS,
        conditions=services.PACKAGING_CONDITIONS)


@receiving_bp.route("/<int:batch_id>/labels")
@module_required("receiving")
def labels(batch_id):
    record = db.get("receiving_batches", batch_id)
    if not record:
        abort(404)
    boxes = services.receiving_box_rows(batch_id=batch_id)
    only = request.args.get("only")
    if only:
        wanted = {_int(x) for x in only.split(",")}
        boxes = [b for b in boxes if b["id"] in wanted]
    return render_template("receiving/labels.html", batch=record, boxes=boxes,
                           fresh=request.args.get("fresh"))


@receiving_bp.route("/<int:batch_id>/close", methods=["POST"])
@module_required("receiving")
def close(batch_id):
    record, err = services.close_receiving_batch(batch_id, current_user()["id"])
    if err:
        flash(err, "error")
    else:
        flash("Delivery %s closed." % record.get("ref_no"), "success")
    return redirect(url_for("receiving.batch", batch_id=batch_id))


# --- One box -----------------------------------------------------------------
def _box_or_404(box_id):
    user = current_user()
    if not (can(user, "receiving") or can(user, "inspection")):
        abort(403)
    rows = [r for r in services.receiving_box_rows()
            if r["id"] == int(box_id)]
    if not rows:
        abort(404)
    return rows[0]


@receiving_bp.route("/box/<int:box_id>")
def box(box_id):
    row = _box_or_404(box_id)
    g.nav_endpoint = ("receiving.inspection"
                      if not can(current_user(), "receiving")
                      else "receiving.index")
    record = db.get("receiving_boxes", box_id)
    return render_template(
        "receiving/box.html", box=row, track=services.box_track(record),
        qr_text=services.box_qr_text(record),
        stages=services.BOX_STAGES[1:],
        can_inspect=can(current_user(), "inspection"))


@receiving_bp.route("/box/<int:box_id>/move", methods=["POST"])
def move_box(box_id):
    _box_or_404(box_id)
    box, err = services.move_receiving_box(
        box_id, request.form.get("stage") or "",
        user_id=current_user()["id"],
        released_to=request.form.get("released_to") or "")
    if err:
        flash(err, "error")
    else:
        flash("Box %s is now in the %s." % (box.get("box_code"),
                                            box.get("stage")), "success")
    return redirect(url_for("receiving.box", box_id=box_id))


# --- Part 2: inspection & cleaning -------------------------------------------
@receiving_bp.route("/inspection")
@module_required("inspection")
def inspection():
    waiting = services.receiving_box_rows(status=services.BOX_AWAITING)
    held = services.receiving_box_rows(status=services.BOX_HOLD)
    done = [r for r in services.receiving_box_rows(
        status=(services.BOX_ACCEPTED, services.BOX_REJECTED))
        if r["checked_at"]]
    done.sort(key=lambda r: r["checked_at"], reverse=True)
    return render_template("receiving/inspection.html", waiting=waiting,
                           held=held, done=done[:8])


@receiving_bp.route("/box/<int:box_id>/inspect", methods=["GET", "POST"])
@module_required("inspection")
def inspect(box_id):
    g.nav_endpoint = "receiving.inspection"
    row = _box_or_404(box_id)
    if row["status"] != services.BOX_AWAITING:
        flash("Box %s was already inspected." % row["box_code"], "error")
        return redirect(url_for("receiving.box", box_id=box_id))
    form = request.form
    if request.method == "POST":
        box, err = services.inspect_receiving_box(
            box_id, current_user()["id"],
            usable_qty=form.get("usable_qty"),
            unusable_qty=form.get("unusable_qty") or 0,
            damaged_qty=form.get("damaged_qty") or 0,
            unusable_reason=form.get("unusable_reason") or "",
            damage_reason=form.get("damage_reason") or "",
            cleaned=form.get("cleaned") == "1",
            visual_inspection=form.get("visual_inspection") or "",
            coa_check=form.get("coa_check") or "",
            sampling_test=form.get("sampling_test") or "",
            acceptance=form.get("acceptance") or "",
            nonconformity=form.get("nonconformity") or "",
            action_taken=form.get("action_taken") or "",
            verified_by_name=form.get("verified_by_name") or "")
        if not err:
            flash("Box %s inspected — %s." % (box.get("box_code"),
                                              box.get("acceptance_status")),
                  "success" if box.get("acceptance_status") == "Accepted"
                  else "error")
            nxt = services.receiving_box_rows(status=services.BOX_AWAITING)
            if nxt and request.form.get("then") == "next":
                return redirect(url_for("receiving.inspect", box_id=nxt[0]["id"]))
            return redirect(url_for("receiving.box", box_id=box_id))
        flash(err, "error")

    return render_template(
        "receiving/inspect.html", box=row, form=form,
        results=services.INSPECTION_RESULTS, coa=services.COA_RESULTS,
        sampling=services.SAMPLING_RESULTS, acceptance=services.ACCEPTANCE,
        waiting_count=len(services.receiving_box_rows(
            status=services.BOX_AWAITING)),
        start=1 if request.method == "POST" else 0)


@receiving_bp.route("/box/<int:box_id>/hold", methods=["POST"])
@module_required("inspection")
def decide_hold(box_id):
    box, err = services.decide_held_box(
        box_id, request.form.get("decision") or "", current_user()["id"],
        note=request.form.get("note") or "")
    if err:
        flash(err, "error")
    else:
        flash("Box %s is now %s." % (box.get("box_code"),
                                     box.get("acceptance_status")), "success")
    return redirect(url_for("receiving.box", box_id=box_id))


# --- Reports -------------------------------------------------------------------
@receiving_bp.route("/report")
def report():
    """The paper Raw Materials Receiving and Inspection Report, filled in."""
    user = current_user()
    if not (can(user, "receiving") or can(user, "inspection")):
        abort(403)
    date_from = request.args.get("from") or services.month_start_iso()
    date_to = request.args.get("to") or services.today_iso()
    rows = [r for r in services.receiving_box_rows()
            if date_from <= (r["received_date"] or "") <= date_to]
    rows.sort(key=lambda r: (r["received_date"] or "", r["id"]))
    return render_template("receiving/report.html", rows=rows,
                           date_from=date_from, date_to=date_to)


@receiving_bp.route("/damage")
def damage():
    user = current_user()
    if not (can(user, "receiving") or can(user, "inspection")):
        abort(403)
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
