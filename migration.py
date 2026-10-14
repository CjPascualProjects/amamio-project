"""MySQL migration blueprint (Super Admin only).

Shows the relational shape of the JSON store and hands over ready-to-run
``schema.sql`` / ``data.sql`` files, so moving the system onto a MySQL server
never needs a developer on site.
"""
from flask import Blueprint, Response, render_template, request

import db
import mysql_export
from security import module_required

migration_bp = Blueprint("migration", __name__)


@migration_bp.route("/")
@module_required("migration")
def index():
    rows_by_table = mysql_export.collect_rows()
    tables = []
    for name in mysql_export._ordered_tables():
        spec = db.SCHEMA[name]
        tables.append({
            "name": name,
            "columns": len(spec["columns"]),
            "rows": len(rows_by_table.get(name, [])),
            "embedded": name not in db.COLLECTIONS,
            "links": ", ".join(sorted(set(spec.get("foreign_keys", {}).values()))),
        })
    return render_template("migration/index.html", tables=tables,
                           database=mysql_export.DATABASE_NAME,
                           total_rows=sum(t["rows"] for t in tables))


@migration_bp.route("/download/<kind>")
@module_required("migration")
def download(kind):
    database = (request.args.get("database")
                or mysql_export.DATABASE_NAME).strip() or \
        mysql_export.DATABASE_NAME
    if kind == "schema":
        body, filename = mysql_export.build_schema_sql(database), "schema.sql"
    elif kind == "data":
        body, filename = mysql_export.build_data_sql(database), "data.sql"
    else:
        return Response("Unknown export.", status=404, mimetype="text/plain")
    return Response(body, mimetype="application/sql", headers={
        "Content-Disposition": 'attachment; filename="%s"' % filename,
    })
