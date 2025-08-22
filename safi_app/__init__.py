import os
from flask import Flask
from flask_cors import CORS
from authlib.integrations.flask_client import OAuth
from werkzeug.middleware.proxy_fix import ProxyFix
from .config import Config

# Initialize extensions here, but don't configure them with the app yet
oauth = OAuth()
cors = CORS()

def create_app():
    """Application factory function."""
    app = Flask(__name__, static_folder='../public', static_url_path='/')
    app.config.from_object(Config)
    
    # Apply middleware
    app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

    # Configure extensions with the app instance inside the factory
    oauth.init_app(app)
    cors.init_app(app, supports_credentials=True)

    # Register the Google OAuth client
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

    # Import and register blueprints inside the factory
    # This avoids circular imports because the blueprints are imported
    # after the 'oauth' object has been created and configured.
    from .api.auth import auth_bp
    from .api.conversations import conversations_bp
    
    app.register_blueprint(auth_bp, url_prefix='/api')
    app.register_blueprint(conversations_bp, url_prefix='/api')

    # Route to serve the frontend
    @app.route('/')
    def serve_index():
        return app.send_static_file('index.html')

    return app
