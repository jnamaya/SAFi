import faiss
import pickle
import os
import numpy as np
from sentence_transformers import SentenceTransformer

# --- CONFIGURATION ---
# These constants should match the ones used in your index.py script.
VECTOR_STORE_PATH = "/var/www/safi/vector_store"
EMBEDDING_MODEL = 'all-MiniLM-L6-v2'

class Retriever:
    """
    Handles loading the FAISS index and performing vector searches.
    This component finds the most relevant document chunks for a given query.
    """
    def __init__(self):
        """
        Initializes the Retriever by loading the embedding model,
        the FAISS index, and the document chunks from disk.
        """
        print("Loading retriever resources...")
        try:
            # Load the same sentence transformer model used for indexing.
            self.model = SentenceTransformer(EMBEDDING_MODEL)
            
            # Load the FAISS index from the vector_store directory.
            index_path = os.path.join(VECTOR_STORE_PATH, "safi.index")
            self.index = faiss.read_index(index_path)
            
            # Load the corresponding text chunks.
            chunks_path = os.path.join(VECTOR_STORE_PATH, "chunks.pkl")
            with open(chunks_path, "rb") as f:
                self.chunks = pickle.load(f)
                
            print(f"Retriever loaded successfully. Index contains {self.index.ntotal} vectors.")
        
        except FileNotFoundError as e:
            print(f"Error loading retriever: {e}")
            print("Please make sure you have run the index.py script successfully and that the 'vector_store' directory is in the correct location.")
            # Set to None to prevent errors if the index is missing.
            self.model = None
            self.index = None
            self.chunks = None

    def search(self, query: str, k: int = 3) -> str:
        """
        Finds the top 'k' most relevant document chunks for a given query.
        
        Args:
            query: The user's question or prompt.
            k: The number of relevant chunks to retrieve.
            
        Returns:
            A single string containing the concatenated relevant chunks,
            or an empty string if the retriever is not properly initialized.
        """
        # If the index failed to load, return an empty context.
        if not self.index or not self.model:
            return ""
            
        # 1. Encode the user's query into a vector.
        query_embedding = self.model.encode([query]).astype('float32')
        
        # 2. Search the FAISS index for the 'k' nearest neighbors.
        distances, indices = self.index.search(query_embedding, k)
        
        # 3. Retrieve the actual text chunks using the indices.
        results = [self.chunks[i] for i in indices[0]]
        
        # 4. Join the chunks into a single string to be used as context.
        return "\n\n---\n\n".join(results)
