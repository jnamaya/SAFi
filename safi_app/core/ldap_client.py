import re

from ..config import Config

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
    text = str(exc)
    low = text.lower()
    if "strongerauthrequired" in low or "signing" in low:
        return {"ok": False, "code": "ldap_signing_required",
                "message": "The domain controller rejects unsigned LDAP binds. "
                           "Install a certificate on the DC and use LDAPS/StartTLS "
                           "(SAFI_LDAP_URL=ldaps://...), or relax the DC's "
                           "'LDAP server signing requirements' policy."}
    if "starttls" in low or "ssl wrapping" in low:
        return {"ok": False, "code": "ldap_tls_failed",
                "message": "The directory could not establish TLS. The domain "
                           "controller likely has no certificate installed "
                           "(required for LDAPS on 636 and StartTLS on 389)."}
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
    identifier = (identifier or "").strip()
    if "\\" in identifier:
        dom, _, user = identifier.rpartition("\\")
        return user.strip(), dom.strip().lower() or None
    if "@" in identifier and identifier.count("@") == 1:
        user, _, dom = identifier.partition("@")
        return user.strip(), dom.strip().lower() or None
    return identifier, None


def _make_server():
    from ldap3 import Server, Tls
    import ssl as _ssl

    use_ssl = Config.LDAP_URL.lower().startswith("ldaps://")
    if Config.LDAP_TLS_VERIFY:
        tls = Tls(validate=_ssl.CERT_REQUIRED, version=_ssl.PROTOCOL_TLS_CLIENT,
                  ca_certs_file=Config.LDAP_TLS_CA_FILE or None)
    else:
        tls = Tls(validate=_ssl.CERT_NONE, version=_ssl.PROTOCOL_TLS_CLIENT)
    return Server(Config.LDAP_URL, port=Config.LDAP_PORT, use_ssl=use_ssl, tls=tls,
                  connect_timeout=Config.LDAP_TIMEOUT, get_info=None)


def _needs_starttls() -> bool:
    return bool(Config.LDAP_STARTTLS) and not Config.LDAP_URL.lower().startswith("ldaps://")


def authenticate(username: str, password: str) -> dict:
    if not Config.ldap_configured():
        return {"ok": False, "code": "ldap_not_configured", "message": "LDAP sign-in is not configured."}
    if not username or not password:
        return {"ok": False, "code": "invalid_credentials", "message": "Invalid username or password."}

    try:
        import ldap3
    except ImportError:
        return {"ok": False, "code": "ldap_not_configured", "message": "LDAP support is not installed on this deployment."}

    from ldap3 import Connection, SUBTREE

    server = _make_server()

    user_dn = None
    email = name = None
    try:
        if Config.LDAP_BIND_DN:
            svc = Connection(server, user=Config.LDAP_BIND_DN,
                             password=Config.LDAP_BIND_PASSWORD,
                             receive_timeout=Config.LDAP_TIMEOUT)
            svc.open()
            if _needs_starttls() and not svc.start_tls():
                raise Exception(f"service TLS failed: {svc.last_error or svc.result}")
            if not svc.bind():
                raise Exception(f"service bind failed: {svc.last_error or svc.result}")
            try:
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
            finally:
                svc.unbind()
        else:
            user_dn = Config.LDAP_USER_FILTER.format(username=_escape_dn(username))
            if "=" not in user_dn:
                return {"ok": False, "code": "ldap_not_configured",
                        "message": "SAFI_LDAP_BIND_DN is required to resolve accounts."}

        conn = Connection(server, user=user_dn, password=password,
                          receive_timeout=Config.LDAP_TIMEOUT)
        if _needs_starttls():
            if not conn.open() or not conn.start_tls():
                raise Exception(f"user TLS failed: {conn.last_error or conn.result}")
        if not conn.bind():
            raise Exception(f"user bind failed: {conn.last_error or conn.result}")
        conn.unbind()
    except Exception as exc:
        return _parse_bind_error(exc)

    return {"ok": True, "dn": user_dn, "email": (email or "").strip().lower() or None,
            "name": (name or "").strip() or None}


def get_groups(user_dn: str):
    if not Config.ldap_configured() or not Config.LDAP_BIND_DN or not user_dn:
        return None
    try:
        import ldap3
        from ldap3 import Connection, SUBTREE

        server = _make_server()
        svc = Connection(server, user=Config.LDAP_BIND_DN,
                         password=Config.LDAP_BIND_PASSWORD,
                         receive_timeout=Config.LDAP_TIMEOUT)
        svc.open()
        if _needs_starttls() and not svc.start_tls():
            return None
        if not svc.bind():
            return None
        try:
            svc.search(user_dn, "(objectClass=*)", search_scope="BASE",
                       attributes=["memberOf"])
            if not svc.entries:
                return []
            entry = svc.entries[0]
            if "memberOf" not in entry:
                return []
            return [str(v) for v in entry["memberOf"].values]
        finally:
            try:
                svc.unbind()
            except Exception:
                pass
    except Exception:
        return None


def _escape_filter(value: str) -> str:
    return re.sub(r"([\\\*\(\)\x00-\x1f])", lambda m: "\\" + format(ord(m.group(1)), "02x"), value)


def dn_to_domain(dn: str):
    parts = []
    for comp in (dn or "").split(","):
        attr, _, val = comp.strip().partition("=")
        if attr.strip().lower() == "dc" and val.strip():
            parts.append(val.strip().lower())
    return ".".join(parts) if parts else None


def directory_owns_domain(domain: str):
    if not Config.ldap_configured() or not Config.LDAP_BIND_DN or not domain:
        return None
    domain = domain.strip().lower()
    try:
        import ldap3
        from ldap3 import Connection

        server = _make_server()
        conn = Connection(server, user=Config.LDAP_BIND_DN,
                          password=Config.LDAP_BIND_PASSWORD,
                          receive_timeout=Config.LDAP_TIMEOUT)
        conn.open()
        if _needs_starttls() and not conn.start_tls():
            return None
        if not conn.bind():
            return None
        try:
            conn.search("", "(objectClass=*)", search_scope="BASE",
                        attributes=["namingContexts", "rootDomainNamingContext"])
            if not conn.entries:
                return None
            entry = conn.entries[0]
            contexts = []
            for attr in ("namingContexts", "rootDomainNamingContext"):
                if attr in entry:
                    contexts.extend(dn_to_domain(str(v)) for v in entry[attr].values)
            contexts = sorted({c for c in contexts if c})
            owns = domain in contexts
            return {"ok": owns, "contexts": contexts}
        finally:
            try:
                conn.unbind()
            except Exception:
                pass
    except Exception:
        return None


def _escape_dn(value: str) -> str:
    specials = '\\,+"\'<>;=#'
    return "".join("\\" + ch if ch in specials or ord(ch) < 32 else ch for ch in value)
