"""Authentication & role-based authorization for the Amamio Farm Products
Sales & Inventory Management System.

Seven roles (per the client's team structure):

    super_admin      Super Admin               — full control, incl. roles
    admin            Admin                     — day-to-day control & approvals
    receiving_head   Receiving Team Head       — records every delivery and
                                                 labels it with QR codes
    production_head  Production Team Head      — inspection & cleaning, honey
                                                 QC, batch records, production
    packing_head     Packing Team Head         — packing, dispatch, sales uploads
    packing_member   Packing Team Member       — records packing and dispatch
    assets_head      Assets Maintenance Head   — equipment, supplies in/out,
                                                 maintenance, sanitation

Access is expressed per *module* (a nav destination / blueprint area).  The
PERMISSIONS map is the single source of truth used for both the sidebar
(``can(user, module)``) and the route guards (``module_required``).
"""
from functools import wraps

from flask import abort, redirect, session, url_for

import db

# --- Roles -----------------------------------------------------------------
ROLES = [
    ("super_admin", "Super Admin",
     "Full system control: users, roles, settings and all operations"),
    ("admin", "Admin",
     "Approves requests, oversees operations, reviews reports"),
    ("receiving_head", "Receiving Team Head",
     "Records every delivery at the receiving area and labels it with QR codes"),
    ("production_head", "Production Team Head",
     "Inspection & cleaning, honey QC, batch records and production runs"),
    ("packing_head", "Packing Team Head",
     "Leads packing and dispatch per channel; uploads platform sales"),
    ("packing_member", "Packing Team Member",
     "Records what was packed, disbursed and handed to the courier"),
    ("assets_head", "Assets Maintenance Head",
     "Equipment, supplies in/out, maintenance, cleaning and pest control"),
]
ROLE_KEYS = [r[0] for r in ROLES]
ROLE_LABELS = {r[0]: r[1] for r in ROLES}
ROLE_DESCRIPTIONS = {r[0]: r[2] for r in ROLES}

# Roles that behave as "management" — they see everything and approve requests.
ADMIN_ROLES = {"super_admin", "admin"}

# Legacy role keys (from the pre-Amamio prototype) mapped onto the new set so
# existing data/accounts keep working after an upgrade.
LEGACY_ROLE_MAP = {
    "manager": "admin",
    "inventory": "production_head",
    "production": "production_head",
    "sales": "packing_head",
    "warehouse": "packing_head",
}

# --- Module access ---------------------------------------------------------
# module_key -> set of roles allowed.  super_admin/admin are allowed everywhere
# except where a module is explicitly restricted below.
_ALL = set(ROLE_KEYS)
_HEADS = _ALL - {"packing_member"}
PERMISSIONS = {
    "dashboard":     _ALL,
    "inventory":     _ALL,                       # everyone can view stock
    "qr":            _ALL,                       # one scanner for the floor
    "chatbot":       _ALL,
    "notifications": _ALL,
    "requests":      _HEADS,                     # every head can raise requests
    "analytics":     ADMIN_ROLES,
    "approvals":     ADMIN_ROLES,
    "reports":       ADMIN_ROLES,
    "users":         ADMIN_ROLES,
    "migration":     {"super_admin"},

    # Module 1 — receiving area, then inspection & cleaning.
    "receiving":     ADMIN_ROLES | {"receiving_head"},
    "inspection":    ADMIN_ROLES | {"receiving_head", "production_head"},
    # Module 2 — honey containers are logged on arrival, QC'd by production.
    "honey":         ADMIN_ROLES | {"receiving_head", "production_head"},
    # Production records (batch manufacturing, daily report, retention).
    "production":    ADMIN_ROLES | {"production_head"},
    "catalog":       ADMIN_ROLES | {"production_head"},
    # Module 3 — equipment and supplies, every movement in and out.
    "assets":        ADMIN_ROLES | {"assets_head"},
    "supplies":      ADMIN_ROLES | {"assets_head", "receiving_head"},
    "facility":      ADMIN_ROLES | {"assets_head", "production_head"},
    "suppliers":     ADMIN_ROLES | {"receiving_head", "production_head",
                                    "assets_head"},
    # Module 4 — packing, disbursement and courier hand-over.
    "packing":       ADMIN_ROLES | {"packing_head", "packing_member"},
    # Module 5 — marketplace uploads and sales reports.
    "platforms":     ADMIN_ROLES | {"packing_head"},
    # Stock release: packing requests it, production fulfils it.
    "sales":         ADMIN_ROLES | {"packing_head", "production_head"},
    "orders":        ADMIN_ROLES | {"packing_head"},   # customer sales orders
    "deliveries":    ADMIN_ROLES | {"packing_head"},
    "customers":     ADMIN_ROLES | {"packing_head"},
}

# Modules only the Super Admin may reach, whatever PERMISSIONS says.
SUPER_ADMIN_ONLY = {"migration"}

# Sidebar groups: (section label, [(module, label, icon name, endpoint), ...])
# Icon names refer to icons.ICONS (monochrome line icons).  Each role only sees
# the entries it may open, so a floor role gets a short, focused menu.
NAV = [
    ("Start", [
        ("dashboard", "Home",           "dashboard", "auth.dashboard"),
        ("qr",        "Scan a QR code", "qr", "qr.scan"),
    ]),
    ("Receiving & Inspection", [
        ("receiving",  "Receiving Area",        "receiving", "receiving.index"),
        ("inspection", "Inspection & Cleaning", "inspect", "receiving.inspection"),
        ("honey",      "Honey Containers",      "honey", "honey.index"),
    ]),
    ("Production", [
        ("production", "Batch Records",           "production", "production.index"),
        ("production", "Daily Production Report", "reports", "production.daily_report"),
        ("production", "Retention Samples",       "retention", "production.retention"),
        ("catalog",    "Products & Recipes",      "recipes", "catalog.index"),
        ("inventory",  "Stock on Hand",           "inventory", "inventory.index"),
    ]),
    ("Packing & Sales", [
        ("packing",    "Packing & Dispatch",      "packing", "packing.index"),
        ("platforms",  "Sales Uploads & Reports", "platforms", "platforms.index"),
        ("orders",     "Sales Orders",            "orders", "orders.index"),
        ("sales",      "Stock Release",           "release", "sales.index"),
        ("deliveries", "Deliveries",              "deliveries", "deliveries.index"),
        ("customers",  "Customers",               "customers", "customers.index"),
    ]),
    ("Assets & Facility", [
        ("assets",    "Equipment & Assets",    "assets", "assets.index"),
        ("supplies",  "Supplies In / Out",     "swap", "supplies.index"),
        ("facility",  "Cleaning & Sanitation", "sparkle", "facility.sanitation"),
        ("facility",  "Pest Control",          "shield", "facility.pest"),
        ("suppliers", "Supplier Directory",    "suppliers", "suppliers.index"),
    ]),
    ("Management", [
        ("requests",  "Requests",  "requests", "requests.index"),
        ("approvals", "Approvals", "approvals", "approvals.index"),
        ("reports",   "Reports",   "reports", "reports.index"),
        ("analytics", "Analytics", "analytics", "analytics.index"),
    ]),
    ("General", [
        ("notifications", "Notifications", "notifications", "notifications.index"),
        ("users",         "Users",         "users", "auth.users"),
        ("migration",     "MySQL Export",  "database", "migration.index"),
    ]),
]

def normalize_role(role):
    """Map a legacy role key onto the current role set."""
    if role in ROLE_KEYS:
        return role
    return LEGACY_ROLE_MAP.get(role, role)


def is_admin(user):
    """True for Super Admin / Admin — the two management roles."""
    if not user:
        return False
    return normalize_role(user.get("role")) in ADMIN_ROLES


def is_super_admin(user):
    return bool(user) and normalize_role(user.get("role")) == "super_admin"


def can(user, module):
    """True if the given user dict may access the module."""
    if not user:
        return False
    role = normalize_role(user.get("role"))
    if module in SUPER_ADMIN_ONLY:
        return role == "super_admin"
    if role in ADMIN_ROLES:
        return True
    allowed = PERMISSIONS.get(module)
    return bool(allowed) and role in allowed


def current_user():
    """Return the logged-in user dict from session, or None."""
    uid = session.get("user_id")
    if uid is None:
        return None
    user = db.get("users", uid)
    if user and not user.get("active", True):
        return None
    return user


def login_required(f):
    """Redirect to the login page if the request is not authenticated."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        if current_user() is None:
            return redirect(url_for("auth.login"))
        return f(*args, **kwargs)
    return wrapper


def role_required(*roles):
    """403 unless the user's role is in ``roles``.

    Super Admin and Admin always pass, except when the decorator names
    ``super_admin`` alone — that restricts the route to the Super Admin."""
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            user = current_user()
            if user is None:
                return redirect(url_for("auth.login"))
            role = normalize_role(user.get("role"))
            if set(roles) == {"super_admin"}:
                if role != "super_admin":
                    abort(403)
                return f(*args, **kwargs)
            if role not in ADMIN_ROLES and role not in roles:
                abort(403)
            return f(*args, **kwargs)
        return wrapper
    return decorator


def module_required(module):
    """403 unless the current user may access ``module`` (per PERMISSIONS)."""
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            user = current_user()
            if user is None:
                return redirect(url_for("auth.login"))
            if not can(user, module):
                abort(403)
            return f(*args, **kwargs)
        return wrapper
    return decorator
