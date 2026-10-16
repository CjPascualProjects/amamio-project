"""Application factory for the Amamio Farm Products Sales & Inventory
Management System.

Run with:  python run.py   (or  python app.py)  then open http://localhost:5000
"""
import os
from datetime import date, timedelta

from flask import Flask, g, request

import db
import icons
import page_notes
import platform_service
import security
import services
from seed import seed_if_empty
from security import current_user

# Hardcoded fallback for the prototype; set AMAMIO_SECRET_KEY in production.
SECRET_KEY = os.environ.get("AMAMIO_SECRET_KEY",
                            "amamio-ims-secret-key-change-me")


def create_app():
    app = Flask(__name__)
    app.secret_key = SECRET_KEY
    # "Remember me" keeps the session for this long; otherwise it ends with
    # the browser.
    app.permanent_session_lifetime = timedelta(days=30)

    os.makedirs(db.DATA_DIR, exist_ok=True)
    seed_if_empty()
    # Shipped import templates are installed separately from the demo seed so
    # they also appear on a system that already holds real data.
    platform_service.seed_builtin_templates()

    # --- Register all blueprints ------------------------------------------
    from auth import auth_bp
    from catalog import catalog_bp
    from inventory import inventory_bp
    from requests_bp import requests_bp
    from approvals import approvals_bp
    from qr_bp import qr_bp
    from production import production_bp
    from sales import sales_bp
    from notifications import notifications_bp
    from analytics_bp import analytics_bp
    from suppliers import suppliers_bp
    from customers import customers_bp
    from orders import orders_bp
    from deliveries import deliveries_bp
    from reports import reports_bp
    from chatbot import chatbot_bp
    from receiving import receiving_bp
    from honey import honey_bp
    from packing import packing_bp
    from platforms import platforms_bp
    from assets import assets_bp
    from migration import migration_bp
    from supplies import supplies_bp
    from facility import facility_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(catalog_bp, url_prefix="/catalog")
    app.register_blueprint(inventory_bp, url_prefix="/inventory")
    app.register_blueprint(requests_bp, url_prefix="/requests")
    app.register_blueprint(approvals_bp, url_prefix="/approvals")
    app.register_blueprint(qr_bp, url_prefix="/qr")
    app.register_blueprint(production_bp, url_prefix="/production")
    app.register_blueprint(sales_bp, url_prefix="/sales")
    app.register_blueprint(notifications_bp, url_prefix="/notifications")
    app.register_blueprint(analytics_bp, url_prefix="/analytics")
    app.register_blueprint(suppliers_bp, url_prefix="/suppliers")
    app.register_blueprint(customers_bp, url_prefix="/customers")
    app.register_blueprint(orders_bp, url_prefix="/orders")
    app.register_blueprint(deliveries_bp, url_prefix="/deliveries")
    app.register_blueprint(reports_bp, url_prefix="/reports")
    app.register_blueprint(chatbot_bp, url_prefix="/chatbot")
    app.register_blueprint(receiving_bp, url_prefix="/receiving")
    app.register_blueprint(honey_bp, url_prefix="/honey")
    app.register_blueprint(packing_bp, url_prefix="/packing")
    app.register_blueprint(platforms_bp, url_prefix="/platforms")
    app.register_blueprint(assets_bp, url_prefix="/assets")
    app.register_blueprint(migration_bp, url_prefix="/migration")
    app.register_blueprint(supplies_bp, url_prefix="/supplies")
    app.register_blueprint(facility_bp, url_prefix="/facility")

    app.jinja_env.globals["icon"] = icons.icon
    app.jinja_env.filters["qty"] = services.fmt_qty
    app.jinja_env.filters["peso"] = services.fmt_peso

    # --- Global template context ------------------------------------------
    def _nav_active():
        """The one sidebar entry to highlight for this request.

        A view may name it via ``g.nav_endpoint``; otherwise an exact endpoint
        match wins, then the first entry from the same blueprint."""
        chosen = getattr(g, "nav_endpoint", None)
        if chosen:
            return chosen
        endpoints = [it[3] for _, items in security.NAV for it in items]
        if request.endpoint in endpoints:
            return request.endpoint
        for endpoint in endpoints:
            if (request.blueprint and request.blueprint != "auth"
                    and endpoint.split(".")[0] == request.blueprint):
                return endpoint
        return None

    @app.context_processor
    def inject_globals():
        user = current_user()
        from auth import theme_of
        return {
            "theme_pref": theme_of(user) if user else "dark",
            # "About this page" note (page_notes.py), unless the user hid them.
            "show_notes": bool(user) and not user.get("hide_notes"),
            "page_note": page_notes.for_endpoint(request.endpoint) if user else None,
            "nav_active": _nav_active() if user else None,
            "current_user": user,
            "nav_unread": services.unread_count(user["id"]) if user else 0,
            "can": (lambda module: security.can(user, module)),
            "nav_sections": security.NAV,
            "role_labels": security.ROLE_LABELS,
            "is_admin": security.is_admin(user),
            "is_super_admin": security.is_super_admin(user),
            "brand": {"name": "Amamio", "tagline": "Farm Products",
                      "system": "Sales & Inventory"},
            # e.g. "Wed, 14 Oct 2026" — shown in the top bar.
            "today_label": date.today().strftime("%a, %d %b %Y"),
        }

    return app


# Module-level WSGI application for production servers (e.g. gunicorn app:app).
app = create_app()


if __name__ == "__main__":
    app.run(debug=True, port=5000)
