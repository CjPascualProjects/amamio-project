"""Idempotent demo seeding for the Amamio Sales & Inventory Management System.

Seeds only when there are no users yet.  Creates the five team roles, the
suppliers and customers, Amamio's honey catalog with its recipes, ~12 weeks of
backdated demand/production history (so the AI has data to forecast), and live
examples of every monitored flow the client described: receiving boxes with
damage counts, honey containers that passed and failed QC, packing runs per
channel, maintenance logs, and open customer orders.
"""
import random
from datetime import datetime, timedelta, timezone

from werkzeug.security import generate_password_hash

import db
import services
from security import ROLES

WEEKS = 12
TAG = "seed-history"


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
    _seed_bom(materials, products)
    _seed_history(users, materials, products)
    _seed_receiving(users, suppliers, materials)
    _seed_honey(users, suppliers, materials)
    _seed_packing(users, products)
    _seed_maintenance(users, materials)
    _seed_live_docs(users, products, materials)
    _seed_ai_snapshots()


def _seed_ai_snapshots():
    """Populate the AI_Forecasts / AI_Recommendations tables from the demo data."""
    import ai
    services.save_ai_forecasts(ai.forecast_all_products())
    services.save_ai_recommendations(ai.all_recommendations())


def _seed_roles():
    for key, name, desc in ROLES:
        db.insert("roles", {"key": key, "name": name, "description": desc})


def _seed_users():
    people = [
        ("Amamio Super Admin", "superadmin", "super123", "super_admin"),
        ("Amamio Admin", "admin", "admin123", "admin"),
        ("Production Team Head", "production", "prod123", "production_head"),
        ("Packing Team Head", "packing", "pack123", "packing_head"),
        ("Assets & Maintenance Head", "assets", "assets123", "assets_head"),
    ]
    from security import ROLE_LABELS
    users = {}
    for name, username, pw, role in people:
        u = db.insert("users", {
            "name": name, "username": username,
            "password_hash": generate_password_hash(pw),
            "role": role, "email": "%s@amamio.ph" % username,
            "phone": "", "team": ROLE_LABELS.get(role, role),
            "active": True, "last_login": None,
            "created_at": services.now_iso(),
        })
        users[role] = u
    return users


def _seed_suppliers():
    data = [
        ("Mindanao Forest Apiary", "Ana Reyes", "0917-100-2001",
         "orders@mindanaoapiary.ph", "Bukidnon, Mindanao",
         "Raw forest honey by container", 7),
        ("Highland Produce Traders", "Ben Cruz", "0917-100-2002",
         "sales@highlandproduce.ph", "La Trinidad, Benguet",
         "Ginger, turmeric, lemon by crate", 3),
        ("PackRight Supplies", "Cora Lim", "0917-100-2003",
         "sales@packright.ph", "Industrial Ave, Valenzuela",
         "Bottles, jars, labels, cartons", 4),
        ("CleanCo Trading", "Dino Santos", "0917-100-2004",
         "hello@cleanco.ph", "Market St, Quezon City",
         "Sanitizer and cleaning supplies", 3),
    ]
    suppliers = {}
    for name, contact, phone, email, addr, supplies, lead in data:
        s = db.insert("suppliers", {
            "name": name, "contact_person": contact, "phone": phone,
            "email": email, "address": addr, "materials_supplied": supplies,
            "lead_time_days": lead, "notes": "",
            "created_at": services.now_iso(),
        })
        suppliers[name] = s
    return suppliers


def _seed_customers():
    data = [
        ("Metro Grocers", "Liza Tan", "0917-200-3001",
         "purchasing@metrogrocers.ph", "SM North EDSA, Quezon City", "VIP"),
        ("Health Hub Store", "Marco Dela Cruz", "0917-200-3002",
         "orders@healthhub.ph", "BGC, Taguig", "VIP"),
        ("Sunrise Cafe", "Nina Santos", "0917-200-3003",
         "nina@sunrisecafe.ph", "Session Rd, Baguio", "Walk-in"),
        ("Wellness Mart", "Oliver Yu", "0917-200-3004",
         "buyer@wellnessmart.ph", "Ayala Center, Cebu", "VIP"),
    ]
    for name, contact, phone, email, addr, channel in data:
        db.insert("customers", {
            "name": name, "contact_person": contact, "phone": phone,
            "email": email, "address": addr, "channel": channel, "notes": "",
            "created_at": services.now_iso(),
        })


def _seed_materials(suppliers):
    honey = suppliers["Mindanao Forest Apiary"]["id"]
    produce = suppliers["Highland Produce Traders"]["id"]
    pack = suppliers["PackRight Supplies"]["id"]
    clean = suppliers["CleanCo Trading"]["id"]
    # (name, category, unit, track_mode, stock, reorder, supplier, unit cost)
    data = [
        ("Raw Honey", "raw", "kg", "weight", 68.0, 25, honey, 420.0),
        ("Ginger", "raw", "kg", "weight", 42.0, 20, produce, 95.0),
        ("Turmeric", "raw", "kg", "weight", 18.0, 10, produce, 120.0),
        ("Lemon", "raw", "pc", "piece", 640.0, 250, produce, 12.0),
        ("Calamansi", "raw", "kg", "weight", 12.0, 8, produce, 80.0),
        ("Bottle 300 mL", "raw", "pc", "piece", 420.0, 150, pack, 9.0),
        ("Bottle 250 mL", "raw", "pc", "piece", 380.0, 150, pack, 8.0),
        ("Jar 200 mL", "raw", "pc", "piece", 300.0, 120, pack, 11.0),
        ("Bottle 1 L", "raw", "pc", "piece", 90.0, 40, pack, 24.0),
        ("Label sticker", "raw", "pc", "piece", 1800.0, 500, pack, 1.2),
        ("Safety seal", "raw", "pc", "piece", 1500.0, 500, pack, 0.8),
        ("Shipping carton", "raw", "pc", "piece", 260.0, 100, pack, 18.0),
        ("Food-grade sanitizer", "cleaning", "L", "unit", 14.0, 6, clean, 180.0),
        ("Dishwashing liquid", "cleaning", "L", "unit", 9.0, 4, clean, 120.0),
        ("Bottle filling machine", "asset", "unit", "unit", 1.0, 0, pack,
         145000.0),
        ("Digital moisture meter", "asset", "unit", "unit", 2.0, 0, pack,
         28000.0),
        ("Weighing scale (50 kg)", "asset", "unit", "unit", 3.0, 0, pack,
         9500.0),
        ("Stainless steaming vat", "asset", "unit", "unit", 2.0, 0, pack,
         62000.0),
    ]
    materials = {}
    for name, cat, unit, mode, stock, reorder, supplier_id, cost in data:
        m = db.insert("raw_materials", {
            "name": name, "category": cat, "unit": unit, "track_mode": mode,
            "stock_qty": stock, "reorder_level": reorder,
            "supplier_id": supplier_id, "unit_cost": cost, "expiry_date": "",
            "storage_location": "Dry store" if cat == "raw" else "Utility room",
            "created_at": services.now_iso(),
        })
        materials[name] = m
    return materials


def _seed_products():
    # (name, sku, variant, unit, stock, reorder, price, location)
    data = [
        ("Honey Lemon Ginger Concentrate 300 mL", "HLGC-300", "300 mL",
         "bottle", 96.0, 40, 487.0, "Shelf A1"),
        ("Raw Forest Honey 250 mL", "RFH-250", "250 mL", "jar", 72.0, 30,
         499.0, "Shelf A2"),
        ("Raw Forest Honey 1 L", "RFH-1L", "1 Litre", "bottle", 24.0, 12,
         1104.0, "Shelf A3"),
        ("Honey Infused Turmeric Ginger 200 mL", "HIT-200", "200 mL", "jar",
         58.0, 25, 350.0, "Shelf B1"),
        ("Honey Infused Ginger 200 mL", "HIG-200", "200 mL", "jar", 64.0, 25,
         325.0, "Shelf B2"),
    ]
    products = {}
    for name, sku, variant, unit, stock, reorder, price, loc in data:
        p = db.insert("products", {
            "name": name, "sku": sku, "variant": variant, "unit": unit,
            "stock_qty": stock, "reorder_level": reorder, "price": price,
            "location": loc, "category": "finished",
            "created_at": services.now_iso(),
        })
        products[name] = p
    return products


def _seed_bom(materials, products):
    """The recipes the production team checks before every run."""
    def line(product, material, qpu, note=""):
        db.insert("bill_of_materials", {
            "product_id": products[product]["id"],
            "material_id": materials[material]["id"],
            "qty_per_unit": qpu,
            "notes": note,
        })

    hlgc = "Honey Lemon Ginger Concentrate 300 mL"
    line(hlgc, "Raw Honey", 0.18)
    line(hlgc, "Lemon", 3, "By piece — counted, not weighed")
    line(hlgc, "Ginger", 0.08, "By weight")
    line(hlgc, "Bottle 300 mL", 1)
    line(hlgc, "Label sticker", 1)
    line(hlgc, "Safety seal", 1)

    rfh250 = "Raw Forest Honey 250 mL"
    line(rfh250, "Raw Honey", 0.32)
    line(rfh250, "Jar 200 mL", 1)
    line(rfh250, "Label sticker", 1)
    line(rfh250, "Safety seal", 1)

    rfh1l = "Raw Forest Honey 1 L"
    line(rfh1l, "Raw Honey", 1.4)
    line(rfh1l, "Bottle 1 L", 1)
    line(rfh1l, "Label sticker", 1)
    line(rfh1l, "Safety seal", 1)

    hit = "Honey Infused Turmeric Ginger 200 mL"
    line(hit, "Raw Honey", 0.15)
    line(hit, "Turmeric", 0.05)
    line(hit, "Ginger", 0.05)
    line(hit, "Jar 200 mL", 1)
    line(hit, "Label sticker", 1)

    hig = "Honey Infused Ginger 200 mL"
    line(hig, "Raw Honey", 0.16)
    line(hig, "Ginger", 0.09)
    line(hig, "Jar 200 mL", 1)
    line(hig, "Label sticker", 1)


def _txn_dict(item_type, item_id, change, txn_type, ts, user_id):
    return {
        "item_type": item_type, "item_id": int(item_id),
        "change_qty": float(change), "txn_type": txn_type,
        "reference_id": TAG, "user_id": user_id, "timestamp": ts,
    }


def _seed_history(users, materials, products):
    rng = random.Random(42)
    monday0 = _this_monday()
    packing_uid = users["packing_head"]["id"]
    prod_uid = users["production_head"]["id"]

    boms = db.read("bill_of_materials")
    prod_list = list(products.values())
    statuses = ["Fulfilled", "Fulfilled", "Approved", "Fulfilled",
                "Pending Approval", "Rejected"]

    sales_reqs, prod_orders, txns = [], [], []

    for w in range(WEEKS):                       # oldest -> newest
        week_start = monday0 - timedelta(weeks=(WEEKS - 1 - w))
        for idx, product in enumerate(prod_list):
            pid = product["id"]
            base = 8 + idx * 4
            qty = max(1, round(base + w * 1.4 + rng.uniform(-2, 3)))
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
            mat = rng.choice(list(materials.values()))
            recv_ts = _iso(week_start + timedelta(days=rng.randint(0, 3)))
            txns.append(_txn_dict("material", mat["id"], rng.randint(20, 80),
                                  "received", recv_ts, prod_uid))

    db.insert_many("sales_requests", sales_reqs)
    db.insert_many("production_orders", prod_orders)
    db.insert_many("inventory_transactions", txns)


def _seed_receiving(users, suppliers, materials):
    """Two closed deliveries plus one still being checked on the floor."""
    uid = users["production_head"]["id"]
    produce = suppliers["Highland Produce Traders"]["id"]
    pack = suppliers["PackRight Supplies"]["id"]

    # Delivery 1 — produce, fully checked, with some damage.
    batch = services.create_receiving_batch(
        produce, _days_ago(6), uid, delivery_ref="DR-88412",
        remarks="Weekly ginger and lemon delivery.")
    plan = [("Ginger", 12.0, 3, (11.4, 0.6, "Soft and bruised roots")),
            ("Lemon", 120.0, 2, (116.0, 4.0, "Split skins in transit")),
            ("Turmeric", 8.0, 1, (8.0, 0.0, ""))]
    for name, declared, count, (good, damaged, reason) in plan:
        boxes, _ = services.add_receiving_box(batch["id"], materials[name]["id"],
                                              declared, uid, count=count)
        for box in boxes:
            services.check_receiving_box(box["id"], good, damaged, reason,
                                         user_id=uid)
    services.close_receiving_batch(batch["id"], uid)

    # Delivery 2 — packaging, clean.
    batch2 = services.create_receiving_batch(
        pack, _days_ago(3), uid, delivery_ref="PR-20915",
        remarks="Bottles and labels for the next run.")
    for name, declared, count in [("Bottle 300 mL", 200.0, 2),
                                  ("Label sticker", 500.0, 1)]:
        boxes, _ = services.add_receiving_box(batch2["id"],
                                              materials[name]["id"], declared,
                                              uid, count=count)
        for box in boxes:
            services.check_receiving_box(box["id"], declared, 0, "",
                                         user_id=uid)
    services.close_receiving_batch(batch2["id"], uid)

    # Delivery 3 — open, boxes still waiting to be counted.
    batch3 = services.create_receiving_batch(
        produce, services.today_iso(), uid, delivery_ref="DR-88630",
        remarks="Arrived this morning — awaiting count.")
    services.add_receiving_box(batch3["id"], materials["Ginger"]["id"], 15.0,
                               uid, count=2)
    services.add_receiving_box(batch3["id"], materials["Lemon"]["id"], 150.0,
                               uid, count=2)


def _seed_honey(users, suppliers, materials):
    """Containers across all three QC states, including a failure."""
    uid = users["production_head"]["id"]
    apiary = suppliers["Mindanao Forest Apiary"]["id"]
    honey_material = materials["Raw Honey"]["id"]

    # (net kg, result, moisture, appearance, note, allocated to)
    checked = [
        (28.5, "Pass", 17.4, "Clear", "Within spec.", "Raw Forest Honey 250 mL"),
        (31.0, "Pass", 18.9, "Clear", "Within spec.", "Raw Forest Honey 1 L"),
        (26.2, "Pass", 19.6, "Crystallized",
         "Crystallized but within moisture spec — warmed before bottling.", ""),
        (24.8, "Failed", 22.7, "Fermented / off-smell",
         "Above the 20% moisture limit and showing fermentation.",
         "Honey Infused Ginger 200 mL"),
        (29.4, "Failed", 21.2, "With sediment",
         "Sediment and high moisture — diverted to infused products.", ""),
    ]
    for net, result, moisture, appearance, note, allocated in checked:
        container, _ = services.create_honey_container(
            net, uid, supplier_id=apiary, source="Supplier delivery",
            harvest_date=_days_ago(21), received_date=_days_ago(10),
            material_id=honey_material)
        services.record_honey_qc(container["id"], result, moisture, appearance,
                                 notes=note, user_id=uid)
        if allocated:
            services.allocate_honey_container(container["id"], allocated,
                                              user_id=uid)

    # Three containers still queued for the moisture check.
    for net in (27.6, 30.2, 25.9):
        services.create_honey_container(
            net, uid, supplier_id=apiary, source="Own harvest",
            harvest_date=_days_ago(4), received_date=_days_ago(1),
            material_id=honey_material)


def _seed_packing(users, products):
    """One run per channel so the packing monitor is populated from day one."""
    uid = users["packing_head"]["id"]
    hlgc = products["Honey Lemon Ginger Concentrate 300 mL"]["id"]
    rfh = products["Raw Forest Honey 250 mL"]["id"]
    hit = products["Honey Infused Turmeric Ginger 200 mL"]["id"]
    hig = products["Honey Infused Ginger 200 mL"]["id"]

    plan = [
        ("Shopee", _days_ago(2), "SHP-2610107KMYDDCQ",
         [(hlgc, 12, 0), (rfh, 6, 0)], "handed", "SPX Express", "PH269036210686A"),
        ("Lazada", _days_ago(2), "LZD-1119715849296256",
         [(rfh, 8, 0), (hit, 4, 1)], "handed", "J&T Express PH", "820165158961"),
        ("TikTok", _days_ago(1), "TTS-7694272255744952065",
         [(hlgc, 9, 0), (hig, 5, 0)], "packed", "Flash Express", ""),
        ("VIP", _days_ago(1), "VIP-Metro Grocers",
         [(rfh, 10, 0), (hlgc, 10, 0)], "packed", "Own delivery", ""),
        ("Walk-in", services.today_iso(), "WI-0032",
         [(hig, 3, 0)], "open", "", ""),
    ]
    for channel, when, ref, lines, stage, courier, tracking in plan:
        run, err = services.create_packing_run(
            channel, uid,
            [{"product_id": pid, "qty": qty, "damaged_qty": dmg}
             for pid, qty, dmg in lines],
            uid, pack_date=when, order_ref=ref, courier=courier,
            tracking_no=tracking,
            remarks="Seeded example run for the %s channel." % channel)
        if err or not run:
            continue
        if stage in ("packed", "handed"):
            services.mark_packed(run["id"], user_id=uid)
        if stage == "handed":
            services.hand_over_packing_run(
                run["id"], "%s rider" % (courier or "Courier"),
                courier=courier, tracking_no=tracking, user_id=uid)


def _seed_maintenance(users, materials):
    uid = users["assets_head"]["id"]
    plan = [
        ("Bottle filling machine", "Preventive", _days_ago(20),
         "In-house technician", "Completed", 2500.0, _days_ago(-10), 2.0,
         "Nozzle cleaning and seal replacement."),
        ("Digital moisture meter", "Calibration", _days_ago(35),
         "Precision Lab Services", "Completed", 1800.0, _days_ago(-25), 0.5,
         "Annual calibration certificate on file."),
        ("Stainless steaming vat", "Repair", _days_ago(8),
         "Weld Masters", "Completed", 4200.0, _days_ago(-80), 6.0,
         "Re-welded the drain valve."),
        ("Weighing scale (50 kg)", "Inspection", _days_ago(2),
         "In-house technician", "Scheduled", 0.0, _days_ago(-3), 0.0,
         "Monthly accuracy check against test weights."),
    ]
    for name, mtype, done, by, status, cost, due, downtime, notes in plan:
        services.record_maintenance(materials[name]["id"], mtype, done, by,
                                    status, cost=cost, next_due=due,
                                    downtime_hours=downtime, notes=notes,
                                    user_id=uid)


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
        name="Food-grade sanitizer", qty=10,
        description="5 L drums for the bottling line.",
        reason="Below reorder level", needed_by=_days_ago(-7))

    services.create_sales_request(
        requestor_id=users["packing_head"]["id"],
        product_id=products["Raw Forest Honey 250 mL"]["id"], qty=12,
        remarks="Reserve stock for the Sunrise Cafe walk-in pickup.")

    customers = db.read("customers")
    if not customers:
        return
    hlgc = products["Honey Lemon Ginger Concentrate 300 mL"]["id"]
    rfh = products["Raw Forest Honey 250 mL"]["id"]
    packing_uid = users["packing_head"]["id"]

    order1, _ = services.create_sales_order(
        customers[0]["id"],
        [{"product_id": hlgc, "qty": 12, "unit_price": 487},
         {"product_id": rfh, "qty": 6, "unit_price": 499}],
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
