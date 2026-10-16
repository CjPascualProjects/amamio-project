"""Module 5 — sales uploads and sales reports.

Uploading is a short flow: pick the platform, choose the exported file, check
the preview, confirm.  The report then answers "how much did we sell, where,
and when" — daily, weekly, monthly or yearly, per platform, per product —
one view at a time.
"""
import os
from datetime import datetime

from flask import (Blueprint, Response, abort, flash, redirect, render_template,
                   request, url_for)
from werkzeug.utils import secure_filename

import charts
import db
import platform_service as ps
import services
from security import current_user, module_required

platforms_bp = Blueprint("platforms", __name__)

VIEWS = [("overview", "Overview"), ("periods", "By period"),
         ("products", "Products"), ("orders", "Orders"), ("uploads", "Uploads")]
RANGES = [("week", "This week"), ("month", "This month"),
          ("last_month", "Last month"), ("90d", "Last 90 days"),
          ("year", "This year"), ("all", "All time")]


def _int_arg(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _filters():
    """Read the report filter from the query string."""
    grain = request.args.get("grain") or "week"
    if grain not in dict(ps.GRAINS):
        grain = "week"
    preset = request.args.get("range") or ""
    date_from = request.args.get("from") or ""
    date_to = request.args.get("to") or ""
    if preset and preset != "custom":
        date_from, date_to, label = ps.range_for(preset)
    elif date_from or date_to:
        preset, label = "custom", "%s – %s" % (date_from or "…", date_to or "…")
    else:
        preset, label = "all", "All time"
    platform = request.args.get("platform") or ""
    if platform not in ps.PLATFORMS:
        platform = ""
    return {"grain": grain, "range": preset, "from": date_from, "to": date_to,
            "range_label": label, "platform": platform}


def _import_rows():
    imports = sorted(db.read("platform_imports"),
                     key=lambda i: i.get("imported_at", ""), reverse=True)
    return [{
        "id": i["id"], "platform": i.get("platform"),
        "filename": i.get("filename"), "rows_imported": i.get("rows_imported"),
        "duplicates": i.get("duplicates"), "net_amount": i.get("net_amount"),
        "period_from": i.get("period_from"), "period_to": i.get("period_to"),
        "message": i.get("message"), "status": i.get("status"),
        "imported_by": services.user_name(i.get("imported_by")),
        "imported_at": services.fmt_dt(i.get("imported_at")),
    } for i in imports]


@platforms_bp.route("/")
@module_required("platforms")
def index():
    f = _filters()
    view = request.args.get("view") or "overview"
    if view not in dict(VIEWS):
        view = "overview"
    report = ps.sales_report(f["platform"], f["from"], f["to"], f["grain"])
    series = [p for p in ps.PLATFORMS if p in report["present"]]
    chart = charts.stacked_columns(report["periods"][-36:], series,
                                   ps.PLATFORM_COLORS)
    platform_bars = charts.hbars(report["platforms"], "platform", "net",
                                 color_key="color")
    product_bars = charts.hbars(report["products"], "name", "net", limit=8,
                                wide_labels=True)

    orders = report["rows"]
    status = request.args.get("status") or ""
    if view == "orders" and status:
        orders = [r for r in orders if ps._group_of(r) == status]
    query = (request.args.get("q") or "").strip().lower()
    if view == "orders" and query:
        orders = [r for r in orders
                  if query in " ".join(str(r.get(k) or "") for k in
                                       ("order_ref", "product_name", "buyer_name",
                                        "region", "variation")).lower()]

    def link(**changes):
        args = {"view": view, "grain": f["grain"], "range": f["range"],
                "platform": f["platform"]}
        if f["range"] == "custom":
            args.update({"from": f["from"], "to": f["to"]})
        args.update(changes)
        return url_for("platforms.index",
                       **{k: v for k, v in args.items() if v})

    export_args = {"grain": f["grain"], "range": f["range"],
                   "platform": f["platform"]}
    if f["range"] == "custom":
        export_args.update({"from": f["from"], "to": f["to"]})

    return render_template(
        "platforms/index.html",
        export_url=url_for("platforms.export_csv",
                           **{k: v for k, v in export_args.items() if v}),
        **_index_context(f, view, report, series, chart, platform_bars,
                         product_bars, orders, status, link))


def _index_context(f, view, report, series, chart, platform_bars, product_bars,
                   orders, status, link):
    return dict(
        f=f, view=view, views=VIEWS, ranges=RANGES,
        grains=ps.GRAINS, platforms=ps.PLATFORMS, colors=ps.PLATFORM_COLORS,
        report=report, series=series, chart=chart,
        platform_bars=platform_bars, product_bars=product_bars,
        orders=orders[:300], order_count=len(orders), status=status,
        status_groups=ps.STATUS_GROUPS, q=request.args.get("q") or "",
        imports=_import_rows() if view == "uploads" else [],
        has_data=bool(db.read("platform_sales")), link=link,
        group_of=ps._group_of)


@platforms_bp.route("/export.csv")
@module_required("platforms")
def export_csv():
    f = _filters()
    report = ps.sales_report(f["platform"], f["from"], f["to"], f["grain"])
    name = "amamio-sales-%s-%s.csv" % (f["grain"], datetime.now().strftime("%Y%m%d"))
    # Excel opens UTF-8 CSV correctly when it starts with a BOM.
    return Response("\ufeff" + ps.report_csv(report, f["grain"]),
                    mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=%s" % name})


# --- Upload flow ---------------------------------------------------------------
@platforms_bp.route("/upload", methods=["GET", "POST"])
@module_required("platforms")
def upload():
    if request.method == "POST":
        platform = request.form.get("platform") or ""
        source = request.form.get("source") or "upload"
        filename = ""
        if source == "folder":
            filename = os.path.basename(request.form.get("filename") or "")
        else:
            upload_file = request.files.get("workbook")
            if not upload_file or not upload_file.filename:
                flash("Choose the exported file to upload.", "error")
                return redirect(url_for("platforms.upload", platform=platform))
            safe = secure_filename(upload_file.filename)
            if not safe.lower().endswith(ps.ALLOWED_EXT):
                flash("Only Excel (.xlsx) or CSV files can be uploaded.", "error")
                return redirect(url_for("platforms.upload", platform=platform))
            os.makedirs(ps.UPLOAD_DIR, exist_ok=True)
            stem, ext = os.path.splitext(safe)
            safe = "%s-%s%s" % (stem, datetime.now().strftime("%Y%m%d-%H%M%S"), ext)
            upload_file.save(os.path.join(ps.UPLOAD_DIR, safe))
            filename = safe
        path = ps.safe_upload_path(filename)
        if not path or not os.path.isfile(path):
            flash("That file could not be found.", "error")
            return redirect(url_for("platforms.upload", platform=platform))
        return redirect(url_for("platforms.preview", file=filename,
                                platform=platform))

    return render_template("platforms/upload.html", platforms=ps.PLATFORMS,
                           colors=ps.PLATFORM_COLORS, files=ps.folder_files(),
                           chosen=request.args.get("platform") or "")


@platforms_bp.route("/upload/preview", methods=["GET", "POST"])
@module_required("platforms")
def preview():
    filename = os.path.basename(request.values.get("file") or "")
    path = ps.safe_upload_path(filename)
    if not path or not os.path.isfile(path):
        flash("That file could not be found — upload it again.", "error")
        return redirect(url_for("platforms.upload"))
    platform = request.values.get("platform") or ""

    if request.method == "POST":
        record, err = ps.import_file(path, _int_arg(request.form.get("template_id")),
                                     current_user()["id"], filename=filename)
        if err:
            flash(err, "error")
            return redirect(url_for("platforms.preview", file=filename,
                                    platform=platform))
        flash("Uploaded. %s" % record.get("message"), "success")
        return redirect(url_for("platforms.upload_detail", import_id=record["id"]))

    first, err = ps.preview_file(path)
    if err:
        flash(err, "error")
        return redirect(url_for("platforms.upload"))
    chosen_id = _int_arg(request.args.get("template_id"))
    template = ps.get_template(chosen_id) if chosen_id else None
    score = None
    if not template:
        template, score = ps.match_template(first["headers"], platform)
    result, err = (ps.dry_run(path, template["id"]) if template
                   else (None, "No upload template fits this file."))
    return render_template(
        "platforms/preview.html", filename=filename, platform=platform,
        template=template, score=score, result=result, error=err,
        templates=ps.all_templates(active_only=True), headers=first["headers"],
        colors=ps.PLATFORM_COLORS,
        product_names={p["id"]: p.get("name") for p in db.read("products")})


@platforms_bp.route("/uploads/<int:import_id>")
@module_required("platforms")
def upload_detail(import_id):
    record = next((r for r in _import_rows() if r["id"] == import_id), None)
    if not record:
        abort(404)
    rows = [r for r in db.read("platform_sales") if r.get("import_id") == import_id]
    counted = [r for r in rows if ps._group_of(r) in ps.COUNTED_GROUPS]
    return render_template("platforms/upload_detail.html", record=record,
                           rows=rows, counted=counted,
                           colors=ps.PLATFORM_COLORS,
                           net=round(sum(services._to_float(r.get("net_amount"))
                                         for r in counted), 2),
                           orders=len({r.get("order_ref") for r in counted}))


@platforms_bp.route("/uploads/<int:import_id>/delete", methods=["POST"])
@module_required("platforms")
def import_delete(import_id):
    ok, message = ps.delete_import(import_id)
    flash(message, "success" if ok else "error")
    return redirect(url_for("platforms.index", view="uploads"))


# Older links (and the template editor) still point here.
@platforms_bp.route("/import", methods=["GET", "POST"])
@module_required("platforms")
def import_file():
    return redirect(url_for("platforms.upload"))


# --- Column-mapping templates (advanced) -----------------------------------------
@platforms_bp.route("/templates", methods=["GET", "POST"])
@module_required("platforms")
def template_list():
    if request.method == "POST":
        mapping = {key: request.form.get("map_" + key) or ""
                   for key in ps.FIELD_KEYS}
        template, err = ps.save_template(
            request.form.get("name") or "", request.form.get("platform") or "",
            mapping, sheet_index=request.form.get("sheet_index") or 0,
            header_row=request.form.get("header_row") or 0,
            notes=request.form.get("notes") or "",
            template_id=_int_arg(request.form.get("template_id")) or None,
            active=request.form.get("active") != "0")
        if err:
            flash(err, "error")
        else:
            flash("Template '%s' saved." % template.get("name"), "success")
        return redirect(url_for("platforms.template_list"))

    edit_id = _int_arg(request.args.get("edit"))
    columns = []
    sample_file = request.args.get("columns_from") or ""
    if sample_file:
        path = ps.safe_upload_path(sample_file)
        if path and os.path.isfile(path):
            preview_data, err = ps.preview_file(path)
            if preview_data:
                columns = preview_data["headers"]

    return render_template("platforms/templates.html",
                           templates=ps.all_templates(),
                           editing=ps.get_template(edit_id) if edit_id else None,
                           fields=ps.CANONICAL_FIELDS, platforms=ps.PLATFORMS,
                           files=ps.folder_files(), columns=columns,
                           columns_from=sample_file)


@platforms_bp.route("/templates/<int:template_id>/delete", methods=["POST"])
@module_required("platforms")
def template_delete(template_id):
    template = db.get("platform_templates", template_id)
    if not template:
        abort(404)
    db.delete("platform_templates", template_id)
    flash("Template '%s' removed." % template.get("name"), "success")
    return redirect(url_for("platforms.template_list"))
