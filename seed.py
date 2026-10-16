"""Idempotent demo seeding for the Amamio Sales & Inventory Management System.

Seeds only when there are no users yet.  Master data comes from the client's
own paper forms (``seed_catalog.py``): the product list of the Daily
Production Report, the supplies on the four month-end reports, the asset
register and the supplier directory.  On top of that it creates a login per
role, ~12 weeks of backdated history (so the AI has data to forecast), and
live examples of every monitored flow: deliveries received and inspected,
honey containers that passed and failed, packing runs that were disbursed or
handed to the courier, and the sample marketplace exports imported.
"""
import importlib
import os
import random
from datetime import datetime, timedelta, timezone

from werkzeug.security import generate_password_hash

import db
import seed_catalog as cat
import services
from security import ROLE_LABELS, ROLES

WEEKS = 12
TAG = "seed-history"

# (name, username, password, role) — change these before going live.
DEMO_USERS = [
    ("Amamio Super Admin", "superadmin", "super123", "super_admin"),
    ("Amamio Admin", "admin", "admin123", "admin"),
    ("Receiving Team Head", "receiving", "recv123", "receiving_head"),
    ("Production Team Head", "production", "prod123", "production_head"),
    ("Packing Team Head", "packing", "pack123", "packing_head"),
    ("Packer — Joy", "packer1", "member123", "packing_member"),
    ("Packer — Mark", "packer2", "member123", "packing_member"),
    ("Assets Maintenance Head", "assets", "assets123", "assets_head"),
]


def _iso(dt):
    return dt.isoformat()


def _this_monday():
    now = datetime.now(timezone.utc)
    monday = now - timedelta(days=now.weekday())
    return monday.replace(hour=9, minute=0, second=0, microsecond=0)


def _days_ago(n):
    return (datetime.now(timezone.utc) - timedelta(days=n)).date().isoformat()


def seed_if_empty():
    if db.read("users"):
        return

    _seed_roles()
    users = _seed_users()
    suppliers = _seed_suppliers()
    _seed_customers()
    materials = _seed_materials(suppliers)
    products = _seed_products()
    _seed_assets()
    _seed_bom(materials, products)
    _seed_history(users, materials, products)
    _seed_receiving(users, suppliers, materials)
    _seed_honey(users, suppliers, materials)
    _seed_packing(users, products)
    _seed_live_docs(users, products, materials)
    _seed_platform_sales(users)
    _seed_module_demos(users)
    _reconcile_opening_balances()
    _seed_ai_snapshots()


def _reconcile_opening_balances():
    """Make the backdated demo ledger agree with the demo stock levels.

    Stock levels are set directly, but the history adds backdated
    movements; walking the ledger backwards from today's stock could then
    dip below zero (a report would show a negative balance).  Where it
    would, an opening balance is booked before the first movement and the
    stock raised by the same amount, so every running balance is >= 0."""
    txns = db.read("inventory_transactions")
    by_item = {}
    for t in txns:
        by_item.setdefault((t["item_type"], t["item_id"]), []).append(t)
    openings = []
    for (item_type, item_id), rows in by_item.items():
        rows.sort(key=lambda t: t.get("timestamp") or "")
        current = services.current_stock(item_type, item_id)
        running = current - sum(float(t["change_qty"]) for t in rows)
        lowest = running
        for t in rows:
            running += float(t["change_qty"])
            lowest = min(lowest, running)
        if lowest >= -1e-9:
            continue
        deficit = round(-lowest, 3)
        first = datetime.fromisoformat(rows[0]["timestamp"]) - timedelta(minutes=1)
        openings.append(_txn_dict(item_type, item_id, deficit, "adjusted",
                                  _iso(first), None))
        openings[-1]["reference_id"] = "opening balance"
        table = "raw_materials" if item_type == "material" else "products"
        db.update(table, item_id, {"stock_qty": round(current + deficit, 3)})
    db.insert_many("inventory_transactions", openings)


def _seed_ai_snapshots():
    """Populate the AI_Forecasts / AI_Recommendations tables from the demo data."""
    import ai
    services.save_ai_forecasts(ai.forecast_all_products())
    services.save_ai_recommendations(ai.all_recommendations())


def _seed_roles():
    for key, name, desc in ROLES:
        db.insert("roles", {"key": key, "name": name, "description": desc})


def make_user(name, username, password, role):
    return db.insert("users", {
        "name": name, "username": username,
        "password_hash": generate_password_hash(password),
        "role": role, "email": "%s@amamio.ph" % username,
        "phone": "", "team": ROLE_LABELS.get(role, role),
        "active": True, "last_login": None,
        "created_at": services.now_iso(),
    })


def _seed_users():
    users = {}
    for name, username, pw, role in DEMO_USERS:
        u = make_user(name, username, pw, role)
        users.setdefault(role, u)
        users[username] = u
    return users


def _seed_suppliers():
    suppliers = {}
    now = services.now_iso()
    rows = []
    for name, category, items, contact in cat.DEMO_RAW_SUPPLIERS:
        rows.append({"name": name, "tin": "", "category": category,
                     "contact_person": "", "phone": contact, "email": "",
                     "address": "", "materials_supplied": items,
                     "buy_from": "", "lead_time_days": 3, "notes": "Demo supplier",
                     "created_at": now})
    for name, tin, category, items, contact in cat.SUPPLIERS:
        is_phone = any(ch.isdigit() for ch in contact)
        rows.append({"name": name, "tin": tin, "category": category,
                     "contact_person": contact.split(" 0")[0] if is_phone and not contact[:1].isdigit() else "",
                     "phone": contact[contact.find("0"):] if is_phone else "",
                     "email": "", "address": "", "materials_supplied": items,
                     "buy_from": "" if is_phone else contact,
                     "lead_time_days": None, "notes": "", "created_at": now})
    for row in db.insert_many("suppliers", rows):
        suppliers[row["name"]] = row
    return suppliers


def _seed_customers():
    data = [
        ("Metro Grocers", "Liza Tan", "0917-200-3001",
         "purchasing@metrogrocers.ph", "Butuan City", "VIP"),
        ("Health Hub Store", "Marco Dela Cruz", "0917-200-3002",
         "orders@healthhub.ph", "Cagayan de Oro City", "VIP"),
        ("Sunrise Cafe", "Nina Santos", "0917-200-3003",
         "nina@sunrisecafe.ph", "Nasipit, Agusan del Norte", "Walk-in"),
        ("Wellness Mart", "Oliver Yu", "0917-200-3004",
         "buyer@wellnessmart.ph", "Davao City", "VIP"),
    ]
    for name, contact, phone, email, addr, channel in data:
        db.insert("customers", {
            "name": name, "contact_person": contact, "phone": phone,
            "email": email, "address": addr, "channel": channel, "notes": "",
            "created_at": services.now_iso(),
        })


def _seed_materials(suppliers):
    produce = suppliers["Highland Produce Traders"]["id"]
    honey = suppliers["Mindanao Forest Apiary"]["id"]
    cacao = suppliers["Agusan Cacao Growers"]["id"]
    by_cat = {"packaging": suppliers["Davao CVI"]["id"],
              "cleaning": suppliers["Sanitary Care Products Asia"]["id"],
              "office": suppliers["Yopsun"]["id"]}
    raw_source = {"Raw Honey": honey, "Honey Comb": honey,
                  "Cacao Beans": cacao}
    now = services.now_iso()
    rows = []
    for category, sub, name, unit, mode, stock, reorder, cost in cat.MATERIALS:
        supplier_id = (raw_source.get(name, produce) if category == "raw"
                       else by_cat.get(category))
        rows.append({
            "name": name, "category": category, "subcategory": sub,
            "unit": unit, "track_mode": mode, "stock_qty": stock,
            "reorder_level": reorder, "supplier_id": supplier_id,
            "unit_cost": cost, "expiry_date": "",
            "storage_location": {"raw": "Storage Area",
                                 "packaging": "Packing Area",
                                 "cleaning": "Utility Room",
                                 "office": "Office"}[category],
            "created_at": now,
        })
    return {m["name"]: m for m in db.insert_many("raw_materials", rows)}


def _seed_products():
    now = services.now_iso()
    rows, order = [], 0
    for group, family, sizes in cat.PRODUCTS:
        for variant, unit, sku, price in sizes:
            order += 1
            rows.append({
                "name": ("%s %s" % (family, variant)).strip(),
                "sku": sku, "product_group": group, "family": family,
                "variant": variant, "unit": unit, "stock_qty": 0.0,
                "reorder_level": 0, "price": price,
                "location": "Finished Products Area", "category": "finished",
                "sort_order": order, "created_at": now,
            })
    products = {p["name"]: p for p in db.insert_many("products", rows)}
    # Opening stock for the lines the demo history and packing use.
    opening = {
        "Pure Honey 250 mL": (60, 24), "Pure Honey 500 mL": (36, 12),
        "Pure Honey 1 Liter": (24, 10), "RFH with Comb 250 mL": (30, 12),
        "Honey Lemon Ginger Concentrate 300 mL": (96, 40),
        "Honey Calamansi Concentrate 300 mL": (40, 20),
        "Honey Infused Turmeric Ginger 300 mL": (48, 20),
        "Honey Infused Ginger 300 mL": (52, 20),
        "Pure Tableya 200 g": (45, 20), "Cacao Powder 100 g": (38, 15),
        "Robusta Coffee 125 g": (40, 15), "Moringa Powder 100 g": (25, 10),
        "Banana Chips 100 g": (30, 12),
    }
    for name, (stock, reorder) in opening.items():
        products[name] = db.update("products", products[name]["id"],
                                   {"stock_qty": float(stock),
                                    "reorder_level": reorder})
    return products


def _seed_assets():
    now = services.now_iso()
    db.insert_many("assets", [{
        "item_no": item_no, "name": name, "category": category,
        "cost_per_item": None, "quantity": float(qty), "unit": unit,
        "qty_out": 0.0, "condition": condition, "years_in_use": None,
        "remarks": remarks, "serial_number": "", "model": "",
        "manufacturer": "", "date_of_purchase": "", "location": "Production Area",
        "contact_details": "", "active": True, "created_at": now,
    } for item_no, name, category, qty, unit, condition, remarks in cat.ASSETS])


def _seed_bom(materials, products):
    """The recipes the production team checks before every run."""
    def line(product, material, qpu, note=""):
        db.insert("bill_of_materials", {
            "product_id": products[product]["id"],
            "material_id": materials[material]["id"],
            "qty_per_unit": qpu, "notes": note,
        })

    line("Pure Honey 250 mL", "Raw Honey", 0.35)
    line("Pure Honey 250 mL", "Hexagonal Jar 250 mL", 1)
    line("Pure Honey 250 mL", "63 mm Seal (250 mL)", 1)
    line("Pure Honey 500 mL", "Raw Honey", 0.7)
    line("Pure Honey 500 mL", "Hexagonal Jar 500 mL", 1)
    line("Pure Honey 500 mL", "70 mm Seal (500 mL)", 1)
    line("Pure Honey 1 Liter", "Raw Honey", 1.4)
    line("Pure Honey 1 Liter", "Round Bottle 1 Liter", 1)
    line("RFH with Comb 250 mL", "Raw Honey", 0.3)
    line("RFH with Comb 250 mL", "Honey Comb", 0.05)
    line("RFH with Comb 250 mL", "Hexagonal Jar 250 mL", 1)

    hlgc = "Honey Lemon Ginger Concentrate 300 mL"
    line(hlgc, "Raw Honey", 0.18)
    line(hlgc, "Lemon", 3, "By piece — counted, not weighed")
    line(hlgc, "Ginger", 0.08, "By weight")
    line(hlgc, "Square Bottle 300 mL", 1)
    line("Honey Calamansi Concentrate 300 mL", "Raw Honey", 0.18)
    line("Honey Calamansi Concentrate 300 mL", "Calamansi", 0.1)
    line("Honey Calamansi Concentrate 300 mL", "Square Bottle 300 mL", 1)
    line("Honey Infused Turmeric Ginger 300 mL", "Raw Honey", 0.2)
    line("Honey Infused Turmeric Ginger 300 mL", "Turmeric", 0.05)
    line("Honey Infused Turmeric Ginger 300 mL", "Ginger", 0.05)
    line("Honey Infused Turmeric Ginger 300 mL", "Square Bottle 300 mL", 1)
    line("Honey Infused Ginger 300 mL", "Raw Honey", 0.2)
    line("Honey Infused Ginger 300 mL", "Ginger", 0.09)
    line("Honey Infused Ginger 300 mL", "Square Bottle 300 mL", 1)

    line("Pure Tableya 200 g", "Cacao Beans", 0.25)
    line("Pure Tableya 200 g", "Cookie Pouch 5.5x8.5 cm", 1)
    line("Cacao Powder 100 g", "Cacao Beans", 0.15)
    line("Cacao Powder 100 g", "Cacao Powder Pouch (black) 15x22 cm", 1)
    line("Robusta Coffee 125 g", "Robusta Coffee", 0.15)
    line("Robusta Coffee 125 g", "Matte Kraft Pouch (brown) 17x24 cm", 1)
    line("Moringa Powder 100 g", "Moringa", 0.6, "Fresh leaves — dried and ground")
    line("Moringa Powder 100 g", "Matte Kraft Pouch (white) 13x21 cm", 1)
    line("Banana Chips 100 g", "Banana Chips", 0.1)
    line("Banana Chips 100 g", "Banana Chips Jar 440 mL", 1)


def _txn_dict(item_type, item_id, change, txn_type, ts, user_id):
    return {
        "item_type": item_type, "item_id": int(item_id),
        "change_qty": float(change), "txn_type": txn_type,
        "reference_id": TAG, "user_id": user_id, "timestamp": ts,
    }


# Products that get backdated demand / production history.
HISTORY_PRODUCTS = [
    "Pure Honey 250 mL", "Pure Honey 1 Liter",
    "Honey Lemon Ginger Concentrate 300 mL",
    "Honey Infused Turmeric Ginger 300 mL", "Honey Infused Ginger 300 mL",
    "Pure Tableya 200 g", "Robusta Coffee 125 g", "Cacao Powder 100 g",
]


def _seed_history(users, materials, products):
    rng = random.Random(42)
    monday0 = _this_monday()
    packing_uid = users["packing_head"]["id"]
    prod_uid = users["production_head"]["id"]

    boms = db.read("bill_of_materials")
    prod_list = [products[name] for name in HISTORY_PRODUCTS]
    raw = [m for m in materials.values() if m.get("category") == "raw"]
    statuses = ["Fulfilled", "Fulfilled", "Approved", "Fulfilled",
                "Pending Approval", "Rejected"]

    sales_reqs, prod_orders, txns = [], [], []

    for w in range(WEEKS):                       # oldest -> newest
        week_start = monday0 - timedelta(weeks=(WEEKS - 1 - w))
        for idx, product in enumerate(prod_list):
            pid = product["id"]
            base = 6 + (idx % 5) * 3
            qty = max(1, round(base + w * 1.2 + rng.uniform(-2, 3)))
            status = statuses[(w + pid) % len(statuses)]
            created = week_start + timedelta(days=rng.randint(0, 4),
                                             hours=rng.randint(0, 8))
            sales_reqs.append({
                "product_id": pid, "product_name": product["name"],
                "product_unit": product["unit"], "qty": qty,
                "channel": rng.choice(services.PACKING_CHANNELS),
                "requestor_id": packing_uid,
                "requestor_name": users["packing_head"]["name"],
                "status": status, "remarks": TAG, "created_at": _iso(created),
            })
            if status == "Fulfilled":
                txns.append(_txn_dict("product", pid, -qty, "sold",
                                      _iso(created), packing_uid))

            produced = qty + rng.randint(2, 8)
            run_ts = _iso(week_start + timedelta(days=rng.randint(0, 2)))
            prod_orders.append({
                "product_id": pid, "product_name": product["name"],
                "qty": produced, "batch_no": "BR-%d%02d" % (pid, w),
                "status": "Completed", "output_qty": produced,
                "rejected_qty": 0, "damaged_qty": 0, "notes": "",
                "materials_used": [], "user_id": prod_uid, "timestamp": run_ts,
            })
            txns.append(_txn_dict("product", pid, produced, "produced",
                                  run_ts, prod_uid))
            for line in boms:
                if line["product_id"] == pid:
                    used = line["qty_per_unit"] * produced
                    txns.append(_txn_dict("material", line["material_id"],
                                          -used, "consumed", run_ts, prod_uid))

        if w % 2 == 0:
            mat = rng.choice(raw)
            recv_ts = _iso(week_start + timedelta(days=rng.randint(0, 3)))
            txns.append(_txn_dict("material", mat["id"], rng.randint(20, 80),
                                  "received", recv_ts, prod_uid))

    db.insert_many("sales_requests", sales_reqs)
    db.insert_many("production_orders", prod_orders)
    db.insert_many("inventory_transactions", txns)


def _seed_receiving(users, suppliers, materials):
    """Two deliveries already inspected, one still waiting on the floor."""
    uid = users["receiving_head"]["id"]
    qa = users["production_head"]["id"]
    produce = suppliers["Highland Produce Traders"]["id"]
    pack = suppliers["Davao CVI"]["id"]
    m = materials

    def lines(*rows):
        return [{"material_id": m[name]["id"], "qty_per_box": per,
                 "boxes": count, "lot_no": lot, "expiry_date": exp,
                 "packaging_condition": cond, "temperature_c": temp}
                for name, per, count, lot, exp, cond, temp in rows]

    # Delivery 1 — produce, inspected, with some loss.
    batch, boxes, _ = services.receive_delivery(
        uid, produce, _days_ago(6), lines(
            ("Ginger", 12.0, 3, "GIN-1006", "", "Good / intact", 27.0),
            ("Lemon", 120.0, 2, "LEM-1006", "", "Slightly dented / torn", 27.0),
            ("Turmeric", 8.0, 1, "TUR-1006", "", "Good / intact", 27.0)),
        po_no="PO-1043", delivery_ref="DR-88412",
        remarks="Weekly ginger and lemon delivery.")
    outcome = {"Ginger": (11.0, 0.4, 0.6, "Undersized roots", "Soft and bruised"),
               "Lemon": (110.0, 6.0, 4.0, "Overripe", "Split skins in transit"),
               "Turmeric": (8.0, 0.0, 0.0, "", "")}
    for box in boxes:
        good, unusable, damaged, ureason, dreason = outcome[box["material_name"]]
        services.inspect_receiving_box(
            box["id"], qa, good, unusable, damaged, ureason, dreason,
            cleaned=True, visual_inspection="Pass", coa_check="Not required",
            sampling_test="Not required", acceptance="Accepted",
            verified_by_name="Amamio Admin")

    # Delivery 2 — bottles, one carton held for a missing document.
    batch2, boxes2, _ = services.receive_delivery(
        uid, pack, _days_ago(3), lines(
            ("Square Bottle 300 mL", 200.0, 2, "SB300-2210", "", "Good / intact", None),
            ("Hexagonal Jar 250 mL", 150.0, 1, "HX250-2210", "", "Good / intact", None)),
        delivery_ref="DR-55120", remarks="Bottles for the next HLGC run.")
    for i, box in enumerate(boxes2):
        if i == 2:
            services.inspect_receiving_box(
                box["id"], qa, 146.0, 0, 4.0, "", "Cracked rims",
                cleaned=False, visual_inspection="Pass", coa_check="Incomplete",
                sampling_test="Not required", acceptance="Hold",
                nonconformity="Food-grade certificate not included",
                action_taken="Asked supplier to e-mail the certificate")
        else:
            services.inspect_receiving_box(
                box["id"], qa, 200.0, 0, 0, cleaned=False,
                visual_inspection="Pass", coa_check="Complete",
                sampling_test="Not required", acceptance="Accepted")

    # Delivery 3 — arrived this morning, boxes waiting for inspection.
    services.receive_delivery(
        uid, produce, services.today_iso(), lines(
            ("Ginger", 15.0, 2, "GIN-1016", "", "Good / intact", 26.5),
            ("Calamansi", 10.0, 1, "CAL-1016", "", "Good / intact", 26.5),
            ("Lemon", 150.0, 2, "LEM-1016", "", "Good / intact", 26.5)),
        po_no="PO-1051", delivery_ref="DR-88630",
        remarks="Arrived this morning.")


def _seed_honey(users, suppliers, materials):
    """Containers across all three QC states, including failures."""
    recv = users["receiving_head"]["id"]
    qa = users["production_head"]["id"]
    apiary = suppliers["Mindanao Forest Apiary"]["id"]
    honey_material = materials["Raw Honey"]["id"]

    # (net kg, result, moisture, appearance, note, [(product, kg), ...])
    checked = [
        (28.5, "Pass", 17.4, "Clear", "Within spec.",
         [("Pure Honey", 20.0), ("RFH (Raw Forest Honey) with Comb", 8.5)]),
        (31.0, "Pass", 18.9, "Clear", "Within spec.", [("Pure Honey", 12.0)]),
        (26.2, "Pass", 19.6, "Crystallized",
         "Crystallized but within moisture spec — warmed before bottling.", []),
        (24.8, "Failed", 22.7, "Fermented / off-smell",
         "Above the 20% moisture limit and showing fermentation.",
         [("Honey Vinegar", 14.8), ("Honey Lemon Ginger Concentrate", 10.0)]),
        (29.4, "Failed", 21.2, "With sediment",
         "Sediment and high moisture — diverted to infused products.",
         [("Honey Infused Ginger", 9.0)]),
    ]
    for net, result, moisture, appearance, note, uses in checked:
        created, _ = services.log_honey_containers(
            1, net, recv, supplier_id=apiary, source="Supplier delivery",
            harvest_date=_days_ago(21), received_date=_days_ago(10),
            material_id=honey_material)
        container = created[0]
        services.record_honey_qc(container["id"], result, moisture, appearance,
                                 notes=note, user_id=qa)
        for product, kg in uses:
            services.allocate_honey_container(container["id"], product, kg,
                                              user_id=qa)

    # Three containers still waiting for the moisture check.
    services.log_honey_containers(
        3, 27.5, recv, source="Own harvest", harvest_date=_days_ago(4),
        received_date=_days_ago(1), material_id=honey_material)


def _seed_packing(users, products):
    """Runs on every channel: disbursed, with the courier, and waiting."""
    head = users["packing_head"]["id"]
    joy = users["packer1"]["id"]
    mark = users["packer2"]["id"]
    p = {name: prod["id"] for name, prod in products.items()}
    hlgc = p["Honey Lemon Ginger Concentrate 300 mL"]
    rfh = p["RFH with Comb 250 mL"]
    ph = p["Pure Honey 250 mL"]
    hitg = p["Honey Infused Turmeric Ginger 300 mL"]
    hig = p["Honey Infused Ginger 300 mL"]
    tab = p["Pure Tableya 200 g"]

    # channel, date, ref, packer, lines, outcome, courier, tracking, received by
    plan = [
        ("Shopee", _days_ago(2), "SHP-2610107KMYDDCQ", joy,
         [(hlgc, 12, 0), (ph, 6, 0)], "courier", "SPX Express (Shopee)",
         "PH269036210686A", "SPX rider — Ben"),
        ("Lazada", _days_ago(2), "LZD-1119715849296256", mark,
         [(rfh, 8, 0), (hitg, 4, 1)], "courier", "J&T Express",
         "820165158961", "J&T rider — Al"),
        ("VIP", _days_ago(1), "VIP-Metro Grocers", joy,
         [(ph, 10, 0), (hlgc, 10, 0)], "disbursed", "", "",
         "Liza Tan (Metro Grocers)"),
        ("TikTok", _days_ago(1), "TTS-7694272255744952065", mark,
         [(hlgc, 9, 0), (hig, 5, 0)], "packed", "", "", ""),
        ("Walk-in", services.today_iso(), "WI-0032", joy,
         [(tab, 3, 0)], "disbursed", "", "", "Walk-in buyer"),
        ("Shopee", services.today_iso(), "SHP-batch-AM", head,
         [(ph, 4, 0), (hig, 2, 0)], "packed", "", "", ""),
    ]
    for channel, when, ref, packer, lines, outcome, courier, tracking, who in plan:
        run, err = services.pack_now(
            channel, packer,
            [{"product_id": pid, "qty": qty, "damaged_qty": dmg,
              "notes": "Cracked lid" if dmg else ""}
             for pid, qty, dmg in lines],
            head, pack_date=when, order_ref=ref)
        if err or not run:
            continue
        if outcome == "courier":
            services.dispatch_packing_run(
                run["id"], services.DISPATCH_COURIER, who, user_id=packer,
                courier=courier, tracking_no=tracking, parcel_count=len(lines))
        elif outcome == "disbursed":
            services.dispatch_packing_run(
                run["id"], services.DISPATCH_DISBURSED, who, user_id=packer,
                parcel_count=1)


def _seed_live_docs(users, products, materials):
    """Pending approvals and customer orders so no screen starts empty."""
    services.create_production_request(
        requestor_id=users["production_head"]["id"],
        product_id=products["Honey Lemon Ginger Concentrate 300 mL"]["id"],
        qty=120,
        item_lines=[
            {"material_id": materials["Lemon"]["id"], "requested_qty": 360,
             "note": "By piece — 3 per bottle"},
            {"material_id": materials["Ginger"]["id"], "requested_qty": 10,
             "note": "By weight"},
            {"material_id": materials["Raw Honey"]["id"], "requested_qty": 22,
             "note": "Pass-grade honey only"},
        ],
        reason="Out of stock",
        remarks="Lemon and ginger ran out mid-batch; next HLGC run is Monday.",
        needed_by=_days_ago(-4), urgency="Urgent")

    services.create_material_request(
        requestor_id=users["assets_head"]["id"], category="cleaning",
        name="Dishwashing Liquid 3.78 L", qty=4,
        description="For the washing area.",
        reason="Below reorder level", needed_by=_days_ago(-7))

    services.create_sales_request(
        requestor_id=users["packing_head"]["id"],
        product_id=products["Pure Honey 250 mL"]["id"], qty=12,
        remarks="Reserve stock for the Sunrise Cafe walk-in pickup.")

    customers = db.read("customers")
    if not customers:
        return
    hlgc = products["Honey Lemon Ginger Concentrate 300 mL"]["id"]
    ph = products["Pure Honey 250 mL"]["id"]
    packing_uid = users["packing_head"]["id"]

    order1, _ = services.create_sales_order(
        customers[0]["id"],
        [{"product_id": hlgc, "qty": 12, "unit_price": 487},
         {"product_id": ph, "qty": 6, "unit_price": 399}],
        discount=200, remarks="Standard monthly VIP order",
        user_id=packing_uid)
    if order1:
        services.confirm_sales_order(order1["id"], user_id=packing_uid)
        services.record_payment(order1["id"], order1["total"],
                                method="Bank transfer", reference="TRX-0001",
                                user_id=packing_uid)
        delivery, _ = services.create_delivery(
            order1["id"], scheduled_date=_days_ago(1), driver="Rey (Truck 1)",
            address=customers[0]["address"], user_id=packing_uid)
        if delivery:
            services.update_delivery(delivery["id"], status="Delivered",
                                     confirmed=True)

    services.create_sales_order(
        customers[1]["id"],
        [{"product_id": hlgc, "qty": 10, "unit_price": 487}],
        discount=0, remarks="Awaiting confirmation", user_id=packing_uid)


def _seed_platform_sales(users):
    """Import the sample marketplace exports, so Module 5 has data on day one."""
    import platform_service as ps
    ps.seed_builtin_templates()
    uid = users["packing_head"]["id"]
    templates = {t["platform"]: t for t in ps.all_templates()}
    for filename in ps.folder_files():
        name = filename["name"].lower()
        platform = next((p for p in ("Shopee", "Lazada", "TikTok")
                         if p.lower() in name), None)
        if not platform or platform not in templates:
            continue
        path = ps.safe_upload_path(filename["name"])
        if path and os.path.isfile(path):
            ps.import_file(path, templates[platform]["id"], uid,
                           filename=filename["name"])


def _seed_module_demos(users):
    """Example records for the modules that keep their logic in their own
    service file (assets & supplies, production records, facility records)."""
    for name in ("assets_service", "production_service", "facility_service"):
        try:
            module = importlib.import_module(name)
        except ModuleNotFoundError as exc:
            if exc.name != name:
                raise
            continue
        if hasattr(module, "seed_demo"):
            module.seed_demo(users)
