"""JSON file storage layer for the Amamio Sales & Inventory Management System.

Each "table" lives in data/<collection>.json as a JSON list of dicts.  Access is
thread-safe via a module-level RLock; writes are atomic (temp file + os.replace).

DATA_DIR is a module global so it can be reassigned in tests / alternate
deployments before any read/write happens.

MIGRATION TO MySQL
------------------
``SCHEMA`` below declares every collection as a real relational table: column
names, SQL types, primary/foreign keys and which fields are embedded child
lists (which become their own tables).  ``mysql_export.py`` turns that
declaration into ``schema.sql`` + a full data dump, so moving off JSON is a
single command and requires no rewrite of the application code.
"""
import json
import os
import threading
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")

# --- Column type shorthands used by SCHEMA ---------------------------------
ID = "INT UNSIGNED NOT NULL"
FK = "INT UNSIGNED NULL"
STR = "VARCHAR(255) NULL"
SHORT = "VARCHAR(64) NULL"
TEXT = "TEXT NULL"
NUM = "DECIMAL(14,3) NULL"
MONEY = "DECIMAL(14,2) NULL"
BOOL = "TINYINT(1) NOT NULL DEFAULT 0"
TS = "DATETIME NULL"
DATE = "DATE NULL"

# Every collection, declared as a table.  "children" entries are embedded JSON
# lists on the parent record that become separate MySQL tables on migration.
SCHEMA = {
    # --- People & access ---------------------------------------------------
    "users": {
        "columns": {
            "id": ID, "name": STR, "username": "VARCHAR(64) NOT NULL",
            "password_hash": "VARCHAR(255) NULL", "role": SHORT, "email": STR,
            "phone": SHORT, "team": SHORT, "active": BOOL,
            "last_login": TS, "created_at": TS,
        },
        "unique": ["username"],
    },
    "roles": {
        "columns": {"id": ID, "key": SHORT, "name": STR, "description": TEXT},
    },

    # --- Partners ----------------------------------------------------------
    "suppliers": {
        "columns": {
            "id": ID, "name": STR, "contact_person": STR, "phone": SHORT,
            "email": STR, "address": TEXT, "materials_supplied": TEXT,
            "lead_time_days": "INT NULL", "notes": TEXT, "created_at": TS,
        },
    },
    "customers": {
        "columns": {
            "id": ID, "name": STR, "contact_person": STR, "phone": SHORT,
            "email": STR, "address": TEXT, "channel": SHORT, "notes": TEXT,
            "created_at": TS,
        },
    },

    # --- Catalog -----------------------------------------------------------
    "raw_materials": {
        "columns": {
            "id": ID, "name": STR, "category": SHORT, "unit": SHORT,
            "track_mode": SHORT, "stock_qty": NUM, "reorder_level": NUM,
            "supplier_id": FK, "unit_cost": MONEY, "expiry_date": DATE,
            "storage_location": STR, "created_at": TS,
        },
        "foreign_keys": {"supplier_id": "suppliers"},
    },
    "products": {
        "columns": {
            "id": ID, "name": STR, "sku": SHORT, "variant": SHORT, "unit": SHORT,
            "stock_qty": NUM, "reorder_level": NUM, "price": MONEY,
            "location": STR, "category": SHORT, "created_at": TS,
        },
    },
    "bill_of_materials": {
        "columns": {
            "id": ID, "product_id": FK, "material_id": FK, "qty_per_unit": NUM,
            "notes": TEXT,
        },
        "foreign_keys": {"product_id": "products", "material_id": "raw_materials"},
    },

    # --- Receiving area (crates / cage boxes, by weight or by piece) --------
    "receiving_batches": {
        "columns": {
            "id": ID, "ref_no": SHORT, "supplier_id": FK, "supplier_name": STR,
            "delivery_ref": STR, "received_date": DATE, "received_by": FK,
            "status": SHORT, "remarks": TEXT, "box_count": "INT NULL",
            "total_good": NUM, "total_damaged": NUM,
            "created_at": TS, "closed_at": TS,
        },
        "foreign_keys": {"supplier_id": "suppliers", "received_by": "users"},
    },
    "receiving_boxes": {
        "columns": {
            "id": ID, "batch_id": FK, "box_code": SHORT, "seq": "INT NULL",
            "material_id": FK, "material_name": STR, "unit": SHORT,
            "track_mode": SHORT, "declared_qty": NUM, "good_qty": NUM,
            "damaged_qty": NUM, "damage_reason": TEXT, "status": SHORT,
            "stage": SHORT, "location": STR, "checked_by": FK, "checked_at": TS,
            "released_to": SHORT, "released_at": TS, "created_at": TS,
        },
        "foreign_keys": {"batch_id": "receiving_batches",
                         "material_id": "raw_materials", "checked_by": "users"},
    },

    # --- Honey production: containers + moisture/appearance QC --------------
    "honey_containers": {
        "columns": {
            "id": ID, "container_code": SHORT, "batch_ref": SHORT,
            "source": SHORT, "supplier_id": FK, "harvest_date": DATE,
            "received_date": DATE, "gross_weight_kg": NUM, "tare_weight_kg": NUM,
            "net_weight_kg": NUM, "status": SHORT, "moisture_pct": NUM,
            "appearance": SHORT, "qc_notes": TEXT, "qc_by": FK, "qc_at": TS,
            "disposition": SHORT, "allocated_to": STR, "allocated_at": TS,
            "material_id": FK, "created_by": FK, "created_at": TS,
        },
        "foreign_keys": {"supplier_id": "suppliers", "qc_by": "users",
                         "material_id": "raw_materials", "created_by": "users"},
    },

    # --- Packing area (per sales channel) ----------------------------------
    "packing_runs": {
        "columns": {
            "id": ID, "run_code": SHORT, "channel": SHORT, "packer_id": FK,
            "packer_name": STR, "pack_date": DATE, "order_ref": STR,
            "sales_order_id": FK, "status": SHORT, "total_qty": NUM,
            "damaged_qty": NUM, "stock_released": BOOL, "handed_to": STR,
            "handed_at": TS, "courier": STR, "tracking_no": SHORT,
            "remarks": TEXT, "created_by": FK, "created_at": TS,
            "packed_at": TS,
        },
        "children": {"items": "packing_items"},
        "foreign_keys": {"packer_id": "users", "sales_order_id": "sales_orders",
                         "created_by": "users"},
    },
    "packing_items": {
        "columns": {
            "id": ID, "packing_run_id": FK, "product_id": FK, "name": STR,
            "qty": NUM, "unit": SHORT, "damaged_qty": NUM, "notes": TEXT,
        },
        "foreign_keys": {"packing_run_id": "packing_runs",
                         "product_id": "products"},
    },

    # --- Sales platform imports (Shopee / TikTok / Lazada / ...) ------------
    "platform_templates": {
        "columns": {
            "id": ID, "platform": SHORT, "name": STR, "sheet_index": "INT NULL",
            "header_row": "INT NULL", "date_format": SHORT, "active": BOOL,
            "mapping_json": TEXT, "notes": TEXT, "created_at": TS,
            "updated_at": TS,
        },
    },
    "platform_imports": {
        "columns": {
            "id": ID, "platform": SHORT, "template_id": FK, "filename": STR,
            "rows_read": "INT NULL", "rows_imported": "INT NULL",
            "rows_skipped": "INT NULL", "duplicates": "INT NULL",
            "gross_amount": MONEY, "net_amount": MONEY, "period_from": DATE,
            "period_to": DATE, "status": SHORT, "message": TEXT,
            "imported_by": FK, "imported_at": TS,
        },
        "foreign_keys": {"template_id": "platform_templates",
                         "imported_by": "users"},
    },
    "platform_sales": {
        "columns": {
            "id": ID, "platform": SHORT, "import_id": FK, "order_ref": SHORT,
            "order_line": SHORT, "order_date": DATE, "sku": SHORT,
            "product_name": STR, "variation": STR, "product_id": FK,
            "qty": NUM, "unit_price": MONEY, "gross_amount": MONEY,
            "discount": MONEY, "shipping_fee": MONEY, "net_amount": MONEY,
            "order_status": SHORT, "buyer_name": STR, "region": STR,
            "row_no": "INT NULL", "created_at": TS,
        },
        "foreign_keys": {"import_id": "platform_imports",
                         "product_id": "products"},
    },

    # --- Production --------------------------------------------------------
    "production_orders": {
        "columns": {
            "id": ID, "product_id": FK, "product_name": STR, "qty": NUM,
            "batch_no": SHORT, "status": SHORT, "output_qty": NUM,
            "rejected_qty": NUM, "damaged_qty": NUM, "notes": TEXT,
            "user_id": FK, "timestamp": TS,
        },
        "children": {"materials_used": "production_materials"},
        "foreign_keys": {"product_id": "products", "user_id": "users"},
    },
    "production_materials": {
        "columns": {
            "id": ID, "production_order_id": FK, "material_id": FK, "qty": NUM,
        },
        "foreign_keys": {"production_order_id": "production_orders",
                         "material_id": "raw_materials"},
    },

    # --- Assets & maintenance ----------------------------------------------
    "maintenance_logs": {
        "columns": {
            "id": ID, "asset_id": FK, "asset_name": STR, "type": SHORT,
            "performed_on": DATE, "performed_by": STR, "cost": MONEY,
            "next_due": DATE, "status": SHORT, "downtime_hours": NUM,
            "notes": TEXT, "recorded_by": FK, "created_at": TS,
        },
        "foreign_keys": {"asset_id": "raw_materials", "recorded_by": "users"},
    },

    # --- Sales / fulfilment -------------------------------------------------
    "sales_orders": {
        "columns": {
            "id": ID, "customer_id": FK, "customer_name": STR, "channel": SHORT,
            "status": SHORT, "order_date": TS, "subtotal": MONEY,
            "discount": MONEY, "total": MONEY, "payment_status": SHORT,
            "remarks": TEXT, "created_by": FK,
        },
        "children": {"items": "sales_order_items"},
        "foreign_keys": {"customer_id": "customers", "created_by": "users"},
    },
    "sales_order_items": {
        "columns": {
            "id": ID, "sales_order_id": FK, "product_id": FK, "name": STR,
            "qty": NUM, "unit_price": MONEY, "line_total": MONEY,
        },
        "foreign_keys": {"sales_order_id": "sales_orders",
                         "product_id": "products"},
    },
    "payments": {
        "columns": {
            "id": ID, "sales_order_id": FK, "amount": MONEY, "method": SHORT,
            "reference": STR, "paid_at": TS, "recorded_by": FK,
        },
        "foreign_keys": {"sales_order_id": "sales_orders",
                         "recorded_by": "users"},
    },
    "deliveries": {
        "columns": {
            "id": ID, "sales_order_id": FK, "packing_run_id": FK,
            "customer_name": STR, "status": SHORT, "scheduled_date": DATE,
            "driver": STR, "address": TEXT, "delivered_at": TS,
            "confirmed_by_customer": BOOL, "notes": TEXT, "created_by": FK,
        },
        "foreign_keys": {"sales_order_id": "sales_orders",
                         "packing_run_id": "packing_runs", "created_by": "users"},
    },
    "returns": {
        "columns": {
            "id": ID, "sales_order_id": FK, "product_id": FK,
            "product_name": STR, "qty": NUM, "reason": TEXT, "status": SHORT,
            "created_at": TS, "handled_by": FK,
        },
        "foreign_keys": {"sales_order_id": "sales_orders",
                         "product_id": "products", "handled_by": "users"},
    },
    "sales_requests": {
        "columns": {
            "id": ID, "product_id": FK, "product_name": STR,
            "product_unit": SHORT, "qty": NUM, "channel": SHORT,
            "requestor_id": FK, "requestor_name": STR, "status": SHORT,
            "remarks": TEXT, "decided_by": FK, "fulfilled_by": FK,
            "created_at": TS,
        },
        "foreign_keys": {"product_id": "products", "requestor_id": "users",
                         "decided_by": "users", "fulfilled_by": "users"},
    },

    # --- Requests & approvals ----------------------------------------------
    "purchase_requests": {
        "columns": {
            "id": ID, "type": SHORT, "requestor_id": FK, "product_id": FK,
            "product_name": STR, "qty": NUM, "reason": TEXT,
            "needed_by": DATE, "urgency": SHORT, "status": SHORT,
            "remarks": TEXT, "decided_by": FK, "decided_at": TS,
            "created_at": TS,
        },
        "children": {"items": "purchase_request_items"},
        "foreign_keys": {"requestor_id": "users", "product_id": "products",
                         "decided_by": "users"},
    },
    "purchase_request_items": {
        "columns": {
            "id": ID, "purchase_request_id": FK, "item_id": "INT NULL",
            "name": STR, "category": SHORT, "description": TEXT,
            "material_id": FK, "requested_qty": NUM, "approved_qty": NUM,
            "received_qty": NUM, "status": SHORT, "note": TEXT,
            "qr_token": SHORT,
        },
        "foreign_keys": {"purchase_request_id": "purchase_requests",
                         "material_id": "raw_materials"},
    },

    # --- Ledgers & system ---------------------------------------------------
    "inventory_transactions": {
        "columns": {
            "id": ID, "item_type": SHORT, "item_id": FK, "change_qty": NUM,
            "txn_type": SHORT, "reference_id": STR, "user_id": FK,
            "timestamp": TS,
        },
        "foreign_keys": {"user_id": "users"},
    },
    "inventory_adjustments": {
        "columns": {
            "id": ID, "item_type": SHORT, "item_id": FK, "old_qty": NUM,
            "new_qty": NUM, "delta": NUM, "reason": TEXT, "user_id": FK,
            "timestamp": TS,
        },
        "foreign_keys": {"user_id": "users"},
    },
    "damage_records": {
        "columns": {
            "id": ID, "source": SHORT, "reference": STR, "item_type": SHORT,
            "item_id": FK, "item_name": STR, "qty": NUM, "unit": SHORT,
            "stage": SHORT, "reason": TEXT, "recorded_by": FK,
            "recorded_at": TS,
        },
        "foreign_keys": {"recorded_by": "users"},
    },
    "notifications": {
        "columns": {
            "id": ID, "user_id": FK, "message": TEXT, "link": STR,
            "is_read": BOOL, "created_at": TS,
        },
        "foreign_keys": {"user_id": "users"},
    },
    "ai_forecasts": {
        "columns": {
            "id": ID, "product_id": FK, "product_name": STR,
            "generated_at": TS, "horizon_weeks": "INT NULL", "model": SHORT,
            "forecast": TEXT, "future_labels": TEXT,
        },
        "foreign_keys": {"product_id": "products"},
        "json_fields": ["forecast", "future_labels"],
    },
    "ai_recommendations": {
        "columns": {
            "id": ID, "type": SHORT, "subject": STR, "message": TEXT,
            "severity": SHORT, "generated_at": TS, "acted_on": BOOL,
        },
    },
}

# Collections stored as their own JSON file (child tables are embedded).
_CHILD_TABLES = {child for spec in SCHEMA.values()
                 for child in spec.get("children", {}).values()}
COLLECTIONS = [name for name in SCHEMA if name not in _CHILD_TABLES]

_lock = threading.RLock()


def _path(name):
    return os.path.join(DATA_DIR, name + ".json")


def _ensure_dir():
    if not os.path.isdir(DATA_DIR):
        os.makedirs(DATA_DIR, exist_ok=True)


def read(name):
    """Return the list of records for a collection (empty list if missing)."""
    with _lock:
        _ensure_dir()
        path = _path(name)
        if not os.path.exists(path):
            return []
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, ValueError, OSError):
            return []
        return data if isinstance(data, list) else []


def write(name, records):
    """Atomically persist a list of records for a collection."""
    with _lock:
        _ensure_dir()
        path = _path(name)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(records, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        # os.replace can transiently fail on Windows if an indexer / antivirus
        # holds a brief lock on the target; retry a few times before giving up.
        for attempt in range(20):
            try:
                os.replace(tmp, path)
                return
            except PermissionError:
                if attempt == 19:
                    raise
                time.sleep(0.05)


def next_id(name):
    """Return max existing id + 1, or 1 if empty."""
    with _lock:
        records = read(name)
        ids = [int(r.get("id", 0)) for r in records if r.get("id") is not None]
        return (max(ids) + 1) if ids else 1


def get(name, id):
    """Return the record whose id matches int(id), else None."""
    with _lock:
        try:
            target = int(id)
        except (TypeError, ValueError):
            return None
        for r in read(name):
            if int(r.get("id", 0)) == target:
                return r
        return None


def insert(name, obj):
    """Assign a new id, append, persist, and return the same object (mutated)."""
    with _lock:
        records = read(name)
        obj["id"] = next_id(name)
        records.append(obj)
        write(name, records)
        return obj


def insert_many(name, objs):
    """Assign sequential ids to all objs and persist them in a single write."""
    if not objs:
        return objs
    with _lock:
        records = read(name)
        ids = [int(r.get("id", 0)) for r in records if r.get("id") is not None]
        start = (max(ids) + 1) if ids else 1
        for i, obj in enumerate(objs):
            obj["id"] = start + i
            records.append(obj)
        write(name, records)
        return objs


def update(name, id, changes):
    """Merge changes into the matching record, persist, and return it (or None)."""
    with _lock:
        try:
            target = int(id)
        except (TypeError, ValueError):
            return None
        records = read(name)
        updated = None
        for r in records:
            if int(r.get("id", 0)) == target:
                r.update(changes)
                updated = r
                break
        if updated is not None:
            write(name, records)
        return updated


def delete(name, id):
    """Remove the record with the given id. Return True if one was removed."""
    with _lock:
        try:
            target = int(id)
        except (TypeError, ValueError):
            return False
        records = read(name)
        kept = [r for r in records if int(r.get("id", 0)) != target]
        if len(kept) != len(records):
            write(name, kept)
            return True
        return False


def query(collection, **filters):
    """Return records matching all given field==value filters (exact match)."""
    with _lock:
        results = []
        for r in read(collection):
            if all(r.get(k) == v for k, v in filters.items()):
                results.append(r)
        return results
