"""End-to-end smoke test for the Amamio Sales & Inventory Management System.

Runs against a throwaway temp data directory so it never touches your real
data/.  Run with:  python smoke_test.py   (exit code 0 = all passed).
"""
import sys
import tempfile

import db
# Point storage at a fresh temp dir BEFORE the app is created / seeded.
db.DATA_DIR = tempfile.mkdtemp(prefix="amamio-smoke-")

import app as appmod          # noqa: E402  (import after DATA_DIR override)
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


ACCOUNTS = [("superadmin", "super123"), ("admin", "admin123"),
            ("production", "prod123"), ("packing", "pack123"),
            ("assets", "assets123")]

# 1) every demo account logs in and loads its dashboard
for u, p in ACCOUNTS:
    with application.test_client() as c:
        check(login(c, u, p).status_code == 200, "login %s" % u)
        check(c.get("/dashboard").status_code == 200, "dashboard %s" % u)

# 2) analytics + reports render charts
with application.test_client() as c:
    login(c, "admin", "admin123")
    for route in ("/analytics/", "/analytics/forecast", "/reports/"):
        r = c.get(route)
        check(r.status_code == 200 and b"<svg" in r.data,
              "%s renders chart" % route)

# 3) role guards hold
with application.test_client() as c:
    login(c, "packing", "pack123")
    check(c.get("/production/new").status_code == 403,
          "packing head blocked from production")
    check(c.get("/approvals/").status_code == 403,
          "packing head blocked from approvals")
    check(c.get("/receiving/").status_code == 403,
          "packing head blocked from receiving")
with application.test_client() as c:
    login(c, "admin", "admin123")
    check(c.get("/migration/").status_code == 403,
          "admin blocked from the MySQL export (super admin only)")
with application.test_client() as c:
    login(c, "superadmin", "super123")
    check(c.get("/migration/").status_code == 200, "super admin reaches migration")

# 4) receiving: only the GOOD quantity joins stock, damage is logged
with application.test_client() as c:
    login(c, "production", "prod123")
    material = db.query("raw_materials", name="Ginger")[0]
    before = services.current_stock("material", material["id"])
    batch = services.create_receiving_batch(None, services.today_iso(), 1)
    boxes, _ = services.add_receiving_box(batch["id"], material["id"], 10, 1)
    c.post("/receiving/box/%d/check" % boxes[0]["id"],
           data={"good_qty": "9", "damaged_qty": "1",
                 "damage_reason": "Bruised"}, follow_redirects=True)
    after = services.current_stock("material", material["id"])
    check(abs(after - before - 9) < 0.001,
          "receiving added only the good quantity")
    check(any(d["reference"] == boxes[0]["box_code"]
              for d in db.read("damage_records")), "damage recorded per box")

# 5) honey QC: Pass sells, Failed is routed to other products
with application.test_client() as c:
    login(c, "production", "prod123")
    honey = db.query("raw_materials", name="Raw Honey")[0]
    before = services.current_stock("material", honey["id"])
    good, _ = services.create_honey_container(10, 1, material_id=honey["id"])
    bad, _ = services.create_honey_container(10, 1, material_id=honey["id"])
    c.post("/honey/%d" % good["id"], data={"result": "Pass",
           "moisture_pct": "18", "appearance": "Clear"}, follow_redirects=True)
    c.post("/honey/%d" % bad["id"], data={"result": "Failed",
           "moisture_pct": "24", "appearance": "Fermented / off-smell"},
           follow_redirects=True)
    after = services.current_stock("material", honey["id"])
    check(abs(after - before - 10) < 0.001, "only passed honey joined stock")
    check(db.get("honey_containers", good["id"])["disposition"] == "For Selling",
          "passed container routed to selling")
    check(db.get("honey_containers", bad["id"])["disposition"]
          == "For Other Products", "failed container routed to other products")

# 6) packing: a platform run releases finished goods on pack
with application.test_client() as c:
    login(c, "packing", "pack123")
    product = db.read("products")[0]
    before = services.current_stock("product", product["id"])
    run, err = services.create_packing_run(
        "Shopee", None, [{"product_id": product["id"], "qty": 2}], 1)
    check(run is not None and not err, "packing run created")
    c.post("/packing/%d/packed" % run["id"], follow_redirects=True)
    check(abs(before - services.current_stock("product", product["id"]) - 2)
          < 0.001, "packing released finished goods")

# 7) approve a purchase request -> receive via QR adds material stock
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

# 8) a request without a reason is refused
with application.test_client() as c:
    login(c, "production", "prod123")
    before = len(db.read("purchase_requests"))
    c.post("/requests/new/production",
           data={"product_id": 1, "qty": 5, "reason": "",
                 "material_id": 1, "requested_qty": 2}, follow_redirects=True)
    check(len(db.read("purchase_requests")) == before,
          "a request without a reason is refused")

# 9) production consumes materials + adds finished goods
with application.test_client() as c:
    login(c, "production", "prod123")
    before = services.current_stock("product", 1)
    c.post("/production/new", data={"product_id": 1, "qty": 5},
           follow_redirects=True)
    check(services.current_stock("product", 1) == before + 5,
          "production added stock")

# 10) customer order -> confirm deducts stock -> pay -> Paid
with application.test_client() as c:
    login(c, "packing", "pack123")
    c.post("/orders/new", data={"customer_id": 1, "discount": 0, "product_id": 1,
           "qty": 3, "unit_price": 487}, follow_redirects=True)
    o = [o for o in db.read("sales_orders") if o["status"] == "Pending"][-1]
    before = services.current_stock("product", 1)
    c.post("/orders/%d/confirm" % o["id"], follow_redirects=True)
    check(services.current_stock("product", 1) == before - 3,
          "order confirm deducted stock")
    c.post("/orders/%d/pay" % o["id"], data={"amount": o["total"]},
           follow_redirects=True)
    check(db.get("sales_orders", o["id"])["payment_status"] == "Paid",
          "order fully paid")

# 11) QR codes resolve to the right kind of record
with application.test_client() as c:
    login(c, "admin", "admin123")
    for token, kind in (("RB-1", "box"), ("HC-1", "container"),
                        ("PK-1", "packing")):
        data = c.get("/qr/lookup?token=%s" % token).get_json()
        check(bool(data) and data.get("kind") == kind,
              "%s resolves as a %s" % (token, kind))

# 12) the MySQL export builds
import mysql_export            # noqa: E402

schema = mysql_export.build_schema_sql()
data_sql = mysql_export.build_data_sql()
check("CREATE TABLE `receiving_boxes`" in schema,
      "MySQL schema includes the receiving tables")
check("CREATE TABLE `packing_items`" in schema,
      "MySQL schema splits embedded lists into child tables")
check("INSERT INTO `users`" in data_sql, "MySQL data dump includes rows")

# 13) chatbot answers
with application.test_client() as c:
    login(c, "admin", "admin123")
    j = c.post("/chatbot/ask",
               json={"question": "what is low in stock?"}).get_json()
    check(bool(j and j.get("answer")), "chatbot answers")

print("\n=== %d failure(s) ===" % len(fails))
sys.exit(1 if fails else 0)
