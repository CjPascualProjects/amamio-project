"""Module 5 — sales-platform uploads and sales analytics.

The client sells on several platforms (Shopee, TikTok Shop, Lazada, Shopify,
plus VIP and walk-in), each with its own export layout.  Rather than
hard-coding a parser per platform, the system keeps a **generic template**: a
saved mapping from the canonical fields below to whatever the platform calls
its columns.  Uploading a new export and confirming the preview is all an
operator has to do; adding a brand new marketplace is a mapping, not a code
change.  Excel (.xlsx) and CSV files are both accepted.

Canonical fields -> ``platform_sales`` rows, which every report reads from.
Re-uploading a newer export of the same orders updates their status and
amounts instead of counting them twice.
"""
import csv
import datetime
import io
import json
import os
import re

import db
import services
import xlsx

# Where uploaded exports are kept: the ``sales-platform`` folder inside the
# project (override with AMAMIO_SALES_DIR, e.g. a shared network folder).
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.abspath(os.environ.get(
    "AMAMIO_SALES_DIR", os.path.join(BASE_DIR, "sales-platform")))
ALLOWED_EXT = (".xlsx", ".xlsm", ".csv")

PLATFORMS = ["Shopee", "TikTok", "Lazada", "Shopify", "VIP", "Walk-in", "Other"]

# One colour per platform, fixed — a platform keeps its colour on every chart
# whatever the filter.  The values are CSS variables so the light and dark
# themes each use steps validated for colour-blind separation on their own
# card surface (see --plat-* in static/css/style.css).
PLATFORM_COLORS = {
    "Shopee": "var(--plat-shopee)", "TikTok": "var(--plat-tiktok)",
    "Lazada": "var(--plat-lazada)", "Shopify": "var(--plat-shopify)",
    "VIP": "var(--plat-vip)", "Walk-in": "var(--plat-walk-in)",
    "Other": "var(--plat-other)",
}

# How each export describes an order's state, folded into five groups.
# Only Completed and In progress count as sales.
STATUS_GROUPS = ["Completed", "In progress", "Cancelled", "Returned",
                 "Adjustment"]
COUNTED_GROUPS = ("Completed", "In progress")
_STATUS_RULES = [
    ("Adjustment", ("withholding", "adjustment", "fee", "tax", "deduction",
                    "subsidy", "reimbursement")),
    ("Returned", ("return", "refund")),
    ("Cancelled", ("cancel", "unpaid", "failed", "void")),
    ("Completed", ("complete", "delivered", "settled", "paid", "fulfilled",
                   "order")),
    ("In progress", ("to ship", "shipped", "shipping", "ready", "pending",
                     "processing", "packed", "unfulfilled", "in transit")),
]


def status_group(order_status):
    text = (order_status or "").strip().lower()
    if not text:
        return "In progress"
    for group, words in _STATUS_RULES:
        if any(w in text for w in words):
            return group
    return "In progress"


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

# Built-in templates matching the exports the client supplied (plus Shopify's
# standard order export).  Seeded once and editable in the UI.
BUILTIN_TEMPLATES = [
    {
        "platform": "Shopee",
        "name": "Shopee — Orders export",
        "sheet_index": 0,
        "header_row": 0,
        "notes": "Shopee Seller Centre > Orders > Export. One row per product "
                 "line; orders with several products repeat the Order ID. "
                 "'Grand Total' is per ORDER (repeated on every line), so the "
                 "line's 'Product Subtotal' is used as its sale amount.",
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
            "net_amount": "Product Subtotal",
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
                 "export is settlement-level: revenue per order but no SKU or "
                 "quantity, so quantity defaults to 1 per order. Tax and fee "
                 "lines count as adjustments, not sales.",
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
        "platform": "Shopify",
        "name": "Shopify — Orders export (CSV)",
        "sheet_index": 0,
        "header_row": 0,
        "notes": "Shopify admin > Orders > Export > CSV. One row per line "
                 "item; order totals appear on the first line only, so the "
                 "net is worked out per line from price, quantity and "
                 "discount.",
        "mapping": {
            "order_ref": "Name",
            "order_date": "Created at",
            "sku": "Lineitem sku",
            "product_name": "Lineitem name",
            "variation": "",
            "qty": "Lineitem quantity",
            "unit_price": "Lineitem price",
            "gross_amount": "",
            "discount": "Lineitem discount",
            "shipping_fee": "",
            "net_amount": "",
            "order_status": "Financial Status",
            "buyer_name": "Billing Name",
            "region": "Shipping Province",
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


# Mappings shipped by earlier versions that turned out to be wrong:
# (platform, template name, field, wrong column, right column).
_TEMPLATE_FIXES = [
    ("Shopee", "Shopee — Orders export", "net_amount", "Grand Total",
     "Product Subtotal"),
]


def seed_builtin_templates():
    """Install the shipped templates once, keeping any operator edits."""
    for platform, name, field, wrong, right in _TEMPLATE_FIXES:
        for t in db.query("platform_templates", platform=platform, name=name):
            mapping = _decode_mapping(t)
            if mapping.get(field) == wrong:
                mapping[field] = right
                db.update("platform_templates", t["id"], {
                    "mapping_json": json.dumps(mapping, ensure_ascii=False),
                    "updated_at": services.now_iso()})
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


def match_template(headers, platform=None):
    """The template whose mapped columns best fit a file's headers.

    Returns ``(template, score)`` where score is the share of the template's
    mapped columns present in the file (0..1)."""
    header_set = set(headers or [])
    best, best_score = None, 0.0
    for template in all_templates(active_only=True):
        mapped = [c for c in template["mapping"].values() if c]
        if not mapped:
            continue
        score = sum(1 for c in mapped if c in header_set) / float(len(set(mapped)))
        if platform and template.get("platform") == platform:
            score += 0.001          # prefer the chosen platform on a tie
        if score > best_score:
            best, best_score = template, score
    return best, min(best_score, 1.0)


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


# --- Linking platform listings to the catalog ------------------------------
# Marketplace titles are free text ("Premium Raw Forest Honey - Pure Dark
# Honey - 100ml - Amamio Mini Honey"), so a listing is matched to a catalog
# family by keywords, then to a size by the first quantity in the variation
# or title.  Order matters: the most specific family comes first.
_FAMILY_KEYWORDS = [
    ("Honey Lemon Ginger Concentrate", ("lemon ginger", "hlgc")),
    ("Honey Calamansi Concentrate", ("calamansi concentrate", "honey calamansi")),
    ("Honey Infused Turmeric Ginger", ("turmeric ginger", "hit ", "hit&", "(hit)")),
    ("Honey Infused Ginger", ("infused ginger", "hig")),
    ("Honey Vinegar", ("vinegar",)),
    ("RFH with Comb", ("comb",)),
    ("Pure Tableya", ("tableya", "tablea")),
    ("Cacao Nibs", ("nibs",)),
    ("Cacao Powder", ("cacao powder", "cocoa powder")),
    ("Pure Corn Coffee", ("corn coffee",)),
    ("Robusta Coffee", ("robusta",)),
    ("Moringa Powder", ("moringa", "malunggay")),
    ("Turmeric Powder", ("turmeric powder",)),
    ("Banana Chips", ("banana",)),
    ("Uriel Liniment Oil", ("liniment", "uriel")),
    ("Pure Honey", ("raw forest honey", "pure honey", "rfh", "honey")),
]
_SIZE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(ml|l|liter|litre|g|kg)\b", re.I)


def _norm(text):
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9.& ()]", " ",
                                       (text or "").lower())).strip()


def _size_key(text):
    """'1 jar of 500ml' -> (500, 'ml'); '1 liter' -> (1000, 'ml')."""
    match = _SIZE_RE.search(text or "")
    if not match:
        if re.search(r"\b(1|one)\s*(liter|litre|l)\b", (text or "").lower()):
            return (1000.0, "ml")
        return None
    amount, unit = float(match.group(1)), match.group(2).lower()
    if unit in ("l", "liter", "litre"):
        return (amount * 1000, "ml")
    if unit == "kg":
        return (amount * 1000, "g")
    return (amount, unit)


def _match_product(sku, name, variation="", products=None):
    """Best-effort link to the catalog so platform sales roll up per product."""
    products = products if products is not None else db.read("products")
    sku_l = (sku or "").strip().lower()
    if sku_l:
        for product in products:
            if (product.get("sku") or "").strip().lower() == sku_l:
                return product["id"]
    text = " %s %s %s " % (_norm(name), _norm(variation), _norm(sku))
    family = next((fam for fam, words in _FAMILY_KEYWORDS
                   if any(w in text for w in words)), None)
    if not family:
        return None
    candidates = [p for p in products if p.get("family") == family]
    if not candidates:
        return None
    size = (_size_key(variation) or _size_key(sku) or _size_key(name))
    if size:
        for product in candidates:
            if _size_key(product.get("variant")) == size:
                return product["id"]
    return candidates[0]["id"]


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


def _parse_records(template, records, products):
    """Template + raw records -> canonical rows (no ids, not stored)."""
    mapping = template.get("mapping") or {}
    rows, skipped = [], 0
    for index, record in enumerate(records, start=1):
        row = {}
        for key in FIELD_KEYS:
            column = mapping.get(key)
            row[key] = _coerce(FIELD_KINDS[key],
                               record.get(column, "") if column else "")
        if not row.get("order_ref"):
            skipped += 1
            continue
        # Sensible fall-backs so every row carries usable money and quantity.
        if row["qty"] <= 0:
            row["qty"] = 1.0
        if row["gross_amount"] <= 0 and row["unit_price"] > 0:
            row["gross_amount"] = round(row["unit_price"] * row["qty"], 2)
        if row["unit_price"] <= 0 and row["qty"]:
            row["unit_price"] = round(row["gross_amount"] / row["qty"], 2)
        if row["net_amount"] == 0 and not mapping.get("net_amount"):
            row["net_amount"] = round(row["gross_amount"]
                                      - abs(row["discount"]), 2)
        row["status_group"] = status_group(row.get("order_status"))
        row["product_id"] = _match_product(row.get("sku"),
                                           row.get("product_name"),
                                           row.get("variation"), products)
        row["row_no"] = index
        rows.append(row)
    return rows, skipped


def read_file(path, template):
    """Headers and records of a file, through a template's sheet settings."""
    try:
        return xlsx.read_rows(path, template.get("sheet_index") or 0,
                              template.get("header_row") or 0), None
    except xlsx.XlsxError as exc:
        return None, str(exc)


def dry_run(path, template_id):
    """What an import would do, without storing anything — for the preview."""
    template = get_template(template_id)
    if not template:
        return None, "Choose an import template."
    data, err = read_file(path, template)
    if err:
        return None, err
    headers, records = data
    if not records:
        return None, "No data rows were found below the header row."
    missing = [FIELD_LABELS[k] for k in FIELD_KEYS
               if template["mapping"].get(k)
               and template["mapping"][k] not in headers]
    rows, skipped = _parse_records(template, records, db.read("products"))
    existing = {_dedupe_key(template["platform"], r): r
                for r in db.read("platform_sales")
                if r.get("platform") == template["platform"]}
    new = [r for r in rows if _dedupe_key(template["platform"], r) not in existing]
    counted = [r for r in rows if r["status_group"] in COUNTED_GROUPS]
    dates = sorted(r["order_date"] for r in rows if r.get("order_date"))
    groups = {}
    for r in rows:
        groups[r["status_group"]] = groups.get(r["status_group"], 0) + 1
    return {
        "template": template, "headers": headers, "missing": missing,
        "rows": len(rows), "skipped": skipped, "new": len(new),
        "already": len(rows) - len(new),
        "orders": len({r["order_ref"] for r in counted}),
        "units": round(sum(r["qty"] for r in counted), 2),
        "net": round(sum(r["net_amount"] for r in counted), 2),
        "matched": sum(1 for r in rows if r.get("product_id")),
        "period_from": dates[0] if dates else "",
        "period_to": dates[-1] if dates else "",
        "groups": groups,
        "sample": rows[:6],
    }, None


def import_file(path, template_id, user_id, filename=None, skip_duplicates=True):
    """Parse a file through a template and store the canonical rows.

    Rows already imported (same platform, order, product and variation) are
    not added again; their status and amounts are refreshed instead, so a
    newer export of the same orders keeps the reports current.
    Returns ``(import_record, None)`` or ``(None, message)``."""
    template = get_template(template_id)
    if not template:
        return None, "Choose an import template."
    if not os.path.isfile(path):
        return None, "That file could not be found."

    platform = template.get("platform")
    data, err = read_file(path, template)
    if err:
        return None, err
    headers, records = data
    if not records:
        return None, "No data rows were found below the header row."
    missing = [FIELD_LABELS[key] for key in FIELD_KEYS
               if template["mapping"].get(key)
               and template["mapping"][key] not in headers]
    if missing:
        return None, ("This file does not match the %s template — missing "
                      "column(s) for: %s." % (platform, ", ".join(missing)))

    parsed, skipped = _parse_records(template, records, db.read("products"))
    all_sales = db.read("platform_sales")
    existing = {}
    if skip_duplicates:
        for r in all_sales:
            if r.get("platform") == platform:
                existing[_dedupe_key(platform, r)] = r

    imported, updated, duplicates, seen = [], 0, 0, set()
    for row in parsed:
        key = _dedupe_key(platform, row)
        if key in seen:                 # the same line twice in one file
            duplicates += 1
            continue
        seen.add(key)
        old = existing.get(key)
        if old is not None:
            changes = {k: row[k] for k in ("order_status", "status_group",
                                           "net_amount", "gross_amount",
                                           "discount", "qty")
                       if old.get(k) != row[k]}
            if changes:
                old.update(changes)
                updated += 1
            else:
                duplicates += 1
            continue
        row.update({"platform": platform, "import_id": None,
                    "order_line": "", "created_at": services.now_iso()})
        imported.append(row)

    counted = [r for r in imported if r["status_group"] in COUNTED_GROUPS]
    dates = [r["order_date"] for r in imported if r.get("order_date")]
    record = db.insert("platform_imports", {
        "platform": platform,
        "template_id": template["id"],
        "filename": filename or os.path.basename(path),
        "rows_read": len(records),
        "rows_imported": len(imported),
        "rows_skipped": skipped,
        "duplicates": duplicates,
        "gross_amount": round(sum(r["gross_amount"] for r in counted), 2),
        "net_amount": round(sum(r["net_amount"] for r in counted), 2),
        "period_from": min(dates) if dates else "",
        "period_to": max(dates) if dates else "",
        "status": "Imported" if (imported or updated) else "Nothing new",
        "message": ("%d new row(s), %d updated, %d already up to date, %d "
                    "without an order reference."
                    % (len(imported), updated, duplicates, skipped)),
        "imported_by": user_id,
        "imported_at": services.now_iso(),
    })
    for row in imported:
        row["import_id"] = record["id"]
    if updated:
        db.write("platform_sales", all_sales)
    db.insert_many("platform_sales", imported)
    if imported or updated:
        services.notify_team(
            {"packing_head"}, "%s sales uploaded (%s): %s"
            % (platform, record["filename"], record["message"]),
            link="/platforms/?platform=%s" % platform)
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
    return True, ("Upload of %s removed along with its sales rows."
                  % record.get("filename"))


# --- Folder ----------------------------------------------------------------
def folder_files():
    """Exports sitting in sales-platform/, newest first."""
    if not os.path.isdir(UPLOAD_DIR):
        return []
    rows = []
    for name in os.listdir(UPLOAD_DIR):
        if name.startswith("~$") or not name.lower().endswith(ALLOWED_EXT):
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


# --- Reporting -------------------------------------------------------------
GRAINS = [("day", "Daily"), ("week", "Weekly"), ("month", "Monthly"),
          ("year", "Yearly")]


def _group_of(row):
    return row.get("status_group") or status_group(row.get("order_status"))


def sales_rows(platform=None, date_from="", date_to="", limit=None,
               counted_only=False):
    rows = db.read("platform_sales")
    if platform:
        rows = [r for r in rows if r.get("platform") == platform]
    if date_from:
        rows = [r for r in rows if (r.get("order_date") or "") >= date_from]
    if date_to:
        rows = [r for r in rows if (r.get("order_date") or "") <= date_to]
    if counted_only:
        rows = [r for r in rows if _group_of(r) in COUNTED_GROUPS]
    rows.sort(key=lambda r: (r.get("order_date") or "", r.get("id") or 0),
              reverse=True)
    return rows[:limit] if limit else rows


def platform_summary(rows=None):
    """Per-platform totals of counted sales, plus a grand total."""
    rows = sales_rows() if rows is None else rows
    rows = [r for r in rows if _group_of(r) in COUNTED_GROUPS]
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
            "color": PLATFORM_COLORS.get(bucket["platform"], PLATFORM_COLORS["Other"]),
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


def _product_label(row, products):
    product = products.get(row.get("product_id"))
    if product:
        return product.get("name")
    return (row.get("product_name") or row.get("sku") or "").strip()


def top_products(rows=None, limit=10):
    rows = sales_rows() if rows is None else rows
    rows = [r for r in rows if _group_of(r) in COUNTED_GROUPS]
    products = {p["id"]: p for p in db.read("products")}
    buckets = {}
    for row in rows:
        name = _product_label(row, products)
        if not name:
            continue
        bucket = buckets.setdefault(name, {"name": name, "qty": 0.0,
                                           "net": 0.0, "platforms": set(),
                                           "linked": bool(row.get("product_id"))})
        bucket["qty"] += services._to_float(row.get("qty"))
        bucket["net"] += services._to_float(row.get("net_amount"))
        bucket["platforms"].add(row.get("platform"))
    out = [{"name": b["name"], "qty": round(b["qty"], 2),
            "net": round(b["net"], 2), "linked": b["linked"],
            "platforms": ", ".join(sorted(p for p in b["platforms"] if p))}
           for b in buckets.values()]
    out.sort(key=lambda r: r["net"], reverse=True)
    return out[:limit] if limit else out


def daily_series(rows=None, days=30):
    """[(date, net_amount), ...] oldest first — feeds the trend chart."""
    rows = sales_rows(counted_only=True) if rows is None else rows
    buckets = {}
    for row in rows:
        if _group_of(row) not in COUNTED_GROUPS:
            continue
        day = (row.get("order_date") or "")[:10]
        if not day:
            continue
        buckets[day] = buckets.get(day, 0.0) + services._to_float(
            row.get("net_amount"))
    series = sorted(buckets.items())
    return series[-days:]


def period_of(day, grain):
    """('2026-10-14', 'week') -> ('2026-10-12', 'Week of 12 Oct')."""
    try:
        d = datetime.date.fromisoformat(day[:10])
    except (TypeError, ValueError):
        return None, None
    if grain == "day":
        return d.isoformat(), d.strftime("%d %b")
    if grain == "week":
        start = d - datetime.timedelta(days=d.weekday())
        return start.isoformat(), "Wk of %s" % start.strftime("%d %b")
    if grain == "month":
        return d.strftime("%Y-%m"), d.strftime("%b %Y")
    return d.strftime("%Y"), d.strftime("%Y")


def range_for(preset, today=None):
    """Named date ranges for the report filter -> (from, to, label)."""
    today = today or datetime.date.today()
    if preset == "week":
        start = today - datetime.timedelta(days=today.weekday())
        return start.isoformat(), today.isoformat(), "This week"
    if preset == "month":
        return today.replace(day=1).isoformat(), today.isoformat(), "This month"
    if preset == "last_month":
        first = today.replace(day=1)
        last_prev = first - datetime.timedelta(days=1)
        return (last_prev.replace(day=1).isoformat(), last_prev.isoformat(),
                "Last month")
    if preset == "90d":
        return ((today - datetime.timedelta(days=89)).isoformat(),
                today.isoformat(), "Last 90 days")
    if preset == "year":
        return today.replace(month=1, day=1).isoformat(), today.isoformat(), \
            "This year"
    return "", "", "All time"


def sales_report(platform="", date_from="", date_to="", grain="week"):
    """Everything the sales report shows, for one filter."""
    rows = sales_rows(platform or None, date_from, date_to)
    counted = [r for r in rows if _group_of(r) in COUNTED_GROUPS]
    products = {p["id"]: p for p in db.read("products")}

    # Per period, per platform.
    periods = {}
    for r in counted:
        key, label = period_of(r.get("order_date") or "", grain)
        if not key:
            continue
        p = periods.setdefault(key, {"key": key, "label": label, "net": 0.0,
                                     "orders": set(), "units": 0.0,
                                     "by_platform": {}})
        net = services._to_float(r.get("net_amount"))
        p["net"] += net
        p["orders"].add((r.get("platform"), r.get("order_ref")))
        p["units"] += services._to_float(r.get("qty"))
        name = r.get("platform") or "Other"
        p["by_platform"][name] = p["by_platform"].get(name, 0.0) + net
    period_rows = []
    for key in sorted(periods):
        p = periods[key]
        orders = len(p["orders"])
        period_rows.append({
            "key": key, "label": p["label"], "net": round(p["net"], 2),
            "orders": orders, "units": round(p["units"], 2),
            "aov": round(p["net"] / orders, 2) if orders else 0.0,
            "by_platform": {k: round(v, 2) for k, v in p["by_platform"].items()},
        })

    by_platform, totals = platform_summary(rows)
    present = [p for p in PLATFORMS if any(b["platform"] == p for b in by_platform)]

    status = {g: {"group": g, "lines": 0, "orders": set(), "amount": 0.0}
              for g in STATUS_GROUPS}
    for r in rows:
        bucket = status[_group_of(r)]
        bucket["lines"] += 1
        bucket["orders"].add((r.get("platform"), r.get("order_ref")))
        amount = (r.get("net_amount") if _group_of(r) in COUNTED_GROUPS
                  + ("Adjustment",) else r.get("gross_amount"))
        bucket["amount"] += services._to_float(amount)
    status_rows = [{"group": s["group"], "lines": s["lines"],
                    "orders": len(s["orders"]), "amount": round(s["amount"], 2)}
                   for s in status.values() if s["lines"]]

    regions = {}
    for r in counted:
        name = (r.get("region") or "").strip() or "Not given"
        reg = regions.setdefault(name, {"region": name, "orders": set(),
                                        "net": 0.0})
        reg["orders"].add((r.get("platform"), r.get("order_ref")))
        reg["net"] += services._to_float(r.get("net_amount"))
    region_rows = sorted(({"region": v["region"], "orders": len(v["orders"]),
                           "net": round(v["net"], 2)} for v in regions.values()),
                         key=lambda x: x["net"], reverse=True)

    lost = [r for r in rows if _group_of(r) in ("Cancelled", "Returned")]
    orders = totals["orders"]
    return {
        "periods": period_rows,
        "platforms": by_platform,
        "present": present,
        "totals": totals,
        "kpis": {
            "net": totals["net"], "orders": orders, "units": totals["qty"],
            "aov": round(totals["net"] / orders, 2) if orders else 0.0,
            "lost_orders": len({(r.get("platform"), r.get("order_ref"))
                                for r in lost}),
            "lost_amount": round(sum(services._to_float(r.get("gross_amount"))
                                     for r in lost), 2),
            "unlinked": sum(1 for r in counted if not r.get("product_id")),
        },
        "products": top_products(counted, limit=None),
        "status": status_rows,
        "regions": region_rows,
        "rows": rows,
        "product_names": {pid: p.get("name") for pid, p in products.items()},
    }


def report_csv(report, grain):
    """The per-period table as CSV text (opens in Excel)."""
    out = io.StringIO()
    writer = csv.writer(out)
    present = report["present"]
    label = {"day": "Date", "week": "Week starting", "month": "Month",
             "year": "Year"}.get(grain, "Period")
    writer.writerow([label]
                    + ["%s net (PHP)" % p for p in present]
                    + ["Total net (PHP)", "Orders", "Units", "Avg order (PHP)"])
    for p in report["periods"]:
        writer.writerow([p["key"]] + [p["by_platform"].get(x, 0) for x in present]
                        + [p["net"], p["orders"], p["units"], p["aov"]])
    t = report["totals"]
    writer.writerow(["Total"] + [next((b["net"] for b in report["platforms"]
                                       if b["platform"] == x), 0)
                                 for x in present]
                    + [t["net"], t["orders"], t["qty"],
                       report["kpis"]["aov"]])
    return out.getvalue()
