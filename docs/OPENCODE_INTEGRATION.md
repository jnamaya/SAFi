# Using SAFi from opencode

SAFi exposes a standard OpenAI-compatible endpoint, so you can drive a governed
SAFi agent from [opencode](https://opencode.ai), the OpenAI CLI, `curl`, or any
tool that speaks the OpenAI chat protocol.

SAFi's `/v1` endpoint is a *thin adapter*: every turn you send is forwarded to
SAFi's governed pipeline, where your message is checked against a policy before
it is answered. Agent selection, policy resolution, orchestration and audit all
happen in the SAFi backend — the protocol you speak is just the OpenAI one.

```
opencode ── /v1/chat/completions ──▶ SAFi gateway ──▶ governed pipeline
             (model, messages)          (thin)            │
                                    ◀── OpenAI-shaped ──┘   policy check + audit
```

---

## What you need

To use a SAFi instance you need three things **from that instance's operator**:

1. **A base URL** — a public endpoint ending in `/v1`,
   e.g. `https://your-host.example.com/v1`. Anyone can host a SAFi instance
   (see the SAFi repo), or your organisation may run one for you.
2. **An API key** — a policy key granted to you. The key determines **which
   policy governs your turns**; hold on to it and don't share it.
3. **An agent id** — the name of the SAFi agent you'll talk to. These are
   granted per instance; ask the operator for the available agents, or list
   them at runtime (below).

You also need [opencode](https://opencode.ai) installed.

---

## 1. Configure opencode

Create an `opencode.json` in your project (or merge the `provider` block into
an existing one). Replace the placeholders with your own values:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "provider": {
    "safi": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "SAFi (governed)",
      "options": {
        "baseURL": "https://your-host.example.com/v1",
        "apiKey": "{env:SAFI_API_KEY}"
      },
      "models": {
        "your_agent_id": {
          "name": "The SAFi agent's display name",
          "tool_call": false
        }
      }
    }
  }
}
```

Notes:

- **`baseURL`** is the SAFi `/v1` root the operator gave you. It ends in `/v1`
  — keep that suffix.
- **`your_agent_id`** is an agent id from that instance (see below). You can
  register several agents that share the same key.
- **`tool_call: false` is required.** SAFi serves *governed text turns*, not
  tool calls. Leaving it out (or sending tools) yields a governed text answer.

## 2. Set the API key

Export the key the operator gave you wherever opencode can read it:

```bash
export SAFI_API_KEY=sk-safi-…
```

opencode resolves `{env:SAFI_API_KEY}` at startup. The adapter verifies the key
you send against the one it runs with, then passes it to the governed backend,
which resolves it to your policy.

## 3. Chat

Start opencode and pick the SAFi model you configured. Chat normally. A raw
`curl` works too:

```bash
curl https://your-host.example.com/v1/chat/completions \
  -H "Authorization: Bearer $SAFI_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "your_agent_id",
    "user": "your-client-identifier",
    "messages": [{"role": "user", "content": "Hello"}]
  }'
```

Add `"stream": true` for SSE streaming.

---

## Learning what's available on an instance

List the agents a SAFi instance ships (same key, no body):

```bash
curl https://your-host.example.com/v1/models \
  -H "Authorization: Bearer $SAFI_API_KEY"
```

Response is a standard model list; each `id` is an agent id you can use as
`model`. Every instance ships at least a built-in `safi` stewardship agent.

---

## How your turns are governed

1. **Auth.** Your key (as `Authorization: Bearer …` or `X-API-KEY`) must match
   the key the gateway runs with.
2. **Policy resolution.** SAFi looks your key up to find its **policy**. That
   policy is what governs your turns — the key you were granted, not the agent
   id, decides the rules you answer under.
3. **Persona.** Your `model` selects the SAFi agent persona answering you (its
   worldview, scope, and instructions).
4. **Orchestration.** The backend runs its governed pipeline — it checks your
   message against the policy, decides whether (and how) to answer, and audits
   the turn.
5. **Response.** You get back a standard OpenAI-shaped completion, plus SAFi
   headers like `X-SAFi-Will-Decision`.

Conversation history is kept **server-side**, keyed on the `user` request field —
supply a stable value per client so a conversation continues across turns.

---

## Scope & limits

- **Governed text turns only** — no tool calling. If your workflow needs tools,
  use SAFi's other integrations (e.g. the MCP gateway) rather than this one.
- **One policy per key.** Your key is bound to the policy it was granted
  against; you can't request a weaker policy through the API.
- **TLS is required.** The key and your conversation are credentials; only use
  `https://` endpoints.
- **Your instance operator sets the rules.** Policies, retention, and audit are
  configured by the SAFi instance you connect to, not by opencode.