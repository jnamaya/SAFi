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

**The browser installs nothing.** An earlier version let an admin browse the
official registry and install a hosted server from Settings; it was removed.
Installation belongs on the host, where the person doing it already holds the
rights that running someone's code implies, and keeping it there removed a
per-organization install table, an approval workflow and a tenancy problem that
existed only to make a browser safe for a job that was never the browser's.

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

`${VAR}` anywhere in `env`, `args` or `url` is replaced from the SAFi process
environment. Put secrets in your `.env` and reference them here, so the server
file stays safe to copy and commit.

### Naming

The server key becomes a connector name. It may not collide with a built-in
connector (`web_search`, `github`, `google_drive`, `sharepoint`, `find_places`,
and the finance tools). A colliding server is refused at boot and logged, and
its tools are unavailable until you rename it.

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

## 5. MCP server or built-in connector?

Both end up as connectors, both are gated identically, and both leave the same
audit evidence. The difference is the credential, and it decides what each is
for.

**Built-in connectors act as the member.** Google Drive, SharePoint and GitHub
use delegated per-user OAuth. Every read inherits that person's permissions in
the source system, appears under their name in that system's audit log, and
stops working when they are offboarded.

**An MCP server acts as the deployment.** It authenticates with one credential
from its configuration, which makes it a service principal. It has one set of
permissions for everybody.

So:

| Use | Because |
|---|---|
| **MCP server** for a shared or system resource: a company API, an internal pricing service, a read-only operational view, a private service your organization runs | One credential is the correct model, and the data is not scoped to a person |
| **Delegated OAuth connector** for a member's own data: their drive, their mailbox, their repositories | Attribution, per-person permissions, and access that ends at offboarding |

Wiring member data through a service-principal MCP server works, and it costs
you all three of those properties. The source system's log will say SAFi did it,
not who asked.

---

## 6. Trust: who can install what

The line runs between servers that execute code here and servers that do not.

**A local (stdio/package) server can only be installed by whoever controls the
deployment**, through the file on disk. No API route, no admin screen and no
organization setting can add one, and that is deliberate rather than unfinished.
Such a server is an arbitrary command the SAFi process executes with arbitrary
arguments, so installing one is the same level of trust as installing SAFi
itself, the rule the developer guide already states for `SAFI_EXTENSIONS_DIR`.
In a deployment serving several organizations, an admin who could add one could
run code on a host everyone shares.

**A hosted (http/sse) server can be installed by an organization admin** from
Settings, because nothing of the publisher's runs here. It is not free of risk
and the checks in section 8 exist for that: a URL your infrastructure fetches is
a way into your own network unless it is validated, and every argument a model
sends to that server leaves your deployment. An operator who wants none of this
sets `SAFI_MCP_INSTALL_MODE=off`.

Two more things worth knowing before you install something you did not write:

- **Tool descriptions come from the server and go into the model's context.**
  They are instructions written by a third party. SAFi's prompt scanning covers
  what users send, not what a server advertises about itself.
- **A server that updates can change its own tool list.** New tools appear in
  the catalogue and stay unauthorized until someone grants them, but an existing
  tool can change what it does behind a stable name. Pin versions for anything
  you did not write.

---

## 7. Operational notes

- Servers connect once per worker process at boot. The container runs four
  gunicorn workers, so a stdio server means four subprocesses. Anything
  expensive to run should be `http`.
- Sessions stay open for the life of the process. A server that dies is not
  restarted until SAFi restarts; its tools then fail their calls with an error
  the agent sees, and the Will's gating is unaffected.
- A tool call has a 60 second ceiling.
- Changing the server file requires a restart. In Docker, rebuild or restart the
  `app` service; the file is copied into the image.

---

## 8. The operator CLI

`scripts/safi_mcp.py` manages the servers in `MCP_SERVERS_JSON` from a shell. It
exists because the browser can only install hosted servers, which leaves the npm
and pypi majority of the ecosystem unreachable there by design. Whoever runs
this CLI already has shell on the host, so installing a package server adds no
privilege they did not already hold. That is the whole difference.

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
- **It refuses a launcher that is not installed.** The app image ships Python
  and no Node, so an `npx` server would never start. The CLI says so and names
  the missing binary rather than writing a definition that fails silently.
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

## 9. Writing your own server

Any MCP server works. To expose a private API to a governed agent, the smallest
version is a stdio server with one tool per operation. Keep the tool surface
narrow: every tool is something a policy author has to reason about, and a
single `run_query` tool that takes arbitrary SQL cannot be governed by a
parameter constraint in any useful way.

Prefer many specific read tools over one general one. That is what makes the
Will's parameter gate able to say anything meaningful about a call.
