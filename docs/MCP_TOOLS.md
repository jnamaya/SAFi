# MCP tools: installing and configuring them

SAFi agents can call tools. Some ship with the product; others come from MCP
servers you install. This document covers installing a server, granting it, and
the rules that decide which of the two kinds of tool a given job needs.

Audience: whoever controls the deployment, and organization admins installing
hosted servers from the browser. Which of the two paths applies to you depends
on how the server runs, for reasons in [section 6](#6-trust-who-can-install-what).

---

## 1. The short version

There are two ways in, and they are for different things.

**From the browser (Settings, Tool Servers).** An admin searches the official
MCP registry and installs a **hosted** server in one click. A second admin
approves it and it is live, no restart. This is the easy path and it covers most
cases. See [section 8](#8-installing-from-the-registry-in-the-gui).

**From the file (`MCP_SERVERS_JSON`).** The operator's path, and the only way to
install a server that runs **locally** as a package or command. Sections 2
through 4 cover it.

Either way, the rest is the same and is how every tool in SAFi has always
worked:

1. The server is installed and becomes a connector.
2. An organization admin allows the connector.
3. A policy author checks it under Tools & Guardrails.
4. An agent under that policy enables it.
5. The Will authorizes every individual call by exact name.

**Installing grants nothing.** That is the sentence to keep hold of. Making
installation easy is safe because installation is only the first of five steps,
and the other four already existed.

---

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
unauthorized until a person says otherwise. Four rungs, all of which predate
MCP support:

1. **Organization.** An admin allows the connector for the org.
2. **Policy.** The author checks it under Tools & Guardrails. This is a ceiling:
   agents under the policy can never use tools it does not list.
3. **Agent.** The builder enables it on the agent. This is what gets advertised
   to the model.
4. **The Will.** Every individual call is checked against the compiled
   allow-list by exact name, plus any parameter constraints the policy sets.

A policy can narrow within a server by naming individual tool functions instead
of the server, so granting `acme_billing` at the agent level and listing only
`billing_get_invoice` in the policy gives that agent exactly one tool.

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

## 8. Installing from the registry, in the GUI

**Settings → Tool Servers**, admin only. Search the official MCP registry,
press Install, have another admin approve it, and the tools are live without a
restart.

### What the registry does and does not tell you

The official registry verifies **namespace ownership**: publishing under
`io.github.someone/thing` requires proving you are that GitHub identity, or
proving the domain by DNS or HTTP. That makes typosquatting hard and gives every
entry an accountable publisher.

It performs **no code review, no vulnerability scanning, and no security
assessment**. A listing means "this publisher owns this name", never "this code
is safe". Install servers from publishers you would trust with the data your
agents will send them. The screen says the same thing, on purpose.

### What can be installed this way

**Hosted servers only.** A registry entry offers a hosted endpoint, a local
package, or both. Only the hosted kind is installable from a browser, because
installing a package means running its code on the SAFi host, and that is a
decision for whoever controls the deployment rather than for anyone with an
admin login. An entry that is package-only shows why, and points at the file.

`SAFI_MCP_INSTALL_MODE` controls this:

| Value | Effect |
|---|---|
| `remote` | Default. Admins may install hosted servers. |
| `off` | Nothing installable from the browser; the file is the only way in. |
| `all` | Reserved for a future release, where admins may also install package servers. Correct only where the admins and the operator are the same people. Currently treated as `remote`. |

### The checks an endpoint has to pass

All fixed rules, applied before anything is stored:

- **https only.** Plain http would send your prompts and arguments in the clear.
- **No private, loopback or link-local addresses**, checked against what the
  hostname actually resolves to, not against how it is spelled. An
  admin-supplied URL that this server then fetches is a way into your own
  network, and that is the standard shape of the attack.
- **No credentials embedded in the URL.**
- **A host that does not resolve is refused**, rather than accepted in the hope
  it works later.

### Approval

An install lands **pending** and reaches no agent until an admin approves it.
The person who installed it cannot approve it, unless they are the
organization's only eligible reviewer, in which case they can, and the sign-off
is recorded as a **non-independent review** rather than counted as real
oversight. Same rule, and the same underlying check, as knowledge base
documents.

Approving connects the server and scans its tool descriptions against the
prompt-injection signature list. Descriptions are text the publisher wrote that
becomes instructions in the model's context, so a match is surfaced to the
approver as a warning. It is a warning rather than a block: the approver is a
person, and a false positive should not strand a legitimate tool.

### Evidence

Install, approve, reject and remove each write a row to the organization's
compliance log naming the actor, the endpoint and the version. The version is
the exact one the registry published; SAFi never auto-updates a server.

### Tenancy

A server installed by one organization belongs to that organization. Another
organization does not see it in the picker and cannot grant it to an agent, and
that second check runs on save rather than relying on the picker having hidden
it.

---

## 9. Writing your own server

Any MCP server works. To expose a private API to a governed agent, the smallest
version is a stdio server with one tool per operation. Keep the tool surface
narrow: every tool is something a policy author has to reason about, and a
single `run_query` tool that takes arbitrary SQL cannot be governed by a
parameter constraint in any useful way.

Prefer many specific read tools over one general one. That is what makes the
Will's parameter gate able to say anything meaningful about a call.
