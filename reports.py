"""Reports & Analytics hub (proposal section 8) + AI recommendations."""
from flask import Blueprint, render_template

import ai
import assets_service
import db
import platform_service as ps
import services
from security import module_required

reports_bp = Blueprint("reports", __name__)


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _product_unit_cost(product_id, mat_cost):
    cost = 0.0
    for line in db.query("bill_of_materials", product_id=product_id):
        cost += _f(line.get("qty_per_unit")) * mat_cost.get(line.get("material_id"), 0)
    return cost


@reports_bp.route("/")
@module_required("reports")
def index():
    materials = db.read("raw_materials")
    products = db.read("products")
    txns = db.read("inventory_transactions")
    orders = db.read("sales_orders")
    customers = db.read("customers")
    suppliers = db.read("suppliers")
    prod_orders = db.read("production_orders")

    mat_cost = {m["id"]: _f(m.get("unit_cost")) for m in materials}

    # Inventory report
    inv_materials = []
    for m in materials:
        stock = _f(m.get("stock_qty"))
        reorder = _f(m.get("reorder_level"))
        inv_materials.append({
            "name": m.get("name"), "category": m.get("category"),
            "unit": m.get("unit"), "stock": stock, "reorder": reorder,
            "value": stock * _f(m.get("unit_cost")),
            "low": reorder > 0 and stock <= reorder,
        })
    inv_products = []
    for p in products:
        stock = _f(p.get("stock_qty"))
        inv_products.append({
            "name": p.get("name"), "sku": p.get("sku"), "stock": stock,
            "price": _f(p.get("price")), "value": stock * _f(p.get("price")),
        })

    # Units sold per product + revenue/COGS
    sold_by_product = {}
    for t in txns:
        if t.get("item_type") == "product" and t.get("txn_type") == "sold":
            pid = t.get("item_id")
            sold_by_product[pid] = sold_by_product.get(pid, 0.0) + abs(_f(t.get("change_qty")))

    revenue = sum(_f(o.get("total")) for o in orders
                  if o.get("status") in ("Confirmed", "Delivered"))
    paid_total = sum(_f(p.get("amount")) for p in db.read("payments"))
    outstanding = sum(_f(o.get("total")) for o in orders
                      if o.get("status") in ("Confirmed", "Delivered")) - paid_total
    est_cogs = sum(sold_by_product.get(p["id"], 0) *
                   _product_unit_cost(p["id"], mat_cost) for p in products)
    profit = {
        "revenue": round(revenue, 2), "paid": round(paid_total, 2),
        "outstanding": round(max(0.0, outstanding), 2),
        "est_cogs": round(est_cogs, 2),
        "gross_profit": round(revenue - est_cogs, 2),
    }

    # Production report
    prod_rows = sorted(prod_orders, key=lambda o: o.get("timestamp", ""),
                       reverse=True)[:30]
    prod_summary = {
        "runs": len(prod_orders),
        "output": round(sum(_f(o.get("output_qty")) for o in prod_orders), 2),
        "rejected": round(sum(_f(o.get("rejected_qty")) for o in prod_orders), 2),
        "damaged": round(sum(_f(o.get("damaged_qty")) for o in prod_orders), 2),
    }
    damaged = [o for o in prod_orders
               if _f(o.get("damaged_qty")) or _f(o.get("rejected_qty"))]

    # Fast / slow movers
    top = ai.top_products_by_demand(n=50)
    movers = []
    if top:
        vmax = max((v for _, v in top), default=0)
        for name, v in top:
            if vmax <= 0:
                cls = "—"
            elif v >= vmax * 0.66:
                cls = "Fast"
            elif v >= vmax * 0.33:
                cls = "Medium"
            else:
                cls = "Slow"
            movers.append({"name": name, "demand": v, "class": cls})

    # Supplier report
    mat_supplier = {m["id"]: m.get("supplier_id") for m in materials}
    received = {}
    for t in txns:
        if t.get("item_type") == "material" and t.get("txn_type") == "received":
            sup = mat_supplier.get(t.get("item_id"))
            received[sup] = received.get(sup, 0) + 1
    supplier_rows = [{
        "name": s.get("name"), "materials": s.get("materials_supplied"),
        "lead": s.get("lead_time_days"), "received": received.get(s["id"], 0),
    } for s in suppliers]

    # Customer purchase history
    cust_rows = []
    for c in customers:
        c_orders = [o for o in orders if o.get("customer_id") == c["id"]]
        cust_rows.append({
            "name": c.get("name"), "orders": len(c_orders),
            "spend": round(sum(_f(o.get("total")) for o in c_orders), 2),
        })
    cust_rows.sort(key=lambda r: r["spend"], reverse=True)

    # --- Receiving report -------------------------------------------------
    boxes = db.read("receiving_boxes")
    batches = db.read("receiving_batches")
    receiving = {
        "batches": len(batches),
        "boxes": len(boxes),
        "pending": len([b for b in boxes if services.box_status(b)
                        in (services.BOX_AWAITING, services.BOX_HOLD)]),
        "good": round(sum(_f(b.get("good_qty")) for b in boxes
                          if services.box_status(b) == services.BOX_ACCEPTED), 2),
        # Everything that did not join stock: can't be used + damaged.
        "damaged": round(sum(_f(b.get("damaged_qty")) + _f(b.get("unusable_qty"))
                             for b in boxes), 2),
    }
    received_pct = (receiving["damaged"] /
                    (receiving["good"] + receiving["damaged"]) * 100
                    if (receiving["good"] + receiving["damaged"]) else 0)
    receiving["damage_rate"] = round(received_pct, 2)
    receiving_rows = sorted(
        [{"ref_no": b.get("ref_no"), "supplier": b.get("supplier_name"),
          "date": b.get("received_date"), "boxes": b.get("box_count") or 0,
          "good": b.get("total_good") or 0,
          "damaged": _f(b.get("total_damaged")) + _f(b.get("total_unusable")),
          "status": b.get("status"),
          "badge": services.RECEIVING_BADGE.get(b.get("status"), "badge-muted")}
         for b in batches],
        key=lambda r: r["date"] or "", reverse=True)[:20]

    damage_rows, damage_by_source = services.damage_summary()

    # --- Honey QC report --------------------------------------------------
    honey = services.honey_summary()
    honey_rows = sorted(
        [{"code": c.get("container_code"), "date": c.get("received_date"),
          "kg": c.get("net_weight_kg"), "moisture": c.get("moisture_pct"),
          "appearance": c.get("appearance"), "status": c.get("status"),
          "badge": services.QC_BADGE.get(c.get("status"), "badge-muted"),
          "disposition": c.get("disposition"), "used_for": c.get("allocated_to")}
         for c in db.read("honey_containers")],
        key=lambda r: r["date"] or "", reverse=True)[:25]

    # --- Packing report ---------------------------------------------------
    packing = services.packing_summary()
    packers = services.packer_leaderboard()

    # --- Sales platform report -------------------------------------------
    platform_rows, platform_totals = ps.platform_summary()
    platform_top = ps.top_products(limit=10)
    platform_series = ps.daily_series(days=14)

    # --- Maintenance report -----------------------------------------------
    maint_logs = db.read("maintenance_logs")
    maintenance = {
        "logs": len(maint_logs),
        "spend": round(sum(_f(l.get("cost")) for l in maint_logs), 2),
        "downtime": round(sum(_f(l.get("downtime_hours"))
                              for l in maint_logs), 1),
        "due": assets_service.maintenance_due(),
    }

    # AI recommendations grouped (persist the latest snapshot -> AI_Recommendations)
    recs = ai.all_recommendations()
    services.save_ai_recommendations(recs)

    return render_template(
        "reports/index.html", kpis=ai.kpis(), inv_materials=inv_materials,
        inv_products=inv_products, profit=profit, prod_rows=prod_rows,
        prod_summary=prod_summary, damaged=damaged, movers=movers,
        supplier_rows=supplier_rows, cust_rows=cust_rows, recommendations=recs,
        receiving=receiving, receiving_rows=receiving_rows,
        damage_rows=damage_rows, damage_by_source=damage_by_source,
        honey=honey, honey_rows=honey_rows,
        packing=packing, packers=packers,
        platform_rows=platform_rows, platform_totals=platform_totals,
        platform_top=platform_top, platform_series=platform_series,
        maintenance=maintenance)
