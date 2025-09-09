import os
import faiss
import numpy as np
import pickle

# --- ENVIRONMENT SETUP ---
# This section forces all libraries to use a controlled cache directory.
CACHE_DIR = "/var/www/safi/cache"
os.environ["NLTK_DATA"] = CACHE_DIR
os.environ["SENTENCE_TRANSFORMERS_HOME"] = CACHE_DIR
os.environ["HF_HUB_CACHE"] = CACHE_DIR
# -----------------------------

from sentence_transformers import SentenceTransformer
from unstructured.partition.auto import partition
from unstructured.chunking.title import chunk_by_title

# --- CONFIGURATION ---
DOCUMENTS_PATH = "/var/www/safi/rag/docs"

# --- CRITICAL FIX ---
# The VECTOR_STORE_PATH has been changed to an ABSOLUTE path.
# This ensures the index is always saved to the main project root,
# where the live application expects to find it. This eliminates
# the need to manually move the directory after building.
VECTOR_STORE_PATH = "/var/www/safi/vector_store"
# --------------------

EMBEDDING_MODEL = 'all-MiniLM-L6-v2'


def build_index():
    """
    Reads documents, chunks them, creates vector embeddings, and saves them
    into a FAISS index for fast retrieval.
    """
    if not os.path.exists(DOCUMENTS_PATH) or not os.listdir(DOCUMENTS_PATH):
        print(f"Error: The directory '{DOCUMENTS_PATH}' is empty or does not exist.")
        print("Please place your knowledge base files in this directory.")
        return

    print("Loading documents...")
    raw_elements = []
    for filename in os.listdir(DOCUMENTS_PATH):
        filepath = os.path.join(DOCUMENTS_PATH, filename)
        if os.path.isfile(filepath):
            try:
                # 'unstructured' library automatically handles many file types
                elements = partition(filename=filepath, nltk_download_dir=CACHE_DIR)
                raw_elements.extend(elements)
            except Exception as e:
                print(f"Could not process file {filename}: {e}")

    print(f"Found {len(raw_elements)} raw elements from documents.")

    # Guard against no documents being processed
    if not raw_elements:
        print("No documents were processed successfully. Aborting index build.")
        return

    print("Chunking documents...")
    chunks = chunk_by_title(raw_elements, max_characters=512, combine_text_under_n_chars=256)
    chunk_texts = [str(chunk) for chunk in chunks]
    print(f"Created {len(chunk_texts)} text chunks.")

    print(f"Loading embedding model '{EMBEDDING_MODEL}'...")
    model = SentenceTransformer(EMBEDDING_MODEL)

    print("Embedding text chunks... (This may take a while for many documents)")
    embeddings = model.encode(chunk_texts, show_progress_bar=True)

    embeddings = np.array(embeddings).astype('float32')

    print("Building FAISS index...")
    index = faiss.IndexFlatL2(embeddings.shape[1])
    index.add(embeddings)
    print(f"Index built successfully with {index.ntotal} vectors.")

    os.makedirs(VECTOR_STORE_PATH, exist_ok=True)
    faiss.write_index(index, os.path.join(VECTOR_STORE_PATH, "safi.index"))

    with open(os.path.join(VECTOR_STORE_PATH, "chunks.pkl"), "wb") as f:
        pickle.dump(chunk_texts, f)

    print(f"--- Indexing complete! ---")
    print(f"Vector store saved to: '{VECTOR_STORE_PATH}'")


if __name__ == "__main__":
    build_index()

