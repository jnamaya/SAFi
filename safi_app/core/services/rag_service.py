"""Retriever facade: the only place that knows how to obtain a Retriever, run a
search, and render the raw metadata dicts into one context string for the
Intellect. Everything else in the request path sees only this."""
from __future__ import annotations
import logging
from typing import List, Dict, Any

try:
    from .retriever import Retriever, get_cached_retriever
except (ImportError, ValueError) as e:
    logging.critical(f"Failed to import Retriever: {e}. Ensure safi_app/core/services/retriever.py exists.")
    # Stand-in so the app still loads with RAG disabled.
    class Retriever:
        def __init__(self, *args, **kwargs):
            logging.error("Using Mock Retriever class. Import failed.")
        def search(self, *args, **kwargs) -> List[Dict[str, Any]]:
            return []

    def get_cached_retriever(knowledge_base_name):
        return Retriever()


class RAGService:
    def __init__(self, knowledge_base_name: str | None):
        self.log = logging.getLogger(self.__class__.__name__)
        if knowledge_base_name:
            try:
                # Shared, mtime-invalidated instance: this constructor runs on
                # every turn (orchestrator builds a RAGService per request), so
                # loading FAISS + metadata here would be per-request I/O.
                self.retriever = get_cached_retriever(knowledge_base_name)
                self.enabled = True if self.retriever.index else False
                if not self.enabled:
                    self.log.warning(f"RAGService enabled, but Retriever failed to load index for {knowledge_base_name}.")
            except Exception as e:
                self.log.error(f"Failed to initialize Retriever for {knowledge_base_name}: {e}")
                self.retriever = None
                self.enabled = False
        else:
            self.retriever = None
            self.enabled = False
            self.log.info("RAGService disabled (no knowledge_base_name provided).")

    async def get_context(self, query: str, format_string: str) -> str:
        """Format retrieved metadata dicts into one context string.

        `format_string` is applied per chunk with `**doc` as the namespace
        (e.g. "{source}: {text_chunk}"). Returns "" when RAG is disabled and
        "[NO DOCUMENTS FOUND]" when the search returned nothing — the two are
        different signals to the caller and must not be collapsed.
        """
        if not self.enabled or not self.retriever:
            return ""

        # An empty/whitespace template renders every chunk as "" — retrieval
        # succeeds and the caller receives nothing. Same trap intellect.py hit
        # via profile.get("rag_format_string", default) when the stored value
        # was "" rather than absent.
        from .retriever import resolve_rag_format_string
        format_string = resolve_rag_format_string(format_string)

        try:
            # search() is synchronous and FAISS releases the GIL; if it ever
            # becomes a bottleneck it must move to a thread, not a queue.
            retrieved_docs = self.retriever.search(query)
            
            if not retrieved_docs:
                return "[NO DOCUMENTS FOUND]"

            formatted_chunks = []
            for doc in retrieved_docs:
                try:
                    formatted_chunks.append(format_string.format(**doc))
                except KeyError as e:
                    self.log.warning(f"RAG format string failed for key {e}. Falling back to 'text_chunk'.")
                    if "text_chunk" in doc:
                        formatted_chunks.append(doc["text_chunk"])

            return "\n\n".join(formatted_chunks)

        except Exception as e:
            self.log.exception(f"Error during RAG search for query: {query}")
            return f"[RAG ERROR: {e}]"