"""LDAP / Active Directory bind client (enterprise identity LDAP Phase 1).

A thin, deliberately small wrapper around ldap3: bind with a service
account, search for the user by sAMAccountName (or a configured filter),
then a direct bind as that user to verify the AD password. The password is
never stored, logged, or hashed locally — AD is the sole authority.

AD returns rich failure detail inside LDAP error 49 (invalid credentials)
as a "data 775" style subcode; mapping those subcodes lets /login/ldap
surface actionable messages (expired / locked / must-change) instead of a
generic failure.

Imports ldap3 lazily so a deployment without the dependency (and without
SAFI_LDAP_URL set) is completely unaffected.
"""
import re

from ..config import Config

# AD error-49 data subcodes (RFC/MS-ADTS): the reason a bind was refused.
_AD_SUBCODES = {
    "525": ("user_not_found", "Account not found in the directory."),
    "52e": ("invalid_credentials", "Invalid username or password."),
    "530": ("not_permitted_at_time", "Logon not permitted at this time."),
    "531": ("not_permitted_workstation", "Logon not permitted from this computer."),
    "532": ("password_expired", "Your AD password has expired. Change it in Active Directory, then sign in again."),
    "533": ("account_disabled", "Your account is disabled in Active Directory."),
    "701": ("account_expired", "Your AD account has expired."),
    "773": ("password_must_change", "You must change your AD password before signing in."),
    "775": ("account_locked", "Your AD account is locked out. Contact your administrator."),
    "776": ("account_locked", "Your AD account is locked out. Contact your administrator."),
}

_SUBCODE_RE = re.compile(r"data\s+([0-9a-fA-F]{3})", re.IGNORECASE)


def _parse_bind_error(exc) -> dict:
    """Turn an ldap3 bind exception into {ok: False, code, message}."""
    text = str(exc)
    m = _SUBCODE_RE.search(text)
    if m:
        code, message = _AD_SUBCODES.get(m.group(1), ("invalid_credentials", "Invalid username or password."))
        return {"ok": False, "code": code, "message": message}
    if "timeout" in text.lower():
        return {"ok": False, "code": "directory_timeout", "message": "The directory did not respond. Try again."}
    if "unavailable" in text.lower() or "connect" in text.lower():
        return {"ok": False, "code": "directory_unreachable", "message": "The directory is unreachable."}
    return {"ok": False, "code": "invalid_credentials", "message": "Invalid username or password."}


def split_domain_identifier(identifier: str):
    """Accept 'DOMAIN\\user', 'user@domain.example', or bare 'user' and
    return (username, domain_hint). The domain hint is advisory only — the
    authoritative directory is the one SAFi is configured against."""
    identifier = (identifier or "").strip()
    if "\\" in identifier:
        dom, _, user = identifier.rpartition("\\")
        return user.strip(), dom.strip().lower() or None
    if "@" in identifier and identifier.count("@") == 1:
        user, _, dom = identifier.partition("@")
        # user@domain: keep the full UPN suffix as hint, username is local part
        return user.strip(), dom.strip().lower() or None
    return identifier, None


def authenticate(username: str, password: str) -> dict:
    """Verify an AD password by direct bind.

    Returns {"ok": True, "dn", "email", "name"} on success, or
    {"ok": False, "code", "message"} on failure. Never raises for
    authentication outcomes; unreachable directories come back as
    code='directory_unreachable' so the route can return 503-ish signals
    without a traceback.
    """
    if not Config.ldap_configured():
        return {"ok": False, "code": "ldap_not_configured", "message": "LDAP sign-in is not configured."}
    if not username or not password:
        return {"ok": False, "code": "invalid_credentials", "message": "Invalid username or password."}

    try:
        import ldap3
    except ImportError:
        return {"ok": False, "code": "ldap_not_configured", "message": "LDAP support is not installed on this deployment."}

    from ldap3 import Server, Connection, Tls, SUBTREE
    import ssl as _ssl

    use_ssl = Config.LDAP_URL.lower().startswith("ldaps://")
    tls = Tls(validate=_ssl.CERT_REQUIRED, version=_ssl.PROTOCOL_TLS_CLIENT) if use_ssl else None
    server = Server(Config.LDAP_URL, port=Config.LDAP_PORT, use_ssl=use_ssl, tls=tls,
                    connect_timeout=Config.LDAP_TIMEOUT, get_info=None)

    user_dn = None
    email = name = None
    try:
        # 1) Service-account search to resolve the account's DN + attributes.
        if Config.LDAP_BIND_DN:
            with Connection(server, user=Config.LDAP_BIND_DN,
                            password=Config.LDAP_BIND_PASSWORD,
                            auto_bind=True, receive_timeout=Config.LDAP_TIMEOUT) as svc:
                filt = Config.LDAP_USER_FILTER.format(username=_escape_filter(username))
                svc.search(Config.LDAP_BASE_DN, filt, SUBTREE,
                           attributes=[Config.LDAP_EMAIL_ATTR, Config.LDAP_NAME_ATTR])
                if not svc.entries:
                    return {"ok": False, "code": "user_not_found",
                            "message": "Account not found in the directory."}
                entry = svc.entries[0]
                user_dn = entry.entry_dn
                email = (str(entry[Config.LDAP_EMAIL_ATTR]) if Config.LDAP_EMAIL_ATTR in entry else "") or None
                name = (str(entry[Config.LDAP_NAME_ATTR]) if Config.LDAP_NAME_ATTR in entry else "") or None
        else:
            # Anonymous resolution is not possible on AD; require the DN
            # filter to produce a full DN ({username} placeholder position).
            user_dn = Config.LDAP_USER_FILTER.format(username=_escape_dn(username))
            if "=" not in user_dn:
                return {"ok": False, "code": "ldap_not_configured",
                        "message": "SAFI_LDAP_BIND_DN is required to resolve accounts."}

        # 2) Direct bind as the located DN — the actual password check.
        conn = Connection(server, user=user_dn, password=password,
                          auto_bind=True, receive_timeout=Config.LDAP_TIMEOUT)
        conn.unbind()
    except Exception as exc:  # noqa: BLE001 — every failure maps to a code
        return _parse_bind_error(exc)

    return {"ok": True, "dn": user_dn, "email": (email or "").strip().lower() or None,
            "name": (name or "").strip() or None}


def _escape_filter(value: str) -> str:
    """RFC 4515 filter escaping — the username goes into the search filter."""
    return re.sub(r"([\\\*\(\)\x00-\x1f])", lambda m: "\\" + format(ord(m.group(1)), "02x"), value)


def _escape_dn(value: str) -> str:
    """RFC 4514 DN escaping for the no-service-account DN template path."""
    specials = '\\,+"\'<>;=#'
    return "".join("\\" + ch if ch in specials or ord(ch) < 32 else ch for ch in value)
