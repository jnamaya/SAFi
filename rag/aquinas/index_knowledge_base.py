import os
import faiss
import numpy as np
import pickle
import json
from typing import List

# --- ENVIRONMENT SETUP ---
# This section forces all libraries to use a controlled cache directory.
CACHE_DIR = "/var/www/safi/cache"
os.environ["SENTENCE_TRANSFORMERS_HOME"] = CACHE_DIR
os.environ["HF_HUB_CACHE"] = CACHE_DIR
# ----------------------------

from sentence_transformers import SentenceTransformer

# --- CONFIGURATION ---
VECTOR_STORE_PATH = "/var/www/safi/vector_store"
EMBEDDING_MODEL = 'all-MiniLM-L6-v2'

def build_index_from_sources(source_json_paths: List[str], output_index_name: str):
    """
    Reads one or more pre-processed JSON files, combines their chunks,
    creates vector embeddings, and saves them into a unified FAISS index.

    Args:
        source_json_paths: A list of file paths to the JSON chunk files.
        output_index_name: The base name for the output .index and .pkl files.
    """
    all_chunk_texts = []
    all_metadata = []

    # --- CHANGE 1: Loop through multiple source files ---
    for json_path in source_json_paths:
        if not os.path.exists(json_path):
            print(f"Warning: Source file not found at '{json_path}'. Skipping.")
            continue

        print(f"Loading pre-processed chunks from '{json_path}'...")
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            
        # Extract text chunks and metadata from the current file
        all_chunk_texts.extend([item['text_chunk'] for item in data])
        all_metadata.extend([item['metadata'] for item in data])

    if not all_chunk_texts:
        print("Error: No data loaded. No chunks to process. Exiting.")
        return

    print(f"\nLoaded a total of {len(all_chunk_texts)} text chunks from {len(source_json_paths)} source(s).")

    print(f"Loading embedding model '{EMBEDDING_MODEL}'...")
    model = SentenceTransformer(EMBEDDING_MODEL)

    print("Embedding all chunks... (This may take a while for large knowledge bases)")
    embeddings = model.encode(all_chunk_texts, show_progress_bar=True)
    embeddings = np.array(embeddings).astype('float32')

    print("Building unified FAISS index...")
    index = faiss.IndexFlatL2(embeddings.shape[1])
    index.add(embeddings)
    print(f"Index built successfully with {index.ntotal} vectors.")

    os.makedirs(VECTOR_STORE_PATH, exist_ok=True)
    
    # --- CHANGE 2: Save to a unified, named index ---
    index_path = os.path.join(VECTOR_STORE_PATH, f"{output_index_name}.index")
    metadata_path = os.path.join(VECTOR_STORE_PATH, f"{output_index_name}_metadata.pkl")

    faiss.write_index(index, index_path)
    print(f"Successfully saved FAISS index to '{index_path}'")
    
    with open(metadata_path, "wb") as f:
        pickle.dump(all_metadata, f)
    print(f"Successfully saved metadata to '{metadata_path}'")

if __name__ == "__main__":
    # --- DEFINE YOUR KNOWLEDGE BASE SOURCES HERE ---
    #
    # To start, we will just build the index for the Bible.
    # Later, you can add the paths to your processed Summa and Catechism files here.
    # For example:
    #
    # KNOWLEDGE_BASE_FILES = [
    #     'bible_chunks_for_rag.json',
    #     'summa_chunks_for_rag.json',
    #     'catechism_chunks_for_rag.json'
    # ]
    
    KNOWLEDGE_BASE_FILES = [
        'bible_chunks_for_rag.json'
    ]
    
    # Define the name for the persona's knowledge base
    OUTPUT_NAME = "aquinas_kb"

    build_index_from_sources(KNOWLEDGE_BASE_FILES, OUTPUT_NAME)
