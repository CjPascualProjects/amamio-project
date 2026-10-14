"""Honey-production blueprint: containers, QR codes and the moisture /
appearance quality check.

Honey is monitored by container.  Every container carries its own QR code and
must pass a quality check on **moisture content** and **appearance**.  The
result is **Pass** or **Failed** only: a Pass joins sellable honey stock, a
Failure is routed to other products rather than discarded.
"""
from flask import (Blueprint, abort, flash, jsonify, redirect, render_template,
                   request, url_for)

import db
import services
from security import current_user, module_required

honey_bp = Blueprint("honey", __name__)

SOURCES = ["Own harvest", "Supplier delivery", "Contract beekeeper"]


def _container_rows(containers):
    rows = []
    for c in sorted(containers, key=lambda x: x.get("created_at", ""),
                    reverse=True):
        rows.append({
            "id": c["id"], "container_code": c.get("container_code"),
            "batch_ref": c.get("batch_ref"), "source": c.get("source"),
            "supplier_name": c.get("supplier_name"),
            "net_weight_kg": c.get("net_weight_kg"),
            "received_date": c.get("received_date"),
            "harvest_date": c.get("harvest_date"),
            "status": c.get("status"),
            "badge": services.QC_BADGE.get(c.get("status"), "badge-muted"),
            "moisture_pct": c.get("moisture_pct"),
            "appearance": c.get("appearance"),
            "disposition": c.get("disposition"),
            "allocated_to": c.get("allocated_to"),
            "qc_by": services.user_name(c.get("qc_by")),
            "qc_at": services.fmt_dt(c.get("qc_at")),
            "qc_notes": c.get("qc_notes"),
        })
    return rows


@honey_bp.route("/")
@module_required("honey")
def index():
    containers = db.read("honey_containers")
    status = request.args.get("status") or ""
    if status:
        containers = [c for c in containers if c.get("status") == status]
    return render_template("honey/index.html",
                           containers=_container_rows(containers),
                           summary=services.honey_summary(), status=status,
                           moisture_max=services.MOISTURE_PASS_MAX)


@honey_bp.route("/new", methods=["GET", "POST"])
@module_required("honey")
def new():
    if request.method == "POST":
        supplier_raw = (request.form.get("supplier_id") or "").strip()
        try:
            supplier_id = int(supplier_raw) if supplier_raw else None
        except ValueError:
            supplier_id = None
        try:
            count = max(1, min(int(request.form.get("count") or 1), 50))
        except ValueError:
            count = 1

        created, err = [], None
        for _ in range(count):
            container, err = services.create_honey_container(
                request.form.get("net_weight_kg"), current_user()["id"],
                supplier_id=supplier_id,
                source=request.form.get("source") or "Own harvest",
                harvest_date=request.form.get("harvest_date") or "",
                received_date=request.form.get("received_date")
                or services.today_iso(),
                batch_ref=request.form.get("batch_ref") or "",
                gross_weight_kg=request.form.get("gross_weight_kg"),
                tare_weight_kg=request.form.get("tare_weight_kg"))
            if err:
                break
            created.append(container)
        if err and not created:
            flash(err, "error")
            return redirect(url_for("honey.new"))
        flash("%d container(s) logged and queued for quality check."
              % len(created), "success")
        return redirect(url_for("honey.index"))

    return render_template("honey/new.html", suppliers=db.read("suppliers"),
                           sources=SOURCES, today=services.today_iso())


@honey_bp.route("/<int:container_id>", methods=["GET", "POST"])
@module_required("honey")
def qc(container_id):
    container = db.get("honey_containers", container_id)
    if not container:
        abort(404)

    if request.method == "POST":
        updated, err = services.record_honey_qc(
            container_id, request.form.get("result") or "",
            request.form.get("moisture_pct"),
            request.form.get("appearance") or "",
            notes=request.form.get("qc_notes") or "",
            user_id=current_user()["id"])
        if err:
            flash(err, "error")
            return redirect(url_for("honey.qc", container_id=container_id))
        flash("Container %s marked %s — %s."
              % (updated.get("container_code"), updated.get("status"),
                 updated.get("disposition")),
              "success" if updated.get("status") == "Pass" else "error")
        return redirect(url_for("honey.index"))

    return render_template(
        "honey/qc.html", container=container,
        badge=services.QC_BADGE.get(container.get("status"), "badge-muted"),
        appearances=services.QC_APPEARANCE, results=services.QC_RESULTS,
        moisture_max=services.MOISTURE_PASS_MAX,
        qc_by=services.user_name(container.get("qc_by")),
        qc_at=services.fmt_dt(container.get("qc_at")))


@honey_bp.route("/suggest")
@module_required("honey")
def suggest():
    """Live Pass/Failed hint as the checker types the readings."""
    return jsonify({"suggested": services.suggested_qc_result(
        request.args.get("moisture_pct"), request.args.get("appearance") or "")})


@honey_bp.route("/<int:container_id>/allocate", methods=["POST"])
@module_required("honey")
def allocate(container_id):
    container, err = services.allocate_honey_container(
        container_id, request.form.get("allocated_to") or "",
        user_id=current_user()["id"])
    if err:
        flash(err, "error")
    else:
        flash("Container %s allocated to %s."
              % (container.get("container_code"), container.get("allocated_to")),
              "success")
    return redirect(request.form.get("next") or url_for("honey.index"))


@honey_bp.route("/labels")
@module_required("honey")
def labels():
    containers = db.read("honey_containers")
    status = request.args.get("status") or ""
    if status:
        containers = [c for c in containers if c.get("status") == status]
    return render_template("honey/labels.html",
                           containers=_container_rows(containers))
