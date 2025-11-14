import os
from flask import Flask, send_from_directory, jsonify
# REMOVED: from flask_cors import CORS
# REMOVED: from authlib.integrations.flask_client import OAuth
from werkzeug.middleware.proxy_fix import ProxyFix
from .config import Config
from .persistence import database as db
from .extensions import oauth, cors  # <-- IMPORT FROM NEW EXTENSIONS FILE

# REMOVED: oauth = OAuth()
# REMOVED: cors = CORS()

def create_app():
    """Application factory function."""
    app = Flask(__name__, static_folder='../public', static_url_path='/')
    app.config.from_object(Config)
    
    # Apply middleware
    app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

    
    # CRITICAL: Configure CORS to explicitly allow the Authorization header for JWT tokens
    cors.init_app(  # This now configures the imported 'cors' object
        app, 
        supports_credentials=True, 
        origins=Config.ALLOWED_ORIGINS,  # <-- Use dynamic list from Config
        allow_headers=["Content-Type", "Authorization"], 
        expose_headers=["Content-Type"],
        # FIX: Added 'PATCH' to the list of allowed HTTP methods for CORS
        methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"] 
    )

    # Configure the oauth object imported from extensions.py
    oauth.init_app(app)

    # Initialize the database within the app context
    with app.app_context():
        db.init_db()

    # Register the Google OAuth client on the imported object
    oauth.register(
        name='google',
        client_id=app.config['GOOGLE_CLIENT_ID'],
        client_secret=app.config['GOOGLE_CLIENT_SECRET'],
        access_token_url='https://accounts.google.com/o/oauth2/token',
        authorize_url='https://accounts.google.com/o/oauth2/auth',
        api_base_url='https://www.googleapis.com/oauth2/v1/',
        userinfo_endpoint='https://openidconnect.googleapis.com/v1/userinfo',
        client_kwargs={'scope': 'openid email profile'},
        jwks_uri="https://www.googleapis.com/oauth2/v3/certs"
    )

    # Import and register blueprints
    # This is no longer a circular import
    from .api.auth import auth_bp
    from .api.conversations import conversations_bp
    
    app.register_blueprint(auth_bp, url_prefix='/api')
    app.register_blueprint(conversations_bp, url_prefix='/api')

    # Catch-all route for the frontend
    @app.route('/', defaults={'path': ''})
    @app.route('/<path:path>')
    def serve(path):
        
        # Prevent catch-all route from serving HTML for API calls
        if path.startswith('api/'):
            return jsonify({"error": "Not Found", "message": f"API endpoint '{path}' not found."}), 404
            
        if path != "" and os.path.exists(os.path.join(app.static_folder, path)):
            # Serve the static file (e.g., main.js, styles.css)
            return send_from_directory(app.static_folder, path)
        else:
            # For all other paths, serve index.html
            return send_from_directory(app.static_folder, 'index.html')

    return app