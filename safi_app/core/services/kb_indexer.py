"""Builds FAISS indexes for user-created knowledge bases.

THE ONE RULE THIS MODULE ENFORCES
---------------------------------
The input set is `db.list_indexable_documents(kb_id)` — the approved subset —
and nothing else. Approval that only hides a row in the UI is theatre: once
text is embedded it is already answering questions, and no amount of UI state
retracts a vector. Every path that changes what is approved (approve, reject,
delete, share, unshare) must therefore enqueue a rebuild, not just update a
flag. `enqueue_rebuild()` is that call.

WHY FULL REBUILDS
-----------------
`IndexFlatIP` cannot delete vectors. Rebuilding the whole KB on every change is
a few seconds of CPU for corpora this size and it makes "revoke this document"
actually mean something. Incremental `IndexIDMap` + `remove_ids` would be
faster and would make revocation a second code path that can be forgotten —
which is the failure this feature exists to avoid.

WHY NOT PICKLE
--------------
The legacy CLI (`rag/build_index_v2.py`) writes `<name>_metadata.pkl`. These
indexes carry user-uploaded content with a user-driven lifecycle, so their
metadata is written as JSON instead: `pickle.load` on a file whose write path
is reachable from an upload endpoint is a deserialization surface with no
upside. `Retriever` reads either, preferring JSON.
"""
from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import time
from typing import Any, Dict, List, Tuple

from .chunking import chunk_document
from .retriever import (VECTOR_STORE_PATH, embed_texts,
                        get_shared_embedding_model, invalidate_cached_retriever)

log = logging.getLogger(__name__)

# A KB id is a UUID we generated. Anything else never reaches the filesystem.
_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"
                      r"[0-9a-f]{4}-[0-9a-f]{12}$", re.I)

# Documents are indexed in full. This is NOT Config.MAX_DOCUMENT_CHARS (50k),
# which exists to bound a single prompt — reusing it here would silently index
# the first chapter of a long PDF and let the agent answer confidently from it.
MAX_INDEX_CHARS_PER_DOC = int(os.environ.get("SAFI_KB_MAX_DOC_CHARS", "5000000"))


class InvalidKnowledgeBaseId(ValueError):
    """The id is not a UUID we could have generated, so it does not get to
    name a file. This is the path-traversal guard: Retriever builds its path
    by f-string (`retriever.py`), so a `../../` id would otherwise read and
    write outside the vector store."""


def kb_paths(kb_id: str) -> Tuple[str, str]:
    """(index_path, metadata_path) for a KB. Raises InvalidKnowledgeBaseId
    rather than sanitising: an allow-list of characters is a thing to get
    wrong once; a UUID check is a thing that cannot be."""
    if not isinstance(kb_id, str) or not _UUID_RE.match(kb_id):
        raise InvalidKnowledgeBaseId(f"not a knowledge base id: {kb_id!r}")
    return (os.path.join(VECTOR_STORE_PATH, f"{kb_id}.index"),
            os.path.join(VECTOR_STORE_PATH, f"{kb_id}_metadata.json"))


def enqueue_rebuild(kb_id: str) -> None:
    """Marks the KB as needing a rebuild. The indexer service picks it up.

    Call this from EVERY path that changes the approved set. Deliberately does
    not build inline: embedding a large corpus takes tens of seconds and
    gunicorn runs --timeout 120 (see item 14 — the model download that used to
    happen inside a request, under a lock, with nothing in the logs)."""
    from ...persistence import database as db
    db.set_knowledge_base_status(kb_id, 'pending', 'Queued for indexing')


def delete_kb_artifacts(kb_id: str) -> None:
    """Removes a KB's on-disk index. Safe to call when the files are absent."""
    try:
        index_path, meta_path = kb_paths(kb_id)
    except InvalidKnowledgeBaseId:
        return
    for path in (index_path, meta_path):
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
        except OSError as e:
            log.warning("Could not remove %s: %s", path, e)
    invalidate_cached_retriever(kb_id)


def _atomic_write(path: str, write_fn) -> None:
    """Writes via a temp file in the same directory + os.replace, so a reader
    never sees a half-written index."""
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=directory, suffix=".tmp")
    os.close(fd)
    try:
        write_fn(tmp)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def build_kb_index(kb_id: str) -> Dict[str, Any]:
    """Rebuilds one KB from its approved documents. Synchronous; the indexer
    service and the tests both call this. Returns a summary dict.

    Sets status to 'empty' (and deletes the artifacts) when nothing is
    indexable — a KB whose documents are all pending must not keep serving the
    vectors from when they were approved.
    """
    from ...persistence import database as db
    import faiss
    import numpy as np

    index_path, meta_path = kb_paths(kb_id)
    kb = db.get_knowledge_base(kb_id)
    if not kb:
        raise ValueError(f"knowledge base not found: {kb_id}")

    db.set_knowledge_base_status(kb_id, 'indexing', 'Building index')
    try:
        documents = db.list_indexable_documents(kb_id)

        texts: List[str] = []
        metadata: List[Dict[str, Any]] = []
        for doc in documents:
            body = (doc.get("text") or "")[:MAX_INDEX_CHARS_PER_DOC]
            for i, chunk in enumerate(chunk_document(body, doc.get("filename", ""))):
                texts.append(chunk)
                metadata.append({
                    # `source` is what rag_format_string interpolates for
                    # citations, so it must be the human filename, not the id.
                    "source": doc.get("filename") or "document",
                    "chunk_id": f"{doc['id']}-chunk-{i}",
                    "document_id": doc["id"],
                    "text_chunk": chunk,
                })

        if not texts:
            delete_kb_artifacts(kb_id)
            db.set_knowledge_base_status(
                kb_id, 'empty', 'No approved documents to index', chunk_count=0)
            return {"kb_id": kb_id, "chunks": 0, "documents": 0, "status": "empty"}

        model = get_shared_embedding_model()
        embeddings = embed_texts(model, texts)
        index = faiss.IndexFlatIP(embeddings.shape[1])
        index.add(embeddings)

        _atomic_write(index_path, lambda p: faiss.write_index(index, p))
        _atomic_write(meta_path, lambda p: _write_json(p, metadata))
        invalidate_cached_retriever(kb_id)

        db.set_knowledge_base_status(kb_id, 'ready', None,
                                     chunk_count=len(texts), mark_indexed=True)
        log.info("Indexed KB %s: %d chunks from %d documents",
                 kb_id, len(texts), len(documents))
        return {"kb_id": kb_id, "chunks": len(texts),
                "documents": len(documents), "status": "ready"}

    except Exception as e:
        log.exception("Indexing failed for KB %s", kb_id)
        # Leave the previous index in place. A failed rebuild must not silently
        # de-ground an agent that was working a minute ago; the status says so.
        db.set_knowledge_base_status(kb_id, 'failed', str(e)[:500])
        raise


def _write_json(path: str, payload: Any) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)


def run_indexer_loop(poll_seconds: int = 5) -> None:
    """The SERVICE=indexer entrypoint. Claims one pending KB at a time.

    Single-container by design, but the claim is still a conditional UPDATE so
    that running two indexers duplicates work rather than corrupting an index.
    """
    from ...persistence import database as db
    log.info("KB indexer started (poll=%ss, store=%s)", poll_seconds, VECTOR_STORE_PATH)
    # Pay for the embedding model once, at boot, not inside the first job.
    try:
        get_shared_embedding_model()
    except Exception:
        log.exception("Embedding model warm-up failed; will retry per job")

    while True:
        try:
            kb_id = db.claim_pending_knowledge_base()
            if not kb_id:
                time.sleep(poll_seconds)
                continue
            build_kb_index(kb_id)
        except Exception:
            # Never let one bad KB kill the loop — its status is already
            # 'failed' and the next poll moves on.
            log.exception("Indexer iteration failed")
            time.sleep(poll_seconds)
