"""Module 2 — honey containers, QR codes and the moisture / appearance check.

Honey is monitored by container.  Every container carries its own QR code
and is checked on **moisture content** and **appearance**.  The result is
**PASS** or **FAILED** only: passed honey goes to the products sold as honey,
failed honey goes to the products that can still use it.  Each container is
then allocated, kilo by kilo, to the products it went into.
"""
from flask import (Blueprint, abort, flash, jsonify, redirect, render_template,
                   request, url_for)

import db
import services
from security import current_user, module_required

honey_bp = Blueprint("honey", __name__)

SOURCES = [
    ("Own harvest", "From Amamio's own hives"),
    ("Supplier delivery", "Bought from a supplier"),
    ("Contract beekeeper", "From a partner beekeeper"),
]


def _row(c):
    remaining = services._to_float(c.get("remaining_kg", c.get("net_weight_kg")))
    return {
        "id": c["id"], "container_code": c.get("container_code"),
        "batch_ref": c.get("batch_ref"), "source": c.get("source"),
        "supplier_name": c.get("supplier_name"),
        "net_weight_kg": c.get("net_weight_kg"),
        "gross_weight_kg": c.get("gross_weight_kg"),
        "tare_weight_kg": c.get("tare_weight_kg"),
        "received_date": c.get("received_date"),
        "harvest_date": c.get("harvest_date"),
        "status": c.get("status"),
        "badge": services.QC_BADGE.get(c.get("status"), "badge-muted"),
        "moisture_pct": c.get("moisture_pct"),
        "appearance": c.get("appearance"),
        "disposition": c.get("disposition"),
        "allocated_to": c.get("allocated_to"),
        "allocations": [dict(a, by=services.user_name(a.get("allocated_by")),
                             at=services.fmt_dt(a.get("allocated_at")))
                        for a in (c.get("allocations") or [])],
        "remaining_kg": remaining,
        "qc_by": services.user_name(c.get("qc_by")),
        "qc_at": services.fmt_dt(c.get("qc_at")),
        "qc_notes": c.get("qc_notes"),
        "created_at": services.fmt_dt(c.get("created_at")),
    }


@honey_bp.route("/")
@module_required("honey")
def index():
    show = request.args.get("show") or "todo"
    containers = sorted(db.read("honey_containers"),
                        key=lambda x: x.get("created_at", ""), reverse=True)
    if show == "todo":
        listed = [c for c in containers
                  if c.get("status") == "Pending QC"
                  or (c.get("status") in services.QC_RESULTS
                      and services._to_float(c.get("remaining_kg",
                                                   c.get("net_weight_kg"))) > 0)]
    elif show in services.QC_RESULTS:
        listed = [c for c in containers if c.get("status") == show]
    else:
        listed = containers
    return render_template("honey/index.html", containers=[_row(c) for c in listed],
                           summary=services.honey_summary(), show=show,
                           routing=services.honey_product_totals())


@honey_bp.route("/new", methods=["GET", "POST"])
@module_required("honey")
def new():
    form = request.form
    if request.method == "POST":
        supplier_raw = (form.get("supplier_id") or "").strip()
        try:
            supplier_id = int(supplier_raw) if supplier_raw else None
        except ValueError:
            supplier_id = None
        source = form.get("source") or "Own harvest"
        if source == "Own harvest":
            supplier_id = None
        created, err = services.log_honey_containers(
            form.get("count") or 1, form.get("net_weight_kg"),
            current_user()["id"], supplier_id=supplier_id, source=source,
            harvest_date=form.get("harvest_date") or "",
            received_date=form.get("received_date") or services.today_iso(),
            batch_ref=form.get("batch_ref") or "",
            gross_weight_kg=form.get("gross_weight_kg"),
            tare_weight_kg=form.get("tare_weight_kg"))
        if created:
            flash("%d container(s) logged — print a QR label for each one."
                  % len(created), "success")
            return redirect(url_for("honey.labels", fresh=1,
                                    only=",".join(str(c["id"]) for c in created)))
        flash(err, "error")

    return render_template("honey/new.html", suppliers=db.read("suppliers"),
                           sources=SOURCES, today=services.today_iso(),
                           form=form, start=1 if request.method == "POST" else 0)


@honey_bp.route("/<int:container_id>")
@module_required("honey")
def container(container_id):
    record = db.get("honey_containers", container_id)
    if not record:
        abort(404)
    row = _row(record)
    return render_template(
        "honey/container.html", c=row, track=services.honey_track(record),
        products=services.honey_products_for(record.get("status")),
        moisture_max=services.MOISTURE_PASS_MAX,
        qr_text=services.honey_qr_text(record))


@honey_bp.route("/<int:container_id>/qc", methods=["GET", "POST"])
@module_required("honey")
def qc(container_id):
    record = db.get("honey_containers", container_id)
    if not record:
        abort(404)
    if record.get("status") in services.QC_RESULTS:
        return redirect(url_for("honey.container", container_id=container_id))
    form = request.form
    if request.method == "POST":
        updated, err = services.record_honey_qc(
            container_id, form.get("result") or "", form.get("moisture_pct"),
            form.get("appearance") or "", notes=form.get("qc_notes") or "",
            user_id=current_user()["id"])
        if not err:
            flash("Container %s %s — %s."
                  % (updated.get("container_code"),
                     "PASSED" if updated.get("status") == "Pass" else "FAILED",
                     updated.get("disposition")),
                  "success" if updated.get("status") == "Pass" else "error")
            return redirect(url_for("honey.container",
                                    container_id=container_id))
        flash(err, "error")
    return render_template(
        "honey/qc.html", c=_row(record), form=form,
        appearances=services.QC_APPEARANCE,
        moisture_max=services.MOISTURE_PASS_MAX,
        pass_products=services.HONEY_PASS_PRODUCTS,
        fail_products=services.HONEY_FAIL_PRODUCTS,
        start=1 if request.method == "POST" else 0)


@honey_bp.route("/suggest")
@module_required("honey")
def suggest():
    """Live Pass/Failed hint as the checker enters the readings."""
    return jsonify({"suggested": services.suggested_qc_result(
        request.args.get("moisture_pct"), request.args.get("appearance") or "")})


@honey_bp.route("/<int:container_id>/allocate", methods=["POST"])
@module_required("honey")
def allocate(container_id):
    record, err = services.allocate_honey_container(
        container_id, request.form.get("product") or "",
        request.form.get("kg"), user_id=current_user()["id"])
    if err:
        flash(err, "error")
    else:
        flash("Recorded: %s kg of %s went to %s."
              % (services.fmt_qty(request.form.get("kg")),
                 record.get("container_code"), request.form.get("product")),
              "success")
    return redirect(url_for("honey.container", container_id=container_id))


@honey_bp.route("/labels")
@module_required("honey")
def labels():
    containers = db.read("honey_containers")
    only = request.args.get("only")
    if only:
        wanted = set()
        for part in only.split(","):
            try:
                wanted.add(int(part))
            except ValueError:
                pass
        containers = [c for c in containers if c["id"] in wanted]
    else:
        status = request.args.get("status") or "Pending QC"
        containers = [c for c in containers if c.get("status") == status]
    return render_template("honey/labels.html",
                           containers=[_row(c) for c in containers],
                           fresh=request.args.get("fresh"))
