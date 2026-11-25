import logging
import os
import re
import secrets
from pathlib import Path
from flask import Flask, send_file, send_from_directory, jsonify, g, request, Response
from werkzeug.middleware.proxy_fix import ProxyFix
from .config import Config
from .persistence import database as db
from .extensions import oauth, cors
from .core.plugins import builtin as _builtin_plugins
from .core.plugins.registry import register_plugin as _register_plugin
for _plugin_names, _plugin_handler in _builtin_plugins.PLUGIN_REGISTRATIONS:
    _register_plugin(_plugin_names, _plugin_handler)

APPLIANCE_CERT_PATH = Path("/etc/ssl/runsafi/appliance.crt")


_INLINE_SCRIPT_RE = re.compile(r'<script>(?=<!\[CDATA|\s)')


def _serve_index_with_nonce(app):
    nonce = getattr(g, 'csp_nonce', None)
    html = Path(app.static_folder, 'index.html').read_text(encoding='utf-8')
    if nonce:
        html = _INLINE_SCRIPT_RE.sub(f'<script nonce="{nonce}">', html)
    response = Response(html, mimetype='text/html')
    response.headers['Cache-Control'] = 'no-store'
    return response


def _appliance_certificate_response():
    if not APPLIANCE_CERT_PATH.is_file():
        return jsonify({"error": "Appliance certificate is unavailable"}), 404
    response = send_file(
        APPLIANCE_CERT_PATH,
        mimetype="application/x-x509-ca-cert",
        as_attachment=True,
        download_name="safi-appliance.crt",
        max_age=0,
    )
    response.headers["Cache-Control"] = "no-store"
    return response


def create_app():
    app = Flask(__name__, static_folder='../public', static_url_path='/')
    app.config.from_object(Config)
    from .role_config import ROLE_CONFIG, ROLE_CONFIG_VERSION
    app.config["ROLE_CONFIG"] = ROLE_CONFIG
    app.config["ROLE_CONFIG_VERSION"] = ROLE_CONFIG_VERSION
    Config.validate()

    app.config['MAX_CONTENT_LENGTH'] = (max(Config.MAX_UPLOAD_SIZE_MB, Config.MAX_AUDIO_SIZE_MB) + 2) * 1024 * 1024

    from .core.integrity import enforce_at_boot
    enforce_at_boot(app.logger)

    from .core.services.mcp_manager import start_servers
    _mcp = start_servers(Config)
    if _mcp["servers"]:
        for _name, _entry in _mcp["servers"].items():
            if _entry["error"]:
                app.logger.error("MCP server '%s' unavailable: %s", _name, _entry["error"])
            else:
                app.logger.info(
                    "MCP server '%s' ready: %d tool(s).", _name, len(_entry["tools"])
                )
        app.logger.info("MCP: %d tool(s) discovered in total.", _mcp["tool_count"])

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

    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

    cors.init_app(
        app, 
        supports_credentials=True, 
        origins=Config.ALLOWED_ORIGINS,
        allow_headers=["Content-Type", "Authorization"],
        expose_headers=["Content-Type"],
        methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"]
    )

    oauth.init_app(app)

    with app.app_context():
        db.init_db()
        try:
            from .persistence import incident_store
            incident_store.init_schema()
        except Exception as e:
            app.logger.error("Incident module schema initialization failed: %s", e)
        try:
            from .persistence.demo_store import init_demo_usage_schema
            init_demo_usage_schema()
        except Exception as e:
            app.logger.error("demo usage counter init failed: %s", e)
        try:
            from .persistence import mcp_store
            mcp_store.init_schema()
        except Exception as e:
            app.logger.error("MCP server table init failed, GUI install disabled: %s", e)
        try:
            from .persistence import sharing_store
            sharing_store.init_schema()
        except Exception as e:
            app.logger.error("Sharing table init failed, agent sharing disabled: %s", e)
        try:
            from .persistence import conversation_sharing_store
            conversation_sharing_store.init_schema()
        except Exception as e:
            app.logger.error("Conversation sharing table init failed, disabled: %s", e)
        try:
            from .persistence import tool_approval_store
            tool_approval_store.init_schema()
        except Exception as e:
            app.logger.error("Tool-approval table init failed: %s", e)
        try:
            from .persistence import scim_store
            scim_store.init_schema()
        except Exception as e:
            app.logger.error("SCIM table init failed, directory sync disabled: %s", e)
        try:
            from .persistence import rate_limit_store
            rate_limit_store.init_schema()
        except Exception as e:
            app.logger.error("Rate-limit table init failed, using in-memory fallback: %s", e)

        from .bootstrap import initialize as initialize_userland_defaults
        try:
            initialize_userland_defaults()
        except Exception as e:
            app.logger.error("Application data bootstrap failed: %s", e)

    oauth.register(
        name='google',
        client_id=app.config['GOOGLE_CLIENT_ID'],
        client_secret=app.config['GOOGLE_CLIENT_SECRET'],
        access_token_url='https://accounts.google.com/o/oauth2/token',
        authorize_url='https://accounts.google.com/o/oauth2/auth',
        api_base_url='https://www.googleapis.com/oauth2/v1/',
        userinfo_endpoint='https://openidconnect.googleapis.com/v1/userinfo',
        client_kwargs={'scope': 'openid email profile', 'code_challenge_method': 'S256'},
        jwks_uri="https://www.googleapis.com/oauth2/v3/certs"
    )

    microsoft_client_id = app.config.get('MICROSOFT_CLIENT_ID')
    microsoft_client_secret = app.config.get('MICROSOFT_CLIENT_SECRET')

    if microsoft_client_id and microsoft_client_secret:
        oauth.register(
            name='microsoft',
            client_id=microsoft_client_id,
            client_secret=microsoft_client_secret,
            access_token_url='https://login.microsoftonline.com/common/oauth2/v2.0/token',
            authorize_url='https://login.microsoftonline.com/common/oauth2/v2.0/authorize',
            jwks_uri='https://login.microsoftonline.com/common/discovery/v2.0/keys',
            client_kwargs={'scope': 'openid email profile User.Read',
                           'code_challenge_method': 'S256'}
        )
    else:
        app.logger.warning("Microsoft OAuth credentials not found. Microsoft login will be disabled.")

    from .api.auth import auth_bp
    from .api.conversations import conversations_bp
    from .api.agent_api_routes import agent_api_bp
    from .api.policy_api_routes import policy_api_bp
    from .api.organizations import organizations_bp
    from .api.model_api_routes import model_api_bp
    from .api.documents import documents_bp
    from .api.knowledge_api import knowledge_bp
    from .api.incidents_api import incidents_bp
    from .api.records_api import records_bp
    from .api.evaluate_api import evaluate_bp
    from .api.review_api import review_bp
    from .api.audit_api import audit_bp
    from .api.mcp_api import mcp_bp
    from .api.groups_api import groups_bp
    from .api.attention_api import attention_bp
    from .api.scim import scim_bp
    from .api.audio_api import audio_bp

    app.register_blueprint(auth_bp, url_prefix='/api')
    app.register_blueprint(conversations_bp, url_prefix='/api')
    app.register_blueprint(agent_api_bp, url_prefix='/api')
    app.register_blueprint(policy_api_bp, url_prefix='/api')
    app.register_blueprint(organizations_bp, url_prefix='/api')
    app.register_blueprint(model_api_bp, url_prefix='/api')
    app.register_blueprint(documents_bp, url_prefix='/api')
    app.register_blueprint(knowledge_bp, url_prefix='/api')
    app.register_blueprint(incidents_bp, url_prefix='/api')
    app.register_blueprint(records_bp, url_prefix='/api')
    app.register_blueprint(evaluate_bp, url_prefix='/api')
    app.register_blueprint(review_bp, url_prefix='/api')
    app.register_blueprint(audit_bp, url_prefix='/api')
    app.register_blueprint(groups_bp, url_prefix='/api')
    app.register_blueprint(attention_bp, url_prefix='/api')
    app.register_blueprint(audio_bp, url_prefix='/api')
    app.register_blueprint(mcp_bp)
    app.register_blueprint(scim_bp, url_prefix='/scim/v2')

    def _mcp_resync():
        from .core.services.mcp_manager import resync_if_stale
        from .persistence.mcp_store import current_generation
        resync_if_stale(current_generation)

    app.before_request(_mcp_resync)

    from .core.identity import resolve_session, strip_session_shim
    app.before_request(resolve_session)
    app.after_request(strip_session_shim)

    @app.before_request
    def enforce_csrf_origin():
        from urllib.parse import urlparse
        if request.method not in ('POST', 'PUT', 'PATCH', 'DELETE'):
            return None
        if request.path.startswith('/api/public/'):
            return None
        if request.headers.get('Authorization'):
            return None
        cookie_name = app.config.get('SESSION_COOKIE_NAME', 'safi_session')
        if not request.cookies.get(cookie_name):
            return None

        allowed = {o.rstrip('/').lower() for o in (Config.ALLOWED_ORIGINS or []) if o}
        if request.host:
            allowed.add(f"https://{request.host}".lower())
            allowed.add(f"http://{request.host}".lower())
        if Config.WEB_BASE_URL:
            allowed.add(Config.WEB_BASE_URL.rstrip('/').lower())

        origin = (request.headers.get('Origin') or '').strip()
        if origin:
            if origin.rstrip('/').lower() not in allowed:
                return jsonify({"error": "Cross-site request blocked."}), 403
            return None

        referer = (request.headers.get('Referer') or '').strip()
        if referer:
            parsed = urlparse(referer)
            ref_origin = f"{parsed.scheme}://{parsed.netloc}".lower() if parsed.scheme and parsed.netloc else ""
            if not ref_origin or ref_origin not in allowed:
                return jsonify({"error": "Cross-site request blocked."}), 403
            return None

        sec_fetch_site = (request.headers.get('Sec-Fetch-Site') or '').strip().lower()
        if sec_fetch_site == 'cross-site':
            return jsonify({"error": "Cross-site request blocked."}), 403
        return None

    @app.before_request
    def assign_csp_nonce():
        g.csp_nonce = secrets.token_urlsafe(16)

    @app.after_request
    def add_security_headers(response):
        response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        response.headers['Permissions-Policy'] = 'geolocation=(), microphone=(), camera=()'
        nonce = getattr(g, 'csp_nonce', None)
        script_src = f"'self' 'nonce-{nonce}'" if nonce else "'self'"
        style_src = "'self' 'unsafe-inline' https://fonts.googleapis.com"
        response.headers['Content-Security-Policy'] = (
            "default-src 'self'; "
            f"script-src {script_src}; "
            f"style-src {style_src}; "
            "font-src 'self' https://fonts.gstatic.com; "
            "img-src 'self' data: https:; "
            "connect-src 'self' https:; "
            "media-src 'self' blob:; "
            "frame-ancestors 'none'; "
            "base-uri 'self'; "
            "form-action 'self' https://accounts.google.com "
                "https://login.microsoftonline.com https://github.com; "
            "object-src 'none'"
        )
        return response

    @app.get('/appliance.crt')
    def download_appliance_certificate():
        return _appliance_certificate_response()

    @app.route('/', defaults={'path': ''})
    @app.route('/<path:path>')
    def serve(path):
        if path.startswith('api/'):
            return jsonify({"error": "Not Found", "message": f"API endpoint '{path}' not found."}), 404

        if path != "" and os.path.exists(os.path.join(app.static_folder, path)):
            return send_from_directory(app.static_folder, path)
        else:
            return _serve_index_with_nonce(app)

    return app
