"""Catalog blueprint: finished products, raw materials, and Bills of Materials."""
from flask import (Blueprint, abort, flash, redirect, render_template, request,
                   url_for)

import db
import services
from security import current_user, module_required

catalog_bp = Blueprint("catalog", __name__)

DEFAULT_CATEGORIES = ["raw", "cleaning", "asset"]


def _categories():
    cats = list(DEFAULT_CATEGORIES)
    for m in db.read("raw_materials"):
        c = m.get("category")
        if c and c not in cats:
            cats.append(c)
    return cats


@catalog_bp.route("/", methods=["GET", "POST"])
@module_required("catalog")
def index():
    if request.method == "POST":
        pid = (request.form.get("id") or "").strip()
        name = (request.form.get("name") or "").strip()
        sku = (request.form.get("sku") or "").strip()
        variant = (request.form.get("variant") or "").strip()
        unit = (request.form.get("unit") or "pc").strip()
        if not name:
            flash("Product name is required.", "error")
        elif pid:
            db.update("products", pid, {"name": name, "sku": sku,
                                        "variant": variant, "unit": unit})
            flash("Product updated.", "success")
        else:
            db.insert("products", {"name": name, "sku": sku, "variant": variant,
                                   "unit": unit, "stock_qty": 0.0,
                                   "reorder_level": 0, "price": 0.0, "location": ""})
            flash("Product '%s' added." % name, "success")
        return redirect(url_for("catalog.index"))

    products = db.read("products")
    bom_counts = {}
    for line in db.read("bill_of_materials"):
        pid = line.get("product_id")
        bom_counts[pid] = bom_counts.get(pid, 0) + 1
    return render_template("catalog/products.html", products=products,
                           bom_counts=bom_counts)


@catalog_bp.route("/materials", methods=["GET", "POST"])
@module_required("catalog")
def materials():
    if request.method == "POST":
        mid = (request.form.get("id") or "").strip()
        name = (request.form.get("name") or "").strip()
        category = (request.form.get("category") or "raw").strip()
        unit = (request.form.get("unit") or "pc").strip()
        track_mode = (request.form.get("track_mode") or "weight").strip()
        if track_mode not in services.TRACK_MODE_LABELS:
            track_mode = "weight"
        stock = request.form.get("stock_qty") or "0"
        reorder = request.form.get("reorder_level") or "0"
        try:
            stock = float(stock)
            reorder = float(reorder)
        except ValueError:
            flash("Stock and reorder level must be numbers.", "error")
            return redirect(url_for("catalog.materials"))
        supplier_raw = (request.form.get("supplier_id") or "").strip()
        try:
            supplier_id = int(supplier_raw) if supplier_raw else None
        except ValueError:
            supplier_id = None
        try:
            unit_cost = float(request.form.get("unit_cost") or 0)
        except ValueError:
            unit_cost = 0.0
        expiry = (request.form.get("expiry_date") or "").strip()

        if not name:
            flash("Material name is required.", "error")
        elif mid:
            db.update("raw_materials", mid, {
                "name": name, "category": category, "unit": unit,
                "track_mode": track_mode, "reorder_level": reorder,
                "supplier_id": supplier_id, "unit_cost": unit_cost,
                "expiry_date": expiry})
            # Changing stock here records an inventory adjustment in the ledger.
            services.record_adjustment("material", mid, stock,
                                       reason="Stock edit via catalog",
                                       user_id=(current_user() or {}).get("id"))
            flash("Material updated.", "success")
        else:
            db.insert("raw_materials", {
                "name": name, "category": category, "unit": unit,
                "track_mode": track_mode, "stock_qty": stock,
                "reorder_level": reorder, "supplier_id": supplier_id,
                "unit_cost": unit_cost, "expiry_date": expiry,
                "storage_location": "", "created_at": services.now_iso()})
            flash("Material '%s' added." % name, "success")
        return redirect(url_for("catalog.materials"))

    return render_template("catalog/materials.html",
                           materials=db.read("raw_materials"),
                           categories=_categories(),
                           suppliers=db.read("suppliers"),
                           track_modes=services.TRACK_MODES,
                           track_labels=services.TRACK_MODE_LABELS)


@catalog_bp.route("/product/<int:product_id>/bom", methods=["GET", "POST"])
@module_required("catalog")
def product_bom(product_id):
    product = db.get("products", product_id)
    if not product:
        abort(404)

    if request.method == "POST":
        material_id = request.form.get("material_id")
        qty_per_unit = request.form.get("qty_per_unit")
        try:
            material_id = int(material_id)
            qty_per_unit = float(qty_per_unit)
        except (TypeError, ValueError):
            flash("Choose a material and a valid quantity.", "error")
            return redirect(url_for("catalog.product_bom", product_id=product_id))
        existing = [l for l in db.query("bill_of_materials", product_id=product_id)
                    if l.get("material_id") == material_id]
        if existing:
            db.update("bill_of_materials", existing[0]["id"],
                      {"qty_per_unit": qty_per_unit})
            flash("Recipe line updated.", "success")
        else:
            db.insert("bill_of_materials", {"product_id": product_id,
                                            "material_id": material_id,
                                            "qty_per_unit": qty_per_unit})
            flash("Component added to recipe.", "success")
        return redirect(url_for("catalog.product_bom", product_id=product_id))

    materials = db.read("raw_materials")
    mat_by_id = {m["id"]: m for m in materials}
    lines = []
    used_ids = set()
    for line in db.query("bill_of_materials", product_id=product_id):
        mat = mat_by_id.get(line.get("material_id"))
        if not mat:
            continue
        used_ids.add(mat["id"])
        lines.append({"id": line["id"], "material_name": mat.get("name"),
                      "category": mat.get("category"),
                      "qty_per_unit": line.get("qty_per_unit"),
                      "unit": mat.get("unit")})
    return render_template("catalog/bom.html", product=product, lines=lines,
                           available=materials, used_ids=used_ids)


@catalog_bp.route("/bom/<int:bom_id>/remove", methods=["POST"])
@module_required("catalog")
def bom_remove(bom_id):
    line = db.get("bill_of_materials", bom_id)
    product_id = line.get("product_id") if line else None
    db.delete("bill_of_materials", bom_id)
    flash("Recipe line removed.", "success")
    if product_id:
        return redirect(url_for("catalog.product_bom", product_id=product_id))
    return redirect(url_for("catalog.index"))
