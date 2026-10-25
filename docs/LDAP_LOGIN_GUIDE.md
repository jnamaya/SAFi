# Logging in with LDAP / Active Directory

A quick end-user guide for signing in to SAFi with your corporate directory (Active Directory / LDAP) credentials.

## Before you start

LDAP sign-in must be enabled for your organization by an admin (Admin → Settings → Identity & Access → **Enable LDAP sign-in**). If you don't see the LDAP card on the login page, contact your SAFi administrator.

You will need:

- Your AD username, e.g. `CORP\jnelson` or `jnelson@corp.example.com`
- Your AD password
- Your email address on file must match your directory email (SAFi matches accounts by email)

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
