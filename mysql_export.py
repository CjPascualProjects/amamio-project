"""Turn the JSON store into a MySQL database.

JSON files keep the prototype easy to run, but the client will eventually want
a real server.  ``db.SCHEMA`` already declares every collection as a proper
table — this module renders that declaration as:

* ``schema.sql`` — ``CREATE TABLE`` for every table, with primary keys,
  foreign keys and indexes, and
* ``data.sql``   — ``INSERT`` statements for everything currently in ``data/``.

Embedded child lists (an order's ``items``, a production run's
``materials_used``) are flattened into their own tables, so the result is
normalised rather than a JSON blob dump.

From the command line::

    python mysql_export.py                 # writes export/schema.sql + data.sql
    python mysql_export.py --out build/    # choose the output folder

Then, on the server::

    mysql -u root -p -e "CREATE DATABASE amamio CHARACTER SET utf8mb4"
    mysql -u root -p amamio < schema.sql
    mysql -u root -p amamio < data.sql
"""
import argparse
import datetime
import json
import os
import re

import db

DATABASE_NAME = "amamio_ims"
ENGINE = "ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"

# Child tables need a foreign key back to their parent; the column is named
# <parent_singular>_id and is declared in SCHEMA alongside the other columns.
_PARENT_FK = {
    "sales_order_items": ("sales_orders", "sales_order_id"),
    "purchase_request_items": ("purchase_requests", "purchase_request_id"),
    "production_materials": ("production_orders", "production_order_id"),
    "packing_items": ("packing_runs", "packing_run_id"),
}


# --- Value rendering -------------------------------------------------------
def quote(value):
    """Render a Python value as a MySQL literal."""
    if value is None or value == "":
        return "NULL"
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float)):
        return repr(value)
    text = str(value)
    text = (text.replace("\\", "\\\\").replace("'", "\\'")
                .replace("\n", "\\n").replace("\r", "\\r")
                .replace("\x1a", "\\Z"))
    return "'%s'" % text


def _as_bool(value):
    return 1 if value in (True, 1, "1", "true", "True", "yes") else 0


def _as_number(value):
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return int(number) if number == int(number) else number


_ISO_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")


def _as_datetime(value):
    """ISO-8601 (with or without timezone) -> 'YYYY-MM-DD HH:MM:SS'."""
    if not value:
        return None
    text = str(value).strip()
    if not _ISO_RE.match(text):
        return None
    text = text.replace("T", " ")
    # Drop any timezone suffix MySQL DATETIME cannot store.
    text = re.sub(r"(?:Z|[+-]\d{2}:?\d{2})$", "", text).strip()
    text = text.split(".")[0]
    if len(text) == 10:
        return text + " 00:00:00"
    if len(text) == 16:
        return text + ":00"
    return text[:19]


def _as_date(value):
    if not value:
        return None
    text = str(value).strip()[:10]
    return text if _ISO_RE.match(text) else None


def convert(column_type, value):
    """Coerce a JSON value to something the declared SQL type accepts."""
    if column_type.startswith("TINYINT(1)"):
        return _as_bool(value)
    if column_type.startswith(("DECIMAL", "INT")):
        return _as_number(value)
    if column_type.startswith("DATETIME"):
        return _as_datetime(value)
    if column_type.startswith("DATE"):
        return _as_date(value)
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return value


# --- DDL -------------------------------------------------------------------
def _table_ddl(table, spec):
    lines = []
    for column, ctype in spec["columns"].items():
        if column == "id":
            lines.append("  `id` INT UNSIGNED NOT NULL AUTO_INCREMENT")
        else:
            lines.append("  `%s` %s" % (column, ctype))
    lines.append("  PRIMARY KEY (`id`)")
    for column in spec.get("unique", []):
        lines.append("  UNIQUE KEY `uq_%s_%s` (`%s`)" % (table, column, column))

    parent = _PARENT_FK.get(table)
    foreign = dict(spec.get("foreign_keys", {}))
    if parent and parent[1] in spec["columns"]:
        foreign.setdefault(parent[1], parent[0])
    for column, target in foreign.items():
        if column not in spec["columns"] or target not in db.SCHEMA:
            continue
        lines.append("  KEY `ix_%s_%s` (`%s`)" % (table, column, column))
        lines.append(
            "  CONSTRAINT `fk_%s_%s` FOREIGN KEY (`%s`) REFERENCES `%s` (`id`) "
            "ON DELETE %s" % (table, column, column, target,
                              "CASCADE" if parent and column == parent[1]
                              else "SET NULL"))
    return "CREATE TABLE `%s` (\n%s\n) %s;" % (table, ",\n".join(lines), ENGINE)


def _ordered_tables():
    """Parents before children so foreign keys resolve on import."""
    remaining = dict(db.SCHEMA)
    ordered, guard = [], 0
    while remaining and guard < 100:
        guard += 1
        for table in list(remaining):
            spec = remaining[table]
            deps = set(spec.get("foreign_keys", {}).values())
            parent = _PARENT_FK.get(table)
            if parent:
                deps.add(parent[0])
            deps.discard(table)
            if deps <= set(ordered):
                ordered.append(table)
                del remaining[table]
    ordered.extend(remaining)       # cycles (if any) land at the end
    return ordered


def build_schema_sql(database=DATABASE_NAME):
    out = [
        "-- Amamio Farm Products — Sales & Inventory Management System",
        "-- MySQL schema generated from db.SCHEMA on %s."
        % datetime.date.today().isoformat(),
        "-- Mirrors the JSON collections in data/ one-for-one.",
        "",
        "CREATE DATABASE IF NOT EXISTS `%s`" % database,
        "  CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;",
        "USE `%s`;" % database,
        "",
        "SET FOREIGN_KEY_CHECKS = 0;",
        "",
    ]
    tables = _ordered_tables()
    for table in reversed(tables):
        out.append("DROP TABLE IF EXISTS `%s`;" % table)
    out.append("")
    for table in tables:
        out.append(_table_ddl(table, db.SCHEMA[table]))
        out.append("")
    out.append("SET FOREIGN_KEY_CHECKS = 1;")
    return "\n".join(out) + "\n"


# --- Data ------------------------------------------------------------------
def _insert_statements(table, rows, spec):
    if not rows:
        return []
    columns = list(spec["columns"])
    statements = ["-- %s (%d row%s)"
                  % (table, len(rows), "" if len(rows) == 1 else "s")]
    # Batch inserts keep the dump small and the import fast.
    for start in range(0, len(rows), 200):
        chunk = rows[start:start + 200]
        values = []
        for row in chunk:
            rendered = [quote(convert(spec["columns"][c], row.get(c)))
                        for c in columns]
            values.append("  (%s)" % ", ".join(rendered))
        statements.append(
            "INSERT INTO `%s` (%s) VALUES\n%s;"
            % (table, ", ".join("`%s`" % c for c in columns),
               ",\n".join(values)))
    statements.append("")
    return statements


def collect_rows():
    """{table: [row, ...]} with embedded child lists split into their tables."""
    tables = {name: [] for name in db.SCHEMA}
    child_counters = {}

    for collection in db.COLLECTIONS:
        spec = db.SCHEMA[collection]
        children = spec.get("children", {})
        for record in db.read(collection):
            parent = {k: v for k, v in record.items() if k not in children}
            tables[collection].append(parent)
            for field, child_table in children.items():
                fk_column = _PARENT_FK.get(child_table, (None, None))[1]
                for item in (record.get(field) or []):
                    if not isinstance(item, dict):
                        continue
                    child = dict(item)
                    counter = child_counters.get(child_table, 0) + 1
                    child_counters[child_table] = counter
                    child["id"] = counter
                    if fk_column:
                        child[fk_column] = record.get("id")
                    tables[child_table].append(child)
    return tables


def build_data_sql(database=DATABASE_NAME):
    rows_by_table = collect_rows()
    out = [
        "-- Amamio Farm Products data dump generated on %s."
        % datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "USE `%s`;" % database,
        "SET FOREIGN_KEY_CHECKS = 0;",
        "SET NAMES utf8mb4;",
        "",
    ]
    total = 0
    for table in _ordered_tables():
        rows = rows_by_table.get(table, [])
        total += len(rows)
        out.extend(_insert_statements(table, rows, db.SCHEMA[table]))
    out.append("SET FOREIGN_KEY_CHECKS = 1;")
    out.append("-- %d row(s) in total." % total)
    return "\n".join(out) + "\n"


def export(out_dir, database=DATABASE_NAME):
    """Write schema.sql + data.sql and return a small summary dict."""
    os.makedirs(out_dir, exist_ok=True)
    schema_sql = build_schema_sql(database)
    data_sql = build_data_sql(database)
    schema_path = os.path.join(out_dir, "schema.sql")
    data_path = os.path.join(out_dir, "data.sql")
    with open(schema_path, "w", encoding="utf-8") as f:
        f.write(schema_sql)
    with open(data_path, "w", encoding="utf-8") as f:
        f.write(data_sql)
    rows_by_table = collect_rows()
    return {
        "schema_path": schema_path,
        "data_path": data_path,
        "database": database,
        "table_count": len(db.SCHEMA),
        "row_count": sum(len(r) for r in rows_by_table.values()),
        "tables": sorted(((t, len(r)) for t, r in rows_by_table.items()),
                         key=lambda x: x[0]),
    }


def main():
    parser = argparse.ArgumentParser(
        description="Export the JSON store as MySQL schema + data.")
    parser.add_argument("--out", default=os.path.join(db.BASE_DIR, "export"),
                        help="output folder (default: ./export)")
    parser.add_argument("--database", default=DATABASE_NAME,
                        help="target database name")
    args = parser.parse_args()
    result = export(args.out, args.database)
    print("Wrote %s" % result["schema_path"])
    print("Wrote %s" % result["data_path"])
    print("%d tables, %d rows." % (result["table_count"], result["row_count"]))


if __name__ == "__main__":
    main()
