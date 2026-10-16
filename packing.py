"""Module 4 — the packing area.

The packing team (head and members) records each run against one of the
client's channels — VIP, Shopee, TikTok, Lazada or Walk-in: who packed it,
which products and how many, and any damage spotted while packing.  Then the
run is either DISBURSED (handed straight to the customer / VIP / walk-in /
another team) or DELIVERED TO THE LOGISTICS / COURIER with a tracking number.
"""
from datetime import date, timedelta

from flask import (Blueprint, abort, flash, redirect, render_template, request,
                   url_for)

import db
import services
from security import (current_user, is_admin, module_required, normalize_role)

packing_bp = Blueprint("packing", __name__)

PACKER_ROLES = ("packing_head", "packing_member")


def _packers():
    """Everyone who can be named as the packer on a run."""
    return [u for u in db.read("users")
            if u.get("active", True)
            and (normalize_role(u.get("role")) in PACKER_ROLES or is_admin(u))]


def _can_cancel(user):
    return is_admin(user) or normalize_role(user.get("role")) == "packing_head"


def _run_row(r):
    status = services.packing_status(r)
    return {
        "id": r["id"], "run_code": r.get("run_code"),
        "channel": r.get("channel"), "packer_name": r.get("packer_name"),
        "pack_date": r.get("pack_date"), "order_ref": r.get("order_ref"),
        "status": status,
        "badge": services.PACKING_BADGE.get(status, "badge-muted"),
        "total_qty": r.get("total_qty"), "damaged_qty": r.get("damaged_qty"),
        "item_count": len(r.get("items", [])),
        "items": r.get("items", []),
        "courier": r.get("courier"), "tracking_no": r.get("tracking_no"),
        "handed_to": r.get("handed_to"), "parcel_count": r.get("parcel_count"),
        "dispatch_notes": r.get("dispatch_notes"),
        "handed_at": services.fmt_dt(r.get("handed_at")),
        "packed_at": services.fmt_dt(r.get("packed_at")),
        "created_at": services.fmt_dt(r.get("created_at")),
        "remarks": r.get("remarks"),
        "sales_order_id": r.get("sales_order_id"),
        "stock_released": r.get("stock_released"),
    }


def _period(key):
    today = date.today()
    if key == "today":
        return today.isoformat(), today.isoformat()
    if key == "week":
        return (today - timedelta(days=today.weekday())).isoformat(), today.isoformat()
    if key == "month":
        return today.replace(day=1).isoformat(), today.isoformat()
    return "", ""


@packing_bp.route("/")
@module_required("packing")
def index():
    period = request.args.get("period") or "today"
    date_from, date_to = _period(period)
    runs = sorted(db.read("packing_runs"),
                  key=lambda x: x.get("created_at", ""), reverse=True)
    waiting = [_run_row(r) for r in runs if r.get("status") == "Packed"]
    in_progress = [_run_row(r) for r in runs if r.get("status") == "In Progress"]
    recent = [_run_row(r) for r in runs if services.is_dispatched(r)][:8]
    return render_template(
        "packing/index.html", waiting=waiting, in_progress=in_progress,
        recent=recent, period=period,
        summary=services.packing_summary(runs, date_from, date_to))


@packing_bp.route("/new", methods=["GET", "POST"])
@module_required("packing")
def new():
    user = current_user()
    form = request.form
    if request.method == "POST":
        lines = []
        product_ids = form.getlist("product_id")
        quantities = form.getlist("qty")
        damaged = form.getlist("damaged_qty")
        notes = form.getlist("line_notes")
        for i, pid in enumerate(product_ids):
            if not pid:
                continue
            lines.append({
                "product_id": pid,
                "qty": quantities[i] if i < len(quantities) else 0,
                "damaged_qty": damaged[i] if i < len(damaged) else 0,
                "notes": notes[i] if i < len(notes) else "",
            })
        try:
            packer_id = int(form.get("packer_id") or user["id"])
        except ValueError:
            packer_id = user["id"]
        order_raw = (form.get("sales_order_id") or "").strip()
        sales_order_id = int(order_raw) if order_raw.isdigit() else None

        run, err = services.pack_now(
            form.get("channel") or "", packer_id, lines, user["id"],
            pack_date=form.get("pack_date") or services.today_iso(),
            order_ref=form.get("order_ref") or "",
            sales_order_id=sales_order_id,
            remarks=form.get("remarks") or "")
        if run and not err:
            flash("Packed: %s item(s) for %s (%s). Next, disburse it or hand "
                  "it to the courier." % (services.fmt_qty(run.get("total_qty")),
                                          run.get("channel"), run.get("run_code")),
                  "success")
            return redirect(url_for("packing.detail", run_id=run["id"]))
        if run:
            flash("Saved as %s but not marked packed: %s" % (run.get("run_code"),
                                                             err), "error")
            return redirect(url_for("packing.detail", run_id=run["id"]))
        flash(err, "error")

    open_orders = [o for o in db.read("sales_orders")
                   if o.get("status") in ("Pending", "Confirmed")]
    products = []
    for p in sorted(db.read("products"),
                    key=lambda p: (p.get("sort_order") or 0, p.get("name") or "")):
        row = dict(p)
        row["stock"] = services.current_stock("product", p["id"])
        products.append(row)
    lines = []
    if request.method == "POST":
        for i, pid in enumerate(form.getlist("product_id")):
            lines.append({"product_id": pid,
                          "qty": (form.getlist("qty") + [""])[i],
                          "damaged_qty": (form.getlist("damaged_qty") + [""])[i],
                          "notes": (form.getlist("line_notes") + [""])[i]})
    return render_template(
        "packing/new.html", products=products,
        channels=services.PACKING_CHANNELS, packers=_packers(),
        orders=open_orders, today=services.today_iso(), form=form,
        lines=lines, me=user, start=2 if request.method == "POST" else 0)


@packing_bp.route("/<int:run_id>")
@module_required("packing")
def detail(run_id):
    run = db.get("packing_runs", run_id)
    if not run:
        abort(404)
    return render_template(
        "packing/detail.html", run=_run_row(run),
        track=services.packing_track(run),
        created_by=services.user_name(run.get("created_by")),
        dispatched_by=services.user_name(run.get("dispatched_by")),
        can_cancel=_can_cancel(current_user()),
        qr_text=services.packing_qr_text(run))


@packing_bp.route("/<int:run_id>/packed", methods=["POST"])
@module_required("packing")
def packed(run_id):
    run, err = services.mark_packed(run_id, user_id=current_user()["id"])
    if err:
        flash(err, "error")
    else:
        flash("Run %s packed — %s item(s) ready to go out."
              % (run.get("run_code"), services.fmt_qty(run.get("total_qty"))),
              "success")
    return redirect(url_for("packing.detail", run_id=run_id))


@packing_bp.route("/<int:run_id>/dispatch", methods=["GET", "POST"])
@module_required("packing")
def dispatch(run_id):
    run = db.get("packing_runs", run_id)
    if not run:
        abort(404)
    if run.get("status") != "Packed":
        flash("Only a packed run can be disbursed or handed to the courier.",
              "error")
        return redirect(url_for("packing.detail", run_id=run_id))
    form = request.form
    if request.method == "POST":
        updated, err = services.dispatch_packing_run(
            run_id, form.get("dispatch_type") or "", form.get("handed_to") or "",
            user_id=current_user()["id"], courier=form.get("courier") or "",
            tracking_no=form.get("tracking_no") or "",
            parcel_count=form.get("parcel_count"),
            notes=form.get("dispatch_notes") or "")
        if not err:
            flash("Run %s: %s." % (updated.get("run_code"),
                                   updated.get("status").lower()), "success")
            return redirect(url_for("packing.detail", run_id=run_id))
        flash(err, "error")
    return render_template("packing/dispatch.html", run=_run_row(run),
                           types=services.DISPATCH_TYPES,
                           couriers=services.COURIERS, form=form,
                           start=1 if request.method == "POST" else 0)


@packing_bp.route("/<int:run_id>/cancel", methods=["POST"])
@module_required("packing")
def cancel(run_id):
    if not _can_cancel(current_user()):
        abort(403)
    run, err = services.cancel_packing_run(run_id, user_id=current_user()["id"])
    if err:
        flash(err, "error")
        return redirect(url_for("packing.detail", run_id=run_id))
    flash("Run %s cancelled." % run.get("run_code"), "success")
    return redirect(url_for("packing.index"))


@packing_bp.route("/history")
@module_required("packing")
def history():
    """Every run, filterable by channel and status — the full record."""
    runs = db.read("packing_runs")
    channel = request.args.get("channel") or ""
    status = request.args.get("status") or ""
    if channel:
        runs = [r for r in runs if r.get("channel") == channel]
    if status:
        runs = [r for r in runs if services.packing_status(r) == status]
    runs.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return render_template(
        "packing/history.html", runs=[_run_row(r) for r in runs],
        channels=services.PACKING_CHANNELS, channel=channel, status=status,
        statuses=["In Progress", "Packed", services.DISPATCH_DISBURSED,
                  services.DISPATCH_COURIER, "Cancelled"],
        leaderboard=services.packer_leaderboard())


@packing_bp.route("/<int:run_id>/slip")
@module_required("packing")
def slip(run_id):
    run = db.get("packing_runs", run_id)
    if not run:
        abort(404)
    return render_template("packing/slip.html", run=run,
                           packed_at=services.fmt_dt(run.get("packed_at")))
