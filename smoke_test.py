"""End-to-end smoke test for the Amamio Sales & Inventory Management System.

Runs against a throwaway temp data directory so it never touches your real
data/.  Run with:  python smoke_test.py   (exit code 0 = all passed).
"""
import io
import os
import shutil
import sys
import tempfile

import db
# Point storage at a fresh temp dir BEFORE the app is created / seeded.
db.DATA_DIR = tempfile.mkdtemp(prefix="amamio-smoke-")
# Uploaded sales files go to a temp copy of the sales-platform folder.
_SALES = tempfile.mkdtemp(prefix="amamio-sales-")
_HERE = os.path.dirname(os.path.abspath(__file__))
for _name in os.listdir(os.path.join(_HERE, "sales-platform")):
    shutil.copy(os.path.join(_HERE, "sales-platform", _name), _SALES)
os.environ["AMAMIO_SALES_DIR"] = _SALES

import app as appmod          # noqa: E402  (import after DATA_DIR override)
import platform_service as ps  # noqa: E402
import services               # noqa: E402

application = appmod.create_app()
fails = []


def check(cond, msg):
    print(("OK   " if cond else "FAIL ") + msg)
    if not cond:
        fails.append(msg)


def login(c, u, p):
    return c.post("/login", data={"username": u, "password": p},
                  follow_redirects=True)


def stock(name, kind="material"):
    table = "raw_materials" if kind == "material" else "products"
    item = db.query(table, name=name)[0]
    return services.current_stock(kind, item["id"]), item


ACCOUNTS = [("superadmin", "super123"), ("admin", "admin123"),
            ("receiving", "recv123"), ("production", "prod123"),
            ("packing", "pack123"), ("packer1", "member123"),
            ("assets", "assets123")]

# 1) every demo account logs in and gets a home screen with its tasks
for u, p in ACCOUNTS:
    with application.test_client() as c:
        check(login(c, u, p).status_code == 200, "login %s" % u)
        r = c.get("/dashboard")
        check(r.status_code == 200 and b"task-card" in r.data,
              "home screen for %s" % u)

# 1b) each user picks light, dark or "match my device"; it is remembered
with application.test_client() as c:
    login(c, "packer1", "member123")
    check(b'data-theme="dark"' in c.get("/dashboard").data, "dark theme by default")
    c.post("/settings/theme", data={"theme": "light"})
    check(b'data-theme="light"' in c.get("/dashboard").data,
          "light theme is saved and applied")
    c.post("/settings/theme", data={"theme": "system"})
    page = c.get("/dashboard").data
    check(b'data-theme-pref="system"' in page and b'data-theme="' not in page,
          "match-my-device leaves the choice to the device")
    check(c.post("/settings/theme", data={"theme": "pink"}).status_code == 400,
          "an unknown theme is refused")
with application.test_client() as c:
    login(c, "packer2", "member123")
    check(b'data-theme="dark"' in c.get("/dashboard").data,
          "one user's theme does not change another's")

# 1c) every page has an "About this page" note, and users can hide them
import page_notes             # noqa: E402

NOT_PAGES = {"static", "auth.root", "auth.login", "auth.logout",
             "honey.suggest", "qr.lookup", "qr.image", "qr.go",
             "platforms.export_csv", "platforms.import_file",
             "migration.download", "requests.bom_calc", "production.new"}
pages = {r.endpoint for r in application.url_map.iter_rules()
         if "GET" in r.methods and r.endpoint not in NOT_PAGES}
missing = sorted(p for p in pages if not page_notes.for_endpoint(p))
check(not missing, "every page has a note (%s)" % (", ".join(missing) or "all"))
stale = sorted(set(page_notes.NOTES) - pages)
check(not stale, "no note points at a page that no longer exists (%s)"
      % (", ".join(stale) or "none"))
with application.test_client() as c:
    login(c, "receiving", "recv123")
    check(b"About this page" in c.get("/receiving/new").data,
          "notes show by default")
    c.post("/settings/notes", data={"show": "0"})
    check(b'class="page-note' not in c.get("/receiving/new").data,
          "a user can hide the notes")
    c.post("/settings/notes", data={"show": "1"})
    check(b'class="page-note' in c.get("/receiving/new").data,
          "and turn them back on")

# 2) analytics + reports render charts
with application.test_client() as c:
    login(c, "admin", "admin123")
    for route in ("/analytics/", "/analytics/forecast", "/reports/"):
        r = c.get(route)
        check(r.status_code == 200 and b"<svg" in r.data,
              "%s renders chart" % route)

# 3) role guards hold
GUARDS = [
    ("packing", "pack123", "/receiving/", 403),
    ("packing", "pack123", "/approvals/", 403),
    ("packer1", "member123", "/platforms/", 403),
    ("packer1", "member123", "/requests/", 403),
    ("packer1", "member123", "/packing/new", 200),
    ("production", "prod123", "/receiving/new", 403),
    ("production", "prod123", "/receiving/inspection", 200),
    ("receiving", "recv123", "/receiving/new", 200),
    ("receiving", "recv123", "/packing/", 403),
    ("assets", "assets123", "/honey/", 403),
    ("admin", "admin123", "/migration/", 403),
    ("superadmin", "super123", "/migration/", 200),
]
for u, p, route, expected in GUARDS:
    with application.test_client() as c:
        login(c, u, p)
        check(c.get(route).status_code == expected,
              "%s -> %s is %d" % (u, route, expected))

# 4) Module 1, part 1 — the receiving head records a delivery
with application.test_client() as c:
    login(c, "receiving", "recv123")
    ginger_before, ginger = stock("Ginger")
    _, lemon = stock("Lemon")
    unread_before = len([n for n in db.read("notifications") if not n["is_read"]])
    r = c.post("/receiving/new", data={
        "supplier_id": "", "received_date": services.today_iso(),
        "po_no": "PO-T1", "delivery_ref": "DR-T1",
        "material_id": [ginger["id"], lemon["id"]],
        "qty_per_box": ["10", "100"], "boxes": ["2", "1"],
        "lot_no": ["LOT-A", ""], "expiry_date": ["", ""],
        "packaging_condition": ["Good / intact", ""],
        "temperature_c": ["26", ""]}, follow_redirects=False)
    check(r.status_code == 302 and "/labels" in r.headers.get("Location", ""),
          "receiving wizard saves and goes to the QR labels")
    batch = db.read("receiving_batches")[-1]
    boxes = db.query("receiving_boxes", batch_id=batch["id"])
    check(len(boxes) == 3 and all(b["status"] == "Awaiting Inspection"
                                  for b in boxes),
          "one box per QR label, all awaiting inspection")
    check(services.current_stock("material", ginger["id"]) == ginger_before,
          "receiving alone does not add stock")
    unread_after = len([n for n in db.read("notifications") if not n["is_read"]])
    check(unread_after > unread_before,
          "the team is notified a delivery arrived")
    payload = services.qr_payload(boxes[0]["box_code"])
    check("Ginger" in payload and "10 kg" in payload and "LOT-A" in payload,
          "QR label carries the item, quantity and lot")
    data = c.get("/qr/lookup?token=" + payload).get_json()
    check(data.get("kind") == "box", "scanning the full label text finds the box")
    check(c.get("/receiving/%d/labels" % batch["id"]).status_code == 200,
          "labels page renders")

# 5) Module 1, part 2 — inspection & cleaning: usable / can't use / damaged
with application.test_client() as c:
    login(c, "production", "prod123")
    damage_before = len(db.read("damage_records"))
    r = c.post("/receiving/box/%d/inspect" % boxes[0]["id"], data={
        "cleaned": "1", "usable_qty": "8.5", "unusable_qty": "1",
        "damaged_qty": "0.5", "unusable_reason": "Undersized",
        "damage_reason": "Bruised", "visual_inspection": "Pass",
        "coa_check": "Not required", "sampling_test": "Not required",
        "acceptance": "Accepted", "verified_by_name": "QA"},
        follow_redirects=True)
    after = services.current_stock("material", ginger["id"])
    check(abs(after - ginger_before - 8.5) < 0.001,
          "only the usable quantity joined stock")
    check(len(db.read("damage_records")) == damage_before + 2,
          "can't-be-used and damaged are both logged")
    box = db.get("receiving_boxes", boxes[0]["id"])
    check(box["status"] == "Accepted" and box["stage"] == "Storage Area",
          "accepted box moved to the Storage Area")
    # A missing reason is refused.
    c.post("/receiving/box/%d/inspect" % boxes[1]["id"], data={
        "cleaned": "1", "usable_qty": "9", "damaged_qty": "1",
        "visual_inspection": "Pass", "coa_check": "Complete",
        "sampling_test": "Passed", "acceptance": "Accepted"})
    check(db.get("receiving_boxes", boxes[1]["id"])["status"]
          == "Awaiting Inspection", "damage without a reason is refused")
    # Hold: nothing moves until the decision.
    c.post("/receiving/box/%d/inspect" % boxes[1]["id"], data={
        "cleaned": "1", "usable_qty": "10", "visual_inspection": "Pass",
        "coa_check": "Incomplete", "sampling_test": "Pending result",
        "acceptance": "Hold", "nonconformity": "Waiting for COA"})
    held = services.current_stock("material", ginger["id"])
    check(db.get("receiving_boxes", boxes[1]["id"])["status"] == "On Hold"
          and abs(held - after) < 0.001, "a box on hold adds no stock")
    c.post("/receiving/box/%d/hold" % boxes[1]["id"],
           data={"decision": "Accepted", "note": "COA received"})
    check(abs(services.current_stock("material", ginger["id"]) - held - 10)
          < 0.001, "accepting the held box adds its usable quantity")
    r = c.get("/receiving/report?from=2000-01-01")
    check(r.status_code == 200 and b"RECEIVING AND INSPECTION" in r.data.upper(),
          "receiving & inspection report renders")

# 6) Module 2 — honey: PASS to selling, FAILED to other products
with application.test_client() as c:
    login(c, "production", "prod123")
    honey_before, honey = stock("Raw Honey")
    made, _ = services.log_honey_containers(2, 10, 1, material_id=honey["id"])
    good, bad = made
    c.post("/honey/%d/qc" % good["id"], data={"result": "Pass",
           "moisture_pct": "18", "appearance": "Clear"})
    c.post("/honey/%d/qc" % bad["id"], data={"result": "Failed",
           "moisture_pct": "24", "appearance": "Fermented / off-smell"})
    check(abs(services.current_stock("material", honey["id"]) - honey_before - 10)
          < 0.001, "only passed honey joined sellable stock")
    processing = db.query("raw_materials", name=services.PROCESSING_HONEY)
    check(processing and processing[0]["stock_qty"] >= 10,
          "failed honey is kept as honey for processing")
    c.post("/honey/%d/allocate" % bad["id"],
           data={"product": services.HONEY_PASS_PRODUCTS[0], "kg": "5"})
    check(not db.get("honey_containers", bad["id"]).get("allocations"),
          "failed honey cannot go to a PASS product")
    c.post("/honey/%d/allocate" % bad["id"],
           data={"product": services.HONEY_FAIL_PRODUCTS[0], "kg": "4"})
    check(db.get("honey_containers", bad["id"])["remaining_kg"] == 6,
          "allocation records the kg used and what is left")

# 7) Module 4 — packing: packed, then disbursed or handed to the courier
with application.test_client() as c:
    login(c, "packer1", "member123")
    before, product = stock("Pure Honey 250 mL", "product")
    r = c.post("/packing/new", data={
        "channel": "Shopee", "packer_id": str(db.query("users", username="packer1")[0]["id"]),
        "pack_date": services.today_iso(), "order_ref": "SHP-TEST",
        "product_id": [str(product["id"])], "qty": ["3"], "damaged_qty": ["0"],
        "line_notes": [""]})
    run = db.read("packing_runs")[-1]
    check(run["status"] == "Packed" and abs(
        before - services.current_stock("product", product["id"]) - 3) < 0.001,
        "recording packing marks it packed and releases stock")
    c.post("/packing/%d/dispatch" % run["id"], data={
        "dispatch_type": "Handed to Courier", "handed_to": "Rider"})
    check(db.get("packing_runs", run["id"])["status"] == "Packed",
          "courier hand-over needs the courier name")
    c.post("/packing/%d/dispatch" % run["id"], data={
        "dispatch_type": "Handed to Courier", "courier": "J&T Express",
        "handed_to": "Rider Al", "tracking_no": "JT123", "parcel_count": "1"})
    check(db.get("packing_runs", run["id"])["status"] == "Handed to Courier",
          "run handed to the courier")
    summary = services.packing_summary()
    check(summary["courier_qty"] >= 3 and summary["disbursed_qty"] > 0,
          "packing summary counts packed, disbursed and courier separately")
    check(c.post("/packing/%d/cancel" % run["id"]).status_code == 403,
          "a packing member cannot cancel a run")

# 8) Module 5 — sales uploads and reports
# A made-up Shopify CSV goes through the whole flow (upload → preview → save
# → re-upload), so this runs anywhere.  The checks against the real
# marketplace exports run only where those files are present: they hold
# customer data and are kept out of the repository.
SHOPIFY_CSV = (
    "Name,Created at,Financial Status,Lineitem quantity,Lineitem name,"
    "Lineitem price,Lineitem sku,Lineitem discount,Billing Name,"
    "Shipping Province\n"
    "#1001,2026-10-12 10:00:00 +0800,paid,2,Moringa Powder 100g,150,,0,"
    "Ana,Agusan del Norte\n"
    "#1002,2026-10-13 11:00:00 +0800,refunded,1,Pure Honey 250ml,399,,0,"
    "Ben,Cebu\n")
HAVE_EXPORTS = all(os.path.exists(os.path.join(_SALES, n))
                   for n in ("shopee.xlsx", "lazada.xlsx", "tiktok.xlsx"))


def upload(client, platform, name, content):
    """Upload a file and confirm its preview; returns (redirect, preview page)."""
    r = client.post("/platforms/upload", data={
        "platform": platform, "source": "upload",
        "workbook": (io.BytesIO(content), name)},
        content_type="multipart/form-data")
    loc = r.headers.get("Location", "")
    page = client.get(loc) if loc else None
    if loc:
        filename = loc.split("file=")[1].split("&")[0]
        template = [t for t in ps.all_templates() if t["platform"] == platform][0]
        client.post("/platforms/upload/preview", data={
            "file": filename, "platform": platform,
            "template_id": template["id"]})
    return r, page


with application.test_client() as c:
    login(c, "packing", "pack123")
    r, preview = upload(c, "Shopify", "shopify-orders.csv", SHOPIFY_CSV.encode())
    check(r.status_code == 302 and preview is not None
          and preview.status_code == 200 and b"Shopify" in preview.data,
          "upload goes to a preview that recognises the platform")
    rows = [x for x in db.read("platform_sales") if x["platform"] == "Shopify"]
    check(len(rows) == 2 and rows[0]["net_amount"] == 300
          and rows[0]["product_id"], "Shopify CSV saved and matched to the catalog")
    check(rows[1]["status_group"] == "Returned", "a refunded order is not a sale")
    before = len(db.read("platform_sales"))
    r, preview = upload(c, "Shopify", "shopify-orders.csv", SHOPIFY_CSV.encode())
    check(b"already uploaded" in preview.data
          and len(db.read("platform_sales")) == before,
          "re-uploading the same export adds nothing twice")
    report = ps.sales_report(grain="month")
    check(report["kpis"]["orders"] > 0 and report["periods"],
          "monthly sales report has periods and orders")
    r = c.get("/platforms/export.csv?grain=week")
    check(r.status_code == 200 and b"Total" in r.data,
          "weekly report downloads as CSV")
    for view in ("overview", "periods", "products", "orders", "uploads"):
        check(c.get("/platforms/?view=%s&range=all" % view).status_code == 200,
              "sales report view: %s" % view)

    if HAVE_EXPORTS:
        check(any(x["platform"] == "Shopee" for x in db.read("platform_sales")),
              "sample exports were imported on first run")
        shopee = [x for x in db.read("platform_sales") if x["platform"] == "Shopee"]
        check(abs(sum(x["net_amount"] for x in shopee) - 46424.0) < 0.01,
              "Shopee lines use the line subtotal, not the repeated order total")
        tiktok = [x for x in db.read("platform_sales") if x["platform"] == "TikTok"]
        check(any(x["status_group"] == "Adjustment" for x in tiktok),
              "TikTok tax lines count as adjustments, not sales")
    else:
        print("SKIP checks on the sample exports (sales-platform/*.xlsx not "
              "present — they are kept out of git)")

# 8b) Module 3, production records, facility records — pages and rules
import assets_service      # noqa: E402
import facility_service    # noqa: E402
import production_service  # noqa: E402

PAGES = {
    "assets": ["/assets/", "/assets/move", "/assets/new", "/assets/movements",
               "/assets/print/inventory", "/assets/1", "/assets/1/log",
               "/supplies/", "/supplies/move", "/supplies/count",
               "/supplies/report", "/supplies/movements",
               "/facility/sanitation", "/facility/sanitation/new",
               "/facility/sanitation/print", "/facility/pest",
               "/facility/pest/print", "/suppliers/",
               "/suppliers/new", "/suppliers/print"],
    "production": ["/production/", "/production/batch/new", "/production/batch/1",
                   "/production/batch/1/print", "/production/daily-report",
                   "/production/daily-report?view=day&all=1",
                   "/production/retention", "/production/retention/new",
                   "/production/retention/print"],
}
for user, pw in (("assets", "assets123"), ("production", "prod123")):
    with application.test_client() as c:
        login(c, user, pw)
        bad = [u for u in PAGES[user] if c.get(u).status_code != 200]
        if user == "assets":   # this month is done in the demo -> opens it
            r = c.get("/facility/pest/new")
            bad += [] if r.status_code in (200, 302) else ["/facility/pest/new"]
        check(not bad, "%s pages render (%s)" % (user, ", ".join(bad) or "all"))

# Equipment OUT then back IN, every move recorded.
heat_gun = db.query("assets", item_no="AFP-023")[0]
out_before = heat_gun.get("qty_out") or 0
move, err = assets_service.record_movement(
    heat_gun["id"], "OUT", assets_service.OUT_BORROWED, 1, person="Packing team",
    destination="Packing Area", user_id=1, notify=False)
check(not err and db.get("assets", heat_gun["id"])["qty_out"] == out_before + 1,
      "equipment OUT is recorded and counted as out")
move, err = assets_service.record_movement(
    heat_gun["id"], "IN", assets_service.IN_RETURNED, 1, person="Packing team",
    user_id=1, notify=False)
check(not err and db.get("assets", heat_gun["id"])["qty_out"] == out_before,
      "equipment IN brings it back")
check(len(db.query("asset_movements", asset_id=heat_gun["id"])) >= 2,
      "every equipment movement is logged")

# Supplies: an OUT can never exceed what is on hand.
tape_before, tape = stock("Packaging Tape")
_, err = assets_service.record_supply_movement(
    tape["id"], "OUT", tape_before + 1, assets_service.SUPPLY_OUT_REASONS[1],
    person="Packing", user_id=1, notify=False)
check(bool(err), "supply OUT larger than stock is refused")
_, err = assets_service.record_supply_movement(
    tape["id"], "OUT", 2, assets_service.SUPPLY_OUT_REASONS[1], person="Packing",
    user_id=1, notify=False)
check(not err and abs(services.current_stock("material", tape["id"])
                      - (tape_before - 2)) < 0.001, "supply OUT reduces stock")
report = assets_service.month_end_report("packaging", services.this_month())
check(bool(report), "month-end report builds")

# Batch Manufacturing Record: stock moves once, on APPROVED.
mp_before, moringa_p = stock("Moringa Powder 100 g", "product")
lines = production_service.default_dispensing(moringa_p["id"], 2)
rec, err = production_service.start_batch(
    1, moringa_p["id"], 2, services.today_iso(), "",
    services.today_iso() + "T08:00", lines,
    production_service.procedure_for(moringa_p))
check(not err and rec, "batch record started")
production_service.sign_dispensing(rec["id"], [("Ana", "Ben")] * len(lines), 1)
for i in range(len(rec["steps"])):
    production_service.sign_step(rec["id"], i, "Ana", "Ben", 1)
done, err = production_service.finish_batch(
    rec["id"], 1, services.today_iso() + "T15:00", 2,
    production_service.APPROVED, "QA Officer")
check(not err and abs(services.current_stock("product", moringa_p["id"])
                      - mp_before - 2) < 0.001,
      "an approved batch adds its yield to finished goods")
_, err = production_service.finish_batch(
    rec["id"], 1, services.today_iso() + "T15:00", 2,
    production_service.APPROVED, "QA Officer")
check(bool(err) and abs(services.current_stock("product", moringa_p["id"])
                        - mp_before - 2) < 0.001, "a batch never posts twice")

# Facility: today's pre-production check; an open repair shows up as open.
areas = [{"current_status": facility_service.CLEAN, "action": "",
          "date_undertaken": "", "remarks": ""} for _ in facility_service.LOCATIONS]
areas[2] = {"current_status": facility_service.NEEDS_REPAIR,
            "action": "Fix the leaking faucet", "date_undertaken": "",
            "remarks": ""}
open_before = facility_service.open_sanitation_count()
try:
    facility_service.save_sanitation(1, services.today_iso(), facility_service.PRE,
                                     areas, "Cleaner", "Supervisor", notify=False)
    saved = True
except facility_service.RecordError:
    saved = False
check(saved and facility_service.open_sanitation_count() == open_before + 1,
      "sanitation record saved; the open repair is tracked")

# 9) approve a purchase request -> receive via QR adds material stock
with application.test_client() as c:
    login(c, "admin", "admin123")
    req = [r for r in db.read("purchase_requests")
           if r["status"] == "Pending Approval"
           and r["items"][0].get("material_id")][0]
    item = req["items"][0]
    before = services.current_stock("material", item["material_id"])
    c.post("/approvals/%d" % req["id"], data={"action": "approve",
           "approved_qty_%d" % item["item_id"]: str(item["requested_qty"])},
           follow_redirects=True)
    tok = db.get("purchase_requests", req["id"])["items"][0]["qr_token"]
    c.post("/qr/receive", json={"token": tok})
    after = services.current_stock("material", item["material_id"])
    check(after > before, "QR receive increased material stock")
    again = c.post("/qr/receive", json={"token": tok})
    check(again.status_code == 400
          and services.current_stock("material", item["material_id"]) == after,
          "re-receive is idempotent")

# 10) a request without a reason is refused
with application.test_client() as c:
    login(c, "production", "prod123")
    before = len(db.read("purchase_requests"))
    c.post("/requests/new/production",
           data={"product_id": 1, "qty": 5, "reason": "",
                 "material_id": 1, "requested_qty": 2}, follow_redirects=True)
    check(len(db.read("purchase_requests")) == before,
          "a request without a reason is refused")

# 11) customer order -> confirm deducts stock -> pay -> Paid
with application.test_client() as c:
    login(c, "packing", "pack123")
    _, product = stock("Pure Honey 250 mL", "product")
    c.post("/orders/new", data={"customer_id": 1, "discount": 0,
           "product_id": product["id"], "qty": 3, "unit_price": 399},
           follow_redirects=True)
    o = [o for o in db.read("sales_orders") if o["status"] == "Pending"][-1]
    before = services.current_stock("product", product["id"])
    c.post("/orders/%d/confirm" % o["id"], follow_redirects=True)
    check(services.current_stock("product", product["id"]) == before - 3,
          "order confirm deducted stock")
    c.post("/orders/%d/pay" % o["id"], data={"amount": o["total"]},
           follow_redirects=True)
    check(db.get("sales_orders", o["id"])["payment_status"] == "Paid",
          "order fully paid")

# 12) QR codes resolve to the right kind of record
with application.test_client() as c:
    login(c, "admin", "admin123")
    for token, kind in (("RB-1", "box"), ("HC-1", "container"),
                        ("PK-1", "packing")):
        data = c.get("/qr/lookup?token=%s" % token).get_json()
        check(bool(data) and data.get("kind") == kind,
              "%s resolves as a %s" % (token, kind))
    check(c.get("/qr/image/RB-1").status_code == 200, "QR image renders")

# 13) the MySQL export builds, including the new tables
import mysql_export            # noqa: E402

schema = mysql_export.build_schema_sql()
data_sql = mysql_export.build_data_sql()
for table in ("receiving_boxes", "packing_items", "honey_allocations",
              "assets", "asset_movements", "stock_movements",
              "month_end_count_lines", "batch_dispensing", "batch_steps",
              "retention_samples", "sanitation_areas", "pest_control_areas"):
    check("CREATE TABLE `%s`" % table in schema,
          "MySQL schema has %s" % table)
check("INSERT INTO `users`" in data_sql, "MySQL data dump includes rows")

# 14) chatbot answers
with application.test_client() as c:
    login(c, "admin", "admin123")
    j = c.post("/chatbot/ask",
               json={"question": "what is low in stock?"}).get_json()
    check(bool(j and j.get("answer")), "chatbot answers")

print("\n=== %d failure(s) ===" % len(fails))
sys.exit(1 if fails else 0)
