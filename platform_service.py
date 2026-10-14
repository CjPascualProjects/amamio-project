"""Sales-platform monitoring: import any marketplace Excel export.

The client sells on several platforms, each with its own export layout.  Rather
than hard-coding a parser per platform, the system keeps a **generic template**:
a saved mapping from the canonical fields below to whatever the platform calls
its columns.  Dropping a new workbook into ``sales-platform/`` and picking the
matching template is all an operator has to do; adding a brand new marketplace
is a mapping, not a code change.

Canonical fields -> ``platform_sales`` rows, which every report reads from.
"""
import datetime
import json
import os
import re

import db
import services
import xlsx

# Where operators drop their exports.  Lives beside the app folder so the same
# path works from the repo and from an installed copy.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.abspath(os.path.join(BASE_DIR, "..", "sales-platform"))

PLATFORMS = ["Shopee", "TikTok", "Lazada", "VIP", "Walk-in", "Other"]

# (key, label, required, kind)  — kind drives parsing: text / number / money / date
CANONICAL_FIELDS = [
    ("order_ref",     "Order reference",   True,  "text"),
    ("order_date",    "Order date",        False, "date"),
    ("sku",           "Seller SKU",        False, "text"),
    ("product_name",  "Product name",      False, "text"),
    ("variation",     "Variation",         False, "text"),
    ("qty",           "Quantity",          False, "number"),
    ("unit_price",    "Unit price",        False, "money"),
    ("gross_amount",  "Gross amount",      False, "money"),
    ("discount",      "Discount",          False, "money"),
    ("shipping_fee",  "Shipping fee",      False, "money"),
    ("net_amount",    "Net / paid amount", False, "money"),
    ("order_status",  "Order status",      False, "text"),
    ("buyer_name",    "Buyer",             False, "text"),
    ("region",        "Region / province", False, "text"),
]
FIELD_KEYS = [f[0] for f in CANONICAL_FIELDS]
FIELD_LABELS = {f[0]: f[1] for f in CANONICAL_FIELDS}
FIELD_KINDS = {f[0]: f[3] for f in CANONICAL_FIELDS}

# Built-in templates matching the exports the client supplied.  They are seeded
# into ``platform_templates`` on first run and are editable in the UI.
BUILTIN_TEMPLATES = [
    {
        "platform": "Shopee",
        "name": "Shopee — Orders export",
        "sheet_index": 0,
        "header_row": 0,
        "notes": "Shopee Seller Centre > Orders > Export. One row per product "
                 "line; orders with several products repeat the Order ID.",
        "mapping": {
            "order_ref": "Order ID",
            "order_date": "Order Creation Date",
            "sku": "SKU Reference No.",
            "product_name": "Product Name",
            "variation": "Variation Name",
            "qty": "Quantity",
            "unit_price": "Deal Price",
            "gross_amount": "Product Subtotal",
            "discount": "Total Discount(PHP)",
            "shipping_fee": "Buyer Paid Shipping Fee",
            "net_amount": "Grand Total",
            "order_status": "Order Status",
            "buyer_name": "Username (Buyer)",
            "region": "Province",
        },
    },
    {
        "platform": "Lazada",
        "name": "Lazada — Orders export",
        "sheet_index": 0,
        "header_row": 0,
        "notes": "Lazada Seller Center > Orders > Export. One row per order "
                 "item; paidPrice already includes the shipping fee.",
        "mapping": {
            "order_ref": "orderNumber",
            "order_date": "createTime",
            "sku": "sellerSku",
            "product_name": "itemName",
            "variation": "variation",
            "qty": "",
            "unit_price": "unitPrice",
            "gross_amount": "unitPrice",
            "discount": "sellerDiscountTotal",
            "shipping_fee": "shippingFee",
            "net_amount": "paidPrice",
            "order_status": "status",
            "buyer_name": "customerName",
            "region": "shippingCity",
        },
    },
    {
        "platform": "TikTok",
        "name": "TikTok Shop — Order details (settlement)",
        "sheet_index": 0,
        "header_row": 0,
        "notes": "TikTok Shop > Finance > Settlements > Order details. This "
                 "export is settlement-level: it carries revenue per order but "
                 "no SKU or quantity, so quantity defaults to 1 per order.",
        "mapping": {
            "order_ref": "Order/Adjustment ID",
            "order_date": "Order created time",
            "sku": "",
            "product_name": "",
            "variation": "",
            "qty": "",
            "unit_price": "",
            "gross_amount": "Total Revenue",
            "discount": "Seller discounts",
            "shipping_fee": "Customer shipping fee",
            "net_amount": "Total settlement amount",
            "order_status": "Transaction type",
            "buyer_name": "",
            "region": "",
        },
    },
    {
        "platform": "Other",
        "name": "Generic — blank template",
        "sheet_index": 0,
        "header_row": 0,
        "notes": "Start here for a new marketplace: upload the file, then pick "
                 "which of its columns feeds each field below.",
        "mapping": {key: "" for key in FIELD_KEYS},
    },
]


# --- Template storage ------------------------------------------------------
def _decode_mapping(template):
    raw = template.get("mapping_json") or "{}"
    try:
        mapping = json.loads(raw)
    except (ValueError, TypeError):
        mapping = {}
    return {key: (mapping.get(key) or "") for key in FIELD_KEYS}


def template_view(template):
    """A template dict with its mapping decoded, ready for templates/UI."""
    view = dict(template)
    view["mapping"] = _decode_mapping(template)
    view["mapped_count"] = sum(1 for v in view["mapping"].values() if v)
    return view


def all_templates(platform=None, active_only=False):
    rows = db.read("platform_templates")
    if platform:
        rows = [t for t in rows if t.get("platform") == platform]
    if active_only:
        rows = [t for t in rows if t.get("active", True)]
    rows.sort(key=lambda t: (t.get("platform") or "", t.get("name") or ""))
    return [template_view(t) for t in rows]


def get_template(template_id):
    template = db.get("platform_templates", template_id)
    return template_view(template) if template else None


def save_template(name, platform, mapping, sheet_index=0, header_row=0,
                  notes="", template_id=None, active=True):
    if not (name or "").strip():
        return None, "Give the template a name."
    if platform not in PLATFORMS:
        return None, "Choose a platform."
    clean = {key: (mapping.get(key) or "").strip() for key in FIELD_KEYS}
    if not clean.get("order_ref"):
        return None, "Map the order reference column — it identifies each sale."
    payload = {
        "platform": platform,
        "name": name.strip(),
        "sheet_index": max(0, int(sheet_index or 0)),
        "header_row": max(0, int(header_row or 0)),
        "date_format": "auto",
        "active": bool(active),
        "mapping_json": json.dumps(clean, ensure_ascii=False),
        "notes": (notes or "").strip(),
        "updated_at": services.now_iso(),
    }
    if template_id:
        existing = db.get("platform_templates", template_id)
        if not existing:
            return None, "Template not found."
        return template_view(db.update("platform_templates", template_id,
                                       payload)), None
    payload["created_at"] = services.now_iso()
    return template_view(db.insert("platform_templates", payload)), None


def seed_builtin_templates():
    """Install the shipped templates once, keeping any operator edits."""
    existing = {(t.get("platform"), t.get("name"))
                for t in db.read("platform_templates")}
    for spec in BUILTIN_TEMPLATES:
        if (spec["platform"], spec["name"]) in existing:
            continue
        db.insert("platform_templates", {
            "platform": spec["platform"],
            "name": spec["name"],
            "sheet_index": spec["sheet_index"],
            "header_row": spec["header_row"],
            "date_format": "auto",
            "active": True,
            "mapping_json": json.dumps(
                {key: spec["mapping"].get(key, "") for key in FIELD_KEYS},
                ensure_ascii=False),
            "notes": spec["notes"],
            "created_at": services.now_iso(),
            "updated_at": services.now_iso(),
        })


# --- Value parsing ---------------------------------------------------------
_NUMBER_RE = re.compile(r"-?\d+(?:[\d,]*\d)?(?:\.\d+)?")
_DATE_PATTERNS = [
    (re.compile(r"^(\d{4})[-/](\d{1,2})[-/](\d{1,2})"), ("y", "m", "d")),
    (re.compile(r"^(\d{1,2})[-/](\d{1,2})[-/](\d{4})"), ("d", "m", "y")),
]
_MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun",
     "jul", "aug", "sep", "oct", "nov", "dec"])}
_TEXT_DATE_RE = re.compile(r"^(\d{1,2})\s+([A-Za-z]{3,})\s+(\d{4})")


def parse_number(value):
    """'1,234.50 PHP' -> 1234.5 ; blanks and junk -> 0.0."""
    if value in (None, ""):
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    match = _NUMBER_RE.search(str(value).replace(",", ""))
    if not match:
        return 0.0
    try:
        return float(match.group(0))
    except ValueError:
        return 0.0


def parse_date(value):
    """Normalise the many date spellings in platform exports to YYYY-MM-DD."""
    text = str(value or "").strip()
    if not text:
        return ""
    match = _TEXT_DATE_RE.match(text)           # '04 Oct 2026 18:58'
    if match:
        month = _MONTHS.get(match.group(2)[:3].lower())
        if month:
            return "%s-%02d-%02d" % (match.group(3), month, int(match.group(1)))
    for pattern, order in _DATE_PATTERNS:       # '2026-10-10', '10/04/2026'
        match = pattern.match(text)
        if not match:
            continue
        parts = dict(zip(order, match.groups()))
        try:
            year, month, day = (int(parts["y"]), int(parts["m"]),
                                int(parts["d"]))
        except (KeyError, ValueError):
            continue
        if 1 <= month <= 12 and 1 <= day <= 31:
            return "%04d-%02d-%02d" % (year, month, day)
    return text[:10]


def _coerce(kind, value):
    if kind == "number":
        return parse_number(value)
    if kind == "money":
        return round(parse_number(value), 2)
    if kind == "date":
        return parse_date(value)
    return str(value or "").strip()


# --- Import ----------------------------------------------------------------
def preview_file(path, sheet_index=0, header_row=None, sample=5):
    """Read headers + a few rows so the operator can confirm the mapping."""
    try:
        sheets = xlsx.sheet_names(path)
        rows = xlsx.read_sheet(path, sheet_index, max_rows=60)
    except xlsx.XlsxError as exc:
        return None, str(exc)
    if not rows:
        return None, "That sheet is empty."
    if header_row is None:
        header_row = xlsx.detect_header_row(rows)
    headers, records = xlsx.read_rows(path, sheet_index, header_row,
                                      max_rows=sample + header_row + 1)
    return {
        "sheets": sheets,
        "sheet_index": sheet_index,
        "header_row": header_row,
        "headers": headers,
        "sample": records[:sample],
    }, None


def _dedupe_key(platform, row):
    return "|".join([
        platform or "",
        str(row.get("order_ref") or "").strip().lower(),
        str(row.get("sku") or "").strip().lower(),
        str(row.get("product_name") or "").strip().lower(),
        str(row.get("variation") or "").strip().lower(),
    ])


def _existing_keys(platform):
    return {_dedupe_key(platform, row)
            for row in db.read("platform_sales")
            if row.get("platform") == platform}


def _match_product(sku, name):
    """Best-effort link to the catalog so platform sales roll up per product."""
    products = db.read("products")
    sku = (sku or "").strip().lower()
    if sku:
        for product in products:
            if (product.get("sku") or "").strip().lower() == sku:
                return product["id"]
    name = (name or "").strip().lower()
    if name:
        for product in products:
            pname = (product.get("name") or "").strip().lower()
            if pname and (pname == name or pname in name):
                return product["id"]
    return None


def import_file(path, template_id, user_id, filename=None, skip_duplicates=True):
    """Parse a workbook through a template and store the canonical rows.

    Returns ``(import_record, None)`` or ``(None, message)``."""
    template = get_template(template_id)
    if not template:
        return None, "Choose an import template."
    if not os.path.isfile(path):
        return None, "That file could not be found."

    platform = template.get("platform")
    mapping = template.get("mapping") or {}
    try:
        headers, records = xlsx.read_rows(path, template.get("sheet_index") or 0,
                                          template.get("header_row") or 0)
    except xlsx.XlsxError as exc:
        return None, str(exc)
    if not records:
        return None, "No data rows were found below the header row."

    missing = [FIELD_LABELS[key] for key in FIELD_KEYS
               if mapping.get(key) and mapping[key] not in headers]
    if missing:
        return None, ("This file does not match the template — missing "
                      "column(s) for: %s." % ", ".join(missing))

    seen = _existing_keys(platform) if skip_duplicates else set()
    imported, skipped, duplicates = [], 0, 0
    gross_total = net_total = 0.0
    dates = []

    for index, record in enumerate(records, start=1):
        row = {}
        for key in FIELD_KEYS:
            column = mapping.get(key)
            row[key] = _coerce(FIELD_KINDS[key],
                               record.get(column, "") if column else "")
        if not row.get("order_ref"):
            skipped += 1
            continue

        key = _dedupe_key(platform, row)
        if skip_duplicates and key in seen:
            duplicates += 1
            continue
        seen.add(key)

        # Sensible fall-backs so every row carries usable money and quantity.
        if row["qty"] <= 0:
            row["qty"] = 1.0
        if row["gross_amount"] <= 0 and row["unit_price"] > 0:
            row["gross_amount"] = round(row["unit_price"] * row["qty"], 2)
        if row["unit_price"] <= 0 and row["qty"]:
            row["unit_price"] = round(row["gross_amount"] / row["qty"], 2)
        if row["net_amount"] == 0:
            row["net_amount"] = round(row["gross_amount"] - row["discount"], 2)

        gross_total += row["gross_amount"]
        net_total += row["net_amount"]
        if row["order_date"]:
            dates.append(row["order_date"])

        row.update({
            "platform": platform,
            "import_id": None,
            "order_line": "",
            "product_id": _match_product(row.get("sku"),
                                         row.get("product_name")),
            "row_no": index,
            "created_at": services.now_iso(),
        })
        imported.append(row)

    record = db.insert("platform_imports", {
        "platform": platform,
        "template_id": template["id"],
        "filename": filename or os.path.basename(path),
        "rows_read": len(records),
        "rows_imported": len(imported),
        "rows_skipped": skipped,
        "duplicates": duplicates,
        "gross_amount": round(gross_total, 2),
        "net_amount": round(net_total, 2),
        "period_from": min(dates) if dates else "",
        "period_to": max(dates) if dates else "",
        "status": "Imported" if imported else "Nothing imported",
        "message": "",
        "imported_by": user_id,
        "imported_at": services.now_iso(),
    })
    for row in imported:
        row["import_id"] = record["id"]
    db.insert_many("platform_sales", imported)

    record = db.update("platform_imports", record["id"], {
        "message": ("%d row(s) imported, %d duplicate(s) skipped, %d row(s) "
                    "without an order reference."
                    % (len(imported), duplicates, skipped)),
    })
    return record, None


def delete_import(import_id):
    """Undo one import, removing the sales rows it created."""
    record = db.get("platform_imports", import_id)
    if not record:
        return False, "Import not found."
    kept = [row for row in db.read("platform_sales")
            if row.get("import_id") != int(import_id)]
    db.write("platform_sales", kept)
    db.delete("platform_imports", import_id)
    return True, ("Import of %s removed along with its sales rows."
                  % record.get("filename"))


# --- Folder & reporting ----------------------------------------------------
def folder_files():
    """Workbooks sitting in sales-platform/, newest first."""
    if not os.path.isdir(UPLOAD_DIR):
        return []
    rows = []
    for name in os.listdir(UPLOAD_DIR):
        if name.startswith("~$") or not name.lower().endswith((".xlsx", ".xlsm")):
            continue
        path = os.path.join(UPLOAD_DIR, name)
        try:
            stat = os.stat(path)
        except OSError:
            continue
        rows.append({
            "name": name,
            "size_kb": round(stat.st_size / 1024.0, 1),
            "modified": services.fmt_dt(
                datetime.datetime.fromtimestamp(stat.st_mtime).isoformat()),
        })
    rows.sort(key=lambda r: r["modified"], reverse=True)
    return rows


def safe_upload_path(filename):
    """Resolve a name from the folder listing without escaping the folder."""
    name = os.path.basename(filename or "")
    if not name or name.startswith("~$"):
        return None
    path = os.path.abspath(os.path.join(UPLOAD_DIR, name))
    if os.path.dirname(path) != UPLOAD_DIR:
        return None
    return path


def sales_rows(platform=None, date_from="", date_to="", limit=None):
    rows = db.read("platform_sales")
    if platform:
        rows = [r for r in rows if r.get("platform") == platform]
    if date_from:
        rows = [r for r in rows if (r.get("order_date") or "") >= date_from]
    if date_to:
        rows = [r for r in rows if (r.get("order_date") or "") <= date_to]
    rows.sort(key=lambda r: (r.get("order_date") or "", r.get("id") or 0),
              reverse=True)
    return rows[:limit] if limit else rows


def platform_summary(rows=None):
    """Per-platform totals, plus a grand total, for dashboards and reports."""
    rows = sales_rows() if rows is None else rows
    buckets = {}
    for row in rows:
        bucket = buckets.setdefault(row.get("platform") or "Other", {
            "platform": row.get("platform") or "Other",
            "orders": set(), "qty": 0.0, "gross": 0.0, "net": 0.0, "lines": 0,
        })
        bucket["orders"].add(row.get("order_ref"))
        bucket["qty"] += services._to_float(row.get("qty"))
        bucket["gross"] += services._to_float(row.get("gross_amount"))
        bucket["net"] += services._to_float(row.get("net_amount"))
        bucket["lines"] += 1
    out = []
    for bucket in buckets.values():
        out.append({
            "platform": bucket["platform"],
            "orders": len(bucket["orders"]),
            "lines": bucket["lines"],
            "qty": round(bucket["qty"], 2),
            "gross": round(bucket["gross"], 2),
            "net": round(bucket["net"], 2),
        })
    out.sort(key=lambda r: r["net"], reverse=True)
    totals = {
        "orders": sum(r["orders"] for r in out),
        "lines": sum(r["lines"] for r in out),
        "qty": round(sum(r["qty"] for r in out), 2),
        "gross": round(sum(r["gross"] for r in out), 2),
        "net": round(sum(r["net"] for r in out), 2),
    }
    return out, totals


def top_products(rows=None, limit=10):
    rows = sales_rows() if rows is None else rows
    buckets = {}
    for row in rows:
        name = (row.get("product_name") or row.get("sku") or "").strip()
        if not name:
            continue
        bucket = buckets.setdefault(name, {"name": name, "qty": 0.0,
                                           "net": 0.0, "platforms": set()})
        bucket["qty"] += services._to_float(row.get("qty"))
        bucket["net"] += services._to_float(row.get("net_amount"))
        bucket["platforms"].add(row.get("platform"))
    out = [{"name": b["name"], "qty": round(b["qty"], 2),
            "net": round(b["net"], 2),
            "platforms": ", ".join(sorted(p for p in b["platforms"] if p))}
           for b in buckets.values()]
    out.sort(key=lambda r: r["net"], reverse=True)
    return out[:limit]


def daily_series(rows=None, days=30):
    """[(date, net_amount), ...] oldest first — feeds the trend chart."""
    rows = sales_rows() if rows is None else rows
    buckets = {}
    for row in rows:
        day = (row.get("order_date") or "")[:10]
        if not day:
            continue
        buckets[day] = buckets.get(day, 0.0) + services._to_float(
            row.get("net_amount"))
    series = sorted(buckets.items())
    return series[-days:]
