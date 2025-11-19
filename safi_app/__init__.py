"""
Application factory for the Flask backend.

This file contains the `create_app` function which initializes and configures
the Flask application, including middleware, extensions (CORS, OAuth),
database connections, and API blueprints.
"""
import os
from flask import Flask, send_from_directory, jsonify
from werkzeug.middleware.proxy_fix import ProxyFix
from .config import Config
from .persistence import database as db
from .extensions import oauth, cors  # Import centralized extension instances

def create_app():
    """
    Application factory function. Creates and configures the Flask app.
    
    Returns:
        The configured Flask app instance.
    """
    # Initialize Flask app, pointing static files to the '../public' directory
    app = Flask(__name__, static_folder='../public', static_url_path='/')
    app.config.from_object(Config)
    
    # Apply ProxyFix middleware to correctly handle headers from a reverse proxy
    # (e.g., Nginx, Heroku) for things like HTTPS and client IP.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

    
    # Configure CORS (Cross-Origin Resource Sharing)
    cors.init_app(
        app, 
        supports_credentials=True, 
        origins=Config.ALLOWED_ORIGINS,  # Use dynamic origin list from config
        allow_headers=["Content-Type", "Authorization"], # Allow auth headers for JWTs
        expose_headers=["Content-Type"],
        methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"] # Ensure all methods are allowed
    )

    # Initialize extensions
    oauth.init_app(app)

    # Initialize the database connection pool within the app context
    with app.app_context():
        db.init_db()

    # Register the Google OAuth client with Authlib
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

    # Register the Microsoft OAuth client
    microsoft_client_id = app.config.get('MICROSOFT_CLIENT_ID')
    microsoft_client_secret = app.config.get('MICROSOFT_CLIENT_SECRET')

    if microsoft_client_id and microsoft_client_secret:
        oauth.register(
            name='microsoft',
            client_id=microsoft_client_id,
            client_secret=microsoft_client_secret,
            # FIX: Use manual endpoints instead of server_metadata_url.
            # This bypasses the strict 'iss' claim validation which fails for 
            # multi-tenant apps where the issuer URL changes per tenant.
            access_token_url='https://login.microsoftonline.com/common/oauth2/v2.0/token',
            authorize_url='https://login.microsoftonline.com/common/oauth2/v2.0/authorize',
            jwks_uri='https://login.microsoftonline.com/common/discovery/v2.0/keys',
            client_kwargs={'scope': 'openid email profile User.Read'}
        )
    else:
        app.logger.warning("Microsoft OAuth credentials not found. Microsoft login will be disabled.")

    # Import and register API blueprints
    from .api.auth import auth_bp
    from .api.conversations import conversations_bp
    from .api.profile_api_routes import profile_bp
    
    app.register_blueprint(auth_bp, url_prefix='/api')
    app.register_blueprint(conversations_bp, url_prefix='/api')
    app.register_blueprint(profile_bp, url_prefix='/api')

    # Catch-all route to serve the Single Page Application (SPA) frontend
    @app.route('/', defaults={'path': ''})
    @app.route('/<path:path>')
    def serve(path):
        """
        Serves static files for the frontend.
        - If the path is a file (e.g., main.js), it serves the file.
        - If the path is a route (e.g., /chat), it serves index.html.
        - It explicitly blocks API calls from being served as HTML.
        """
        # Prevent API routes from being handled by the static file server
        if path.startswith('api/'):
            return jsonify({"error": "Not Found", "message": f"API endpoint '{path}' not found."}), 404
            
        if path != "" and os.path.exists(os.path.join(app.static_folder, path)):
            # Serve the requested static file (e.g., main.js, styles.css)
            return send_from_directory(app.static_folder, path)
        else:
            # Serve the main index.html for all other routes to support
            # frontend routing (e.g., /login, /chat/123)
            return send_from_directory(app.static_folder, 'index.html')

    return app