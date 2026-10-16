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
            "phone": SHORT, "team": SHORT, "theme": SHORT, "hide_notes": BOOL,
            "active": BOOL,
            "last_login": TS, "created_at": TS,
        },
        "unique": ["username"],
    },
    "roles": {
        "columns": {"id": ID, "key": SHORT, "name": STR, "description": TEXT},
    },

    # --- Partners ----------------------------------------------------------
    # Mirrors the paper Supplier Directory: supplier, TIN, items, contact,
    # filed under Office / Production / Packing.
    "suppliers": {
        "columns": {
            "id": ID, "name": STR, "tin": SHORT, "category": SHORT,
            "contact_person": STR, "phone": SHORT, "email": STR,
            "address": TEXT, "materials_supplied": TEXT, "buy_from": STR,
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
    # Every stocked item that is not equipment: raw materials, packaging
    # (jars / bottles / pouches / cap seals / packing supplies), cleaning and
    # office supplies.  ``category`` says which month-end report it is on,
    # ``subcategory`` the heading within that report.
    "raw_materials": {
        "columns": {
            "id": ID, "name": STR, "category": SHORT, "subcategory": SHORT,
            "unit": SHORT, "track_mode": SHORT, "stock_qty": NUM,
            "reorder_level": NUM, "supplier_id": FK, "unit_cost": MONEY,
            "expiry_date": DATE, "storage_location": STR, "created_at": TS,
        },
        "foreign_keys": {"supplier_id": "suppliers"},
    },
    # Finished goods, one row per size (as on the Daily Production Report):
    # ``product_group`` = Honey / Cacao / Coffee / Powder / Others,
    # ``family`` = e.g. "Pure Honey", ``variant`` = e.g. "250 mL".
    "products": {
        "columns": {
            "id": ID, "name": STR, "sku": SHORT, "product_group": SHORT,
            "family": STR, "variant": SHORT, "unit": SHORT, "stock_qty": NUM,
            "reorder_level": NUM, "price": MONEY, "location": STR,
            "category": SHORT, "sort_order": "INT NULL", "created_at": TS,
        },
    },
    "bill_of_materials": {
        "columns": {
            "id": ID, "product_id": FK, "material_id": FK, "qty_per_unit": NUM,
            "notes": TEXT,
        },
        "foreign_keys": {"product_id": "products", "material_id": "raw_materials"},
    },

    # --- Module 1: receiving area, then inspection & cleaning ---------------
    # Part 1: the Receiving Team Head opens a delivery and labels every box /
    # crate with a QR code.  Part 2: each box is inspected and cleaned, and
    # its content split into usable / can't be used / damaged.  The columns
    # follow the paper "Raw Materials Receiving and Inspection Report".
    "receiving_batches": {
        "columns": {
            "id": ID, "ref_no": SHORT, "supplier_id": FK, "supplier_name": STR,
            "po_no": SHORT, "delivery_ref": STR, "received_date": DATE,
            "received_by": FK, "status": SHORT, "remarks": TEXT,
            "box_count": "INT NULL", "total_declared": NUM, "total_good": NUM,
            "total_unusable": NUM, "total_damaged": NUM,
            "checked_by_name": STR, "approved_by_name": STR,
            "created_at": TS, "closed_at": TS,
        },
        "foreign_keys": {"supplier_id": "suppliers", "received_by": "users"},
    },
    "receiving_boxes": {
        "columns": {
            "id": ID, "batch_id": FK, "box_code": SHORT, "seq": "INT NULL",
            "material_id": FK, "material_name": STR, "unit": SHORT,
            "track_mode": SHORT, "declared_qty": NUM, "lot_no": SHORT,
            "expiry_date": DATE, "packaging_condition": SHORT,
            "temperature_c": NUM,
            # Part 2 — inspection & cleaning
            "good_qty": NUM, "unusable_qty": NUM, "unusable_reason": TEXT,
            "damaged_qty": NUM, "damage_reason": TEXT, "cleaned": BOOL,
            "visual_inspection": SHORT, "coa_check": SHORT,
            "sampling_test": SHORT, "acceptance_status": SHORT,
            "nonconformity": TEXT, "action_taken": TEXT,
            "verified_by_name": STR, "checked_by": FK, "checked_at": TS,
            # Where the box is on the floor
            "status": SHORT, "stage": SHORT, "location": STR,
            "released_to": SHORT, "released_at": TS,
            "received_by": FK, "created_at": TS,
        },
        "foreign_keys": {"batch_id": "receiving_batches",
                         "material_id": "raw_materials", "checked_by": "users",
                         "received_by": "users"},
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
            "allocated_kg": NUM, "remaining_kg": NUM,
            "material_id": FK, "created_by": FK, "created_at": TS,
        },
        "children": {"allocations": "honey_allocations"},
        "foreign_keys": {"supplier_id": "suppliers", "qc_by": "users",
                         "material_id": "raw_materials", "created_by": "users"},
    },
    # Where a container's honey went: PASS honey to selling products, FAILED
    # honey to the products that can still use it.
    "honey_allocations": {
        "columns": {
            "id": ID, "honey_container_id": FK, "product": STR, "kg": NUM,
            "allocated_by": FK, "allocated_at": TS,
        },
        "foreign_keys": {"honey_container_id": "honey_containers",
                         "allocated_by": "users"},
    },

    # --- Module 4: packing area (per sales channel) ------------------------
    # In Progress -> Packed -> Disbursed (handed straight to the customer /
    # VIP / walk-in) or Handed to Courier (logistics, with tracking number).
    "packing_runs": {
        "columns": {
            "id": ID, "run_code": SHORT, "channel": SHORT, "packer_id": FK,
            "packer_name": STR, "pack_date": DATE, "order_ref": STR,
            "sales_order_id": FK, "status": SHORT, "total_qty": NUM,
            "damaged_qty": NUM, "stock_released": BOOL,
            "dispatch_type": SHORT, "handed_to": STR, "handed_at": TS,
            "courier": STR, "tracking_no": SHORT, "parcel_count": "INT NULL",
            "dispatch_notes": TEXT, "dispatched_by": FK,
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
            "order_status": SHORT, "status_group": SHORT, "buyer_name": STR,
            "region": STR, "row_no": "INT NULL", "created_at": TS,
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

    # --- Module 3: equipment, supplies and every movement in and out ---------
    # The asset register follows the paper "Inventory of Assets" (AFP-001 …)
    # plus the header block of the "Equipment Maintenance Log".
    "assets": {
        "columns": {
            "id": ID, "item_no": SHORT, "name": STR, "category": SHORT,
            "cost_per_item": MONEY, "quantity": NUM, "unit": SHORT,
            "qty_out": NUM, "condition": SHORT, "years_in_use": NUM,
            "remarks": TEXT, "serial_number": SHORT, "model": SHORT,
            "manufacturer": STR, "date_of_purchase": DATE, "location": STR,
            "contact_details": STR, "active": BOOL, "created_at": TS,
        },
        "unique": ["item_no"],
    },
    "asset_movements": {
        "columns": {
            "id": ID, "asset_id": FK, "asset_name": STR, "direction": SHORT,
            "qty": NUM, "reason": SHORT, "person": STR, "destination": STR,
            "expected_return": DATE, "notes": TEXT, "recorded_by": FK,
            "moved_at": TS,
        },
        "foreign_keys": {"asset_id": "assets", "recorded_by": "users"},
    },
    "maintenance_logs": {
        "columns": {
            "id": ID, "asset_id": FK, "asset_name": STR, "type": SHORT,
            "performed_on": DATE, "performed_time": SHORT, "description": TEXT,
            "performed_by": STR,
            "cost": MONEY, "next_due": DATE, "status": SHORT,
            "downtime_hours": NUM, "notes": TEXT, "recorded_by": FK,
            "created_at": TS,
        },
        "foreign_keys": {"asset_id": "assets", "recorded_by": "users"},
    },
    # Supplies (raw / packaging / cleaning / office) taken in or issued out.
    "stock_movements": {
        "columns": {
            "id": ID, "material_id": FK, "material_name": STR,
            "category": SHORT, "direction": SHORT, "qty": NUM, "unit": SHORT,
            "reason": SHORT, "person": STR, "reference": STR, "notes": TEXT,
            "balance_after": NUM, "recorded_by": FK, "moved_at": TS,
        },
        "foreign_keys": {"material_id": "raw_materials", "recorded_by": "users"},
    },
    # The paper month-end reports: a physical count per category per month.
    "month_end_counts": {
        "columns": {
            "id": ID, "period": SHORT, "category": SHORT, "counted_by": FK,
            "counted_at": TS, "notes": TEXT, "adjusted": BOOL,
        },
        "children": {"lines": "month_end_count_lines"},
        "foreign_keys": {"counted_by": "users"},
    },
    "month_end_count_lines": {
        "columns": {
            "id": ID, "month_end_count_id": FK, "material_id": FK, "name": STR,
            "unit": SHORT, "system_qty": NUM, "physical_qty": NUM,
            "variance": NUM,
        },
        "foreign_keys": {"month_end_count_id": "month_end_counts",
                         "material_id": "raw_materials"},
    },

    # --- Facility records (paper forms) ------------------------------------
    "sanitation_records": {
        "columns": {
            "id": ID, "record_date": DATE, "phase": SHORT,
            "conducted_by": STR, "inspected_by": STR, "remarks": TEXT,
            "recorded_by": FK, "created_at": TS,
        },
        "children": {"areas": "sanitation_areas"},
        "foreign_keys": {"recorded_by": "users"},
    },
    "sanitation_areas": {
        "columns": {
            "id": ID, "sanitation_record_id": FK, "location": STR,
            "current_status": SHORT, "action": TEXT, "date_undertaken": DATE,
            "remarks": TEXT,
        },
        "foreign_keys": {"sanitation_record_id": "sanitation_records"},
    },
    "pest_control_records": {
        "columns": {
            "id": ID, "period": SHORT, "record_date": DATE,
            "monitored_by": STR, "remarks": TEXT, "recorded_by": FK,
            "created_at": TS,
        },
        "children": {"areas": "pest_control_areas"},
        "foreign_keys": {"recorded_by": "users"},
    },
    "pest_control_areas": {
        "columns": {
            "id": ID, "pest_control_record_id": FK, "area": STR,
            "pest_activity": BOOL, "observation": TEXT,
            "corrective_action": TEXT, "signed_by": STR,
        },
        "foreign_keys": {"pest_control_record_id": "pest_control_records"},
    },

    # --- Production records (paper forms) ----------------------------------
    # Batch Manufacturing Record: header, dispensing & weighing, procedure,
    # yield and the QA's final disposition.
    "batch_records": {
        "columns": {
            "id": ID, "batch_no": SHORT, "product_id": FK, "product_name": STR,
            "batch_size": NUM, "production_date": DATE, "expiry_date": DATE,
            "start_at": TS, "end_at": TS, "theoretical_yield": NUM,
            "actual_yield": NUM, "test_date": DATE, "test_result_date": DATE,
            "yield_conducted_by": STR, "yield_checked_by": STR,
            "test_conducted_by": STR, "test_checked_by": STR,
            "disposition": SHORT, "qa_name": STR, "qa_date": DATE,
            "remarks": TEXT, "status": SHORT, "stock_posted": BOOL,
            "created_by": FK, "created_at": TS, "completed_at": TS,
        },
        "children": {"dispensing": "batch_dispensing",
                     "steps": "batch_steps"},
        "foreign_keys": {"product_id": "products", "created_by": "users"},
    },
    "batch_dispensing": {
        "columns": {
            "id": ID, "batch_record_id": FK, "material_id": FK,
            "ingredient": STR, "lot_no": SHORT, "expiry_date": DATE,
            "theoretical_qty": NUM, "unit": SHORT, "conducted_by": STR,
            "checked_by": STR,
        },
        "foreign_keys": {"batch_record_id": "batch_records",
                         "material_id": "raw_materials"},
    },
    "batch_steps": {
        "columns": {
            "id": ID, "batch_record_id": FK, "process": STR,
            "conducted_by": STR, "checked_by": STR, "done": BOOL,
            "done_at": TS,
        },
        "foreign_keys": {"batch_record_id": "batch_records"},
    },
    "retention_samples": {
        "columns": {
            "id": ID, "batch_no": SHORT, "batch_record_id": FK,
            "product_id": FK, "product_name": STR, "description": TEXT,
            "prod_date": DATE, "exp_date": DATE, "qty": NUM,
            "disposal_date": DATE, "status": SHORT, "remarks": TEXT,
            "inspected_by": STR, "approved_by": STR, "created_by": FK,
            "created_at": TS,
        },
        "foreign_keys": {"batch_record_id": "batch_records",
                         "product_id": "products", "created_by": "users"},
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
