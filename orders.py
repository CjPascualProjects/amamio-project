"""Customer sales orders: quotation/invoice, confirmation (stock release),
payments, delivery scheduling, and returns."""
from flask import (Blueprint, abort, flash, redirect, render_template, request,
                   url_for)

import db
import services
from security import current_user, module_required

orders_bp = Blueprint("orders", __name__)


@orders_bp.route("/")
@module_required("orders")
def index():
    orders = sorted(db.read("sales_orders"),
                    key=lambda o: o.get("order_date", ""), reverse=True)
    rows = []
    for o in orders:
        rows.append({
            "id": o["id"], "customer_name": o.get("customer_name"),
            "order_date": (o.get("order_date") or "")[:10],
            "item_count": len(o.get("items", [])),
            "total": float(o.get("total") or 0),
            "status": o.get("status"),
            "status_badge": services.ORDER_BADGE.get(o.get("status"), "badge-muted"),
            "payment_status": o.get("payment_status"),
            "payment_badge": services.PAYMENT_BADGE.get(o.get("payment_status"),
                                                        "badge-muted"),
        })
    return render_template("orders/index.html", orders=rows)


@orders_bp.route("/new", methods=["GET", "POST"])
@module_required("orders")
def new():
    if request.method == "POST":
        customer_id = request.form.get("customer_id")
        discount = request.form.get("discount") or 0
        remarks = request.form.get("remarks") or ""
        product_ids = request.form.getlist("product_id")
        qtys = request.form.getlist("qty")
        prices = request.form.getlist("unit_price")
        try:
            customer_id = int(customer_id)
        except (TypeError, ValueError):
            flash("Choose a customer.", "error")
            return redirect(url_for("orders.new"))
        lines = []
        for i, pid in enumerate(product_ids):
            try:
                qty = float(qtys[i]) if i < len(qtys) else 0
            except ValueError:
                qty = 0
            if qty > 0:
                price = prices[i] if i < len(prices) else None
                lines.append({"product_id": int(pid), "qty": qty,
                              "unit_price": price})
        order, err = services.create_sales_order(customer_id, lines, discount,
                                                 remarks, current_user()["id"])
        if err:
            flash(err, "error")
            return redirect(url_for("orders.new"))
        flash("Sales order #%d created." % order["id"], "success")
        return redirect(url_for("orders.detail", id=order["id"]))

    return render_template("orders/new.html", customers=db.read("customers"),
                           products=db.read("products"))


@orders_bp.route("/<int:id>")
@module_required("orders")
def detail(id):
    order = db.get("sales_orders", id)
    if not order:
        abort(404)
    payments = db.query("payments", sales_order_id=id)
    deliveries = db.query("deliveries", sales_order_id=id)
    returns = db.query("returns", sales_order_id=id)
    paid = services.order_paid_amount(id)
    return render_template(
        "orders/detail.html", order=order, payments=payments,
        deliveries=deliveries, returns=returns, paid=paid,
        balance=max(0.0, float(order.get("total") or 0) - paid),
        status_badge=services.ORDER_BADGE, payment_badge=services.PAYMENT_BADGE,
        delivery_badge=services.DELIVERY_BADGE)


@orders_bp.route("/<int:id>/confirm", methods=["POST"])
@module_required("orders")
def confirm(id):
    ok, message = services.confirm_sales_order(id, user_id=current_user()["id"])
    flash(message, "success" if ok else "error")
    return redirect(url_for("orders.detail", id=id))


@orders_bp.route("/<int:id>/pay", methods=["POST"])
@module_required("orders")
def pay(id):
    amount = request.form.get("amount")
    method = request.form.get("method") or "Cash"
    reference = request.form.get("reference") or ""
    ok, message = services.record_payment(id, amount, method, reference,
                                          user_id=current_user()["id"])
    flash(message, "success" if ok else "error")
    return redirect(url_for("orders.detail", id=id))


@orders_bp.route("/<int:id>/deliver", methods=["POST"])
@module_required("orders")
def deliver(id):
    scheduled = request.form.get("scheduled_date") or ""
    driver = request.form.get("driver") or ""
    address = request.form.get("address") or ""
    delivery, err = services.create_delivery(id, scheduled, driver, address,
                                             user_id=current_user()["id"])
    flash(err or "Delivery #%d scheduled." % delivery["id"],
          "error" if err else "success")
    return redirect(url_for("orders.detail", id=id))


@orders_bp.route("/<int:id>/return", methods=["POST"])
@module_required("orders")
def return_line(id):
    product_id = request.form.get("product_id")
    qty = request.form.get("qty")
    reason = request.form.get("reason") or ""
    try:
        product_id = int(product_id)
    except (TypeError, ValueError):
        flash("Choose a product to return.", "error")
        return redirect(url_for("orders.detail", id=id))
    ret, err = services.process_return(id, product_id, qty, reason,
                                       user_id=current_user()["id"])
    flash(err or "Return recorded; stock restored.", "error" if err else "success")
    return redirect(url_for("orders.detail", id=id))
