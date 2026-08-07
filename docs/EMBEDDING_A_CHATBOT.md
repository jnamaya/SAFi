# Embedding a SAFi chatbot in an external site

There is **no WordPress-specific code in SAFi**. The integration is a standard
HTTP API over TLS, and the two mentions of "WordPress" in the codebase are
comments describing who happened to call an endpoint first:

```
safi_app/config.py:312       # Models used exclusively by the public WordPress chatbot endpoint.
safi_app/api/conversations.py:401   Process a user prompt from the public WordPress chatbot.
```

No table, column, migration, config flag or code branch is WordPress-aware. The
endpoint does not inspect `User-Agent`, `Referer` or `Origin`. The
`wp_safi_chat_…` strings visible in stored user ids come from the *caller's*
`conversation_id` — the server only ever prefixes it (`public_<conversation_id>`).
Anything that can make an HTTPS POST can drive this: WordPress, Drupal, a static
site with a serverless function, Zendesk, an internal intranet page.

---

## Serve it over TLS

Every example below uses `https://`. That is a requirement, not a convention.

**SAFi does not terminate TLS itself.** gunicorn listens on port 5000 and the
Compose file publishes `${APP_PORT}:5000` as plain TCP, so encryption is your
reverse proxy's job — nginx, Caddy, a load balancer, whatever fronts the host.
Nothing in SAFi will stop you exposing that port directly, and nothing will warn
you if you do.

Over cleartext, three things travel in the open:

- **the policy API key** (`/api/bot/process_prompt`) — a bearer credential:
  whoever holds it can spend your model budget under your policy, and the turns
  they generate land in your audit trail attributed to you
- **the `conversation_id`** — [a credential in its own right](#conversation_id-is-a-credential-treat-it-as-one),
  since it addresses a conversation's history
- **the visitor's prompt and the governed answer**, which is the content your
  retention and erasure obligations are written about

The app assumes TLS is in front of it and behaves accordingly:

- it sends `Strict-Transport-Security: max-age=31536000; includeSubDomains` on
  every response (`safi_app/__init__.py:142`) — which browsers ignore entirely
  when the response arrives over cleartext, so it protects nobody there
- its CSP restricts `connect-src` to `'self' https:`
- `SESSION_COOKIE_SECURE` is `True` **and** `WEB_BASE_URL.startswith("https")`
  (`safi_app/config.py:151`). Declaring an `http://` base URL silently drops the
  `Secure` flag from session cookies. That is deliberate — it is what lets a
  laptop install work at all — and it is also why an `http://` `WEB_BASE_URL`
  has no place in a deployment anyone else uses.

---

## Choose an endpoint

| | `/api/public/process_prompt` | `/api/bot/process_prompt` |
|---|---|---|
| Auth | none | Policy API Key header |
| Governing policy | the deployment default | **the policy the key belongs to** |
| Org attribution | `SAFI_PUBLIC_ORG_ID` | the key's policy `org_id` |
| Rate limit | per IP, `SAFI_DAILY_PROMPT_LIMIT` (default 20/day) | none built in |
| Identity | derived from `conversation_id` | caller supplies `user_id` |
| Use when | a public marketing-site widget | you need a specific policy governing it, or per-user identity |

**Pick `/api/bot/` if the bot is doing anything a compliance team cares about.**
It is the only way to choose which policy governs the turn, and it attributes to
that policy's organization automatically.

---

## `/api/public/process_prompt`

```http
POST /api/public/process_prompt
Content-Type: application/json

{ "conversation_id": "<opaque, stable per visitor session>",
  "message": "How does your pricing work?" }
```

Response (fields a widget actually needs):

| field | use |
|---|---|
| `finalOutput` | the text to render — already governed |
| `messageId` | correlate with the audit record |
| `spirit_score` | alignment 0–10, or `null` while the audit finishes |
| `willDecision` | `approve` / `redirected` / `violation` |
| `aiProvenance` | AI-generated marker (EU AI Act Art. 50(2)) — surface it |
| `suggestedPrompts` | optional follow-up chips |

Errors: `400` missing fields; `429` with `{"code": "LIMIT_REACHED"}` when the
per-IP daily cap is hit. Handle 429 explicitly — it is a normal condition on a
busy public page, not a fault.

### `conversation_id` has a hard 36-character limit

Every conversation-id column in the schema is `char(36)` — sized for a UUID —
across `conversations`, `chat_history`, `governance_records`,
`chat_audit_trail`, `review_queue` and `saved_content`. **Send more than 36
characters and you now get a `400` with `{"code": "CONVERSATION_ID_TOO_LONG"}`.**

Mind your prefix. A namespace tag plus a 32-hex-character random id does not fit:

```php
// 45 chars — REJECTED (13-char prefix + 32 hex)
$cid = 'wp_safi_chat_' . bin2hex( random_bytes( 16 ) );

// 35 chars — fits, and keeps all 128 bits
$cid = 'wp_' . bin2hex( random_bytes( 16 ) );

// 36 chars — also fine, and what the column was designed for
$cid = wp_generate_uuid4();
```

This was a real outage: a widget whose id grew to 45 characters had every send
fail on `INSERT INTO conversations` with MySQL `1406 Data too long for column
'id'`, returned as a bare HTTP 500 with an HTML body. In the browser that
appeared as `Unexpected token '<' ... is not valid JSON`, which points nowhere
near the cause. The endpoint validates the length up front now, before any
database work, so the error tells you what is wrong.

### `conversation_id` is a credential. Treat it as one.

The server derives the visitor's identity from it (`public_<conversation_id>`) and
resumes that conversation's memory. **Whoever knows a `conversation_id` can
continue that conversation and elicit its history.**

So it must be **high-entropy and unguessable**:

```php
// good — 32 hex chars from a CSPRNG, stored in the visitor's session
$cid = bin2hex( random_bytes( 16 ) );

// BAD — enumerable. An attacker walks the timestamp space and resumes
// other visitors' conversations.
$cid = 'wp_safi_chat_' . round( microtime( true ) * 1000 );
```

If your existing integration uses a timestamp, millisecond counter, incrementing
number or anything derived from the visitor's identity, **rotate it**. Existing
conversations remain reachable to anyone who guesses the old id.

---

## `/api/bot/process_prompt`

```http
POST /api/bot/process_prompt
X-API-KEY: sk-safi-…          (or: Authorization: Bearer sk-safi-…)
Content-Type: application/json

{ "user_id": "<stable per person>",
  "conversation_id": "<stable per thread>",
  "message": "…",
  "persona": "safi" }
```

`401` on an unknown key. Users are registered just-in-time with a synthetic
email — note that the domain is currently **hardcoded** to
`@bot.safinstitute.org` (`conversations.py:251`) regardless of who is deploying,
so a self-hoster's bot users get someone else's domain. Cosmetic, but it will
look wrong in a user export. `user_id` should be stable per person — a CRM id, an
SSO subject, or a random id you persist in the visitor's session. It is **not**
a credential in the way `conversation_id` is, but it does determine whose
conversation history is joined, so do not make it guessable either.

### Minting a key

Keys are stored as SHA-256 only, so **an existing key cannot be recovered** — if
you have lost it, mint a new one. As a user with the `editor` role or above:

```bash
curl -X POST https://<your-safi-host>/api/policies/<policy_id>/keys \
     -H 'Content-Type: application/json' \
     -b '<your session cookie>' \
     -d '{"label":"wordpress-site"}'
# => {"ok": true, "api_key": "sk-safi-…"}   <-- shown ONCE
```

Store it in your site's secret store, never in page source or client JS.

---

## Call it from the server, not the browser

CORS is restricted to `ALLOWED_ORIGINS`. A site on a different domain making a
`fetch()` from the page will be blocked — the preflight returns `200` with no
`Access-Control-Allow-Origin`, so the browser drops the response. Verify with:

```bash
curl -i -X OPTIONS https://<your-safi-host>/api/public/process_prompt \
  -H 'Origin: https://your-site.example' \
  -H 'Access-Control-Request-Method: POST' | grep -i access-control-allow
```

No header back means that origin is not allowed.

**Calling from the server is the better design regardless**, and it is what you
should do even if you control `ALLOWED_ORIGINS`:

- the API key never reaches the browser (mandatory for `/api/bot/`)
- the SAFi host is not exposed in page source
- you can add your own rate limiting, caching and abuse controls
- your own logs capture the exchange

Only add an origin to `ALLOWED_ORIGINS` if you have a genuine reason to call from
client JS, and never with a `/api/bot/` key.

---

## Minimal WordPress plugin

Server-side proxy: a REST route your JS calls, which forwards to SAFi. No key or
host in the browser.

```php
<?php
/**
 * Plugin Name: SAFi Chat Proxy
 * Description: Server-side proxy to a governed SAFi agent.
 */

add_action( 'rest_api_init', function () {
	register_rest_route( 'safi/v1', '/chat', array(
		'methods'             => 'POST',
		'callback'            => 'safi_chat_proxy',
		'permission_callback' => '__return_true', // public widget
	) );
} );

function safi_chat_proxy( WP_REST_Request $request ) {
	$message = trim( (string) $request->get_param( 'message' ) );
	if ( $message === '' || mb_strlen( $message ) > 4000 ) {
		return new WP_Error( 'bad_message', 'Message missing or too long.', array( 'status' => 400 ) );
	}

	// One unguessable conversation id per visitor, persisted in their session.
	// This is a credential: whoever holds it can resume the conversation.
	if ( ! session_id() ) {
		session_start();
	}
	if ( empty( $_SESSION['safi_cid'] ) ) {
		$_SESSION['safi_cid'] = bin2hex( random_bytes( 16 ) );
	}

	$response = wp_remote_post(
		SAFI_HOST . '/api/bot/process_prompt',
		array(
			'timeout' => 120, // governed turns run several model calls
			'headers' => array(
				'Content-Type' => 'application/json',
				'X-API-KEY'    => SAFI_API_KEY, // from wp-config.php, never in JS
			),
			'body'    => wp_json_encode( array(
				'user_id'         => 'wpvisitor_' . $_SESSION['safi_cid'],
				'conversation_id' => $_SESSION['safi_cid'],
				'message'         => $message,
			) ),
		)
	);

	if ( is_wp_error( $response ) ) {
		return new WP_Error( 'safi_unreachable', 'Assistant unavailable.', array( 'status' => 503 ) );
	}

	$code = wp_remote_retrieve_response_code( $response );
	$body = json_decode( wp_remote_retrieve_body( $response ), true );

	if ( 429 === $code ) {
		return new WP_Error( 'safi_rate_limited', 'Daily limit reached.', array( 'status' => 429 ) );
	}
	if ( 200 !== $code || empty( $body['finalOutput'] ) ) {
		return new WP_Error( 'safi_failed', 'Assistant could not answer.', array( 'status' => 502 ) );
	}

	// Return only what the widget renders. Do not leak governance internals
	// (ledger, reflection, provenance of the reasoning) to an anonymous page.
	return rest_ensure_response( array(
		'answer'       => $body['finalOutput'],
		'ai_generated' => true, // Art. 50(2): tell the visitor it is AI
		'message_id'   => $body['messageId'] ?? null,
	) );
}
```

In `wp-config.php`:

```php
define( 'SAFI_HOST', 'https://your-safi-host' );
define( 'SAFI_API_KEY', 'sk-safi-…' );
```

Notes on the above:

- **`timeout` 120s.** A governed turn is several model calls (Intellect, Will,
  Conscience, Spirit). WordPress defaults to 5s and would abandon every request.
- **Don't return the full SAFi payload to the page.** The response carries
  governance internals; an anonymous widget needs the answer and the AI marker.
- **Tell the visitor it's AI.** `aiProvenance` exists for EU AI Act Art. 50(2);
  a widget that hides it defeats the point.

---

## Don't boot your widget from `DOMContentLoaded` alone

If any part of your widget runs in the browser, initialise it like this:

```js
function boot() { /* wire up the widget */ }

if (document.readyState === "loading") {
	document.addEventListener("DOMContentLoaded", boot);
} else {
	boot();   // already parsed — an event listener would never fire
}
```

This is not defensive padding. Page-speed plugins routinely defer, combine or
lazy-load JavaScript, and they inject the script **after** `DOMContentLoaded` has
already fired. A listener registered for an event that has passed never runs, so
the widget renders its markup and then does nothing — **with no console error**,
which makes it painful to diagnose.

Seen in production with LiteSpeed Cache: with JS Defer on and the script not in
`js_defer_exc`, LiteSpeed combined it into
`wp-content/litespeed/js/<hash>.js`, rewrote the tag to
`type="litespeed/javascript"`, loaded it from its own loader on the first user
event, and then dispatched **`DOMContentLiteSpeedLoaded`** — its own event name,
not `DOMContentLoaded`. The widget was inert until the boot guard above replaced
the listener. Test `readyState` rather than listening for a specific optimiser's
event: it holds for inline, `defer`, `async` and late-injected scripts alike, and
survives the optimiser being reconfigured.

Two related traps from the same incident:

- **A version bump is what exposes this.** Changing your enqueued `?ver=`
  invalidates the optimiser's cached bundle and forces a fresh pass, so a latent
  incompatibility surfaces on an unrelated edit. Purge the page cache after
  changing plugin assets and check the widget, not just the page.
- **Never leave a backup file inside the webroot.** `plugin.php.bak` is not mapped
  to the PHP handler, so the server returns your **source** as plain text on
  request. Keep backups outside the document root.

---

## Confirm it is actually being audited

After the first live turn:

1. **Audit Hub → the owning org** — the turn should appear in the Log Explorer
   with its policy id and version.
2. If it does not, it is almost certainly unattributed. Check:
   ```bash
   python scripts/audit_unattributed.py
   ```
   Records with `org_id = NULL` are **invisible to every Audit Hub view and to
   both exports**, because `org_id = NULL` matches nothing in SQL. On
   `/api/public/` set `SAFI_PUBLIC_ORG_ID`; on `/api/bot/` make sure the key's
   policy has an `org_id`.
3. **Check the review queue.** An unattributed turn is also never sampled for
   supervisory review, so it sits outside your FINRA 3110/3120 and Art. 14
   denominator. For a public-facing bot that is usually the *last* thing you want
   excluded.

---

## Security checklist

- [ ] SAFi reachable over TLS only — the API key and `conversation_id` are
      credentials, and SAFi does not terminate TLS itself
- [ ] `WEB_BASE_URL` set to the `https://` address, so session cookies keep
      their `Secure` flag
- [ ] `conversation_id` from a CSPRNG, not a timestamp or counter
- [ ] API key server-side only; never in page source or client JS
- [ ] Calling from the server, not the browser (so CORS is irrelevant)
- [ ] Message length capped before forwarding
- [ ] `429` handled as a normal condition
- [ ] Your own rate limiting in front of the proxy — `/api/bot/` has none
- [ ] AI-generated disclosure shown to the visitor
- [ ] Turns landing under the intended org, verified in the Audit Hub
