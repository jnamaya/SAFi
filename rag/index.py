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
VECTOR_STORE_PATH = "/var/www/safi/vector_store"
EMBEDDING_MODEL = 'all-MiniLM-L6-v2'


def build_index():
    """
    Reads documents, chunks them, creates vector embeddings, and saves them
    into a FAISS index for fast retrieval, now including source metadata.
    """
    if not os.path.exists(DOCUMENTS_PATH) or not os.listdir(DOCUMENTS_PATH):
        print(f"Error: The directory '{DOCUMENTS_PATH}' is empty or does not exist.")
        print("Please place your knowledge base files in this directory.")
        return

    print("Loading documents and associating with sources...")
    # --- CHANGE 1: Store elements with their source filename ---
    docs_with_sources = []
    for filename in os.listdir(DOCUMENTS_PATH):
        filepath = os.path.join(DOCUMENTS_PATH, filename)
        if os.path.isfile(filepath):
            try:
                elements = partition(filename=filepath, nltk_download_dir=CACHE_DIR)
                # Append a tuple of (element, source_filename)
                for el in elements:
                    docs_with_sources.append((el, filename))
            except Exception as e:
                print(f"Could not process file {filename}: {e}")

    print(f"Found {len(docs_with_sources)} raw elements from documents.")

    if not docs_with_sources:
        print("No documents were processed successfully. Aborting index build.")
        return

    print("Chunking documents...")
    # unstructured's chunking functions can lose metadata, so we process file by file
    # This is a simplified approach; more complex logic could preserve metadata through chunking
    
    # --- CHANGE 2: Create chunks and associate them back to their source ---
    # We will create two parallel lists: one for text, one for the (text, source) tuples.
    all_chunk_texts = []
    chunks_with_sources = []

    # Group elements by their source file
    from collections import defaultdict
    elements_by_file = defaultdict(list)
    for el, source in docs_with_sources:
        elements_by_file[source].append(el)

    for source, elements in elements_by_file.items():
        chunks = chunk_by_title(elements, max_characters=512, combine_text_under_n_chars=256)
        for chunk in chunks:
            chunk_text = str(chunk)
            all_chunk_texts.append(chunk_text)
            chunks_with_sources.append((chunk_text, source))

    print(f"Created {len(all_chunk_texts)} text chunks.")

    print(f"Loading embedding model '{EMBEDDING_MODEL}'...")
    model = SentenceTransformer(EMBEDDING_MODEL)

    print("Embedding text chunks... (This may take a while for many documents)")
    embeddings = model.encode(all_chunk_texts, show_progress_bar=True)
    embeddings = np.array(embeddings).astype('float32')

    print("Building FAISS index...")
    index = faiss.IndexFlatL2(embeddings.shape[1])
    index.add(embeddings)
    print(f"Index built successfully with {index.ntotal} vectors.")

    os.makedirs(VECTOR_STORE_PATH, exist_ok=True)
    faiss.write_index(index, os.path.join(VECTOR_STORE_PATH, "safi.index"))

    # --- CHANGE 3: Save the list of (text, source) tuples ---
    with open(os.path.join(VECTOR_STORE_PATH, "chunks.pkl"), "wb") as f:
        pickle.dump(chunks_with_sources, f)

    print(f"--- Indexing complete! ---")
    print(f"Vector store saved to: '{VECTOR_STORE_PATH}'")


if __name__ == "__main__":
    build_index()
