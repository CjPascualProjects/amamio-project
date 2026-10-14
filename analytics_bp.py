"""Analytics blueprint: descriptive overview + AI demand forecast (read-only)."""
from flask import Blueprint, render_template

import ai
import services
from security import module_required

analytics_bp = Blueprint("analytics", __name__)


@analytics_bp.route("/")
@module_required("analytics")
def index():
    return render_template("analytics/index.html", kpis=ai.kpis(),
                           charts=ai.overview_charts())


@analytics_bp.route("/forecast")
@module_required("analytics")
def forecast():
    cards_raw = ai.forecast_all_products()
    services.save_ai_forecasts(cards_raw)      # persist AI_Forecasts snapshot
    return render_template(
        "analytics/forecast.html",
        periods=ai.PERIODS,
        model_backend=ai.model_backend(),
        cards=ai.forecast_cards_from(cards_raw),
        risks=ai.material_risk(),
        risk_badge={"high": "badge-danger", "medium": "badge-warn", "low": "badge-ok"},
    )
