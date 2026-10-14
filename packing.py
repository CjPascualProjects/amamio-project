"""Packing-area blueprint.

Before anything ships, it is packed against one of the client's channels —
VIP, Shopee, TikTok, Lazada or Walk-in.  Each run records who packed it, the
date, the products and quantities, and any damage spotted while packing, then
moves through In Progress -> Packed -> Handed Over.
"""
from flask import (Blueprint, abort, flash, redirect, render_template, request,
                   url_for)

import db
import services
from security import current_user, is_admin, module_required, normalize_role

packing_bp = Blueprint("packing", __name__)


def _packers():
    """Everyone who can be named as the packer on a run."""
    return [u for u in db.read("users")
            if u.get("active", True)
            and (normalize_role(u.get("role")) in ("packing_head",)
                 or is_admin(u))]


def _run_rows(runs):
    rows = []
    for r in sorted(runs, key=lambda x: x.get("created_at", ""), reverse=True):
        rows.append({
            "id": r["id"], "run_code": r.get("run_code"),
            "channel": r.get("channel"), "packer_name": r.get("packer_name"),
            "pack_date": r.get("pack_date"), "order_ref": r.get("order_ref"),
            "status": r.get("status"),
            "badge": services.PACKING_BADGE.get(r.get("status"), "badge-muted"),
            "total_qty": r.get("total_qty"), "damaged_qty": r.get("damaged_qty"),
            "item_count": len(r.get("items", [])),
            "courier": r.get("courier"), "tracking_no": r.get("tracking_no"),
            "handed_to": r.get("handed_to"),
            "created_at": services.fmt_dt(r.get("created_at")),
        })
    return rows


@packing_bp.route("/")
@module_required("packing")
def index():
    runs = db.read("packing_runs")
    channel = request.args.get("channel") or ""
    status = request.args.get("status") or ""
    filtered = runs
    if channel:
        filtered = [r for r in filtered if r.get("channel") == channel]
    if status:
        filtered = [r for r in filtered if r.get("status") == status]
    return render_template(
        "packing/index.html", runs=_run_rows(filtered),
        summary=services.packing_summary(runs),
        leaderboard=services.packer_leaderboard(),
        channels=services.PACKING_CHANNELS, channel=channel, status=status,
        statuses=list(services.PACKING_BADGE))


@packing_bp.route("/new", methods=["GET", "POST"])
@module_required("packing")
def new():
    if request.method == "POST":
        product_ids = request.form.getlist("product_id")
        quantities = request.form.getlist("qty")
        damaged = request.form.getlist("damaged_qty")
        notes = request.form.getlist("line_notes")
        lines = []
        for i, pid in enumerate(product_ids):
            if not pid:
                continue
            lines.append({
                "product_id": pid,
                "qty": quantities[i] if i < len(quantities) else 0,
                "damaged_qty": damaged[i] if i < len(damaged) else 0,
                "notes": notes[i] if i < len(notes) else "",
            })
        order_raw = (request.form.get("sales_order_id") or "").strip()
        try:
            sales_order_id = int(order_raw) if order_raw else None
        except ValueError:
            sales_order_id = None
        packer_raw = (request.form.get("packer_id") or "").strip()
        try:
            packer_id = int(packer_raw) if packer_raw else current_user()["id"]
        except ValueError:
            packer_id = current_user()["id"]

        run, err = services.create_packing_run(
            request.form.get("channel") or "", packer_id, lines,
            current_user()["id"],
            pack_date=request.form.get("pack_date") or services.today_iso(),
            order_ref=request.form.get("order_ref") or "",
            sales_order_id=sales_order_id,
            remarks=request.form.get("remarks") or "",
            courier=request.form.get("courier") or "",
            tracking_no=request.form.get("tracking_no") or "")
        if err:
            flash(err, "error")
            return redirect(url_for("packing.new"))
        flash("Packing run %s opened for %s." % (run.get("run_code"),
                                                 run.get("channel")), "success")
        return redirect(url_for("packing.detail", run_id=run["id"]))

    open_orders = [o for o in db.read("sales_orders")
                   if o.get("status") in ("Pending", "Confirmed")]
    products = []
    for p in db.read("products"):
        row = dict(p)
        row["stock"] = services.current_stock("product", p["id"])
        products.append(row)
    return render_template("packing/new.html", products=products,
                           channels=services.PACKING_CHANNELS,
                           packers=_packers(), orders=open_orders,
                           today=services.today_iso())


@packing_bp.route("/<int:run_id>")
@module_required("packing")
def detail(run_id):
    run = db.get("packing_runs", run_id)
    if not run:
        abort(404)
    return render_template(
        "packing/detail.html", run=run,
        badge=services.PACKING_BADGE.get(run.get("status"), "badge-muted"),
        created_by=services.user_name(run.get("created_by")),
        created_at=services.fmt_dt(run.get("created_at")),
        packed_at=services.fmt_dt(run.get("packed_at")),
        handed_at=services.fmt_dt(run.get("handed_at")))


@packing_bp.route("/<int:run_id>/packed", methods=["POST"])
@module_required("packing")
def packed(run_id):
    run, err = services.mark_packed(run_id, user_id=current_user()["id"])
    if err:
        flash(err, "error")
    else:
        flash("Run %s packed — %g item(s) ready for hand-over."
              % (run.get("run_code"), services._to_float(run.get("total_qty"))),
              "success")
    return redirect(url_for("packing.detail", run_id=run_id))


@packing_bp.route("/<int:run_id>/handover", methods=["POST"])
@module_required("packing")
def handover(run_id):
    run, err = services.hand_over_packing_run(
        run_id, request.form.get("handed_to") or "",
        courier=request.form.get("courier") or "",
        tracking_no=request.form.get("tracking_no") or "",
        user_id=current_user()["id"])
    if err:
        flash(err, "error")
    else:
        flash("Run %s handed over to %s." % (run.get("run_code"),
                                             run.get("handed_to")), "success")
    return redirect(url_for("packing.detail", run_id=run_id))


@packing_bp.route("/<int:run_id>/cancel", methods=["POST"])
@module_required("packing")
def cancel(run_id):
    run, err = services.cancel_packing_run(run_id, user_id=current_user()["id"])
    if err:
        flash(err, "error")
    else:
        flash("Run %s cancelled." % run.get("run_code"), "success")
    return redirect(url_for("packing.index"))


@packing_bp.route("/<int:run_id>/slip")
@module_required("packing")
def slip(run_id):
    run = db.get("packing_runs", run_id)
    if not run:
        abort(404)
    return render_template("packing/slip.html", run=run,
                           packed_at=services.fmt_dt(run.get("packed_at")))
