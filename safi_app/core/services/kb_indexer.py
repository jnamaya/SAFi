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

_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"
                      r"[0-9a-f]{4}-[0-9a-f]{12}$", re.I)

MAX_INDEX_CHARS_PER_DOC = int(os.environ.get("SAFI_KB_MAX_DOC_CHARS", "5000000"))


class InvalidKnowledgeBaseId(ValueError):
    pass


def kb_paths(kb_id: str) -> Tuple[str, str]:
    if not isinstance(kb_id, str) or not _UUID_RE.match(kb_id):
        raise InvalidKnowledgeBaseId(f"not a knowledge base id: {kb_id!r}")
    return (os.path.join(VECTOR_STORE_PATH, f"{kb_id}.index"),
            os.path.join(VECTOR_STORE_PATH, f"{kb_id}_metadata.json"))


def enqueue_rebuild(kb_id: str) -> None:
    from ...persistence import database as db
    db.set_knowledge_base_status(kb_id, 'pending', 'Queued for indexing')


def delete_kb_artifacts(kb_id: str) -> None:
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
        db.set_knowledge_base_status(kb_id, 'failed', str(e)[:500])
        raise


def _write_json(path: str, payload: Any) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)


def run_indexer_loop(poll_seconds: int = 5) -> None:
    from ...persistence import database as db
    log.info("KB indexer started (poll=%ss, store=%s)", poll_seconds, VECTOR_STORE_PATH)
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
            log.exception("Indexer iteration failed")
            time.sleep(poll_seconds)
