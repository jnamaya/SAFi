import faiss
import pickle
import os
import numpy as np
import re
from sentence_transformers import SentenceTransformer
from typing import List, Dict, Any

# --- CONFIGURATION (Assuming these paths are correct for your environment) ---
VECTOR_STORE_PATH = "./vector_store" # Using a local vector store
CACHE_DIR = "./cache" # Using a local cache dir for portability
EMBEDDING_MODEL = 'all-MiniLM-L6-v2'

os.environ["NLTK_DATA"] = CACHE_DIR
os.environ["SENTENCE_TRANSFORMERS_HOME"] = CACHE_DIR
os.environ["HF_HUB_CACHE"] = CACHE_DIR
os.makedirs(CACHE_DIR, exist_ok=True)
# ----------------------------->


class Retriever:
    """
    Handles loading a FAISS index and performing HYBRID searches.
    It uses a keyword search for citations and a vector search for semantic queries.
    Its search() method returns a list of metadata dictionaries, not a formatted string.
    """
    def __init__(self, knowledge_base_name: str):
        """
        Initializes the Retriever by loading the FAISS index and metadata
        for the specified knowledge base.
        
        Args:
            knowledge_base_name: The name of the knowledge base (e.g., "bible_bsb_v1").
        """
        self.kb_name = knowledge_base_name  # Store the knowledge base name
        self.model = None
        self.index = None
        self.metadata = []
        try:
            index_path = os.path.join(VECTOR_STORE_PATH, f"{knowledge_base_name}.index")
            metadata_path = os.path.join(VECTOR_STORE_PATH, f"{knowledge_base_name}_metadata.pkl")
            if not os.path.exists(index_path) or not os.path.exists(metadata_path):
                print(f"Warning: Index files not found for kb '{knowledge_base_name}'")
                return
            
            print(f"Loading index for: {knowledge_base_name}")
            self.index = faiss.read_index(index_path)
            
            with open(metadata_path, "rb") as f:
                self.metadata = pickle.load(f)
            
            print(f"Loading embedding model: {EMBEDDING_MODEL}")
            self.model = SentenceTransformer(EMBEDDING_MODEL, cache_folder=CACHE_DIR)
            print(f"Retriever for '{knowledge_base_name}' loaded successfully.")
            
        except Exception as e:
            print(f"Error loading retriever for '{knowledge_base_name}': {e}")

    def _is_citation_query(self, query: str) -> bool:
        """Checks if the query is a Bible citation (e.g., "John 3:16")."""
        # This regex looks for (Book Name) (Chapter Number)
        # It's simplified to allow for queries like "Genesis 1"
        citation_regex = re.compile(r'(\d?\s?[A-Za-z]+)\s(\d+)')
        return citation_regex.search(query) is not None

    def _keyword_search(self, query: str, k: int = 50) -> List[int]:
        """
        Performs a keyword search for Bible citations.
        Returns a list of indices from the metadata.
        
        *** This is the modified function. ***
        """
        print(f"Performing keyword search for: {query}")
        # Regex to find all "Book Chapter" matches
        citation_regex = re.compile(r'(\d?\s?[A-Za-z]+)\s(\d+)')
        matches = citation_regex.finditer(query)
        if not matches: 
            return []

        all_indices = set()
        for match in matches:
            book = match.group(1).strip().lower()
            chapter = int(match.group(2).strip())
            
            # --- MODIFIED LOGIC ---
            # This loop is now "bilingual" and can read BOTH metadata structures
            # to remain compatible with other personas (like SAFi).
            
            candidate_indices = []
            for i, meta in enumerate(self.metadata):
                book_to_check = ''
                chapter_to_check = -1 # Use an invalid chapter number

                if 'metadata' in meta and isinstance(meta.get('metadata'), dict):
                    # This is the NEW structure (e.g., bsb_chunks.json)
                    # We look *inside* the 'metadata' key.
                    book_to_check = meta['metadata'].get('book', '').lower()
                    chapter_to_check = meta['metadata'].get('chapter')
                else:
                    # This is the OLD structure (e.g., SAFi or old bible_asv)
                    # We look at the *top level* for the keys.
                    book_to_check = meta.get('book', '').lower()
                    chapter_to_check = meta.get('chapter')

                # Now, perform the check on the extracted values
                if book_to_check == book and chapter_to_check == chapter:
                    candidate_indices.append(i)
            # --- END OF MODIFIED LOGIC ---

            all_indices.update(candidate_indices)
        
        # Sort the indices to return the verses in the correct order.
        return sorted(list(all_indices))

    def search(self, query: str, k: int = 5) -> List[Dict[str, Any]]:
        """
        Performs a hybrid search.
        Returns a list of metadata dictionaries for the matching chunks.
        """
        if not self.index or not self.model or not self.metadata:
            print("Retriever not initialized.")
            return []

        indices_to_return = []
        
        # --- MODIFIED LOGIC ---
        # Changed from "== 'bible_asv'" to "startswith('bible')"
        # This now works for 'bible_asv', 'bible_bsb_v1', etc.
        # without affecting non-bible personas like 'SAFi_docs'.
        if self.kb_name.lower().startswith("bible") and self._is_citation_query(query):
            print("Bible citation detected, using keyword search.")
            # For chapter lookups, we might need many more than 5 chunks.
            indices_to_return = self._keyword_search(query, k=50) 
        
        if not indices_to_return:
            print("Performing semantic vector search.")
            query_embedding = self.model.encode([query]).astype('float32')
            
            # FAISS search returns (distances, indices)
            distances, indices = self.index.search(query_embedding, k)
            
            # We only care about the indices
            indices_to_return = indices[0]

        # Map indices back to their full metadata
        results: List[Dict[str, Any]] = []
        for idx in indices_to_return:
            if idx < 0 or idx >= len(self.metadata):
                continue # Skip invalid indices
            meta = self.metadata[idx]
            results.append(meta)
            
        return results

if __name__ == '__main__':
    # --- Example Usage ---
    # 1. First, make sure you have run the index builder:
    # python build_index_v2.py --name "bible_bsb_v1" --source_json "bsb_chunks.json"
    
    print("\n--- Initializing Retriever for 'bible_bsb_v1' ---")
    bible_retriever = Retriever(knowledge_base_name="bible_bsb_v1")

    if bible_retriever.index:
        # Example 1: Citation Search (triggers keyword search)
        print("\n--- Testing Citation Search (Genesis 1) ---")
        citation_query = "What happened in Genesis 1?"
        citation_results = bible_retriever.search(citation_query, k=5)
        for i, res in enumerate(citation_results):
            # Print the 'reference' field from our new metadata structure
            print(f"  Result {i+1}: {res.get('reference')}")
            # print(res) # Uncomment to see the full metadata object

        # Example 2: Semantic Search (triggers vector search)
        print("\n--- Testing Semantic Search (Creation) ---")
        semantic_query = "how was the world created?"
        semantic_results = bible_retriever.search(semantic_query, k=5)
        for i, res in enumerate(semantic_results):
            print(f"  Result {i+1}: {res.get('reference')}")
            # print(res) # Uncomment to see the full metadata object
    else:
        print("\nCould not load 'bible_bsb_v1' index.")
        print("Please run the build_index_v2.py script first.")
        
    # Example 3: Test a different (non-bible) persona to show it's unaffected
    print("\n--- Initializing Retriever for 'SAFi_docs_v1' (Example) ---")
    # This will likely fail as we haven't built this index,
    # but it demonstrates how the logic would be separate.
    safi_retriever = Retriever(knowledge_base_name="SAFi_docs_v1")
    if safi_retriever.index:
         # ...
         pass
    else:
        print("Could not load 'SAFi_docs_v1' index (as expected).")
