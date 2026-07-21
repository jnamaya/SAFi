"""
Application factory for the Flask backend.

This file contains the `create_app` function which initializes and configures
the Flask application, including middleware, extensions (CORS, OAuth),
database connections, and API blueprints.
"""
import logging
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
    Config.validate()

    # Enterprise identity Phase 1: the cookie holds only a server-side session
    # id. Permanent so the sid survives browser restarts (absolute/idle expiry
    # is enforced server-side); REFRESH_EACH_REQUEST must stay False or the
    # in-memory session shim would be serialized on every response (see
    # core/identity.py).
    from datetime import timedelta
    app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)
    app.config['SESSION_REFRESH_EACH_REQUEST'] = False
    app.config.setdefault('SESSION_COOKIE_HTTPONLY', True)
    app.config.setdefault('SESSION_COOKIE_SAMESITE', 'Lax')

    from .persistence import crypto
    if not crypto.is_enabled():
        logging.getLogger(__name__).warning(
            "SAFI_ENCRYPTION_KEY not set — application-level encryption DISABLED; "
            "sensitive columns will be written in plaintext"
        )

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
        # PKCE (S256) on top of the confidential-client secret — OIDC + PKCE
        # is the standard DDQs cite (DESIGN_ENTERPRISE_IDENTITY.md §2.5).
        client_kwargs={'scope': 'openid email profile', 'code_challenge_method': 'S256'},
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
            client_kwargs={'scope': 'openid email profile User.Read',
                           'code_challenge_method': 'S256'}
        )
    else:
        app.logger.warning("Microsoft OAuth credentials not found. Microsoft login will be disabled.")

    # Import and register API blueprints
    from .api.auth import auth_bp
    from .api.conversations import conversations_bp
    from .api.profile_api_routes import profile_bp
    from .api.profile_api_routes import profile_bp
    from .api.agent_api_routes import agent_api_bp
    from .api.policy_api_routes import policy_api_bp
    from .api.organizations import organizations_bp
    from .api.model_api_routes import model_api_bp
    from .api.documents import documents_bp
    from .api.incidents_api import incidents_bp
    from .api.records_api import records_bp
    from .api.evaluate_api import evaluate_bp
    from .api.review_api import review_bp

    app.register_blueprint(auth_bp, url_prefix='/api')
    app.register_blueprint(conversations_bp, url_prefix='/api')
    app.register_blueprint(profile_bp, url_prefix='/api')
    app.register_blueprint(agent_api_bp, url_prefix='/api')
    app.register_blueprint(policy_api_bp, url_prefix='/api')
    app.register_blueprint(organizations_bp, url_prefix='/api')
    app.register_blueprint(model_api_bp, url_prefix='/api')
    app.register_blueprint(documents_bp, url_prefix='/api')
    app.register_blueprint(incidents_bp, url_prefix='/api')
    app.register_blueprint(records_bp, url_prefix='/api')
    app.register_blueprint(evaluate_bp, url_prefix='/api')
    app.register_blueprint(review_bp, url_prefix='/api')

    # Server-side session resolution (enterprise identity Phase 1).
    from .core.identity import resolve_session, strip_session_shim
    app.before_request(resolve_session)
    app.after_request(strip_session_shim)

    @app.after_request
    def add_security_headers(response):
        # HSTS: enforce HTTPS for 1 year; only active when served over TLS
        response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
        # Prevent MIME-type sniffing
        response.headers['X-Content-Type-Options'] = 'nosniff'
        # Block this app from being embedded in iframes (clickjacking)
        response.headers['X-Frame-Options'] = 'DENY'
        # Limit referrer info sent to third-party sites
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        # Restrict access to sensitive browser APIs
        response.headers['Permissions-Policy'] = 'geolocation=(), microphone=(), camera=()'
        # CSP: unsafe-inline is required by the existing inline scripts/styles in index.html;
        # remove it once those are refactored to use nonces.
        response.headers['Content-Security-Policy'] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com; "
            "img-src 'self' data: https:; "
            "connect-src 'self' https:; "
            "frame-ancestors 'none'; "
            "base-uri 'self'; "
            "form-action 'self' https://accounts.google.com "
                "https://login.microsoftonline.com https://github.com; "
            "object-src 'none'"
        )
        return response

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