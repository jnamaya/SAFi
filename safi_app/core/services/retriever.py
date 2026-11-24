import faiss
import json
import pickle
import os
import numpy as np
import re
import logging
import threading
from fastembed import TextEmbedding
from typing import List, Dict, Any, Optional

_APP_DIR = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), *([".."] * 3)))
VECTOR_STORE_PATH = os.environ.get("SAFI_VECTOR_STORE_PATH", os.path.join(_APP_DIR, "vector_store"))
CACHE_DIR = os.environ.get("SAFI_MODEL_CACHE_DIR", os.path.join(_APP_DIR, "cache"))
EMBEDDING_MODEL = os.environ.get("SAFI_EMBEDDING_MODEL", 'all-MiniLM-L6-v2')


def _hub_model_name(name: str) -> str:
    return name if "/" in name else f"sentence-transformers/{name}"

os.environ["NLTK_DATA"] = CACHE_DIR
os.environ["SENTENCE_TRANSFORMERS_HOME"] = CACHE_DIR
os.environ["HF_HUB_CACHE"] = CACHE_DIR
os.makedirs(CACHE_DIR, exist_ok=True)


_SHARED_MODEL = None
_MODEL_LOCK = threading.Lock()

def get_shared_embedding_model():
    global _SHARED_MODEL
    with _MODEL_LOCK:
        if _SHARED_MODEL is None:
            logging.info(f"Loading Global Embedding Model: {EMBEDDING_MODEL} (ONNX)")
            _SHARED_MODEL = TextEmbedding(
                model_name=_hub_model_name(EMBEDDING_MODEL), cache_dir=CACHE_DIR)
    return _SHARED_MODEL


DEFAULT_RAG_FORMAT_STRING = "SOURCE: {source}\nCONTENT:\n{text_chunk}\n---"


def resolve_rag_format_string(configured) -> str:
    if isinstance(configured, str) and configured.strip():
        return configured
    return DEFAULT_RAG_FORMAT_STRING


def embed_texts(model, texts: List[str]) -> np.ndarray:
    return np.array(list(model.embed(texts)), dtype="float32")


_SAFE_KB_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


class UnsafeKnowledgeBaseName(ValueError):
    pass


def _kb_index_path(knowledge_base_name: str) -> str:
    if not isinstance(knowledge_base_name, str) or not _SAFE_KB_NAME.match(knowledge_base_name):
        raise UnsafeKnowledgeBaseName(f"unsafe knowledge base name: {knowledge_base_name!r}")
    path = os.path.join(VECTOR_STORE_PATH, f"{knowledge_base_name}.index")
    store_root = os.path.realpath(VECTOR_STORE_PATH)
    if os.path.commonpath([os.path.realpath(os.path.dirname(path)), store_root]) != store_root:
        raise UnsafeKnowledgeBaseName(f"resolves outside the vector store: {knowledge_base_name!r}")
    return path


_RETRIEVER_CACHE: "OrderedDict[str, Any]" = None
_RETRIEVER_CACHE_LOCK = threading.Lock()
RETRIEVER_CACHE_SIZE = int(os.environ.get("SAFI_RETRIEVER_CACHE_SIZE", "8"))


def get_cached_retriever(knowledge_base_name: str):
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
    with _RETRIEVER_CACHE_LOCK:
        if _RETRIEVER_CACHE:
            _RETRIEVER_CACHE.pop(knowledge_base_name, None)


class Retriever:
    def __init__(self, knowledge_base_name: str):
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
                with open(metadata_path, "rb") as f:
                    metadata = pickle.load(f)

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

            self.model = get_shared_embedding_model()
            self.log.info(f"Retriever for '{knowledge_base_name}' attached to global model.")

        except Exception as e:
            self.log.exception(f"Error loading retriever for '{knowledge_base_name}': {e}")

    def _is_citation_query(self, query: str) -> bool:
        citation_regex = re.compile(r'(\d?\s?[A-Za-z]+)\s(\d+)')
        return citation_regex.search(query) is not None

    def _keyword_search(self, query: str, k: Optional[int] = None) -> List[int]:
        self.log.info(f"Performing keyword search for: {query}")
        citation_regex = re.compile(r'(\d?\s?[A-Za-z]+)\s(\d+)')
        matches = citation_regex.finditer(query)
        if not matches:
            return []

        all_indices = set()
        for match in matches:
            book = match.group(1).strip().lower()
            chapter = int(match.group(2).strip())
            verse_lo = verse_hi = None
            tail = query[match.end():]
            span = re.match(r'[\s:;]*([\d\s,;:–—\-]+)', tail)
            if span:
                numbers = [int(n) for n in re.findall(r'\d+', span.group(1))]
                if numbers:
                    verse_lo, verse_hi = min(numbers), max(numbers)

            candidate_indices = []
            for i, meta in enumerate(self.metadata):
                book_to_check = ''
                chapter_to_check = -1
                start_verse = end_verse = None

                if 'metadata' in meta and isinstance(meta.get('metadata'), dict):
                    book_to_check = meta['metadata'].get('book', '').lower()
                    chapter_to_check = meta['metadata'].get('chapter')
                    start_verse = meta['metadata'].get('start_verse')
                    end_verse = meta['metadata'].get('end_verse')
                else:
                    book_to_check = meta.get('book', '').lower()
                    chapter_to_check = meta.get('chapter')
                    start_verse = meta.get('start_verse')
                    end_verse = meta.get('end_verse')

                if book_to_check != book or chapter_to_check != chapter:
                    continue
                if verse_lo is not None and start_verse is not None and end_verse is not None:
                    if end_verse < verse_lo or start_verse > verse_hi:
                        continue
                candidate_indices.append(i)

            all_indices.update(candidate_indices)

        ordered = sorted(all_indices)
        return ordered if k is None else ordered[:k]

    def search(self, query: str, k: int = 5) -> List[Dict[str, Any]]:
        if not self.index or not self.model or not self.metadata:
            self.log.warning("Retriever.search() called but not initialized.")
            return []

        indices_to_return = []
        
        if self.kb_name.lower().startswith("bible") and self._is_citation_query(query):
            self.log.info("Bible citation detected, using keyword search.")
            indices_to_return = self._keyword_search(query)
        
        if not indices_to_return:
            self.log.info("Performing semantic vector search.")
            query_embedding = embed_texts(self.model, [query])
            distances, indices = self.index.search(query_embedding, k)
            indices_to_return = indices[0] 

        results: List[Dict[str, Any]] = []
        for idx in indices_to_return:
            if idx < 0 or idx >= len(self.metadata):
                continue 
            meta = self.metadata[idx]
            results.append(meta)
            
        return results