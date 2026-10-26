# Logging in with LDAP / Active Directory

A quick end-user guide for signing in to SAFi with your corporate directory (Active Directory / LDAP) credentials.

## Before you start

LDAP sign-in must be enabled for your organization by an admin (Admin → Settings → Identity & Access → **Enable LDAP sign-in**). If you don't see the LDAP card on the login page, contact your SAFi administrator.

You will need:

- Your AD username, e.g. `CORP\jnelson` or `jnelson@corp.example.com`
- Your AD password
- Your email address on file must match your directory email (SAFi matches accounts by email)
- The email is read from the attribute named by `SAFI_LDAP_EMAIL_ATTR` (default `mail`). If AD accounts have an empty `mail`, set `SAFI_LDAP_EMAIL_ATTR=userPrincipalName` and make the UPN (e.g. `chepa@safi.local`) match the SAFi account email

## How to log in

1. Open the SAFi login page.
2. Click the **Sign in with Active Directory** card (below the standard email/password form).
3. Enter your AD identifier in `DOMAIN\username` or `user@domain` format and your AD password.
4. Click **Sign in**.

If your credentials check out, one of three things happens:

### Case 1: No MFA required
You're signed in straight away. Done.

### Case 2: MFA required and you're already enrolled
SAFi asks for a 6-digit code from your authenticator app. Enter the current code to finish signing in.

### Case 3: MFA required and you're not enrolled yet
Your first login starts a **restricted enrollment session** (valid 5 minutes). During that window:

1. Go to your profile / TOTP setup screen.
2. Scan the QR code with any authenticator app (Google Authenticator, Microsoft Authenticator, 1Password, etc.).
3. Enter the 6-digit code to confirm enrollment.
4. Verify once more to establish your full session.

You'll only do this once — after enrollment, future logins follow Case 2.

## First login without a pre-existing account

SAFi is invite-only by default:

- **If you were invited** (or your organization has auto-provisioning enabled), your account is created automatically on your first successful LDAP login, with the role you were invited as.
- **If you have no invitation and auto-provisioning is off**, login is rejected even with correct AD credentials. Ask an admin for an invitation.

## Roles and groups

Your SAFi role is read from your AD group memberships **at every login** — it is not cached. If an admin changes your groups in AD, your SAFi role updates the next time you sign in. Users not matching any group mapping get the default `member` role.

## Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| "No LDAP card on the login page" | LDAP sign-in disabled for your org — ask your admin. |
| "Invalid credentials" | Wrong username format or expired AD password — reset it via your usual IT channel. |
| Login rejected with correct credentials (403) | No SAFi account/invitation for your email — request an invite. |
| "Directory unavailable" (503) | Your domain controller is unreachable — SAFi will retry once it's back; contact IT. |
| MFA code rejected | Codes are time-based — make sure your phone clock is correct, then try the next code. |

## Notes

- SAFi never stores your AD password; each login performs a fresh bind against your directory.
- If the directory is temporarily down during login, your existing role is preserved rather than blocking sign-in where possible.

---

# Administrator appendix: TLS, signing requirements, and certificates

This section is for the SAFi administrator and whoever manages the domain controller (DC).

## SAFi LDAP settings

Configured via environment variables in `.env` (see `safi_app/config.py`):

| Variable | Purpose |
|---|---|
| `SAFI_LDAP_URL` | `ldap://dc.example.com` (plain, port 389), `ldap://...` + StartTLS, or `ldaps://dc.example.com` (TLS, port 636) |
| `SAFI_LDAP_BASE_DN` | Search base, e.g. `DC=safi,DC=local` |
| `SAFI_LDAP_BIND_DN` / `SAFI_LDAP_BIND_PASSWORD` | Read-only service account used to search for users |
| `SAFI_LDAP_STARTTLS` | `true` to issue StartTLS on port 389 (ignored for `ldaps://`) |
| `SAFI_LDAP_TLS_VERIFY` | `true` (default) to verify the DC certificate; `false` for lab use only |
| `SAFI_LDAP_TLS_CA_FILE` | Path (inside the app container) to your internal CA bundle, e.g. `/app/certs/safi-ca.pem` |

Restart the app container after changing these.

## Why "Invalid username or password" can be a DC policy issue

Many domains set the GPO **Computer Configuration → Windows Settings → Security Settings → Local Policies → Security Options → *Domain controller: LDAP server signing requirements* = Required**. In that mode the DC refuses every unsigned simple bind (LDAP error `strongerAuthRequired`), and SAFi cannot work around it client-side. The two fixes:

1. **Install a certificate on the DC and use StartTLS/LDAPS** (recommended — keeps signing required).
2. Set the GPO to **None** (lab environments only — sends credentials without channel protection is acceptable risk in a lab, never in production).

## Installing a certificate on the domain controller

The DC needs a server-authentication certificate whose Subject or SAN matches the name in `SAFI_LDAP_URL`, issued by a CA the SAFi container trusts. It must land in the **local machine's Personal (My) store**, and the NTDS service must be restarted to pick it up.

### Option A: Active Directory Certificate Services (AD CS) autoenrollment — recommended

If the domain has an AD CS enterprise CA:

1. On the DC, open `certlm.msc` (Local Computer certificate store).
2. Check **Personal → Certificates** for a certificate with:
   - Intended purpose **Server Authentication**
   - Subject/SAN containing the DC's FQDN (e.g. `dc01.safi.local`)
   - A private key present
3. If it's missing, ensure the **Domain Controller** / **Domain Controller Authentication** certificate template allows autoenrollment for the DC's computer account, then run:
   `certutil -pulse` (triggers autoenrollment immediately) or `gpupdate /force` and wait a minute.
4. Restart the LDAP service so it binds the new cert:
   `net stop ntds && net start ntds` (brief AD outage — do this in a maintenance window), or reboot the DC.
5. Verify LDAPS is live: `openssl s_client -connect dc01.safi.local:636` — you should get a certificate chain, not "connection reset."

### Option B: Manual import (no AD CS)

If there's no enterprise CA, issue a certificate from any CA you control (e.g. a small internal OpenSSL CA):

1. Generate a key + CSR for the DC's FQDN on any machine:
   `openssl req -new -newkey rsa:2048 -nodes -keyout dc01.key -out dc01.csr -subj "/CN=dc01.safi.local"`
2. Sign the CSR with your CA, including a SAN of `DNS:dc01.safi.local` (modern clients require the SAN; the CN alone is not enough).
3. Export the signed cert **with its private key** as a PFX:
   `openssl pkcs12 -export -in dc01.crt -inkey dc01.key -out dc01.pfx`
4. On the DC: `certlm.msc` → **Personal → Certificates → All Tasks → Import** → select `dc01.pfx` (mark the key exportable is not required).
5. Also import your CA certificate into **Trusted Root Certification Authorities** (machine store) on the DC.
6. Restart NTDS as in Option A step 4, and verify with `openssl s_client`.

### Point SAFi at LDAPS

1. Copy your internal CA bundle into the app (e.g. mount `./certs:/app/certs` in `docker-compose.override.yml`).
2. In `.env` set:
   - `SAFI_LDAP_URL=ldaps://dc01.safi.local`
   - `SAFI_LDAP_TLS_CA_FILE=/app/certs/safi-ca.pem`
   - `SAFI_LDAP_TLS_VERIFY=true`
3. Restart the app container and test a login.

Lab shortcut: `SAFI_LDAP_TLS_VERIFY=false` skips chain validation — never use in production.

## SAFi-side error reporting

With `SAFI_LDAP_URL=ldap://...` and no signing support, SAFi now reports the true cause instead of a generic "Invalid username or password" (`safi_app/core/ldap_client.py`, `_parse_bind_error`):

| Reported error | Meaning |
|---|---|
| `invalid_credentials` | The bind DN or password was actually wrong |
| `ldap_signing_required` | DC GPO requires signing; bind refused — fix per the sections above |
| `ldap_tls_failed` | StartTLS/LDAPS negotiation failed (usually a missing/untrusted DC certificate) |
| 503 directory unavailable | DC unreachable or timed out |
