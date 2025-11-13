from flask import Blueprint, request, jsonify, current_app, Response
from ..core.orchestrator import SAFi
import json
import asyncio # Although generate_speech_audio is sync, keep this if other parts are async

# Define a Blueprint for TTS functionality
tts_bp = Blueprint('tts', __name__)

@tts_bp.route('/tts_audio', methods=['POST'])
def tts_audio_endpoint():
    """
    Handles POST request to generate TTS audio and stream the MP3 back.
    """
    user_id = get_user_id()
    if not user_id:
        return jsonify({"error": "Authentication required."}), 401
    
    try:
        data = request.get_json()
        text_to_speak = data.get('text')
        
        if not text_to_speak:
            return jsonify({"error": "Missing 'text' in request body."}), 400
        
        # Get the SAFi instance configured for the user's active profile and models
        # NOTE: Since the full SAFi creation logic is complex, we need a way 
        # to get the correctly configured SAFi instance for the *current* user.
        # This requires helper functions from `conversations.py`. 
        # We will replicate necessary helpers or assume they are accessible.

        # --- Simplified SAFi Access (Requires imports/logic from conversations.py) ---
        user_details = current_app.db_helpers.get_user_details(user_id) # Hypothetical helper
        user_profile_name = user_details.get('active_profile') or current_app.config.DEFAULT_PROFILE
        prof = current_app.db_helpers.get_profile(user_profile_name) 
        
        intellect_model = user_details.get('intellect_model') or current_app.config.INTELLECT_MODEL
        will_model = user_details.get('will_model') or current_app.config.WILL_MODEL
        conscience_model = user_details.get('conscience_model') or current_app.config.CONSCIENCE_MODEL

        # Create a new SAFi instance specifically for this request (expensive but accurate)
        saf_system = SAFi(
            config=current_app.config,
            value_profile_or_list=prof,
            intellect_model=intellect_model,
            will_model=will_model,
            conscience_model=conscience_model
        )
        # --- End Simplified SAFi Access ---

        # Call the orchestrator's synchronous TTS method
        audio_content = saf_system.generate_speech_audio(text_to_speak)
        
        if audio_content is None:
            return jsonify({"error": "TTS generation failed on the backend."}), 500

        # Return the audio content as a stream with the correct headers
        response = Response(audio_content, mimetype='audio/mpeg')
        response.headers['Content-Disposition'] = 'attachment; filename=speech.mp3'
        return response

    except json.JSONDecodeError:
        return jsonify({"error": "Invalid JSON format."}), 400
    except Exception as e:
        current_app.logger.error(f"Error processing TTS request: {e}")
        return jsonify({"error": f"Internal Server Error: {str(e)}"}), 500