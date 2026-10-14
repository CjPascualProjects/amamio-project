"""Notifications blueprint."""
from flask import (Blueprint, flash, redirect, render_template, request, url_for)

import db
import services
from security import current_user, module_required

notifications_bp = Blueprint("notifications", __name__)


def _back():
    ref = request.referrer or ""
    if "/notifications" in ref:
        return redirect(ref)
    return redirect(url_for("notifications.index"))


@notifications_bp.route("/")
@module_required("notifications")
def index():
    user = current_user()
    mine = [n for n in db.read("notifications")
            if int(n.get("user_id", 0)) == user["id"]]
    mine.sort(key=lambda n: n.get("created_at", ""), reverse=True)
    notes = []
    for n in mine:
        row = dict(n)
        row["created_at"] = (n.get("created_at") or "")[:16].replace("T", " ")
        notes.append(row)
    unread = sum(1 for n in mine if not n.get("is_read"))
    return render_template("notifications/index.html", notes=notes, unread=unread)


@notifications_bp.route("/<int:note_id>/read", methods=["POST"])
@module_required("notifications")
def mark_read(note_id):
    user = current_user()
    note = db.get("notifications", note_id)
    if not note or int(note.get("user_id", 0)) != user["id"]:
        flash("Notification not found.", "error")
        return _back()
    db.update("notifications", note_id, {"is_read": True})
    return _back()


@notifications_bp.route("/read-all", methods=["POST"])
@module_required("notifications")
def mark_all_read():
    user = current_user()
    for n in db.read("notifications"):
        if int(n.get("user_id", 0)) == user["id"] and not n.get("is_read"):
            db.update("notifications", n["id"], {"is_read": True})
    flash("All notifications marked read.", "success")
    return _back()
