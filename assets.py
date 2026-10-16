"""Module 3 — equipment & assets: the register, every IN / OUT, maintenance.

The Assets Maintenance Head records every unit that leaves the site or comes
back (borrowed, sent for repair, lent, disposed, returned, newly bought) in a
short step-by-step flow, and keeps each machine's Equipment Maintenance Log.
The printable "Inventory of Assets" and per-equipment maintenance log follow
the client's paper forms.  All logic lives in ``assets_service``.
"""
from flask import (Blueprint, abort, flash, redirect, render_template, request,
                   url_for)

import assets_service as svc
import db
import services
from security import current_user, module_required

assets_bp = Blueprint("assets", __name__)


def _asset_or_404(asset_id):
    asset = db.get("assets", asset_id)
    if not asset or not asset.get("active", True):
        abort(404)
    return asset


def _grouped_options():
    """[(category, [assets])] for the 'which item?' selects."""
    rows = [svc.asset_row(a) for a in svc.active_assets()]
    return svc.group_assets(rows)


# --- The register ------------------------------------------------------------
@assets_bp.route("/")
@module_required("assets")
def index():
    show = request.args.get("show") or "all"
    if show not in ("all", "out", "attention"):
        show = "all"
    rows = svc.asset_rows(show if show != "out" else "all")
    return render_template(
        "assets/index.html", show=show,
        groups=svc.group_assets(rows) if show != "out" else [],
        out_rows=svc.assets_out() if show == "out" else [],
        stats=svc.asset_summary(), due=svc.maintenance_due())


@assets_bp.route("/<int:asset_id>")
@module_required("assets")
def detail(asset_id):
    asset = _asset_or_404(asset_id)
    logs = svc.maintenance_rows(asset_id)
    row = svc.asset_row(asset, logs[0] if logs else None)
    return render_template(
        "assets/detail.html", a=row,
        moves=svc.movement_rows(asset_id, limit=8),
        logs=logs[:6], log_count=len(logs),
        out_rows=[o for o in svc.assets_out() if o["asset_id"] == asset_id])


@assets_bp.route("/movements")
@module_required("assets")
def movements():
    direction = request.args.get("direction") or ""
    if direction not in ("", "IN", "OUT"):
        direction = ""
    return render_template("assets/movements.html", direction=direction,
                           moves=svc.movement_rows(direction=direction or None,
                                                   limit=200))


# --- IN / OUT ----------------------------------------------------------------
@assets_bp.route("/move", methods=["GET", "POST"])
@module_required("assets")
def move():
    form = request.form if request.method == "POST" else request.args
    start = 0
    if request.method == "POST":
        movement, err = svc.record_movement(
            form.get("asset_id"), form.get("direction"), form.get("reason"),
            form.get("qty"), person=form.get("person") or "",
            destination=form.get("destination") or "",
            expected_return=form.get("expected_return") or "",
            notes=form.get("notes") or "", condition=form.get("condition") or "",
            user_id=current_user()["id"])
        if not err:
            flash("%s recorded: %s × %s (%s)." % (
                movement["direction"], services.fmt_qty(movement["qty"]),
                movement["asset_name"], movement["reason"]), "success")
            return redirect(url_for("assets.detail", asset_id=movement["asset_id"]))
        flash(err, "error")
        start = 2
    elif form.get("asset_id") and form.get("direction") in ("IN", "OUT"):
        start = 2       # came from an equipment page: straight to "why"
    elif form.get("asset_id"):
        start = 0
    return render_template(
        "assets/move.html", form=form, start=start, groups=_grouped_options(),
        out_reasons=svc.ASSET_OUT_REASONS, in_reasons=svc.ASSET_IN_REASONS,
        returnable=svc.RETURNABLE_OUT, conditions=svc.ASSET_CONDITIONS,
        today=services.today_iso())


# --- Add / edit equipment ------------------------------------------------------
def _asset_form(asset=None):
    form = request.form
    if request.method == "POST":
        record, err = svc.save_asset(form, current_user()["id"],
                                     asset_id=asset["id"] if asset else None)
        if not err:
            flash(("%s updated." if asset else "%s added to the register as %s.")
                  % ((record["name"],) if asset else (record["name"], record["item_no"])),
                  "success")
            return redirect(url_for("assets.detail", asset_id=record["id"]))
        flash(err, "error")
    return render_template(
        "assets/form.html", asset=asset,
        form=form if request.method == "POST" else (asset or {}),
        categories=svc.asset_categories(), conditions=svc.ASSET_CONDITIONS,
        next_no=asset.get("item_no") if asset else svc.next_item_no(),
        today=services.today_iso())


@assets_bp.route("/new", methods=["GET", "POST"])
@module_required("assets")
def new():
    return _asset_form()


@assets_bp.route("/<int:asset_id>/edit", methods=["GET", "POST"])
@module_required("assets")
def edit(asset_id):
    return _asset_form(_asset_or_404(asset_id))


# --- Maintenance ---------------------------------------------------------------
@assets_bp.route("/maintenance", methods=["GET", "POST"])
@assets_bp.route("/<int:asset_id>/maintenance", methods=["GET", "POST"])
@module_required("assets")
def maintenance(asset_id=None):
    form = request.form if request.method == "POST" else request.args
    chosen = asset_id or svc._int(form.get("asset_id"))
    if chosen:
        _asset_or_404(chosen)
    start = 1 if chosen else 0
    if request.method == "POST":
        log, err = svc.record_maintenance(
            form.get("asset_id") or chosen, form.get("type") or "",
            form.get("performed_on") or "", form.get("performed_by") or "",
            form.get("status") or "", description=form.get("description") or "",
            performed_time=form.get("performed_time") or "",
            cost=form.get("cost") or 0, next_due=form.get("next_due") or "",
            downtime_hours=form.get("downtime_hours") or 0,
            notes=form.get("notes") or "", user_id=current_user()["id"])
        if not err:
            flash("%s logged for %s." % (log["type"], log["asset_name"]), "success")
            return redirect(url_for("assets.detail", asset_id=log["asset_id"]))
        flash(err, "error")
        start = 1
    return render_template(
        "assets/maintenance.html", form=form, chosen=chosen, start=start,
        groups=_grouped_options(), types=svc.MAINTENANCE_TYPES,
        statuses=svc.MAINTENANCE_STATUS, today=services.today_iso())


# --- Printable paper forms -----------------------------------------------------
@assets_bp.route("/print/inventory")
@module_required("assets")
def inventory_print():
    rows = svc.asset_rows()
    groups = svc.group_assets(rows)
    return render_template("assets/inventory_print.html", groups=groups,
                           today=services.today_iso(),
                           total_units=sum(r["quantity"] for r in rows))


@assets_bp.route("/<int:asset_id>/log")
@module_required("assets")
def maintenance_print(asset_id):
    asset = _asset_or_404(asset_id)
    logs = list(reversed(svc.maintenance_rows(asset_id)))   # oldest first
    return render_template("assets/log_print.html", a=asset, logs=logs,
                           today=services.today_iso())
