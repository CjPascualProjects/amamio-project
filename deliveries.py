"""Delivery and Distribution blueprint."""
from flask import (Blueprint, flash, redirect, render_template, request, url_for)

import db
import services
from security import module_required

deliveries_bp = Blueprint("deliveries", __name__)

STATUSES = ["Scheduled", "In Transit", "Delivered", "Cancelled"]


@deliveries_bp.route("/")
@module_required("deliveries")
def index():
    deliveries = sorted(db.read("deliveries"),
                        key=lambda d: d.get("id", 0), reverse=True)
    rows = []
    for d in deliveries:
        row = dict(d)
        row["badge"] = services.DELIVERY_BADGE.get(d.get("status"), "badge-muted")
        rows.append(row)
    return render_template("deliveries/index.html", deliveries=rows,
                           statuses=STATUSES)


@deliveries_bp.route("/<int:id>/update", methods=["POST"])
@module_required("deliveries")
def update(id):
    status = request.form.get("status")
    driver = request.form.get("driver")
    notes = request.form.get("notes")
    confirmed = request.form.get("confirmed") == "1"
    delivery = services.update_delivery(id, status=status, driver=driver,
                                        confirmed=confirmed, notes=notes)
    if delivery:
        flash("Delivery #%d updated." % id, "success")
    else:
        flash("Delivery not found.", "error")
    return redirect(url_for("deliveries.index"))
