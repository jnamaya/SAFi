"""
Handles loading a FAISS index and performing hybrid searches.

This module provides the Retriever class, which encapsulates all logic for 
interfacing with a FAISS vector store and associated metadata. It supports
hybrid search, automatically using a keyword-based method for citation 
queries (e.g., "John 3:16") and a semantic vector search for all other queries.
"""
import faiss
import pickle
import os
import numpy as np
import re
import logging
from sentence_transformers import SentenceTransformer
from typing import List, Dict, Any

# --- CONFIGURATION ---
# FIX: Use environment variables to allow production config overrides.
# Default to relative paths for dev, but allow absolute paths for prod.
VECTOR_STORE_PATH = os.environ.get("SAFI_VECTOR_STORE_PATH", "./vector_store")
CACHE_DIR = os.environ.get("SAFI_MODEL_CACHE_DIR", "./cache")
EMBEDDING_MODEL = os.environ.get("SAFI_EMBEDDING_MODEL", 'all-MiniLM-L6-v2')

# Set environment variables for model caching
os.environ["NLTK_DATA"] = CACHE_DIR
os.environ["SENTENCE_TRANSFORMERS_HOME"] = CACHE_DIR
os.environ["HF_HUB_CACHE"] = CACHE_DIR
os.makedirs(CACHE_DIR, exist_ok=True)
# --------------------->


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
        self.log = logging.getLogger(self.__class__.__name__)
        
        try:
            index_path = os.path.join(VECTOR_STORE_PATH, f"{knowledge_base_name}.index")
            metadata_path = os.path.join(VECTOR_STORE_PATH, f"{knowledge_base_name}_metadata.pkl")
            
            if not os.path.exists(index_path) or not os.path.exists(metadata_path):
                self.log.warning(f"Index files not found for kb '{knowledge_base_name}' at {VECTOR_STORE_PATH}. Retriever will be disabled.")
                return
            
            self.log.info(f"Loading index for: {knowledge_base_name}")
            self.index = faiss.read_index(index_path)
            
            # SECURITY WARNING: pickle.load is vulnerable to arbitrary code execution if 
            # the metadata file is compromised. In a high-security environment, 
            # consider migrating metadata to JSON or SQLite.
            with open(metadata_path, "rb") as f:
                self.metadata = pickle.load(f)
            
            self.log.info(f"Loading embedding model: {EMBEDDING_MODEL}")
            self.model = SentenceTransformer(EMBEDDING_MODEL, cache_folder=CACHE_DIR)
            self.log.info(f"Retriever for '{knowledge_base_name}' loaded successfully.")
            
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
        
        return sorted(list(all_indices))

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
            query_embedding = self.model.encode([query]).astype('float32')
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