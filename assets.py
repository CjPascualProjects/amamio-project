"""Assets & maintenance blueprint — the Assets/Maintenance Team Head's desk.

Equipment and cleaning supplies live in ``raw_materials`` under the ``asset`` /
``cleaning`` categories; this module adds the service history on top: what was
done, when, by whom, what it cost and when the next service falls due.
"""
from flask import (Blueprint, abort, flash, redirect, render_template, request,
                   url_for)

import db
import services
from security import current_user, module_required

assets_bp = Blueprint("assets", __name__)

ASSET_CATEGORIES = ("asset", "cleaning")


def _assets():
    return [m for m in db.read("raw_materials")
            if m.get("category") in ASSET_CATEGORIES]


@assets_bp.route("/")
@module_required("assets")
def index():
    logs = db.read("maintenance_logs")
    by_asset = {}
    for log in logs:
        by_asset.setdefault(log.get("asset_id"), []).append(log)

    rows = []
    for asset in _assets():
        history = sorted(by_asset.get(asset["id"], []),
                         key=lambda l: l.get("performed_on", ""), reverse=True)
        last = history[0] if history else None
        rows.append({
            "id": asset["id"], "name": asset.get("name"),
            "category": asset.get("category"), "unit": asset.get("unit"),
            "stock_qty": asset.get("stock_qty"),
            "location": asset.get("storage_location") or "",
            "unit_cost": asset.get("unit_cost"),
            "log_count": len(history),
            "last_type": last.get("type") if last else "",
            "last_done": last.get("performed_on") if last else "",
            "next_due": last.get("next_due") if last else "",
            "status": last.get("status") if last else "No record",
            "badge": services.MAINTENANCE_BADGE.get(
                last.get("status") if last else "", "badge-muted"),
        })
    rows.sort(key=lambda r: (r["next_due"] or "9999", r["name"] or ""))

    due = services.maintenance_due()
    stats = {
        "asset_count": len([r for r in rows if r["category"] == "asset"]),
        "cleaning_count": len([r for r in rows if r["category"] == "cleaning"]),
        "due_count": len(due),
        "overdue_count": len([d for d in due if d["overdue"]]),
        "spend": round(sum(services._to_float(l.get("cost")) for l in logs), 2),
    }
    return render_template("assets/index.html", rows=rows, stats=stats, due=due)


@assets_bp.route("/maintenance", methods=["GET", "POST"])
@module_required("assets")
def maintenance():
    if request.method == "POST":
        log, err = services.record_maintenance(
            request.form.get("asset_id"), request.form.get("type") or "",
            request.form.get("performed_on") or "",
            request.form.get("performed_by") or "",
            request.form.get("status") or "",
            cost=request.form.get("cost") or 0,
            next_due=request.form.get("next_due") or "",
            downtime_hours=request.form.get("downtime_hours") or 0,
            notes=request.form.get("notes") or "",
            user_id=current_user()["id"])
        if err:
            flash(err, "error")
        else:
            flash("%s logged for %s." % (log.get("type"), log.get("asset_name")),
                  "success")
        return redirect(url_for("assets.maintenance"))

    asset_id = request.args.get("asset_id")
    logs = sorted(db.read("maintenance_logs"),
                  key=lambda l: l.get("performed_on", ""), reverse=True)
    if asset_id:
        try:
            logs = [l for l in logs if l.get("asset_id") == int(asset_id)]
        except ValueError:
            pass
    rows = [{
        "id": l["id"], "asset_name": l.get("asset_name"), "type": l.get("type"),
        "performed_on": l.get("performed_on"),
        "performed_by": l.get("performed_by"), "cost": l.get("cost"),
        "next_due": l.get("next_due"), "status": l.get("status"),
        "badge": services.MAINTENANCE_BADGE.get(l.get("status"), "badge-muted"),
        "downtime_hours": l.get("downtime_hours"), "notes": l.get("notes"),
        "recorded_by": services.user_name(l.get("recorded_by")),
        "created_at": services.fmt_dt(l.get("created_at")),
    } for l in logs]

    return render_template("assets/maintenance.html", rows=rows,
                           assets=_assets(), types=services.MAINTENANCE_TYPES,
                           statuses=services.MAINTENANCE_STATUS,
                           today=services.today_iso(), asset_id=asset_id)


@assets_bp.route("/<int:asset_id>")
@module_required("assets")
def detail(asset_id):
    asset = db.get("raw_materials", asset_id)
    if not asset or asset.get("category") not in ASSET_CATEGORIES:
        abort(404)
    logs = sorted(db.query("maintenance_logs", asset_id=asset_id),
                  key=lambda l: l.get("performed_on", ""), reverse=True)
    return render_template("assets/detail.html", asset=asset, logs=logs,
                           badges=services.MAINTENANCE_BADGE,
                           spend=round(sum(services._to_float(l.get("cost"))
                                           for l in logs), 2))
