"""Authentication, dashboard and user-management blueprint (auth_bp)."""
from flask import (Blueprint, flash, jsonify, redirect, render_template,
                   request, session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

import db
import home
import services
from security import (ROLE_DESCRIPTIONS, ROLE_KEYS, ROLE_LABELS, current_user,
                      is_admin, is_super_admin, login_required, normalize_role,
                      role_required)

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/")
def root():
    return redirect(url_for("auth.dashboard"))


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user() is not None:
        return redirect(url_for("auth.dashboard"))
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        users = db.query("users", username=username)
        user = users[0] if users else None
        if user and check_password_hash(user.get("password_hash", ""), password):
            if not user.get("active", True):
                flash("This account is disabled. Contact an administrator.",
                      "error")
                return render_template("login.html")
            session["user_id"] = user["id"]
            session.permanent = request.form.get("remember") == "1"
            db.update("users", user["id"], {"last_login": services.now_iso()})
            flash("Welcome back, %s." % user.get("name", username), "success")
            return redirect(url_for("auth.dashboard"))
        flash("Invalid username or password.", "error")
    return render_template("login.html")


THEMES = ("light", "dark", "system")


def theme_of(user):
    """A user's colour theme: light, dark, or system (match the device)."""
    theme = (user or {}).get("theme")
    return theme if theme in THEMES else "dark"


@auth_bp.route("/settings/theme", methods=["POST"])
@login_required
def set_theme():
    """Save the user's colour theme (the topbar sun / moon menu)."""
    theme = request.form.get("theme") or (request.get_json(silent=True) or {}).get("theme")
    if theme not in THEMES:
        return jsonify({"message": "Choose light, dark or system."}), 400
    db.update("users", current_user()["id"], {"theme": theme})
    if request.is_json or request.headers.get("X-Requested-With") == "fetch":
        return jsonify({"theme": theme})
    back = request.referrer or url_for("auth.dashboard")
    return redirect(back if back.startswith(request.host_url) else
                    url_for("auth.dashboard"))


@auth_bp.route("/settings/notes", methods=["POST"])
@login_required
def set_notes():
    """Show or hide the 'About this page' notes for this user."""
    show = request.form.get("show") == "1"
    db.update("users", current_user()["id"], {"hide_notes": not show})
    if request.headers.get("X-Requested-With") == "fetch":
        return jsonify({"show": show})
    back = request.referrer or url_for("auth.dashboard")
    return redirect(back if back.startswith(request.host_url) else
                    url_for("auth.dashboard"))


@auth_bp.route("/logout")
def logout():
    session.pop("user_id", None)
    flash("You have been logged out.", "success")
    return redirect(url_for("auth.login"))


@auth_bp.route("/dashboard")
@login_required
def dashboard():
    """Home: the few things this user does, and what is waiting for them."""
    return render_template("dashboard.html", **home.context(current_user()))


@auth_bp.route("/users", methods=["GET", "POST"])
@role_required("admin")
def users():
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        role = request.form.get("role") or ""
        email = (request.form.get("email") or "").strip()
        phone = (request.form.get("phone") or "").strip()
        if not (name and username and password and role):
            flash("Name, username, password and role are all required.", "error")
        elif role not in ROLE_KEYS:
            flash("Invalid role.", "error")
        elif role == "super_admin" and not is_super_admin(current_user()):
            flash("Only a Super Admin can create another Super Admin.", "error")
        elif db.query("users", username=username):
            flash("Username already exists.", "error")
        elif len(password) < 6:
            flash("Use a password of at least 6 characters.", "error")
        else:
            db.insert("users", {
                "name": name, "username": username,
                "password_hash": generate_password_hash(password),
                "role": role, "email": email, "phone": phone,
                "team": ROLE_LABELS.get(role, role), "active": True,
                "last_login": None, "created_at": services.now_iso(),
            })
            flash("User '%s' created as %s."
                  % (username, ROLE_LABELS.get(role, role)), "success")
        return redirect(url_for("auth.users"))

    rows = []
    for u in db.read("users"):
        role = normalize_role(u.get("role"))
        rows.append({
            "id": u["id"], "name": u.get("name"), "username": u.get("username"),
            "email": u.get("email"), "phone": u.get("phone"),
            "role": role, "role_label": ROLE_LABELS.get(role, role),
            "active": u.get("active", True),
            "last_login": services.fmt_dt(u.get("last_login")) or "Never",
            "created_at": services.fmt_dt(u.get("created_at"), 10),
        })
    rows.sort(key=lambda r: (ROLE_KEYS.index(r["role"])
                             if r["role"] in ROLE_KEYS else 99, r["name"] or ""))
    return render_template("users.html", users=rows, roles=ROLE_KEYS,
                           role_labels=ROLE_LABELS,
                           role_descriptions=ROLE_DESCRIPTIONS,
                           can_manage_super=is_super_admin(current_user()))


def _other_active_admins(exclude_id):
    """Active accounts that could still administer the system."""
    return [u for u in db.read("users")
            if is_admin(u) and u.get("active", True) and u["id"] != exclude_id]


def _other_super_admins(exclude_id):
    return [u for u in db.read("users")
            if is_super_admin(u) and u.get("active", True)
            and u["id"] != exclude_id]


@auth_bp.route("/users/<int:id>/toggle", methods=["POST"])
@role_required("admin")
def toggle_user(id):
    me = current_user()
    target = db.get("users", id)
    if not target:
        flash("User not found.", "error")
    elif target["id"] == me["id"]:
        flash("You cannot change your own account status.", "error")
    elif is_super_admin(target) and not is_super_admin(me):
        flash("Only a Super Admin can change a Super Admin account.", "error")
    else:
        new_active = not target.get("active", True)
        if not new_active and is_super_admin(target) \
                and not _other_super_admins(id):
            flash("Cannot deactivate the last active Super Admin.", "error")
        elif not new_active and is_admin(target) and not _other_active_admins(id):
            flash("Cannot deactivate the last account with admin access.",
                  "error")
        else:
            db.update("users", id, {"active": new_active})
            flash("User '%s' %s." % (target.get("username"),
                                     "activated" if new_active
                                     else "deactivated"), "success")
    return redirect(url_for("auth.users"))


@auth_bp.route("/users/<int:id>/role", methods=["POST"])
@role_required("admin")
def change_role(id):
    me = current_user()
    role = request.form.get("role") or ""
    target = db.get("users", id)
    if not target:
        flash("User not found.", "error")
    elif role not in ROLE_KEYS:
        flash("Invalid role.", "error")
    elif (is_super_admin(target) or role == "super_admin") \
            and not is_super_admin(me):
        flash("Only a Super Admin can grant or remove Super Admin access.",
              "error")
    elif is_super_admin(target) and role != "super_admin" \
            and not _other_super_admins(id):
        flash("Cannot change the role of the last active Super Admin.", "error")
    elif is_admin(target) and role not in ("super_admin", "admin") \
            and not _other_active_admins(id):
        flash("Cannot remove admin access from the last admin account.", "error")
    else:
        db.update("users", id, {"role": role,
                                "team": ROLE_LABELS.get(role, role)})
        flash("Role for '%s' set to %s."
              % (target.get("username"), ROLE_LABELS.get(role, role)), "success")
    return redirect(url_for("auth.users"))


@auth_bp.route("/users/<int:id>/password", methods=["POST"])
@role_required("admin")
def reset_password(id):
    me = current_user()
    target = db.get("users", id)
    password = request.form.get("password") or ""
    if not target:
        flash("User not found.", "error")
    elif is_super_admin(target) and not is_super_admin(me) \
            and target["id"] != me["id"]:
        flash("Only a Super Admin can reset a Super Admin password.", "error")
    elif len(password) < 6:
        flash("Use a password of at least 6 characters.", "error")
    else:
        db.update("users", id,
                  {"password_hash": generate_password_hash(password)})
        flash("Password reset for '%s'." % target.get("username"), "success")
    return redirect(url_for("auth.users"))
