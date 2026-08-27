# MCP tools: installing and configuring them

SAFi agents can call tools. Some ship with the product; others come from MCP
servers you install. This document covers installing a server, granting it, and
the rules that decide which of the two kinds of tool a given job needs.

Audience: whoever controls the deployment installs servers (sections 2 and 8);
policy editors decide which of their tools may be used (section 4).

---

## 1. How a tool reaches an agent

One pipeline, five steps, and each one is a different person's decision:

1. **Install** (operator, on the host). `scripts/safi_mcp.py add ...` writes the
   server into the file `MCP_SERVERS_JSON` names. Section 9.
2. **Discover** (SAFi). It connects to the server and asks what tools it has.
3. **Catalogue** (Settings → Tools Catalog). The server and its tools appear,
   **visible and completely inactive**. Nothing can call them.
4. **Policy** (editor). In a policy's Tools & Guardrails step, enable the
   specific tools agents under that policy may use, and leave the rest off.
5. **Assign** (agent). An agent gets the tools its policy allows, and the Will
   checks every call against that list by exact name before it runs.

**Installation happens on the host, in step 1, and nowhere else.** There is no
API route and no admin screen for it. It belongs where the person doing it
already holds the rights that running someone else's code implies. Settings,
Tools Catalog is where an installed server is seen, signed in to and granted,
which is steps 3 and 4.

## 2. Installing a server

`MCP_SERVERS_JSON` points at a JSON file, by default
`safi_app/core/mcp_servers/mcp_servers.json`, which ships empty. Each key is a
server; each server becomes one connector.

### stdio (a local process)

```json
{
  "acme_billing": {
    "label": "Acme Billing API",
    "transport": "stdio",
    "command": "npx",
    "args": ["-y", "@acme/billing-mcp"],
    "env": { "ACME_TOKEN": "${ACME_TOKEN}" }
  }
}
```

### http (a remote server)

```json
{
  "internal_pricing": {
    "label": "Pricing Service",
    "transport": "http",
    "url": "https://pricing.internal.example.com/mcp"
  }
}
```

### Fields

| Field | Applies to | Meaning |
|---|---|---|
| `label` | all | What people see in the picker. Defaults to the key. |
| `transport` | all | `stdio` (default), `http`, or `sse`. |
| `command`, `args`, `cwd` | stdio | The process to run. |
| `env` | stdio | Environment for the child process. Nothing is inherited implicitly. |
| `url` | http, sse | The server endpoint. |
| `enabled` | all | Set `false` to keep a definition without connecting it. |
| `connect_timeout` | all | Seconds to wait at boot. Default 20. |
| `orgs` | all | Organization ids allowed to use this server. Absent means all of them. |

`${VAR}` anywhere in `env`, `args` or `url` is replaced from the SAFi process
environment. Put secrets in your `.env` and reference them here, so the server
file stays safe to copy and commit.

### On a shared deployment, restrict the server

An installed server holds ONE credential and every organization on the
deployment can otherwise reach it. If more than one organization uses this
install, name the ones allowed:

```json
{ "acme_billing": { "...": "...", "orgs": ["6f1c…", "9a20…"] } }
```

Absent means every organization, which is right for a single-tenant install and
wrong to assume on a shared one.

**Demo and guest accounts never get installed servers, whatever this says.** The
public demo login makes a guest an admin of a throwaway organization, and being
an admin of a sandbox is not a basis for using the operator's Google account.
The catalogue hides them, the save path refuses them, and a call is refused at
dispatch.

### Naming

The server key becomes a connector name. It may not collide with a built-in
connector (`web_search`, `find_places`, and the finance tools). A colliding
server is refused at boot and logged, and its tools are unavailable until you
rename it.

The same rule applies one level down: a discovered tool whose name matches a
built-in tool is skipped. Built-ins always win, so no server you install can
quietly repoint a tool an existing agent already uses.

---

## 3. Checking that it worked

Restart, then read the boot log:

```
MCP server 'acme_billing' ready: 4 tool(s).
MCP: 4 tool(s) discovered in total.
```

A server that fails says so and the app keeps running:

```
MCP server 'acme_billing' unavailable: [Errno 2] No such file or directory
```

**A server that fails to connect leaves its tools absent, never present and
ungoverned.** Nothing is added to the catalogue, nothing is expanded into any
agent's authorized list, and if a model names one of those tools anyway the Will
blocks the call. There is no state in which a tool runs without having been
granted.

---

## 4. Granting it

Discovery only populates the catalogue. **Discovery never grants anything.** A
newly installed server, or a new tool inside an already-installed one, is
unauthorized until a person says otherwise.

**Tool by tool, not server by server.** Each tool from an installed server is
offered as its own entry in a policy's Tools & Guardrails step, so an editor
enables `billing_get_invoice` and leaves `billing_issue_refund` off. Built-in
connectors are still offered as a bundle, because their contents were reviewed
when they shipped; an installed server's were not.

Three rungs, all of which predate MCP support:

1. **Policy.** The editor enables specific tools under Tools & Guardrails. This
   is a ceiling: agents under the policy can never use a tool it does not list.
2. **Agent.** The builder assigns the tools the policy allows. This is what gets
   advertised to the model.
3. **The Will.** Every individual call is checked against the compiled
   allow-list by exact name, plus any parameter constraints the policy sets.

### Read-only and parameter constraints

MCP lets a server describe its own tools as read-only. SAFi ignores that.
Built-in tools have a reviewed read-only list that skips parameter checking;
tools from installed servers always take the full path, so a policy's parameter
constraints are always enforced on them. This costs nothing and removes a way
for a third party to weaken your own policy.

---

## 5. Per-user authorization (OAuth 2.1)

A server that implements the MCP authorization specification does not take a
static credential at all. Install it with `--auth oauth`:

```
scripts/safi_mcp.py add --url https://tools.example.com/mcp --auth oauth
```

Each member then presses **Sign in** on the server's card in Settings → Tools
Catalog, authenticates at the deployment's IdP (Keycloak, Auth0, or any
RFC 8414-compliant server), and from then on every call that member's agents
make to that server runs as that member. This is the fix for the shared-identity
problem below: attribution comes back, and offboarding a person cuts their
access.

**What SAFi holds, and pointedly does not.** The token SAFi stores is
audience-bound to the MCP server (requested via RFC 8707's `resource` parameter
at both the authorization and the token endpoint). It is not a Google or other
upstream credential and works nowhere but that one server, which validates it
against the IdP's JWKS (signature, issuer, expiry, and strictly the audience)
and performs its own upstream exchange (RFC 8693) if it needs one. A token
stolen from SAFi opens one tool server, not a mailbox.

Operational notes:

- The flow is authorization code with PKCE (S256), always. Nothing implicit.
- If the IdP offers dynamic client registration, SAFi registers itself once and
  reuses it; otherwise set `client_id` (and `client_secret` via `${VAR}`) in the
  server's definition, with redirect URI
  `{WEB_BASE_URL}/api/mcp/auth/<key>/callback`.
- The tool catalog appears after the FIRST sign-in: an OAuth server shows its
  tools to a token, not to the boot process. Until then the card says so.
- Tokens live in the encrypted `oauth_tokens` table, with an evidence row
  written in the same transaction.
- Offboarding reaches the server, not just SAFi's row. When a member
  disconnects, deletes their account, or is removed from their organization,
  SAFi calls the revocation endpoint the server's metadata advertises
  (RFC 7009) before deleting its own token. SAFi's gateways cascade from
  there: every gateway token for that person dies, the stored upstream
  tokens die, and Google's own revocation endpoint is called where it
  applies (Microsoft has no equivalent, so destroying the only stored copy
  is the control). Best effort by design: an unreachable server never
  blocks an offboarding, and a server without a revocation endpoint
  (GitHub's official server, today) falls back to deletion of SAFi's row.
- Guests can never connect, and the `orgs` restriction applies as usual.
- A reference resource server, pure Python on SAFi's own dependencies and
  exercised end to end by the test suite, ships as
  `scripts/oauth_resource_server.py`.

### Worked example: GitHub's official remote server

GitHub's hosted MCP server implements this specification, so it connects with
no gateway and no local process. It offers no dynamic registration, so the
deployment brings its own OAuth App (GitHub → Settings → Developer settings →
OAuth Apps) with the callback URL
`{WEB_BASE_URL}/api/mcp/auth/github_mcp/callback`, then:

```
GITHUB_MCP_CLIENT_ID=...       # in .env
GITHUB_MCP_CLIENT_SECRET=...

scripts/safi_mcp.py add --url https://api.githubcopilot.com/mcp --auth oauth \
    --key github_mcp --label "GitHub (official)" \
    --client-id '${GITHUB_MCP_CLIENT_ID}' \
    --client-secret '${GITHUB_MCP_CLIENT_SECRET}' \
    --scopes "repo,read:user,read:org"
```

Set `--scopes` deliberately, and know one measured fact: GitHub's hosted
server gates its ENTIRE repos toolset behind the full `repo` scope. Tokens
carrying only `public_repo` are refused even for reading a public repository
(verified 2026-08-15 by replay: `get_me` worked while every repos tool failed
with the same token, first at `read:org`, then again at `public_repo`).
Classic scopes have no read-only form of `repo`, so the token every member
grants can technically write to their repositories. That is exactly the gap
SAFi's own layers absorb: enable only the read tools in the policy and the
Will refuses everything else per call, whatever the token could do.

One honest caveat: GitHub's tokens are ordinary GitHub OAuth tokens, not
audience-bound JWTs, so the no-passthrough property is weaker here than with a
spec-complete IdP: the token SAFi stores would also work against GitHub's API
directly. That is the same storage posture as the built-in GitHub connector,
with a far larger tool set and no code for us to maintain.

### The Workspace gateway: per-user Google, ready to run

`scripts/workspace_gateway.py` is a complete example of this architecture with
real tools behind it: each member signs in at Google's own consent screen and
their agents gain read-only Google tools that run as them. It is its own small
authorization server AND the protected resource, co-located, so no Keycloak or
Auth0 is needed: Google tokens live inside the gateway (Fernet-encrypted,
keyed by the verified subject) and never reach SAFi; SAFi holds only a token
whose audience is the gateway.

v1 tools, read-only by doctrine: `whoami`, `calendar_list_events`,
`drive_search`, `drive_get_file_contents`, `gmail_search`. Nothing that
sends, moves or deletes.

Setup:

1. Create (or reuse) a Google OAuth client and add
   `{GATEWAY_BASE_URL}/google/callback` to its authorized redirect URIs.
2. Run the gateway (see `deploy/systemd/safi-workspace-gateway.service` for
   bare metal). Put TLS in front of it; the base URL must be https in
   production.
3. Install it in SAFi from the host:
   `scripts/safi_mcp.py add --url {GATEWAY_BASE_URL}/mcp --auth oauth`
4. Members press Sign in on its card in Settings, Tools Catalog.

### Running a gateway under Docker

Both gateways are compose services, off by default behind a profile, sharing
the `safi:latest` image the way `purge` and `scheduler` already do:

```bash
cp gateways/graph-gateway.env.example gateways/graph-gateway.env   # fill it in
docker compose --profile gateways up -d
```

A plain `docker compose up` is unchanged and starts no gateway, so a
deployment that wants neither provider never has to think about this. The env
files are gitignored; the `.example` templates are not.

Three things compose decides for you, each because leaving it to the operator
has a failure mode worth naming:

- **`GATEWAY_DB` points at a named volume**, one per gateway, and the compose
  `environment:` block overrides whatever the env file says. The store holds
  the signing key, the registered clients and every member's upstream tokens.
  Anywhere inside the image, `docker compose up --build` silently signs
  everyone out and sends them back through consent at Google or Microsoft.
- **`PORT` is fixed** at 8402 and 8403 inside the container. Map them
  elsewhere on the host with `WORKSPACE_GATEWAY_PORT` / `GRAPH_GATEWAY_PORT`.
- **Neither gateway depends on the database**, and neither sets `DB_HOST`, so
  they skip the entrypoint's MySQL wait. A gateway that refused to start
  because the app's database was down would take sign-in with it for a service
  that never touches MySQL.

**TLS is still yours.** `GATEWAY_BASE_URL` must be https and these containers
speak plain HTTP, so put your existing terminator in front of the published
port and set `GATEWAY_BASE_URL` to that public hostname. Compose has no proxy
service on purpose: SAFi does not own your ingress. `GATEWAY_BASE_URL` is also
the exact origin you register as the redirect URI and pass to
`safi_mcp.py add --url`, so it can never be a compose service name.

**Adding a scope later costs every connected member a reconnect.** Consent is
bound to the scope set that was granted, so a stored refresh token never
widens on its own. When mail and calendar were added on 2026-08-25, members
already connected kept working file tools while the new ones answered 403
until each person signed in again. The catalog count does not move either: it
is served from the discovery cache, which only refreshes on a sign-in. Plan
the announcement with the deploy, because the symptom reads like a bug.

### The Graph gateway: per-user Microsoft 365, same architecture

`scripts/graph_gateway.py` is the same architecture for Microsoft Graph.
Microsoft does publish an official MCP server, but it requires an M365
Copilot license, and SAFi does not require a competing AI product's license
as a dependency for its own tools. The two gateways share one implementation
of the OAuth machinery (`scripts/gateway_core.py`); each provider file is
only the endpoints, scopes, identity mapping and tools.

Tools, read-only by doctrine: `microsoft_whoami`, `files_list`,
`files_search`, `file_get_contents`, `sites_search`, `site_files_search`,
`mail_search`, `microsoft_calendar_events`. OneDrive, SharePoint, Outlook mail
and calendar, nothing writable.

Mail and calendar return less than they could, on purpose, matching what the
Workspace gateway returns for Google. `mail_search` gives subject, sender and
date, never a body: the scope is `Mail.ReadBasic`, which does not grant bodies,
so Entra holds that line rather than the tool code choosing not to ask.
`microsoft_calendar_events` gives titles and start times, never attendees,
location or body. A mailbox holds third parties who never agreed to be read by
this system, an attendee list discloses a relationship, and a tool result
becomes evidence in the governance record and inherits its retention.

It is `microsoft_calendar_events`, not `calendar_list_events`: the Workspace
gateway already owns that name, and two servers claiming one name collide in
the connector registry, where the first registration wins and the loser is
skipped without an error.

Setup:

1. Create an Entra app registration (Web platform) with
   `{GATEWAY_BASE_URL}/microsoft/callback` as a redirect URI, a client
   secret, and the delegated Graph permissions `User.Read`,
   `Files.Read.All`, `Sites.Read.All`, `Mail.ReadBasic`, `Calendars.Read`.
   Use `Mail.ReadBasic`, not `Mail.Read`: the wider scope grants message
   bodies that no tool here reads. Set `ENTRA_TENANT` to your tenant id to pin
   sign-in to one tenant, or leave the default `organizations` to accept any
   work or school account.
2. Run the gateway (see `deploy/systemd/safi-graph-gateway.service` for bare
   metal; default port 8403). TLS in front, https base URL in production.
3. Install it in SAFi from the host:
   `scripts/safi_mcp.py add --url {GATEWAY_BASE_URL}/mcp --auth oauth`
4. Members press Sign in on its card in Settings, Tools Catalog.

## 6. Static credential or per-user sign-in?

Both kinds of MCP server end up as connectors, both are gated identically, and
both leave the same audit evidence. The difference is the credential, and it
decides what each is for.

**A static server acts as the deployment.** It authenticates with one
credential from its configuration, which makes it a service principal. It has
one set of permissions for everybody.

**An OAuth server acts as the member.** Each person signs in once, and every
call their agents make runs as them: it inherits their permissions in the
source system, appears under their name in that system's audit log, and stops
working when they are offboarded.

So:

| Use | Because |
|---|---|
| **A static server** for a shared or system resource: a company API, an internal pricing service, a read-only operational view, a private service your organization runs | One credential is the correct model, and the data is not scoped to a person |
| **An OAuth server** for a member's own data: their files, their mailbox, their repositories | Attribution, per-person permissions, and access that ends at offboarding |

Wiring member data through a service-principal server works, and it costs you
all three of those properties. The source system's log will say SAFi did it,
not who asked.

(Until 2026-08-15 the per-user side was served by built-in "delegated"
connectors for GitHub, Google Drive and SharePoint. All three retired in
favour of the OAuth servers above: GitHub's official server, the Workspace
gateway, and the Graph gateway. Same credential model, no in-process code.)

---

## 7. Trust: who can install what

**Any server, of either transport, can only be installed by whoever controls the
deployment**, through the file on disk. No API route, no admin screen and no
organization setting can add one, and that is deliberate rather than unfinished.

For a local (stdio/package) server the reason is direct: it is an arbitrary
command the SAFi process executes with arbitrary arguments, so installing one is
the same level of trust as installing SAFi itself, the rule the developer guide
already states for `SAFI_EXTENSIONS_DIR`. In a deployment serving several
organizations, an admin who could add one could run code on a host everyone
shares.

A hosted (http/sse) server runs nothing of the publisher's here, but it is not
free of risk either, and the checks in section 8 exist for that: a URL your
infrastructure fetches is a way into your own network unless it is validated,
and every argument a model sends to that server leaves your deployment. Both
decisions belong to the same person for the same reason.

Two more things worth knowing before you install something you did not write:

- **Tool descriptions come from the server and go into the model's context.**
  They are instructions written by a third party. SAFi's prompt scanning covers
  what users send, not what a server advertises about itself.
- **A server that updates can change its own tool list.** New tools appear in
  the catalogue and stay unauthorized until someone grants them, but an existing
  tool can change what it does behind a stable name. Pin versions for anything
  you did not write.

---

## 8. Operational notes

- Servers connect once per worker process at boot. The container runs four
  gunicorn workers, so a stdio server means four subprocesses. Anything
  expensive to run should be `http`.
- Sessions stay open for the life of the process. A server that dies is not
  restarted until SAFi restarts; its tools then fail their calls with an error
  the agent sees, and the Will's gating is unaffected.
- A tool call has a 60 second ceiling.
- **A write through `scripts/safi_mcp.py` needs no restart. A hand edit does.**
  The CLI bumps a generation counter, and workers re-read the file on their next
  request when it moves. Editing the file directly leaves the counter where it
  was, so running workers keep the server list they already have until SAFi
  restarts. Prefer the CLI, and restart the `app` service if you edit by hand.
- **Under Docker the file is on a mount, not in the image.** `docker-compose.yml`
  points `MCP_SERVERS_JSON` at `/app/mcp/servers.json` and mounts `./mcp` there,
  so installed servers survive `up --build` and no rebuild is needed to add one.
  The mount exists precisely because the file used to be copied in, where every
  rebuild replaced an operator's server list with the empty one from the repo.
  See `mcp/README.md`. Anything a definition points at has to live on that same
  mount for the same reason.

---

## 9. The operator CLI

`scripts/safi_mcp.py` manages the servers in `MCP_SERVERS_JSON` from a shell. It
is how servers are installed, and the only way. Whoever runs this CLI already
has shell on the host, so installing a server adds no privilege they did not
already hold. That is the whole point.

```
scripts/safi_mcp.py list                     # what is configured, and where from
scripts/safi_mcp.py search filesystem        # the registry, packages included
scripts/safi_mcp.py add io.github.owner/svc  # from the registry
scripts/safi_mcp.py add --url https://example.com/mcp
scripts/safi_mcp.py add --command npx --args "-y,@scope/server@1.2.3"
scripts/safi_mcp.py check                    # connect to everything, report
scripts/safi_mcp.py remove <key>
scripts/safi_mcp.py disable <key>            # keep the definition, stop connecting
```

Three things it does that matter:

- **It checks before it saves.** A server that does not answer is not written to
  the file unless you pass `--force`, so a typo does not become a mystery later.
- **It refuses a launcher that is not installed.** Most of the registry is npm
  packages, and a host without Node could never start one. The CLI checks for
  the launcher and names the missing binary rather than writing a definition
  that fails silently. The Docker image carries Node and `npx`, so package
  servers work there; a bare-metal host is where this check earns its keep.
- **No restart.** Every write bumps the same counter the GUI uses, so running
  workers re-read the file on their next request.

### A worked example: Google Workspace

The Gemini CLI Workspace extension is a real MCP server, and installing it shows
what a substantial one involves. It is distributed as a git checkout rather than
a package, so it is cloned, built once, and started directly:

```
git clone --depth 1 https://github.com/gemini-cli-extensions/workspace.git mcp/workspace
docker compose exec app sh -c "cd /app/mcp/workspace && npm install"
docker compose exec app python scripts/safi_mcp.py add \
    --command node --args="workspace-server/dist/index.js,--use-dot-names" \
    --cwd /app/mcp/workspace --key workspace --label "Google Workspace"
```

Then authorize it, interactively, from a terminal with a TTY:

```
docker compose exec app sh -c "cd /app/mcp/workspace && npm run auth-utils -- login"
```

It prints a Google URL, you sign in, and you paste the returned JSON back.

**Read this before you enable any of it.** The server advertises 57 tools, and
they are not all reads: `gmail.send`, `gmail.modify`, `drive.trashFile`,
`drive.moveFile`, `calendar.deleteEvent` and `chat.sendMessage` all act on the
world. It authenticates as ONE Google identity, whoever completed that login, so
every agent granted these tools acts as that person, and that account's audit
log is where the activity appears. This is the service-principal case from
section 5, applied to exactly the data section 5 says it is wrong for.

That is not a reason to avoid it, but it is a reason to grant narrowly. Enable a
read-only subset in a policy first (`drive.search`, `calendar.listEvents`,
`docs.getText`, `time.getCurrentDate`) and leave anything that sends, moves or
deletes switched off until you have a reason and a reviewer.

Two operational notes specific to servers of this shape:

- **Credentials live next to the checkout** (`gemini-cli-workspace-token.json`),
  which is on the mount and therefore survives rebuilds. Their encryption key is
  salted with the hostname, so `docker-compose.yml` pins `hostname: safi-app`;
  without that the container id changes on every `up` and the saved token
  silently stops decrypting.
- **`--cwd` matters.** A server distributed as a checkout resolves its own files
  relative to where it started, so it needs a working directory rather than an
  absolute path alone.

### Try it: the bundled demo server

`mcp/demo_server.py` is a two-tool server for seeing the pipeline work:

```
docker compose exec app python scripts/safi_mcp.py add \
    --command python --args "/app/mcp/demo_server.py" --key demo --label "Demo Server"
```

Enable `demo_echo` and not `demo_word_count` in a policy, assign that policy to
an agent, and the agent gets exactly one of the two.

### On bare metal

Everything works the same: the runtime spawns a subprocess or opens an HTTP
connection, and nothing in it is Docker-specific. Four differences are worth
setting up deliberately.

**Run the CLI as the service user.** The app runs as `safi`, so that is who has
to read the server file and start the servers:

```bash
cd /var/www/safi
sudo -u safi ./venv/bin/python scripts/safi_mcp.py list
```

Running it as root writes a file the service may not be able to read, and puts
any package cache in root's home rather than the service user's.

**Keep the server file OUTSIDE the checkout.** Upgrades are `git pull`, and the
file shipped inside the package is tracked, so servers written into it either
block the pull or get replaced by it. Point `MCP_SERVERS_JSON` somewhere the
service user owns and git does not:

```
MCP_SERVERS_JSON=/home/safi/mcp-servers.json
```

The same goes for anything a definition points at: server checkouts, scripts and
the credential files they write. Put them under the service user's home, not
under `/var/www/safi`.

**Node is not installed by the bare-metal instructions.** The Docker image ships
it; a bare-metal host does not, so `npx` servers need Node installed for the
`safi` user to run (`apt install nodejs npm`, or NodeSource for a current
version). Hosted (`--url`) servers need nothing.

**Do not add systemd hardening without checking this.** The shipped unit sets
`User`, `Group` and `WorkingDirectory` and nothing else. Adding `PrivateTmp`,
`ProtectHome` or `NoNewPrivileges=yes` will stop stdio servers starting or cut
them off from their credential files, and the failure surfaces as
`MCPError: Connection closed` rather than as a permissions error.

### In Docker, the server file must be a mount

`docker-compose.yml` mounts `./mcp` and points `MCP_SERVERS_JSON` at
`/app/mcp/servers.json`. That is not a convenience: the Dockerfile copies
`safi_app/` into the image, so a server file living under it is replaced on
every `docker compose up --build`, which silently wipes the operator's installed
servers and makes the CLI useless across rebuilds. If you move the file, keep it
outside the copied paths.

### Package servers: what runs them

The container image ships **Node 22**, so `npx` servers work out of the box:

```
docker compose exec app python scripts/safi_mcp.py \
    add --command npx --args="-y,@modelcontextprotocol/server-everything"
```

Note the `--args=` form. A value starting with a dash is read as an option
otherwise, and `--args "-y,..."` fails with "expected one argument".

Python packages need `uvx`, which is not installed: `pip install uv` in the
image adds it. Hosted (`--url`) servers need no local runtime at all.

Two consequences of running npm servers worth knowing:

- **The first start downloads the package.** The npm cache is a named volume
  (`npm_cache`), so that happens once per deployment rather than on every
  container start. A server whose package cannot be fetched simply fails, and
  its tools are absent.
- **An unpinned package is fetched fresh.** `npx -y @scope/server` can run
  different code tomorrow than today with nothing in your deployment having
  changed. Pin the version, and prefer `add <registry-name>`, which uses the
  exact version the publisher released.

### Pin your packages

`npx -y @scope/server` fetches from the network at every boot, so the code
running on your host can change without anyone touching your deployment. The CLI
warns when it sees no version pin. Registry installs use the exact version the
registry published, which is why `add <registry-name>` is preferable to writing
the command by hand.

### What it does not do

It installs; it grants nothing. A server added here is a connector an
organization must still allow, a policy must still list, and an agent must still
enable, and the Will still authorizes call by call.

---

## 10. Writing your own server

Any MCP server works. To expose a private API to a governed agent, the smallest
version is a stdio server with one tool per operation. Keep the tool surface
narrow: every tool is something a policy author has to reason about, and a
single `run_query` tool that takes arbitrary SQL cannot be governed by a
parameter constraint in any useful way.

Prefer many specific read tools over one general one. That is what makes the
Will's parameter gate able to say anything meaningful about a call.
