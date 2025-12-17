from flask import Blueprint, jsonify, session, current_app
from ..config import Config

model_api_bp = Blueprint('model_api', __name__)

@model_api_bp.route('/models', methods=['GET'], strict_slashes=False)
def list_models():
    """
    Returns available AI models for different faculties.
    """
    user = session.get('user')
    if not user: return jsonify({"error": "Unauthorized"}), 401

    # In a real system, these might come from a DB or LLM Provider handshake.
    # For now, we define standard supported models.
    
    models = [
        # INTELLECT (High reasoning, context window)
        {"id": "gpt-4o", "category": "Intellect", "name": "GPT-4o", "provider": "OpenAI", "description": "High intelligence, multimodal standard."},
        {"id": "gpt-4-turbo", "category": "Intellect", "name": "GPT-4 Turbo", "provider": "OpenAI", "description": "Legacy high-intelligence model."},
        {"id": "llama-3.1-70b-versatile", "category": "Intellect", "name": "Llama 3.1 70B", "provider": "Groq", "description": "Fast, open-source high intelligence."},
        {"id": "llama-3.1-8b-instant", "category": "Intellect", "name": "Llama 3.1 8B", "provider": "Groq", "description": "Super fast, lower reasoning."},

        # SUPPORT (Conscience/Will - Efficiency focused)
        {"id": "gpt-4o-mini", "category": "Support", "name": "GPT-4o Mini", "provider": "OpenAI", "description": "Efficient, cost-effective reasoning."},
        {"id": "llama-3.1-8b-instant", "category": "Support", "name": "Llama 3.1 8B", "provider": "Groq", "description": "Extremely fast for rule checking."},
        {"id": "gemma-7b-it", "category": "Support", "name": "Gemma 7B", "provider": "Groq", "description": "Google's open efficient model."}
    ]

    return jsonify({"ok": True, "models": models})
