---
title: SAFi README: Knowledge Bases and Tools
slug: readme-knowledge-bases-and-tools
tags: ["safi", "readme", "knowledge", "tools", "mcp", "rag", "safi"]
summary: Agents draw on two kinds of outside context, governed on the same principle. Knowledge Bases are internal repositories the organization controls end to end; Tools are connections to external MCP services whose use is decided per tool, per policy, per call.
version: 1.0
---

# SAFi README: Knowledge Bases and Tools

Agents draw on two kinds of outside context, and both are governed on the same
principle.

**Knowledge Bases** are internal repositories the organization uploads, reviews
and controls end to end.

**Tools** are connections to external services (MCP servers) whose use is decided
per tool, per policy, per call.

## Installation grants nothing

Installing a tool does not give any agent the ability to use it. There are
several separate decisions:

1. **Install, on the host.** Whoever operates the deployment installs an MCP
   server from the host's terminal. There is deliberately no way to install one
   from the browser, because installing a server can mean running external code,
   and that decision belongs to whoever already holds host access.
2. **Discover.** SAFi connects to the server and asks what tools it offers, then
   catalogs them. At this point they are visible and completely inactive.
3. **Enable, in a policy.** An editor enables specific tools in a policy. This is
   a ceiling: agents under that policy can never use a tool the policy does not
   list.
4. **Assign, to an agent.** The agent is given the tools its policy allows.

After all of that, the Will still checks every individual call against the
allowed list before it runs, and the call is recorded in the audit trail. In an
organization, adding tools to a policy's declared list is held for approval by
the designated approvers; removals apply immediately, because narrowing what an
agent can do never needs to wait.

## Tools that act as a person

Some tools act as a specific individual rather than as the deployment. Those
require that person to sign in once, either from the composer's **+** panel or
from a link the agent hands them at the moment of need. Guest accounts can never
connect a per-user tool.

## Where the details live

The repository documents the whole lifecycle, from upload or install through to a
governed call, including who approves what and who signs in, in
`docs/KNOWLEDGE_AND_TOOLS.md`. The operator manual for MCP servers, covering
installation with the CLI, per-user OAuth, credentials and scopes, with worked
examples including GitHub's official server, is in `docs/MCP_TOOLS.md`.
