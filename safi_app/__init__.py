"""Application factory for the Flask backend.

create_app() wires the extensions, the boot-time schema and the API
blueprints. Two orderings in it are load-bearing, and both are noted inline:
the integrity check runs before MCP discovery (so the boot log reads kernel
first, deployment second), and the demo-usage backfill runs before the demo
purge that could otherwise delete the orphans it rebuilds history from.
"""
import logging
import os
from pathlib import Path
from flask import Flask, send_file, send_from_directory, jsonify
from werkzeug.middleware.proxy_fix import ProxyFix
from .config import Config
from .persistence import database as db
from .extensions import oauth, cors  # Import centralized extension instances
# Host-side composition: user-land plugin modules describe registrations as
# data; the host wires them into the generic core registry.
from .core.plugins import builtin as _builtin_plugins
from .core.plugins.registry import register_plugin as _register_plugin
for _plugin_names, _plugin_handler in _builtin_plugins.PLUGIN_REGISTRATIONS:
    _register_plugin(_plugin_names, _plugin_handler)

APPLIANCE_CERT_PATH = Path("/etc/ssl/runsafi/appliance.crt")


def _appliance_certificate_response():
    """Serve the public appliance certificate for client trust-store setup."""
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

    # Reject an oversized request body at the framework edge (413) before Flask
    # buffers the whole thing into memory. Without this the per-endpoint size
    # check in documents.py only runs AFTER the upload is fully read, so a large
    # body is a memory cost we take before we decline it. Sized off the upload
    # limit plus headroom for multipart overhead and non-upload JSON bodies.
    app.config['MAX_CONTENT_LENGTH'] = (max(Config.MAX_UPLOAD_SIZE_MB, Config.MAX_AUDIO_SIZE_MB) + 2) * 1024 * 1024

    # Measured boot (backlog 39): hash the Core Loop against the release
    # manifest once, log the fingerprint or the taint loudly, and stamp the
    # result into every governance record from here on. Default is
    # warn-and-run — AGPL permits running modified code; only the NAME is
    # conditional (§IV). SAFI_ENFORCE_INTEGRITY=strict refuses to start on
    # anything but verified-intact.
    from .core.integrity import enforce_at_boot
    enforce_at_boot(app.logger)

    # Operator-installed MCP tool servers (backlog 47b). Connect once per
    # process and register what they expose as connectors, so an organization
    # can allow them and a policy can grant them. After the integrity check on
    # purpose: what tools exist is a property of the deployment, and the log
    # reads in the right order (which kernel, then what was installed on it).
    #
    # Each gunicorn worker runs this, so a stdio server means one subprocess per
    # worker (4 in the container, 1 on the bare-metal unit). Servers that are
    # expensive to run should be HTTP.
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

    # ProxyFix so headers from a reverse proxy (Nginx, or a fronting load
    # balancer) are trusted for scheme and client IP.
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
        from .bootstrap import initialize as initialize_userland_defaults
        try:
            initialize_userland_defaults()
        except Exception as e:
            app.logger.error("Application data bootstrap failed: %s", e)
        try:
            from .persistence import incident_store
            incident_store.init_schema()
        except Exception as e:
            app.logger.error("Incident module schema initialization failed: %s", e)
        # Demo signup counter, and a ONE-TIME backfill from orphaned audit rows.
        # Ordering matters: this must run at boot, before the widened demo purge
        # in cleanup_old_demo_users() can remove the orphans it reconstructs
        # history from (GOVERNANCE_BACKLOG 82). Idempotent after the first run.
        try:
            from .persistence.demo_store import init_demo_usage_schema
            init_demo_usage_schema()
        except Exception as e:
            app.logger.error("demo usage counter init failed: %s", e)
        # The MCP reload counter (backlog 48b). Its own module, deliberately
        # outside the manifest-covered database.py: a scheduling signal is not a
        # record of what the system decided.
        try:
            from .persistence import mcp_store
            mcp_store.init_schema()
        except Exception as e:
            app.logger.error("MCP server table init failed, GUI install disabled: %s", e)
        # The stores below are all Section III org configuration, outside
        # database.py for the same reason: org sharing (55), conversation and
        # folder sharing (56), tool-grant workflow state (57b), SCIM directory
        # state (68). None of them is the governance ledger.
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

    microsoft_client_id = app.config.get('MICROSOFT_CLIENT_ID')
    microsoft_client_secret = app.config.get('MICROSOFT_CLIENT_SECRET')

    if microsoft_client_id and microsoft_client_secret:
        oauth.register(
            name='microsoft',
            client_id=microsoft_client_id,
            client_secret=microsoft_client_secret,
            # Manual endpoints instead of server_metadata_url: discovery would
            # bring strict 'iss' claim validation, which fails for multi-tenant
            # apps where the issuer URL changes per tenant.
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
    from .api.profile_api_routes import profile_bp
    from .api.profile_api_routes import profile_bp
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
    app.register_blueprint(profile_bp, url_prefix='/api')
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
    # SCIM lives at its own root, not under /api: identity providers expect a
    # clean /scim/v2 base URL. Auth is the per-org bearer token, not a session.
    app.register_blueprint(scim_bp, url_prefix='/scim/v2')

    # Pick up servers the operator added with scripts/safi_mcp.py. One indexed
    # read, and it only reconnects when the generation actually moved, so the
    # steady state cost is a single SELECT rather than any reconnection work.
    def _mcp_resync():
        from .core.services.mcp_manager import resync_if_stale
        from .persistence.mcp_store import current_generation
        resync_if_stale(current_generation)

    app.before_request(_mcp_resync)

    # Server-side session resolution (enterprise identity Phase 1).
    from .core.identity import resolve_session, strip_session_shim
    app.before_request(resolve_session)
    app.after_request(strip_session_shim)

    @app.after_request
    def add_security_headers(response):
        # HSTS: enforce HTTPS for 1 year; only active when served over TLS
        response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
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

    @app.get('/appliance.crt')
    def download_appliance_certificate():
        return _appliance_certificate_response()

    @app.route('/', defaults={'path': ''})
    @app.route('/<path:path>')
    def serve(path):
        # An unknown /api/... path must 404 as JSON, not fall through to the
        # SPA fallback below and hand the caller index.html.
        if path.startswith('api/'):
            return jsonify({"error": "Not Found", "message": f"API endpoint '{path}' not found."}), 404

        if path != "" and os.path.exists(os.path.join(app.static_folder, path)):
            return send_from_directory(app.static_folder, path)
        else:
            return send_from_directory(app.static_folder, 'index.html')

    return app
