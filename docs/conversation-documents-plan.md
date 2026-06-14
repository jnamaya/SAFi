# Implementation Plan — Persistent Conversation Documents ("pinned sources")

**Status:** Proposed · **Date:** 2026-06-03 · **Owner:** TBD

## 1. Problem & goal

Today a user can upload a document, but SAFi treats it as **one-shot**: the browser extracts
the text and appends it to that *single* user message (`public/js/core/chat.js:741`), via the
stateless endpoint `POST /documents/extract` (`safi_app/api/documents.py:22`). The text is never
stored and never re-supplied. Once that message scrolls out of the verbatim window — the **last 6
messages / 3 turn-pairs** (`safi_app/core/orchestrator.py:381`) — and unless the rolling
`memory_summary` happened to capture the relevant bit, the document is effectively gone. This is
the "it forgot my file" behavior.

**Goal:** Persist uploaded documents *per conversation* and re-supply them as a stable, governed
**source** on every turn — the way Gemini/ChatGPT pin an upload — without breaking SAFi's token
budget or governance guarantees.

### Non-goals
- Cross-conversation document libraries (that's the existing static `rag_knowledge_base` path).
- OCR / image understanding (extraction stays text-only: `.txt/.md/.pdf/.docx/.csv`).

## 2. Design overview — hybrid, sized by document length

| Mode | Trigger | Mechanism | Cost profile |
|------|---------|-----------|--------------|
| **A. Full-text pin** | doc ≤ `PIN_FULLTEXT_CHAR_THRESHOLD` (e.g. 6–8k chars) | store text, inject verbatim every turn | high per-turn, exact recall |
| **B. Per-conversation RAG** | doc larger than threshold, or total pinned budget exceeded | chunk + embed at pin time into a per-conversation FAISS index; retrieve top-k per turn | low per-turn, lossy |

A per-turn **token budget** (`MAX_PINNED_CONTEXT_CHARS`) caps total injected pinned text. Small docs
that collectively exceed the budget get demoted to mode B. This matters because the intellect model
is `llama-3.1-8b-instant` (small context, cheap) and the **Conscience audit also receives the
context** (see §5) — so every pinned char is paid for *twice* per turn.

**Phasing:** Ship **Phase A (mode A only)** first to validate UX + governance, then add **Phase B**.

## 3. Data model

New table (create alongside the others in `safi_app/persistence/database.py` `init_db`):

```sql
CREATE TABLE conversation_documents (
    id              CHAR(36) PRIMARY KEY,
    conversation_id CHAR(36) NOT NULL,
    user_id         VARCHAR(255) NOT NULL,
    filename        VARCHAR(512) NOT NULL,
    content         LONGTEXT,              -- extracted text (mode A) / source of truth for chunking (mode B)
    total_chars     INT,
    mode            ENUM('fulltext','rag') NOT NULL DEFAULT 'fulltext',
    index_ref       VARCHAR(255),          -- vector_store basename for mode B, else NULL
    status          ENUM('active','removed') NOT NULL DEFAULT 'active',
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_conv (conversation_id, status)
);
```

CRUD helpers in `database.py`: `insert_conversation_document`, `fetch_active_conversation_documents(cid)`,
`mark_conversation_document_removed(doc_id, user_id)`.

## 4. Backend changes (touch points)

1. **New routes** (extend `safi_app/api/documents.py`, or a conversation-scoped blueprint):
   - `POST /conversations/<cid>/documents` — extract (reuse `extract_text`), run **pin-time scope
     check** (§5), choose mode by size, persist row; for mode B build the per-conversation index.
   - `GET  /conversations/<cid>/documents` — list active pinned docs (for the UI chips).
   - `DELETE /conversations/<cid>/documents/<doc_id>` — set `status='removed'`, drop index file.
   - All gated by the existing ownership check (`db.ensure_conversation_access`).

2. **Context assembly** (`safi_app/core/orchestrator.py:376–390`): after fetching summary/history,
   add `pinned_docs = db.fetch_active_conversation_documents(conversation_id)`. Build:
   - mode A docs → concatenated full text (clamped to `MAX_PINNED_CONTEXT_CHARS`).
   - mode B docs → `ConversationRetriever(cid).search(user_prompt)` top-k chunks.
   Combine into a single `pinned_context` string.

3. **Intellect** (`safi_app/core/faculties/intellect.py:55`): add param `pinned_context: str = ""`.
   Inject it into `system_prompt` (line 180) as a labelled block, placed **after**
   `agent_context_injection` and before `memory_injection`:
   ```
   PINNED SOURCES (documents attached to this conversation — treat as authoritative source material):
   <pinned_sources>{pinned_context}</pinned_sources>
   ```
   **Critically**, fold it into `final_context_for_audit` (line 202) so the Conscience audit sees it
   (see §5). Add the matching kwarg at the call site (`orchestrator.py:459`) and on the retry/tool-
   agent path so it persists across tool rounds (mirror `precomputed_retrieved_context`).

4. **Retriever for Phase B** (`safi_app/core/services/retriever.py`): today `Retriever` loads a
   prebuilt `{name}.index` + `{name}_metadata.pkl` from `vector_store/`. Reuse the chunk/embed logic
   in `rag/build_index.py` to write `vector_store/conv_<cid>_<doc_id>.index` at pin time, then load
   it via the existing `Retriever(knowledge_base_name=...)` path. The shared embedding model
   (`_SHARED_MODEL`) is already a singleton, so no extra model load.

## 5. Governance integration (the part that makes this *more* than UX)

- **Audit visibility:** The Conscience auditor already receives `retrieved_context` and runs the
  **Grounding Fidelity** gate against it (`safi_app/core/faculties/conscience.py:96`,
  `orchestrator.py:695`). By routing `pinned_context` into `final_context_for_audit`
  (`intellect.py:202`), pinned documents flow through the *same* governance pipeline for free — and
  grounding is now verifiable on **every** turn, not just the upload turn. This strengthens SAFi's
  core "grounded, auditable answers" claim.
- **Scope check at pin time:** Today the frontend injects a per-message "is this document in your
  role?" instruction (`chat.js:751`). Because a pinned doc is *durable*, run that check **once, at
  pin time** (a lightweight Conscience/relevance call) and refuse to pin out-of-scope documents,
  rather than re-litigating it every turn. (Note: scope itself remains policy-layer — see
  `docs`/memory `governance_scope_is_policy_layer`.)
- **Audit log provenance:** persisting the source lets the audit ledger reference *which* pinned
  document grounded a claim. Consider stamping `doc_id`s into `reasoning_log`.

## 6. Retention, privacy, cleanup

Persisting document text server-side is a real policy concern for a governance product.
- **Cascade deletes:** wire `conversation_documents` cleanup (rows + `vector_store/conv_*` files)
  into `delete_conversation` (`database.py:894`), `delete_all_conversations` (`:904`), and
  `delete_user` (`:670`). NB: `delete_conversation` currently deletes only the `conversations` row —
  confirm/extend cascade for `chat_history` too while here.
- **Retention window:** optional TTL purge (`PINNED_DOC_RETENTION_DAYS`) via a periodic job.
- **Access control:** every route gated by `ensure_conversation_access`; never serve a doc across
  users/conversations.
- **Summarizer interaction:** the background summarizer (`orchestrator_mixins/tasks.py:21`) must
  **exclude** pinned-doc text from its input, or it will waste tokens trying to fold a document into
  the conversation summary.

## 7. Frontend changes (`public/js/core/chat.js`)

- On upload, call the new pin endpoint instead of appending extracted text to the message
  (`chat.js:741`). Render the doc as a **persistent source chip** above the composer (with a remove
  "×"), distinct from the current transient file chips.
- Load active pinned docs on conversation open (`GET /conversations/<cid>/documents`).
- Remove the per-message full-text append path (it becomes redundant and double-counts tokens).
- Rebuild CSS after template/Tailwind changes: `cd public && npx tailwindcss -i ./css/input.css -o ./css/main.css`.

## 8. Config (`safi_app/config.py`, env-overridable like the existing upload flags at :201)

```python
ENABLE_CONVERSATION_DOCUMENTS  = env_bool("SAFI_ENABLE_CONV_DOCS", True)
PIN_FULLTEXT_CHAR_THRESHOLD    = int(os.environ.get("SAFI_PIN_FULLTEXT_CHARS", "8000"))
MAX_PINNED_CONTEXT_CHARS       = int(os.environ.get("SAFI_MAX_PINNED_CHARS", "16000"))
MAX_PINNED_DOCS_PER_CONV       = int(os.environ.get("SAFI_MAX_PINNED_DOCS", "5"))
PINNED_DOC_RETENTION_DAYS      = int(os.environ.get("SAFI_PINNED_DOC_RETENTION_DAYS", "0"))  # 0 = no auto-purge
```

## 9. Phasing

**Phase A — full-text pin (MVP, ~smallest useful slice):**
table + CRUD, pin/list/delete routes, pin-time scope check, inject into Intellect + audit, retention
cascade, frontend source chip, exclude from summarizer. Mode A only; large docs rejected with a
"too large to pin" message. Validates UX + governance end-to-end.

**Phase B — per-conversation RAG:** chunk+embed at pin, `ConversationRetriever`, hybrid sizing &
token-budget demotion, top-k injection.

## 10. Testing

- **Unit:** CRUD; cascade cleanup on conversation/user delete; mode selection by size; budget clamp.
- **Integration:** upload a doc, ask a question about it **>3 turns later**, confirm the answer is
  grounded (the original regression this fixes). Confirm `conscienceLedger` shows Grounding Fidelity
  evaluating the pinned source.
- **Governance:** out-of-scope doc is refused at pin time; in-scope doc grounds answers and is cited.
- **Cost guard:** verify total injected pinned chars never exceed `MAX_PINNED_CONTEXT_CHARS` and that
  Conscience audit payload size stays bounded.

## 11. Open decisions

1. **Storage location:** DB `LONGTEXT` (simple, transactional, cascades cleanly) vs. object store /
   filesystem (better for big files). Recommend DB for Phase A given the 50k-char extract cap.
2. **Threshold tuning:** `PIN_FULLTEXT_CHAR_THRESHOLD` vs. the small intellect context window — may
   want a model-aware budget rather than a fixed number.
3. **Pin-time scope check cost:** one extra LLM call per upload — acceptable? (Alternative: cheap
   embedding-similarity check against the agent's worldview.)
4. **Should pinned docs survive into the per-agent long-term memory** (`agent_context_memory`), or
   stay strictly conversation-scoped? Recommend conversation-scoped to limit retention surface.
