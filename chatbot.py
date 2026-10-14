"""AI Chatbot Assistant blueprint.

The assistant is a floating widget available on every authenticated page (see
templates/base.html); this blueprint just answers its questions over live data.
"""
from flask import Blueprint, jsonify, request

import ai
from security import module_required

chatbot_bp = Blueprint("chatbot", __name__)


@chatbot_bp.route("/ask", methods=["POST"])
@module_required("chatbot")
def ask():
    if request.is_json:
        question = (request.get_json(silent=True) or {}).get("question", "")
    else:
        question = request.form.get("question", "")
    return jsonify({"answer": ai.chatbot_answer(question)})
