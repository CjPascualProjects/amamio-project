"""Production records: Batch Manufacturing Records, the Daily Production
Report and the Retention Record — each one focused step at a time.

Logic lives in ``production_service``; this file only reads forms and picks
templates."""
from datetime import datetime

from flask import (Blueprint, abort, flash, g, redirect, render_template, request,
                   url_for)

import db
import production_service as ps
import services
from security import current_user, module_required

production_bp = Blueprint("production", __name__)


@production_bp.before_request
def _nav_entry():
    """Retention pages highlight "Retention Samples" in the sidebar."""
    if (request.endpoint or "").startswith("production.retention"):
        g.nav_endpoint = "production.retention"


def _uid():
    user = current_user()
    return user["id"] if user else None


def _batch_or_404(batch_id):
    rec = ps.get_batch(batch_id)
    if not rec:
        abort(404)
    return rec


# --- Batch records -------------------------------------------------------------
@production_bp.route("/")
@module_required("production")
def index():
    show = request.args.get("show", "recent")
    in_progress = [ps.decorate(r) for r in ps.batch_rows(ps.IN_PROGRESS)]
    finished = [ps.decorate(r) for r in ps.batch_rows()
                if r.get("status") in (ps.COMPLETED, ps.CANCELLED)]
    if show != "all":
        finished = finished[:8]
    return render_template("production/index.html", stats=ps.batch_summary(),
                           in_progress=in_progress, finished=finished, show=show)


@production_bp.route("/new")
@module_required("production")
def new():
    """Old 'record a production run' link — a run is now a batch record."""
    return redirect(url_for("production.start", **request.args))


@production_bp.route("/batch/new", methods=["GET", "POST"])
@module_required("production")
def start():
    user = current_user()
    form, lines, steps, start_step = {}, None, None, 0
    if request.method == "POST":
        form = request.form.to_dict()
        lines = ps.parse_dispensing(request.form)
        steps = request.form.getlist("step_process")
        rec, err = ps.start_batch(user["id"], form.get("product_id"),
                                  form.get("batch_size"), form.get("production_date"),
                                  form.get("expiry_date"), form.get("start_at"),
                                  lines, steps, batch_no=form.get("batch_no", ""))
        if not err:
            flash("Batch %s started for %s." % (rec["batch_no"], rec["product_name"]),
                  "success")
            return redirect(url_for("production.batch", batch_id=rec["id"]))
        flash(err, "error")
        start_step = 2 if ("ingredient" in err or "dispens" in err or "weight" in err) \
            else 3 if "procedure" in err else 0 if err.startswith("Choose the product") else 1
    elif request.args.get("product_id"):
        form = {"product_id": request.args.get("product_id"),
                "batch_size": request.args.get("qty", "")}
    today = services.today_iso()
    return render_template(
        "production/start.html", groups=ps.product_groups(),
        materials=ps.ingredient_materials(), data=ps.wizard_data(),
        form=form, lines=lines, steps=steps, start=start_step, today=today,
        default_expiry=ps.default_expiry(today),
        now_local=datetime.now().strftime("%Y-%m-%dT%H:%M"),
        next_no=ps.next_batch_no())


@production_bp.route("/batch/<int:batch_id>")
@module_required("production")
def batch(batch_id):
    rec = ps.decorate(_batch_or_404(batch_id))
    conducted, checked = ps.last_signers(rec)
    current = ps.current_step_index(rec)
    return render_template(
        "production/batch.html", rec=rec, track=ps.track(rec),
        current=current, shortages=ps.material_shortages(rec.get("dispensing") or []),
        conducted=conducted or current_user().get("name", ""), checked=checked,
        created_by=services.user_name(rec.get("created_by")))


@production_bp.route("/batch/<int:batch_id>/dispensing", methods=["GET", "POST"])
@module_required("production")
def dispensing(batch_id):
    rec = _batch_or_404(batch_id)
    if ps.stage(rec) != "dispensing":
        return redirect(url_for("production.batch", batch_id=batch_id))
    if request.method == "POST":
        signers = list(zip(request.form.getlist("conducted_by"),
                           request.form.getlist("checked_by")))
        _, err = ps.sign_dispensing(batch_id, signers, _uid())
        if not err:
            flash("Dispensing & weighing signed off. Next: the procedure.", "success")
            return redirect(url_for("production.batch", batch_id=batch_id))
        flash(err, "error")
    return render_template("production/dispensing.html", rec=ps.decorate(rec),
                           me=current_user().get("name", ""),
                           shortages=ps.material_shortages(rec.get("dispensing") or []))


@production_bp.route("/batch/<int:batch_id>/step", methods=["POST"])
@module_required("production")
def step(batch_id):
    _batch_or_404(batch_id)
    rec, err = ps.sign_step(batch_id, request.form.get("index"),
                            request.form.get("conducted_by"),
                            request.form.get("checked_by"), _uid())
    if err:
        flash(err, "error")
    elif ps.stage(rec) == "finish":
        flash("All procedure steps are done. Next: yield and QA.", "success")
    return redirect(url_for("production.batch", batch_id=batch_id))


@production_bp.route("/batch/<int:batch_id>/undo-step", methods=["POST"])
@module_required("production")
def undo_step(batch_id):
    _batch_or_404(batch_id)
    _, err = ps.undo_last_step(batch_id)
    if err:
        flash(err, "error")
    return redirect(url_for("production.batch", batch_id=batch_id))


@production_bp.route("/batch/<int:batch_id>/cancel", methods=["POST"])
@module_required("production")
def cancel(batch_id):
    _batch_or_404(batch_id)
    rec, err = ps.cancel_batch(batch_id, _uid())
    flash(err or "Batch %s cancelled — no stock was moved." % rec["batch_no"],
          "error" if err else "success")
    return redirect(url_for("production.batch", batch_id=batch_id))


@production_bp.route("/batch/<int:batch_id>/finish", methods=["GET", "POST"])
@module_required("production")
def finish(batch_id):
    rec = _batch_or_404(batch_id)
    if ps.stage(rec) != "finish":
        return redirect(url_for("production.batch", batch_id=batch_id))
    form, start_step = {}, 0
    if request.method == "POST":
        form = request.form.to_dict()
        done, err = ps.finish_batch(
            batch_id, _uid(), form.get("end_at"), form.get("actual_yield"),
            form.get("disposition"), form.get("qa_name"), qa_date=form.get("qa_date"),
            test_date=form.get("test_date"), test_result_date=form.get("test_result_date"),
            remarks=form.get("remarks"),
            yield_conducted_by=form.get("yield_conducted_by"),
            yield_checked_by=form.get("yield_checked_by"),
            test_conducted_by=form.get("test_conducted_by"),
            test_checked_by=form.get("test_checked_by"))
        if not err:
            if done["disposition"] == ps.APPROVED:
                flash("Batch %s approved — %s added to stock." % (
                    done["batch_no"], services.fmt_qty(done["actual_yield"], ps.product_unit(done))),
                    "success")
            else:
                flash("Batch %s disapproved — materials used, nothing added to stock." %
                      done["batch_no"], "success")
            return redirect(url_for("production.batch", batch_id=batch_id))
        flash(err, "error")
        start_step = next((idx for needle, idx in (
            ("batch ended", 0), ("end must be", 0), ("actual yield", 1),
            ("test result", 2), ("APPROVED or", 3), ("name of the QA", 4),
            ("(remarks)", 4)) if needle in err), 5)
    conducted, checked = ps.last_signers(rec)
    return render_template(
        "production/finish.html", rec=ps.decorate(rec), form=form, start=start_step,
        today=services.today_iso(),
        now_local=datetime.now().strftime("%Y-%m-%dT%H:%M"),
        conducted=conducted, checked=checked,
        shortages=ps.material_shortages(rec.get("dispensing") or []),
        used=[l for l in rec.get("dispensing") or [] if l.get("material_id")])


@production_bp.route("/batch/<int:batch_id>/print")
@module_required("production")
def batch_print(batch_id):
    rec = ps.decorate(_batch_or_404(batch_id))
    return render_template("production/bmr_print.html", rec=rec,
                           fmt_local=ps.fmt_local)


# --- Daily Production Report ---------------------------------------------------
@production_bp.route("/daily-report")
@module_required("production")
def daily_report():
    month = request.args.get("month") or services.this_month()
    view = request.args.get("view", "week")
    show_all = request.args.get("all") == "1"
    report = ps.daily_report(month, view, show_all)
    return render_template("production/daily_report.html", r=report)


# --- Retention samples ---------------------------------------------------------
@production_bp.route("/retention")
@module_required("production")
def retention():
    show = request.args.get("show", "retained")
    if show not in ("retained", "due", "disposed"):
        show = "retained"
    return render_template("production/retention.html",
                           samples=ps.retention_rows(show), show=show,
                           stats=ps.retention_summary(), today=services.today_iso())


@production_bp.route("/retention/new", methods=["GET", "POST"])
@module_required("production")
def retention_new():
    form, start_step = {}, 0
    if request.method == "POST":
        form = request.form.to_dict()
        from_batch = form.get("source") == "batch"
        sample, err = ps.add_retention(
            _uid(), form.get("qty"), form.get("prod_date"), form.get("exp_date"),
            batch_record_id=form.get("batch_record_id") if from_batch else None,
            batch_no="" if from_batch else form.get("batch_no"),
            product_id=None if from_batch else form.get("product_id"),
            description=form.get("description"), remarks=form.get("remarks"),
            inspected_by=form.get("inspected_by"), approved_by=form.get("approved_by"))
        if not err:
            flash("Retention sample kept for batch %s." % sample["batch_no"], "success")
            return redirect(url_for("production.retention"))
        flash(err, "error")
        start_step = ((1 if from_batch else 2)
                      if err in ("Choose a batch record.", "Enter the batch number.",
                                 "Choose the product.")
                      else 4 if "inspected" in err else 3)
    elif request.args.get("batch_id"):
        form = {"source": "batch", "batch_record_id": request.args.get("batch_id")}
        start_step = 3 if ps.get_batch(form["batch_record_id"]) else 0
    batches = [r for r in ps.batch_rows(ps.COMPLETED)]
    return render_template("production/retention_new.html", form=form, start=start_step,
                           batches=batches, groups=ps.product_groups(),
                           me=current_user().get("name", ""), today=services.today_iso())


@production_bp.route("/retention/<int:sample_id>/dispose", methods=["GET", "POST"])
@module_required("production")
def retention_dispose(sample_id):
    sample = db.get("retention_samples", sample_id)
    if not sample:
        abort(404)
    if request.method == "POST":
        _, err = ps.dispose_retention(sample_id, request.form.get("disposal_date"),
                                      request.form.get("remarks"), _uid())
        if not err:
            flash("Sample from batch %s marked as disposed." % sample["batch_no"], "success")
            return redirect(url_for("production.retention", show="disposed"))
        flash(err, "error")
    product = db.get("products", sample.get("product_id")) if sample.get("product_id") else None
    return render_template("production/retention_dispose.html", s=sample,
                           unit=(product or {}).get("unit", ""),
                           due=ps.retention_due(sample), today=services.today_iso())


@production_bp.route("/retention/print")
@module_required("production")
def retention_print():
    date_from = request.args.get("from", "")
    date_to = request.args.get("to", "")
    rows = ps.retention_rows("all")
    if date_from:
        rows = [r for r in rows if (r.get("prod_date") or "") >= date_from]
    if date_to:
        rows = [r for r in rows if (r.get("prod_date") or "") <= date_to]
    rows.sort(key=lambda r: (r.get("prod_date") or "", r.get("id") or 0))
    return render_template("production/retention_print.html", rows=rows,
                           date_from=date_from, date_to=date_to)
