"""Production blueprint: preview material requirements, then record a run."""
from flask import (Blueprint, flash, redirect, render_template, request, url_for)

import db
import services
from security import current_user, module_required

production_bp = Blueprint("production", __name__)


@production_bp.route("/")
@module_required("production")
def index():
    products = []
    for p in db.read("products"):
        row = dict(p)
        row["stock"] = float(p.get("stock_qty") or 0)
        products.append(row)
    return render_template("production/index.html", products=products,
                           history=services.production_history())


@production_bp.route("/new", methods=["GET", "POST"])
@module_required("production")
def new():
    if request.method == "POST":
        product_id = request.form.get("product_id")
        qty = request.form.get("qty")
        try:
            product_id = int(product_id)
            qty = float(qty)
        except (TypeError, ValueError):
            flash("Choose a product and quantity.", "error")
            return redirect(url_for("production.new"))
        try:
            rejected = float(request.form.get("rejected") or 0)
            damaged = float(request.form.get("damaged") or 0)
        except ValueError:
            rejected = damaged = 0.0
        order, err = services.record_production(product_id, qty, rejected=rejected,
                                                damaged=damaged,
                                                user_id=current_user()["id"])
        if err:
            flash(err, "error")
            return redirect(url_for("production.new", product_id=product_id, qty=qty))
        flash("Recorded production of %g x %s (batch %s)."
              % (qty, order.get("product_name"), order.get("batch_no")), "success")
        return redirect(url_for("production.index"))

    products = db.read("products")
    product_id = request.args.get("product_id")
    qty_arg = request.args.get("qty")
    selected = db.get("products", product_id) if product_id else None
    qty = 0.0
    rows = None
    can = False
    if selected and qty_arg:
        try:
            qty = float(qty_arg)
            rows = services.requirements_for(selected["id"], qty)
            can = all(r["shortfall"] <= 0 for r in rows)
        except ValueError:
            qty = 0.0
    return render_template("production/new.html", products=products,
                           selected=selected, qty=qty, rows=rows, can_produce=can)
