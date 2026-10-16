"""Supplier Directory — the client's paper list (SUPPLIER, TIN, ITEMS,
Contact#) filed under Raw / Production / Packing / Office.

One supplier per page, added or edited in a short wizard, and a printable
copy of the whole directory grouped by category.
"""
from flask import (Blueprint, abort, flash, g, redirect, render_template,
                   request, url_for)

import db
import services
from security import module_required

suppliers_bp = Blueprint("suppliers", __name__)

CATEGORIES = ["Raw", "Production", "Packing", "Office"]
CATEGORY_HINTS = {
    "Raw": "Honey, produce and other raw materials",
    "Production": "Equipment, ingredients and supplies for production",
    "Packing": "Jars, bottles, pouches, labels, boxes, tape",
    "Office": "Paper, ink and office supplies",
}
BUY_FROM = ["Shopee", "Lazada", "TikTok", "Direct", "Other"]


def _norm_category(value):
    for c in CATEGORIES:
        if (value or "").strip().lower() in (c.lower(), c.lower()[:4]):
            return c
    return ""


def _buy_choice(value):
    """Map a stored buy_from onto (chip, other-text)."""
    value = (value or "").strip()
    if not value:
        return "", ""
    for b in BUY_FROM[:-1]:
        if value.lower() == b.lower():
            return b, ""
    return "Other", value


def _contact_line(s):
    """What goes in the paper's Contact# column."""
    parts = [s.get("contact_person"), s.get("phone"), s.get("buy_from")]
    return " · ".join(p for p in parts if p)


def _view(s):
    cat = _norm_category(s.get("category"))
    return dict(s, category=cat or "Other", contact_line=_contact_line(s),
                search=" ".join(str(s.get(k) or "") for k in (
                    "name", "tin", "materials_supplied", "contact_person",
                    "phone", "email", "buy_from", "address")).lower())


def _all():
    return sorted((_view(s) for s in db.read("suppliers")),
                  key=lambda s: (s.get("name") or "").lower())


@suppliers_bp.route("/")
@module_required("suppliers")
def index():
    cat = request.args.get("cat") or "All"
    if cat not in CATEGORIES:
        cat = "All"
    everyone = _all()
    counts = {c: sum(1 for s in everyone if s["category"] == c) for c in CATEGORIES}
    counts["All"] = len(everyone)
    rows = everyone if cat == "All" else [s for s in everyone if s["category"] == cat]
    return render_template("suppliers/index.html", suppliers=rows, cat=cat,
                           categories=CATEGORIES, counts=counts,
                           q=request.args.get("q") or "")


def _form_payload(form):
    name = (form.get("name") or "").strip()[:120]
    category = _norm_category(form.get("category"))
    buy = (form.get("buy_from") or "").strip()
    if buy == "Other":
        buy = (form.get("buy_from_other") or "").strip()[:80] or "Other"
    elif buy not in BUY_FROM:
        buy = ""
    try:
        lead = int(form.get("lead_time_days")) if form.get("lead_time_days") else None
        if lead is not None and lead < 0:
            lead = None
    except (TypeError, ValueError):
        lead = None
    payload = {
        "name": name, "category": category,
        "materials_supplied": (form.get("materials_supplied") or "").strip()[:1000],
        "tin": (form.get("tin") or "").strip()[:30],
        "contact_person": (form.get("contact_person") or "").strip()[:120],
        "phone": (form.get("phone") or "").strip()[:40],
        "email": (form.get("email") or "").strip()[:120],
        "address": (form.get("address") or "").strip()[:300],
        "buy_from": buy, "lead_time_days": lead,
        "notes": (form.get("notes") or "").strip()[:500],
    }
    return payload


def _check(payload, supplier_id=None):
    """Return (message, wizard step) or None."""
    if not payload["name"]:
        return "Enter the supplier's name.", 0
    if not payload["category"]:
        return "Choose what the supplier is filed under.", 0
    for s in db.read("suppliers"):
        if (s.get("name") or "").strip().lower() == payload["name"].lower() \
                and s.get("id") != supplier_id:
            return "'%s' is already in the directory." % s.get("name"), 0
    if payload["email"] and "@" not in payload["email"]:
        return "That email address doesn't look right.", 2
    return None


def _wizard(supplier, form, start, title, submit):
    source = form if form else supplier or {}
    chip, other = _buy_choice(source.get("buy_from"))
    if form:
        chip, other = form.get("buy_from") or "", form.get("buy_from_other") or ""
    return render_template(
        "suppliers/form.html", supplier=supplier, f=source, start=start,
        categories=CATEGORIES, hints=CATEGORY_HINTS, buy_options=BUY_FROM,
        buy_chip=chip, buy_other=other, page_title=title, submit_label=submit,
        category=_norm_category(source.get("category")) if not form else form.get("category"))


@suppliers_bp.route("/new", methods=["GET", "POST"])
@module_required("suppliers")
def new():
    g.nav_endpoint = "suppliers.index"
    start = 0
    if request.method == "POST":
        payload = _form_payload(request.form)
        problem = _check(payload)
        if not problem:
            payload["created_at"] = services.now_iso()
            row = db.insert("suppliers", payload)
            flash("Supplier '%s' added." % row["name"], "success")
            return redirect(url_for("suppliers.detail", supplier_id=row["id"]))
        flash(problem[0], "error")
        start = problem[1]
    preset = {"category": request.args.get("cat")} if request.method == "GET" else None
    return _wizard(preset, request.form, start, "Add a supplier", "Add supplier")


@suppliers_bp.route("/<int:supplier_id>")
@module_required("suppliers")
def detail(supplier_id):
    g.nav_endpoint = "suppliers.index"
    s = db.get("suppliers", supplier_id)
    if not s:
        abort(404)
    materials = sorted((m for m in db.read("raw_materials")
                        if m.get("supplier_id") == supplier_id),
                       key=lambda m: (m.get("name") or "").lower())
    deliveries = [b for b in db.read("receiving_batches")
                  if b.get("supplier_id") == supplier_id]
    deliveries.sort(key=lambda b: b.get("received_date") or "", reverse=True)
    return render_template("suppliers/detail.html", s=_view(s),
                           materials=materials, deliveries=deliveries[:5],
                           delivery_count=len(deliveries),
                           hints=CATEGORY_HINTS)


@suppliers_bp.route("/<int:supplier_id>/edit", methods=["GET", "POST"])
@module_required("suppliers")
def edit(supplier_id):
    g.nav_endpoint = "suppliers.index"
    s = db.get("suppliers", supplier_id)
    if not s:
        abort(404)
    start = 0
    if request.method == "POST":
        payload = _form_payload(request.form)
        problem = _check(payload, supplier_id)
        if not problem:
            db.update("suppliers", supplier_id, payload)
            flash("Supplier '%s' updated." % payload["name"], "success")
            return redirect(url_for("suppliers.detail", supplier_id=supplier_id))
        flash(problem[0], "error")
        start = problem[1]
    return _wizard(s, request.form, start, "Edit %s" % s.get("name"), "Save changes")


@suppliers_bp.route("/print")
@module_required("suppliers")
def print_directory():
    g.nav_endpoint = "suppliers.index"
    everyone = _all()
    groups = []
    for c in CATEGORIES + ["Other"]:
        rows = [s for s in everyone if s["category"] == c]
        if rows:
            groups.append((c, rows))
    return render_template("suppliers/print.html", groups=groups,
                           total=len(everyone), today=services.today_iso())
