"""The home screen: "What would you like to do?"

Each role sees only the few things it does, as big task cards (with a count
when something is waiting), then a short "Waiting for you" list.  Admins also
get a handful of headline figures.  Nothing here moves data; it only reads.
"""
from datetime import date, timedelta

from flask import url_for

import assets_service
import db
import facility_service
import platform_service as ps
import services
from security import can, is_admin, normalize_role


def _task(title, sub, icon, endpoint, count=0, primary=False, **args):
    return {"title": title, "sub": sub, "icon": icon,
            "url": url_for(endpoint, **args), "count": count,
            "primary": primary}


def _counts():
    boxes = db.read("receiving_boxes")
    runs = db.read("packing_runs")
    honey = services.honey_summary()
    batches = db.read("batch_records")
    month = services.this_month()
    return {
        "awaiting": sum(1 for b in boxes
                        if services.box_status(b) == services.BOX_AWAITING),
        "held": sum(1 for b in boxes if services.box_status(b) == services.BOX_HOLD),
        "open_deliveries": sum(1 for b in db.read("receiving_batches")
                               if b.get("status") == "Open"),
        "honey_pending": honey["pending"],
        "honey_to_allocate": honey["to_allocate"],
        "packing_open": sum(1 for r in runs if r.get("status") == "In Progress"),
        "packed_waiting": sum(1 for r in runs if r.get("status") == "Packed"),
        "batches_open": sum(1 for b in batches if b.get("status") == "In Progress"),
        "approvals": sum(1 for r in db.read("purchase_requests")
                         if r.get("status") == "Pending Approval")
                     + sum(1 for r in db.read("sales_requests")
                           if r.get("status") == "Pending Approval"),
        "low_stock": len(services.low_stock_materials()),
        "maintenance_due": len(assets_service.maintenance_due()),
        "assets_out": len(assets_service.assets_out()),
        "pest_missing": not any(r.get("period") == month
                                for r in db.read("pest_control_records")),
        "sanitation_open": facility_service.open_sanitation_count(),
        "sanitation_today": facility_service.facility_overview()["sanitation_today"],
    }


def tasks_for(user, c):
    """The task cards for one user, most important first."""
    role = normalize_role(user.get("role"))
    t = []
    if role == "receiving_head":
        t += [
            _task("Receive a delivery", "Record what arrived and print a QR label for each box",
                  "receiving", "receiving.new", primary=True),
            _task("Log honey containers", "Weigh, label and send for moisture check",
                  "honey", "honey.new"),
            _task("Open deliveries", "Deliveries with boxes still waiting for inspection",
                  "receiving", "receiving.index", count=c["open_deliveries"]),
            _task("Supplies in / out", "Packaging, cleaning and office supplies",
                  "swap", "supplies.index"),
            _task("Scan a QR code", "See what a box or container is and where it is",
                  "qr", "qr.scan"),
        ]
    elif role == "production_head":
        t += [
            _task("Inspect & clean boxes", "Count usable, can't be used and damaged",
                  "inspect", "receiving.inspection", count=c["awaiting"] + c["held"],
                  primary=bool(c["awaiting"])),
            _task("Check honey", "Moisture & appearance — PASS or FAILED",
                  "honey", "honey.index", count=c["honey_pending"]),
            _task("Start a batch record", "Dispensing, procedure, yield and QA",
                  "production", "production.index", count=c["batches_open"],
                  primary=not c["awaiting"]),
            _task("Daily production report", "IN, OUT and balance per product this month",
                  "reports", "production.daily_report"),
            _task("Cleaning & sanitation", "Pre- and post-production check of each area",
                  "sparkle", "facility.sanitation"),
            _task("Scan a QR code", "Open any box, container or packing run",
                  "qr", "qr.scan"),
        ]
    elif role in ("packing_head", "packing_member"):
        t += [
            _task("Record packing", "What was packed, for which channel, by whom",
                  "packing", "packing.new", primary=True),
            _task("Send out packed parcels", "Disburse, or hand to the courier",
                  "truck", "packing.index", count=c["packed_waiting"]),
            _task("Scan a QR code", "Open a packing run from its label", "qr", "qr.scan"),
        ]
        if role == "packing_head":
            t += [
                _task("Upload sales file", "Shopee, TikTok, Lazada, Shopify exports",
                      "upload", "platforms.upload"),
                _task("Sales reports", "Weekly, monthly and yearly sales per platform",
                      "chart", "platforms.index"),
            ]
    elif role == "assets_head":
        t += [
            _task("Record equipment IN / OUT", "Borrowed, sent for repair, returned",
                  "tools", "assets.index", count=c["assets_out"], primary=True),
            _task("Supplies in / out", "Cleaning, packaging and office supplies",
                  "swap", "supplies.index", count=c["low_stock"]),
            _task("Maintenance due", "Log service on equipment",
                  "assets", "assets.index", count=c["maintenance_due"]),
            _task("Cleaning & sanitation", "Pre- and post-production check of each area",
                  "sparkle", "facility.sanitation", count=c["sanitation_open"]),
            _task("Pest control", "Monthly inspection of every area",
                  "shield", "facility.pest", count=1 if c["pest_missing"] else 0),
        ]
    else:   # admins
        t += [
            _task("Approvals", "Purchase and stock-release requests waiting for you",
                  "approvals", "approvals.index", count=c["approvals"],
                  primary=bool(c["approvals"])),
            _task("Sales reports", "What sold, on which platform, week by week",
                  "chart", "platforms.index", primary=not c["approvals"]),
            _task("Receiving & inspection", "Deliveries and boxes on the floor",
                  "receiving", "receiving.index", count=c["awaiting"]),
            _task("Packing & dispatch", "Packed, disbursed and with the courier",
                  "packing", "packing.index", count=c["packed_waiting"]),
            _task("Equipment & supplies", "Every IN and OUT, maintenance due",
                  "tools", "assets.index", count=c["maintenance_due"]),
            _task("Reports", "Receiving, QC, packing, damage and AI insight",
                  "reports", "reports.index"),
        ]
    return t


def waiting_for(user, c):
    """A short list of things that need someone's attention."""
    items = []

    def add(ok, text, sub, endpoint, **args):
        if ok:
            items.append({"title": text, "sub": sub,
                          "url": url_for(endpoint, **args)})

    add(can(user, "inspection") and c["awaiting"],
        "%d box(es) waiting for inspection" % c["awaiting"],
        "Received at the Receiving Area", "receiving.inspection")
    add(can(user, "inspection") and c["held"],
        "%d box(es) on hold" % c["held"], "Waiting for a test, document or QA decision",
        "receiving.inspection")
    add(can(user, "honey") and c["honey_pending"],
        "%d honey container(s) to check" % c["honey_pending"],
        "Moisture & appearance", "honey.index")
    add(can(user, "honey") and c["honey_to_allocate"],
        "%d checked container(s) not fully used" % c["honey_to_allocate"],
        "Record which products the honey went into", "honey.index")
    add(can(user, "production") and c["batches_open"],
        "%d batch record(s) in progress" % c["batches_open"],
        "Continue where you left off", "production.index")
    add(can(user, "packing") and c["packing_open"],
        "%d packing run(s) not marked packed" % c["packing_open"], "",
        "packing.index")
    add(can(user, "packing") and c["packed_waiting"],
        "%d packed run(s) waiting to go out" % c["packed_waiting"],
        "Disburse or hand to the courier", "packing.index")
    add(can(user, "approvals") and c["approvals"],
        "%d request(s) to approve" % c["approvals"], "", "approvals.index")
    add(can(user, "assets") and c["maintenance_due"],
        "%d maintenance job(s) due" % c["maintenance_due"],
        "Within the next 14 days", "assets.index")
    add(can(user, "supplies") and c["low_stock"],
        "%d item(s) at or below reorder level" % c["low_stock"],
        "Raise a request before they run out", "supplies.index")
    add(can(user, "facility") and c["sanitation_open"],
        "%d area(s) still need cleaning or repair" % c["sanitation_open"],
        "From the cleaning & sanitation checks", "facility.sanitation",
        show="action")
    add(can(user, "facility") and len(c["sanitation_today"]) < 2
        and normalize_role(user.get("role")) in ("assets_head", "production_head"),
        "Today's cleaning check: %s" % (
            "post-production still to do" if c["sanitation_today"]
            else "not yet recorded"),
        "Pre- and post-production, every area", "facility.sanitation_new")
    add(can(user, "facility") and c["pest_missing"]
        and normalize_role(user.get("role")) in ("assets_head", "super_admin", "admin"),
        "Pest control not yet done this month", "Monthly inspection", "facility.pest")
    return items


def admin_figures():
    today = date.today()
    month_from = today.replace(day=1).isoformat()
    week_from = (today - timedelta(days=today.weekday())).isoformat()
    _, month_sales = ps.platform_summary(ps.sales_rows(date_from=month_from))
    packing = services.packing_summary(date_from=week_from)
    honey = services.honey_summary()
    return [
        {"label": "Platform sales this month", "value": services.fmt_peso(month_sales["net"]),
         "good": True},
        {"label": "Orders this month", "value": month_sales["orders"]},
        {"label": "Packed this week", "value": services.fmt_qty(packing["packed_qty"])},
        {"label": "Honey pass rate", "value": "%s%%" % honey["pass_rate"]},
    ]


def context(user):
    c = _counts()
    return {
        "tasks": tasks_for(user, c),
        "waiting": waiting_for(user, c),
        "figures": admin_figures() if is_admin(user) else [],
        "greeting": _greeting(),
    }


def _greeting():
    from datetime import datetime
    hour = datetime.now().hour
    return ("Good morning" if hour < 12 else
            "Good afternoon" if hour < 18 else "Good evening")
