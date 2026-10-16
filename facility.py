"""Facility records — cleaning & sanitation, and monthly pest control.

Each record is taken in a short wizard (one area per screen), shown on its
own page, and printed on the client's paper layout.  The logic lives in
``facility_service``.
"""
from datetime import date, timedelta

from flask import (Blueprint, abort, flash, g, redirect, render_template,
                   request, url_for)

import db
import facility_service as fs
import services
from security import current_user, module_required

facility_bp = Blueprint("facility", __name__)


def _me():
    return current_user() or {}


# =============================================================================
# Cleaning & sanitation
# =============================================================================
@facility_bp.route("/sanitation")
@module_required("facility")
def sanitation():
    show = request.args.get("show") or "week"
    if show not in ("week", "month", "action"):
        show = "week"
    records, actions = [], []
    if show == "action":
        actions = fs.open_sanitation_actions()
    else:
        start = fs.week_start() if show == "week" else services.this_month() + "-01"
        records = [fs.sanitation_view(r) for r in fs.sanitation_records(date_from=start)]
    today = services.today_iso()
    done_today = {r.get("phase") for r in db.read("sanitation_records")
                  if r.get("record_date") == today}
    return render_template("facility/sanitation.html", show=show,
                           records=records, actions=actions,
                           stats=fs.sanitation_summary(), done_today=done_today,
                           PRE=fs.PRE, POST=fs.POST)


def _sanitation_areas_from(form):
    areas = []
    for i in range(len(fs.LOCATIONS)):
        status = form.get("status_%d" % i) or ""
        done = form.get("done_%d" % i)
        areas.append({
            "current_status": status,
            "action": form.get("action_%d" % i) or "",
            "date_undertaken": (form.get("date_%d" % i) or "") if done == "1" else "",
            "remarks": form.get("remarks_%d" % i) or "",
        })
    return areas


@facility_bp.route("/sanitation/new", methods=["GET", "POST"])
@module_required("facility")
def sanitation_new():
    g.nav_endpoint = "facility.sanitation"
    form = request.form
    start = 0
    if request.method == "POST":
        try:
            rec = fs.save_sanitation(
                _me().get("id"), form.get("record_date"), form.get("phase"),
                _sanitation_areas_from(form), form.get("conducted_by"),
                form.get("inspected_by"), remarks=form.get("remarks") or "")
        except fs.RecordError as exc:
            flash(str(exc), "error")
            start = exc.step
        else:
            view = fs.sanitation_view(rec)
            if view["open_count"]:
                flash("Cleaning record saved — %d area(s) still need action."
                      % view["open_count"], "error")
            else:
                flash("Cleaning record saved — %s." % view["summary"], "success")
            return redirect(url_for("facility.sanitation_record", record_id=rec["id"]))

    # Suggest the phase not yet recorded today.
    today = services.today_iso()
    done = {r.get("phase") for r in db.read("sanitation_records")
            if r.get("record_date") == today}
    suggested = request.args.get("phase")
    if suggested not in fs.SANITATION_PHASES:
        suggested = fs.POST if fs.PRE in done and fs.POST not in done else (
            fs.PRE if fs.PRE not in done else "")
    return render_template(
        "facility/sanitation_new.html", form=form, start=start, today=today,
        locations=fs.LOCATIONS, statuses=fs.SANITATION_STATUSES,
        action_statuses=fs.ACTION_STATUSES, PRE=fs.PRE, POST=fs.POST,
        suggested_phase=suggested, me_name=_me().get("name") or "")


@facility_bp.route("/sanitation/<int:record_id>")
@module_required("facility")
def sanitation_record(record_id):
    g.nav_endpoint = "facility.sanitation"
    rec = db.get("sanitation_records", record_id)
    if not rec:
        abort(404)
    return render_template("facility/sanitation_record.html",
                           rec=fs.sanitation_view(rec),
                           today=services.today_iso())


@facility_bp.route("/sanitation/<int:record_id>/area/<int:index>/done", methods=["POST"])
@module_required("facility")
def sanitation_done(record_id, index):
    try:
        rec = fs.mark_sanitation_done(record_id, index,
                                      request.form.get("date_undertaken"),
                                      remarks=request.form.get("remarks"),
                                      user_id=_me().get("id"))
    except fs.RecordError as exc:
        flash(str(exc), "error")
    else:
        flash("%s marked done." % rec["areas"][index]["location"], "success")
    if request.form.get("back") == "list":
        return redirect(url_for("facility.sanitation", show="action"))
    return redirect(url_for("facility.sanitation_record", record_id=record_id))


def _range_args(default_days):
    today = date.today()
    date_to = request.args.get("to") or today.isoformat()
    date_from = request.args.get("from") or (today - timedelta(days=default_days)).isoformat()
    if date_from > date_to:
        date_from, date_to = date_to, date_from
    return date_from, date_to


@facility_bp.route("/sanitation/print")
@module_required("facility")
def sanitation_print():
    g.nav_endpoint = "facility.sanitation"
    date_from, date_to = _range_args(6)
    return render_template("facility/sanitation_print.html",
                           groups=fs.sanitation_paper_rows(date_from, date_to),
                           date_from=date_from, date_to=date_to,
                           locations=fs.LOCATIONS, location_paper=fs.LOCATION_PAPER,
                           phases=fs.SANITATION_PHASES, phase_paper=fs.PHASE_PAPER)


# =============================================================================
# Pest control
# =============================================================================
@facility_bp.route("/pest")
@module_required("facility")
def pest():
    months = fs.pest_months(12)
    current = months[-1]
    return render_template("facility/pest.html", months=months, current=current,
                           records=[fs.pest_view(r) for r in fs.pest_records()],
                           missing=[m for m in months if m["state"] == "missing"])


def _pest_areas_from(form):
    areas = []
    for i in range(len(fs.PEST_AREAS)):
        seen = form.get("pest_%d" % i)
        areas.append({
            "pest_activity": None if seen not in ("1", "0") else seen == "1",
            "observation": form.get("observation_%d" % i) or "",
            "corrective_action": form.get("corrective_%d" % i) or "",
        })
    return areas


@facility_bp.route("/pest/new", methods=["GET", "POST"])
@module_required("facility")
def pest_new():
    g.nav_endpoint = "facility.pest"
    form = request.form
    start = 0
    if request.method == "POST":
        try:
            rec = fs.save_pest(_me().get("id"), form.get("period"),
                               form.get("record_date"), _pest_areas_from(form),
                               form.get("monitored_by"),
                               remarks=form.get("remarks") or "")
        except fs.RecordError as exc:
            flash(str(exc), "error")
            start = exc.step
        else:
            view = fs.pest_view(rec)
            flash("Pest control for %s saved — %s." % (view["month"], view["summary"].lower()),
                  "error" if view["activity_count"] else "success")
            return redirect(url_for("facility.pest_record", record_id=rec["id"]))

    this_month = services.this_month()
    period = request.args.get("period") or this_month
    if len(period) != 7 or period > this_month:
        period = this_month
    existing = fs.pest_record_for(period)
    if existing and request.method == "GET":
        flash("%s is already recorded." % fs.month_label(period), "success")
        return redirect(url_for("facility.pest_record", record_id=existing["id"]))
    today = services.today_iso()
    default_date = today if period == this_month else fs.month_last_day(period)
    return render_template(
        "facility/pest_new.html", form=form, start=start, period=period,
        this_month=this_month, today=today, default_date=default_date,
        areas=fs.PEST_AREAS, me_name=_me().get("name") or "",
        month_label=fs.month_label(period))


@facility_bp.route("/pest/<int:record_id>")
@module_required("facility")
def pest_record(record_id):
    g.nav_endpoint = "facility.pest"
    rec = db.get("pest_control_records", record_id)
    if not rec:
        abort(404)
    return render_template("facility/pest_record.html", rec=fs.pest_view(rec))


@facility_bp.route("/pest/print")
@module_required("facility")
def pest_print():
    g.nav_endpoint = "facility.pest"
    today = date.today()
    date_to = request.args.get("to") or today.isoformat()
    # Default: this month and the two before it.
    date_from = request.args.get("from") or (
        fs.shift_month(services.this_month(), -2) + "-01")
    if date_from > date_to:
        date_from, date_to = date_to, date_from
    return render_template("facility/pest_print.html",
                           rows=fs.pest_paper_rows(date_from, date_to),
                           date_from=date_from, date_to=date_to,
                           areas=fs.PEST_AREAS, doc_no=fs.PEST_DOC_NO,
                           revision=fs.PEST_REVISION, issue_date=fs.PEST_ISSUE_DATE)
