"""Sales-platform monitoring blueprint.

Operators drop a marketplace export into the ``sales-platform/`` folder (or
upload it here), pick the template that matches its layout, confirm the column
mapping and import.  Imported rows feed the platform reports and the
consolidated sales view.
"""
import os

from flask import (Blueprint, abort, flash, redirect, render_template, request,
                   url_for)
from werkzeug.utils import secure_filename

import db
import platform_service as ps
import services
from security import current_user, module_required

platforms_bp = Blueprint("platforms", __name__)

ALLOWED_EXT = (".xlsx", ".xlsm")


def _int_arg(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


@platforms_bp.route("/")
@module_required("platforms")
def index():
    date_from = request.args.get("from") or ""
    date_to = request.args.get("to") or ""
    platform = request.args.get("platform") or ""
    rows = ps.sales_rows(platform or None, date_from, date_to)
    summary, totals = ps.platform_summary(rows)
    imports = sorted(db.read("platform_imports"),
                     key=lambda i: i.get("imported_at", ""), reverse=True)[:10]
    import_rows = [{
        "id": i["id"], "platform": i.get("platform"),
        "filename": i.get("filename"),
        "rows_imported": i.get("rows_imported"),
        "duplicates": i.get("duplicates"), "net_amount": i.get("net_amount"),
        "period_from": i.get("period_from"), "period_to": i.get("period_to"),
        "imported_by": services.user_name(i.get("imported_by")),
        "imported_at": services.fmt_dt(i.get("imported_at")),
    } for i in imports]

    return render_template(
        "platforms/index.html", summary=summary, totals=totals,
        recent=rows, imports=import_rows,
        top=ps.top_products(rows), series=ps.daily_series(rows),
        platforms=ps.PLATFORMS, platform=platform,
        date_from=date_from, date_to=date_to, row_count=len(rows))


@platforms_bp.route("/import", methods=["GET", "POST"])
@module_required("platforms")
def import_file():
    templates = ps.all_templates(active_only=True)

    if request.method == "POST":
        action = request.form.get("action") or "preview"
        template_id = _int_arg(request.form.get("template_id"))
        source = request.form.get("source") or "folder"
        filename = request.form.get("filename") or ""

        # An uploaded file is saved into sales-platform/ so the folder stays
        # the single place every export lives.
        upload = request.files.get("workbook")
        if source == "upload" and upload and upload.filename:
            safe = secure_filename(upload.filename)
            if not safe.lower().endswith(ALLOWED_EXT):
                flash("Only .xlsx / .xlsm workbooks can be imported.", "error")
                return redirect(url_for("platforms.import_file"))
            os.makedirs(ps.UPLOAD_DIR, exist_ok=True)
            upload.save(os.path.join(ps.UPLOAD_DIR, safe))
            filename = safe
            flash("Saved %s into the sales-platform folder." % safe, "success")

        path = ps.safe_upload_path(filename)
        if not path or not os.path.isfile(path):
            flash("Choose a workbook from the folder, or upload one.", "error")
            return redirect(url_for("platforms.import_file"))

        template = ps.get_template(template_id)
        if not template:
            flash("Choose the template that matches this export.", "error")
            return redirect(url_for("platforms.import_file"))

        sheet_index = _int_arg(request.form.get("sheet_index"),
                               template.get("sheet_index") or 0)
        header_row = _int_arg(request.form.get("header_row"),
                              template.get("header_row") or 0)

        if action == "import":
            record, err = ps.import_file(
                path, template_id, current_user()["id"], filename=filename,
                skip_duplicates=request.form.get("skip_duplicates") == "1")
            if err:
                flash(err, "error")
                return redirect(url_for("platforms.import_file"))
            flash("%s: %s" % (record.get("filename"), record.get("message")),
                  "success")
            return redirect(url_for("platforms.index",
                                    platform=record.get("platform")))

        preview, err = ps.preview_file(path, sheet_index, header_row)
        if err:
            flash(err, "error")
            return redirect(url_for("platforms.import_file"))
        return render_template(
            "platforms/import.html", templates=templates, files=ps.folder_files(),
            preview=preview, selected=template, filename=filename,
            fields=ps.CANONICAL_FIELDS, upload_dir=ps.UPLOAD_DIR)

    return render_template("platforms/import.html", templates=templates,
                           files=ps.folder_files(), preview=None, selected=None,
                           filename="", fields=ps.CANONICAL_FIELDS,
                           upload_dir=ps.UPLOAD_DIR)


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
            preview, err = ps.preview_file(path)
            if preview:
                columns = preview["headers"]

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


@platforms_bp.route("/imports/<int:import_id>/delete", methods=["POST"])
@module_required("platforms")
def import_delete(import_id):
    ok, message = ps.delete_import(import_id)
    flash(message, "success" if ok else "error")
    return redirect(url_for("platforms.index"))
