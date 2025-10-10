import faiss
import pickle
import os
import numpy as np
import re
from sentence_transformers import SentenceTransformer

# --- CONFIGURATION ---
VECTOR_STORE_PATH = "/var/www/safi/vector_store"
EMBEDDING_MODEL = 'all-MiniLM-L6-v2'

class Retriever:
    """
    Handles loading a FAISS index and performing HYBRID searches.
    It uses a keyword search for citations and a vector search for semantic queries.
    """
    def __init__(self, knowledge_base_name: str):
        print(f"\n--- INITIALIZING RETRIEVER FOR KB: '{knowledge_base_name}' ---")
        self.model = None
        self.index = None
        self.metadata = []
        try:
            index_path = os.path.join(VECTOR_STORE_PATH, f"{knowledge_base_name}.index")
            metadata_path = os.path.join(VECTOR_STORE_PATH, f"{knowledge_base_name}_metadata.pkl")
            if not os.path.exists(index_path) or not os.path.exists(metadata_path):
                print(f"--- FATAL ERROR: Index or metadata file not found. ---")
                return
            self.index = faiss.read_index(index_path)
            with open(metadata_path, "rb") as f:
                self.metadata = pickle.load(f)
            self.model = SentenceTransformer(EMBEDDING_MODEL)
            print(f"--- Retriever initialized successfully. Found {len(self.metadata)} documents. ---")
        except Exception as e:
            print(f"--- FATAL ERROR during retriever initialization: {e} ---")

    def _is_citation_query(self, query: str):
        """
        Checks if a query looks like a Bible citation.
        Handles both direct "Genesis 1:1" and natural language "text of Genesis chapter 1".
        """
        # This new, more robust regex looks for both patterns.
        pattern = re.compile(r'\b(\d?\s*[A-Za-z]+)\s+(?:chapter\s+)?(\d+)(?::(\d+))?\b', re.IGNORECASE)
        return pattern.search(query)

    def _keyword_search(self, query: str, k: int = 20): # Increased k to get whole chapters
        """Performs a direct keyword search on the metadata for citations."""
        print(f"--- Performing KEYWORD search for citation: '{query}' ---")
        
        matches = list(re.finditer(r'\b(\d?\s*[A-Za-z]+)\s+(?:chapter\s+)?(\d+)\b', query, re.IGNORECASE))
        if not matches: return []

        all_indices = set()
        for match in matches:
            book = match.group(1).strip().lower()
            chapter = int(match.group(2).strip())
            
            print(f"Found citation in prompt: Book='{book}', Chapter='{chapter}'")

            candidate_indices = [
                i for i, meta in enumerate(self.metadata)
                if meta.get('book', '').lower() == book and meta.get('chapter') == chapter
            ]
            all_indices.update(candidate_indices)
        
        # Sort the indices to return the verses in the correct order.
        return sorted(list(all_indices))

    def search(self, query: str, k: int = 5) -> str:
        if not self.index or not self.model or not self.metadata:
            return ""

        indices_to_return = []
        if self._is_citation_query(query):
            # For chapter lookups, we might need many more than 5 chunks.
            indices_to_return = self._keyword_search(query, k=50) 
        
        if not indices_to_return:
            print(f"\n--- Performing VECTOR search for query: '{query[:80]}...' ---")
            query_embedding = self.model.encode([query]).astype('float32')
            distances, indices = self.index.search(query_embedding, k)
            indices_to_return = indices[0]
            print(f"Top vector search hit (distance: {distances[0][0]}): {self.metadata[indices_to_return[0]] if indices_to_return.size > 0 else 'None'}")

        results = []
        for i in indices_to_return:
            if 0 <= i < len(self.metadata):
                meta = self.metadata[i]
                text_chunk = meta.get('text_chunk', '')
                results.append(f"REFERENCE: {meta.get('book')} {meta.get('chapter')}:{meta.get('start_verse')}-{meta.get('end_verse')}\nCONTENT:\n{text_chunk}\n---")
        
        return "\n".join(results)