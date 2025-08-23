import os
from flask import Flask, send_from_directory
from flask_cors import CORS
from authlib.integrations.flask_client import OAuth
from werkzeug.middleware.proxy_fix import ProxyFix
from .config import Config

# Initialize extensions here, but don't configure them with the app yet
oauth = OAuth()
cors = CORS()

def create_app():
    """Application factory function."""
    # This line is already correctly pointing to your 'public' folder.
    app = Flask(__name__, static_folder='../public', static_url_path='/')
    app.config.from_object(Config)
    
    # Apply middleware - This is important for your production setup.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

    # Configure extensions with the app instance inside the factory
    oauth.init_app(app)
    cors.init_app(app, supports_credentials=True)

    # Register the Google OAuth client using your existing, correct configuration.
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

    # Import and register blueprints inside the factory to avoid circular imports.
    from .api.auth import auth_bp
    from .api.conversations import conversations_bp
    
    app.register_blueprint(auth_bp, url_prefix='/api')
    app.register_blueprint(conversations_bp, url_prefix='/api')

    # --- MODIFIED ROUTE TO SERVE THE FRONTEND ---
    # This replaces your original serve_index route with a "catch-all" that
    # is necessary for single-page applications.
    @app.route('/', defaults={'path': ''})
    @app.route('/<path:path>')
    def serve(path):
        # If the requested path is a file that exists in your 'public' folder (like js/main.js),
        # Flask's static file handling will serve it automatically.
        # If the path is not a file, it's a frontend route, so we serve index.html.
        if path != "" and os.path.exists(os.path.join(app.static_folder, path)):
            return send_from_directory(app.static_folder, path)
        else:
            return send_from_directory(app.static_folder, 'index.html')

    return app
