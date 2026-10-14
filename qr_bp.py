"""QR blueprint: one scanner for every code the floor produces.

Four kinds of code circulate in the business, told apart by their prefix:

    PR-<request>-<item>  a material ordered against an approved purchase request
    RB-<box>             a receiving cage box / crate
    HC-<container>       a honey container awaiting (or carrying) its QC result
    PK-<run>             a packing run

Scanning any of them here resolves what it is and shows the matching action,
so staff only ever need this one screen.
"""
import io
import re

from flask import (Blueprint, Response, abort, flash, jsonify, redirect,
                   render_template, request, url_for)
from markupsafe import escape

import db
import services
from security import current_user, module_required

try:
    import qrcode
    _HAVE_QR = True
except ImportError:  # pragma: no cover - optional dependency
    _HAVE_QR = False

qr_bp = Blueprint("qr", __name__)

# Every token shape the scanner accepts.
TOKEN_RE = re.compile(r"^(?:PR-\d+-\d+|RB-\d+|HC-\d+|PK-\d+)$", re.IGNORECASE)


def _normalize(token):
    return (token or "").strip().upper()


def resolve_token(token):
    """Identify a scanned code.  Returns a dict describing what it points at."""
    token = _normalize(token)
    if not TOKEN_RE.match(token):
        return {"ok": False, "kind": "unknown",
                "message": "Unrecognised code: %s" % (token or "(empty)")}

    prefix = token.split("-")[0]

    if prefix == "RB":
        box = db.get("receiving_boxes", token.split("-")[1])
        if not box:
            return {"ok": False, "kind": "box",
                    "message": "No receiving box matches %s." % token}
        batch = db.get("receiving_batches", box.get("batch_id")) or {}
        return {
            "ok": True, "kind": "box", "token": token, "record": box,
            "title": "Receiving box %s" % token,
            "subtitle": "%s · %s" % (box.get("material_name") or "—",
                                     batch.get("ref_no") or ""),
            "status": box.get("status"),
            "url": url_for("receiving.batch", batch_id=box.get("batch_id")),
            "details": [
                ("Material", box.get("material_name")),
                ("Declared", "%s %s" % (box.get("declared_qty"),
                                        box.get("unit") or "")),
                ("Good", box.get("good_qty")),
                ("Damaged", box.get("damaged_qty")),
                ("Stage", box.get("stage")),
                ("Supplier", batch.get("supplier_name")),
                ("Received", batch.get("received_date")),
            ],
        }

    if prefix == "HC":
        container = db.get("honey_containers", token.split("-")[1])
        if not container:
            return {"ok": False, "kind": "container",
                    "message": "No honey container matches %s." % token}
        return {
            "ok": True, "kind": "container", "token": token,
            "record": container,
            "title": "Honey container %s" % token,
            "subtitle": container.get("batch_ref") or "",
            "status": container.get("status"),
            "url": url_for("honey.qc", container_id=container["id"]),
            "details": [
                ("Net weight", "%s kg" % container.get("net_weight_kg")),
                ("Source", container.get("source")),
                ("Moisture", container.get("moisture_pct")),
                ("Appearance", container.get("appearance")),
                ("Disposition", container.get("disposition")),
                ("Received", container.get("received_date")),
            ],
        }

    if prefix == "PK":
        run = db.get("packing_runs", token.split("-")[1])
        if not run:
            return {"ok": False, "kind": "packing",
                    "message": "No packing run matches %s." % token}
        return {
            "ok": True, "kind": "packing", "token": token, "record": run,
            "title": "Packing run %s" % token,
            "subtitle": "%s · %s" % (run.get("channel") or "",
                                     run.get("packer_name") or ""),
            "status": run.get("status"),
            "url": url_for("packing.detail", run_id=run["id"]),
            "details": [
                ("Channel", run.get("channel")),
                ("Packer", run.get("packer_name")),
                ("Items", len(run.get("items", []))),
                ("Quantity", run.get("total_qty")),
                ("Pack date", run.get("pack_date")),
                ("Courier", run.get("courier")),
            ],
        }

    # PR-<request>-<item>
    request_id, item_id = services.parse_qr_token(token)
    req = db.get("purchase_requests", request_id) if request_id else None
    if not req:
        return {"ok": False, "kind": "purchase",
                "message": "No purchase request matches %s." % token}
    item = next((i for i in req.get("items", [])
                 if i.get("item_id") == item_id), None)
    if not item:
        return {"ok": False, "kind": "purchase",
                "message": "No item on request #%s matches %s."
                           % (request_id, token)}
    material = db.get("raw_materials", item.get("material_id")) or {}
    return {
        "ok": True, "kind": "purchase", "token": token, "record": item,
        "title": "Purchase request #%s" % request_id,
        "subtitle": material.get("name") or item.get("name") or "",
        "status": item.get("status"),
        "url": url_for("requests.detail", id=request_id),
        "details": [
            ("Item", material.get("name") or item.get("name")),
            ("Requested", item.get("requested_qty")),
            ("Approved", item.get("approved_qty")),
            ("Status", item.get("status")),
        ],
    }


@qr_bp.route("/scan")
@module_required("qr")
def scan():
    return render_template("qr/scan.html")


@qr_bp.route("/lookup")
@module_required("qr")
def lookup():
    """JSON resolution of a scanned code, used by the scanner page."""
    result = resolve_token(request.args.get("token"))
    payload = {k: v for k, v in result.items() if k != "record"}
    return jsonify(payload), (200 if result.get("ok") else 404)


@qr_bp.route("/go")
@module_required("qr")
def go():
    """Open whatever a scanned code points at."""
    result = resolve_token(request.args.get("token"))
    if not result.get("ok"):
        flash(result.get("message"), "error")
        return redirect(url_for("qr.scan"))
    return redirect(result["url"])


@qr_bp.route("/receive", methods=["POST"])
@module_required("qr")
def receive():
    """Receive a material against an approved purchase-request token."""
    if request.is_json:
        data = request.get_json(silent=True) or {}
        token = data.get("token")
        received_qty = data.get("received_qty")
        note = data.get("note") or ""
    else:
        token = request.form.get("token")
        received_qty = request.form.get("received_qty")
        note = request.form.get("note") or ""

    result = services.receive_item(token, received_qty, note,
                                   user_id=current_user()["id"])

    if request.is_json:
        status = 200 if result.get("ok") else 400
        return jsonify({"message": result.get("message"),
                        "stock": result.get("stock")}), status

    flash(result.get("message"), "success" if result.get("ok") else "error")
    return redirect(url_for("qr.scan"))


@qr_bp.route("/image/<token>")
@module_required("qr")
def image(token):
    """Render a token as a QR PNG (or a readable placeholder without qrcode)."""
    token = _normalize(token)
    if not TOKEN_RE.match(token):
        abort(404)
    if _HAVE_QR:
        img = qrcode.make(token)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return Response(buf.getvalue(), mimetype="image/png")
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="160" height="160" '
        'viewBox="0 0 160 160"><rect width="160" height="160" fill="#fff" '
        'stroke="#111"/><text x="80" y="80" text-anchor="middle" '
        'font-size="12" font-family="monospace" fill="#111">%s</text></svg>'
        % escape(token))
    return Response(svg, mimetype="image/svg+xml")


@qr_bp.route("/print/<int:request_id>")
@module_required("qr")
def print_codes(request_id):
    req = db.get("purchase_requests", request_id)
    if not req:
        abort(404)
    requestor = db.get("users", req.get("requestor_id"))
    materials_by_id = {m["id"]: m for m in db.read("raw_materials")}
    items = []
    for it in req.get("items", []):
        if not it.get("qr_token"):
            continue
        row = dict(it)
        if it.get("material_id"):
            mat = materials_by_id.get(it.get("material_id"), {})
            row["material_name"] = mat.get("name")
        items.append(row)
    return render_template("qr/print_codes.html", req=req, requestor=requestor,
                           items=items)
