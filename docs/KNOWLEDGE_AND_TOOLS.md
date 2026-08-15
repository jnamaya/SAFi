# How Knowledge Bases and Tools work in SAFi

Agents draw on two kinds of outside context, and they are governed on the same
principle with one deliberate difference.

* **Knowledge Bases** are internal repositories. The organization uploads the
  content, reviews it, and controls it end to end.
* **Tools** are connections to external services (MCP servers). The
  organization decides which services exist and which tools agents may call,
  but the content comes from outside.

Both follow the same arc: someone with the right role sets it up, an approval
or policy step decides what agents may use, and every use is checked and
recorded per turn. The one difference: members never authenticate to use a
Knowledge Base, because the organization already owns the content. Tools that
act on a member's behalf require that member to sign in once, so the external
service knows who each call runs as.

---

## 1. Knowledge Bases

**Create and upload.** An Editor or Administrator opens the Knowledge section
of the Control Panel, creates a Knowledge Base, and uploads documents. The
indexer processes them into a searchable form; documents become retrievable
when indexing finishes.

**Review, when sharing.** A private Knowledge Base needs no review. Sharing
one with the organization is what triggers review, and it works per document:
each document must be approved before its content becomes retrievable by
others. Reviewers are **Administrators and Auditors**. Editors deliberately
cannot approve, even content they did not write, so authorship and sign-off
stay separated.

If the organization has only one eligible reviewer, that person may approve
their own uploads. The sign-off is recorded as a non-independent review rather
than silently counted as oversight, and the exception closes itself the moment
a second reviewer joins. Every creation, share, approval and rejection writes
a compliance-log entry.

**Attach.** A Knowledge Base is attached to an agent, and a policy may
restrict which Knowledge Bases its agents may use. The agent's answers then
ground themselves in the approved content, with sources visible in the chat.

---

## 2. Tools (MCP servers)

**Install, on the host.** Whoever operates the deployment installs a server
from the terminal with `scripts/safi_mcp.py`. There is deliberately no way to
install a server from the browser: installing one can mean running external
code on the host, and that decision belongs to the person who already holds
that level of access. The CLI checks the server before saving it.

**Discover.** SAFi connects to the server and asks what tools it offers.

* A server with a static credential (or none) shows its tools in the Tools
  Catalog immediately.
* A server using per-user sign-in shows its tools after the **first**
  sign-in, because such servers reveal their catalog to a signed-in user, not
  to the deployment. The catalog is cached from then on.

**Provider registration, sometimes.** Some providers' sign-in systems let
SAFi register itself automatically. Others, GitHub among them, require the
administrator to create an OAuth application on the provider's side first and
give SAFi its credentials. Each provider documents its own requirements,
including which scopes its tools need.

---

## 3. Enabling, assigning, and who signs in

Installation grants nothing. Two more decisions make a tool or Knowledge Base
usable, and both are made by people:

1. **Policy.** An Editor enables specific tools in a policy's Tools &
   Guardrails step. This is a ceiling: agents under the policy can never use
   a tool it does not list.
2. **Agent.** The agent is assigned the tools and Knowledge Base its policy
   allows.

Every individual call an agent makes is then checked against that
authorization before it runs, and recorded in the audit trail.

**Signing in, for per-user tools.** Tools that act as a specific person
require that person to connect their account once:

* Members connect from the **Tools** section of the composer's **+** panel,
  which offers exactly the services their agents are authorized to use.
* Or just in time: if an agent needs a tool the member has not connected, its
  reply includes the sign-in link. One click, consent at the provider, ask
  again.
* Administrators can always connect, since the first sign-in is what
  discovers a per-user server's catalog. Guest accounts can never connect.

A member with no agent that could use a tool is never invited to connect it:
connecting exists for the agent's sake, and a credential nothing will read is
not offered.
