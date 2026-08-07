"""
Handles loading a FAISS index and performing hybrid searches.

This module provides the Retriever class, which encapsulates all logic for 
interfacing with a FAISS vector store and associated metadata. It supports
hybrid search, automatically using a keyword-based method for citation 
queries (e.g., "John 3:16") and a semantic vector search for all other queries.
"""
import faiss
import json
import pickle
import os
import numpy as np
import re
import logging
import threading
from fastembed import TextEmbedding
from typing import List, Dict, Any

# --- CONFIGURATION ---
# FIX: Use environment variables to allow production config overrides.
# Default to relative paths for dev, but allow absolute paths for prod.
VECTOR_STORE_PATH = os.environ.get("SAFI_VECTOR_STORE_PATH", "./vector_store")
CACHE_DIR = os.environ.get("SAFI_MODEL_CACHE_DIR", "./cache")
EMBEDDING_MODEL = os.environ.get("SAFI_EMBEDDING_MODEL", 'all-MiniLM-L6-v2')


def _hub_model_name(name: str) -> str:
    """fastembed wants the fully-qualified hub id; sentence-transformers
    accepted the bare one. Accept either so an existing SAFI_EMBEDDING_MODEL
    keeps working after the ONNX swap."""
    return name if "/" in name else f"sentence-transformers/{name}"

# Set environment variables for model caching
os.environ["NLTK_DATA"] = CACHE_DIR
os.environ["SENTENCE_TRANSFORMERS_HOME"] = CACHE_DIR
os.environ["HF_HUB_CACHE"] = CACHE_DIR
os.makedirs(CACHE_DIR, exist_ok=True)
# --------------------->

# --- GLOBAL SINGLETON FOR EMBEDDING MODEL ---
# Optimization: Load the model once, share across all user sessions.
_SHARED_MODEL = None
_MODEL_LOCK = threading.Lock()

def get_shared_embedding_model():
    """Returns the global singleton instance of the embedding model."""
    global _SHARED_MODEL
    with _MODEL_LOCK:
        if _SHARED_MODEL is None:
            logging.info(f"Loading Global Embedding Model: {EMBEDDING_MODEL} (ONNX)")
            _SHARED_MODEL = TextEmbedding(
                model_name=_hub_model_name(EMBEDDING_MODEL), cache_dir=CACHE_DIR)
    return _SHARED_MODEL


# --- DEFAULT CHUNK RENDERING ---------------------------------------------
# How a retrieved metadata dict becomes prompt text when the agent defines no
# rag_format_string of its own. Lives here because this module owns the shape
# of those dicts ("source", "text_chunk", …), so the default rendering of them
# belongs with the contract that produces them.
#
# Every built-in agent sets its own template, so this default is what custom
# (wizard-built) agents get — and it names the source file, because an agent
# grounded in uploaded documents that cannot say WHICH document it used is a
# citation promise the UI makes and the prompt cannot keep. Callers already
# fall back to bare text_chunk on KeyError, so a corpus without "source"
# degrades rather than breaking.
DEFAULT_RAG_FORMAT_STRING = "SOURCE: {source}\nCONTENT:\n{text_chunk}\n---"


def resolve_rag_format_string(configured) -> str:
    """The template to render retrieved chunks with.

    Treats empty and whitespace-only as "not configured", which a plain
    `profile.get(key, default)` does NOT: the agent wizard stores
    `rag_format_string: ""` for every custom agent, so the dict HAS the key and
    the default never applied. The visible symptom was retrieval working
    perfectly and then formatting every chunk to an empty string — five chunks
    found, five empty strings injected, and an agent that behaved as though its
    knowledge base were empty.
    """
    if isinstance(configured, str) and configured.strip():
        return configured          # returned unstripped: trailing "\n---" matters
    return DEFAULT_RAG_FORMAT_STRING


def embed_texts(model, texts: List[str]) -> np.ndarray:
    """fastembed returns a generator of vectors; FAISS needs a float32 matrix.

    Vectors are unit-normalised by the model, exactly as sentence-transformers'
    all-MiniLM-L6-v2 was — verified identical to 5 decimal places — so indexes
    built before the ONNX swap remain valid and IndexFlatIP is still cosine.
    """
    return np.array(list(model.embed(texts)), dtype="float32")


# --- PATH SAFETY ---------------------------------------------------------
# A knowledge base name reaches this module from agents.rag_knowledge_base,
# which since 2026-08-07 can be a user-created KB. The name is interpolated
# straight into a filename, so without this check a name of "../../etc/passwd"
# would read outside the vector store. Built-in corpora ("safi",
# "bible_bsb_v1", "sop_index") are plain identifiers and pass unchanged;
# user KBs are UUIDs and also pass. Everything else is refused.
_SAFE_KB_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


class UnsafeKnowledgeBaseName(ValueError):
    """The KB name could escape VECTOR_STORE_PATH. Refused rather than
    stripped: a sanitiser silently maps two distinct names onto one file,
    which is its own class of bug."""


def _kb_index_path(knowledge_base_name: str) -> str:
    """Resolves a KB name to its index path, refusing anything that is not a
    plain filename component. The realpath check is belt-and-braces against a
    name that passes the regex but resolves outside the store via a symlink."""
    if not isinstance(knowledge_base_name, str) or not _SAFE_KB_NAME.match(knowledge_base_name):
        raise UnsafeKnowledgeBaseName(f"unsafe knowledge base name: {knowledge_base_name!r}")
    path = os.path.join(VECTOR_STORE_PATH, f"{knowledge_base_name}.index")
    store_root = os.path.realpath(VECTOR_STORE_PATH)
    if os.path.commonpath([os.path.realpath(os.path.dirname(path)), store_root]) != store_root:
        raise UnsafeKnowledgeBaseName(f"resolves outside the vector store: {knowledge_base_name!r}")
    return path


# --- RETRIEVER CACHE -----------------------------------------------------
# Retriever was constructed per turn (orchestrator.py builds a RAGService each
# time), which meant a FAISS read plus a metadata load on every request. That
# was tolerable with three built-in indexes and is not once every user can
# create their own. Cached per KB name, invalidated by index mtime so a
# rebuild is picked up without a restart, and bounded so a few hundred KBs
# cannot pin every index in memory in all four gunicorn workers.
_RETRIEVER_CACHE: "OrderedDict[str, Any]" = None  # type: ignore[assignment]
_RETRIEVER_CACHE_LOCK = threading.Lock()
RETRIEVER_CACHE_SIZE = int(os.environ.get("SAFI_RETRIEVER_CACHE_SIZE", "8"))


def get_cached_retriever(knowledge_base_name: str):
    """Returns a shared Retriever, rebuilding it when the index file changed.

    Retriever.search() is read-only over faiss + a list, so sharing one
    instance across threads is safe; faiss releases the GIL during search.
    """
    global _RETRIEVER_CACHE
    from collections import OrderedDict
    with _RETRIEVER_CACHE_LOCK:
        if _RETRIEVER_CACHE is None:
            _RETRIEVER_CACHE = OrderedDict()

        try:
            mtime = os.path.getmtime(_kb_index_path(knowledge_base_name))
        except (OSError, UnsafeKnowledgeBaseName):
            mtime = None

        cached = _RETRIEVER_CACHE.get(knowledge_base_name)
        if cached is not None and cached.index_mtime == mtime:
            _RETRIEVER_CACHE.move_to_end(knowledge_base_name)
            return cached

        retriever = Retriever(knowledge_base_name=knowledge_base_name)
        _RETRIEVER_CACHE[knowledge_base_name] = retriever
        _RETRIEVER_CACHE.move_to_end(knowledge_base_name)
        while len(_RETRIEVER_CACHE) > RETRIEVER_CACHE_SIZE:
            _RETRIEVER_CACHE.popitem(last=False)
        return retriever


def invalidate_cached_retriever(knowledge_base_name: str) -> None:
    """Drops a KB from this process's cache. Only helps the process that
    rebuilt the index — the indexer runs in its own container — which is why
    the mtime check above, not this call, is what actually keeps the gunicorn
    workers current. Kept because tests and any in-process build need it."""
    with _RETRIEVER_CACHE_LOCK:
        if _RETRIEVER_CACHE:
            _RETRIEVER_CACHE.pop(knowledge_base_name, None)


class Retriever:
    """
    Manages a FAISS index and metadata for hybrid (keyword + semantic) search.
    
    The search() method is the primary interface, returning a list of 
    metadata dictionaries for matching document chunks.
    """
    def __init__(self, knowledge_base_name: str):
        """
        Initializes the Retriever by loading the FAISS index and metadata
        for the specified knowledge base.

        Args:
            knowledge_base_name: The name of the knowledge base (e.g., "bible_bsb_v1").
                                 This name is used to find the .index and _metadata.pkl files.
        """
        self.kb_name = knowledge_base_name
        self.model = None
        self.index = None
        self.metadata = []
        self.index_mtime = None
        self.log = logging.getLogger(self.__class__.__name__)

        try:
            index_path = _kb_index_path(knowledge_base_name)
            json_meta_path = os.path.join(VECTOR_STORE_PATH, f"{knowledge_base_name}_metadata.json")
            pkl_meta_path = os.path.join(VECTOR_STORE_PATH, f"{knowledge_base_name}_metadata.pkl")

            # JSON first: user-created KBs (kb_indexer) write JSON precisely so
            # that a file whose write path is reachable from an upload endpoint
            # is never fed to pickle.load. The built-in indexes shipped by
            # rag/build_index_v2.py are still .pkl, hence the fallback.
            metadata_path = json_meta_path if os.path.exists(json_meta_path) else pkl_meta_path

            if not os.path.exists(index_path) or not os.path.exists(metadata_path):
                self.log.warning(f"Index files not found for kb '{knowledge_base_name}' at {VECTOR_STORE_PATH}. Retriever will be disabled.")
                return

            self.log.info(f"Loading index for: {knowledge_base_name}")
            index = faiss.read_index(index_path)

            if metadata_path.endswith(".json"):
                with open(metadata_path, "r", encoding="utf-8") as f:
                    metadata = json.load(f)
            else:
                # Legacy path, built-in corpora only. pickle.load is unsafe on
                # attacker-controlled files; these are produced offline by the
                # CLI builder and shipped with the image.
                with open(metadata_path, "rb") as f:
                    metadata = pickle.load(f)

            # The index and its metadata are two files, so a rebuild cannot
            # swap them in one atomic step. A mismatch means we caught the
            # rename window — refuse rather than serve chunk texts that belong
            # to different vectors, which would be silent mis-citation. The
            # next turn re-reads and finds a consistent pair.
            if index.ntotal != len(metadata):
                self.log.warning(
                    f"Index/metadata mismatch for '{knowledge_base_name}' "
                    f"({index.ntotal} vectors vs {len(metadata)} records) — "
                    "likely mid-rebuild; retrieval disabled for this load.")
                return

            self.index = index
            self.metadata = metadata
            try:
                self.index_mtime = os.path.getmtime(index_path)
            except OSError:
                self.index_mtime = None

            # OPTIMIZATION: Use the global singleton model
            self.model = get_shared_embedding_model()
            self.log.info(f"Retriever for '{knowledge_base_name}' attached to global model.")

        except Exception as e:
            self.log.exception(f"Error loading retriever for '{knowledge_base_name}': {e}")

    def _is_citation_query(self, query: str) -> bool:
        """
        Checks if the query likely contains a Bible citation (e.g., "John 3:16").
        """
        citation_regex = re.compile(r'(\d?\s?[A-Za-z]+)\s(\d+)')
        return citation_regex.search(query) is not None

    def _keyword_search(self, query: str, k: int = 50) -> List[int]:
        """
        Performs a keyword-based search for Bible citations.
        """
        self.log.info(f"Performing keyword search for: {query}")
        citation_regex = re.compile(r'(\d?\s?[A-Za-z]+)\s(\d+)')
        matches = citation_regex.finditer(query)
        if not matches: 
            return []

        all_indices = set()
        for match in matches:
            book = match.group(1).strip().lower()
            chapter = int(match.group(2).strip())
            
            candidate_indices = []
            for i, meta in enumerate(self.metadata):
                book_to_check = ''
                chapter_to_check = -1 

                if 'metadata' in meta and isinstance(meta.get('metadata'), dict):
                    # NEW structure (e.g., bsb_chunks.json)
                    book_to_check = meta['metadata'].get('book', '').lower()
                    chapter_to_check = meta['metadata'].get('chapter')
                else:
                    # OLD structure (e.g., SAFi or old bible_asv)
                    book_to_check = meta.get('book', '').lower()
                    chapter_to_check = meta.get('chapter')

                if book_to_check == book and chapter_to_check == chapter:
                    candidate_indices.append(i)

            all_indices.update(candidate_indices)

        # Honour k. It was accepted and ignored, so a citation returned the WHOLE
        # chapter however long: "Psalm 119" came back as 59 chunks / ~20k chars,
        # and that context is paid for twice per turn (Intellect drafts with it,
        # then Conscience audits with it). Indices are sorted, so slicing keeps
        # the opening of the passage rather than an arbitrary subset.
        #
        # This is a backstop, not the real bound — the character budget in
        # intellect.py is what usually trims, and unlike this slice it tells the
        # model the passage was cut.
        return sorted(list(all_indices))[:k]

    def search(self, query: str, k: int = 5) -> List[Dict[str, Any]]:
        """
        Performs a hybrid search.
        """
        if not self.index or not self.model or not self.metadata:
            self.log.warning("Retriever.search() called but not initialized.")
            return []

        indices_to_return = []
        
        # --- Hybrid Search Logic ---
        # If it's a bible and a citation, use the keyword search
        if self.kb_name.lower().startswith("bible") and self._is_citation_query(query):
            self.log.info("Bible citation detected, using keyword search.")
            indices_to_return = self._keyword_search(query, k=50) 
        
        # If no citation results, or if it wasn't a citation query, perform semantic search
        if not indices_to_return:
            self.log.info("Performing semantic vector search.")
            query_embedding = embed_texts(self.model, [query])
            distances, indices = self.index.search(query_embedding, k)
            indices_to_return = indices[0] 

        # --- Map indices back to their full metadata ---
        results: List[Dict[str, Any]] = []
        for idx in indices_to_return:
            if idx < 0 or idx >= len(self.metadata):
                continue 
            meta = self.metadata[idx]
            results.append(meta)
            
        return results