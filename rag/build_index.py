import os
import faiss
import numpy as np
import pickle
import json
import argparse
from typing import List, Dict, Any
from collections import defaultdict

# --- ENVIRONMENT SETUP ---
CACHE_DIR = "/var/www/safi/cache"
os.environ["NLTK_DATA"] = CACHE_DIR
os.environ["SENTENCE_TRANSFORMERS_HOME"] = CACHE_DIR
os.environ["HF_HUB_CACHE"] = CACHE_DIR
# -----------------------------

from sentence_transformers import SentenceTransformer
from unstructured.partition.auto import partition
from unstructured.chunking.title import chunk_by_title

# --- CONFIGURATION ---
VECTOR_STORE_PATH = "/var/www/safi/vector_store"
EMBEDDING_MODEL = 'all-MiniLM-L6-v2'

def process_raw_documents(source_dir: str) -> List[Dict[str, Any]]:
    """Processes all files in a directory, chunks them, and returns metadata."""
    print(f"--- Processing raw documents from: {source_dir} ---")
    if not os.path.exists(source_dir) or not os.listdir(source_dir):
        print(f"Error: The directory '{source_dir}' is empty or does not exist.")
        return []

    docs_with_sources = []
    for filename in os.listdir(source_dir):
        filepath = os.path.join(source_dir, filename)
        if os.path.isfile(filepath):
            try:
                elements = partition(filename=filepath, nltk_download_dir=CACHE_DIR)
                for el in elements:
                    docs_with_sources.append({'element': el, 'source': filename})
            except Exception as e:
                print(f"Could not process file {filename}: {e}")

    if not docs_with_sources:
        return []

    elements_by_file = defaultdict(list)
    for item in docs_with_sources:
        elements_by_file[item['source']].append(item['element'])

    final_metadata = []
    for source, elements in elements_by_file.items():
        chunks = chunk_by_title(elements, max_characters=512, combine_text_under_n_chars=256)
        for chunk in chunks:
            final_metadata.append({
                'text_chunk': str(chunk),
                'source': source
            })
    
    print(f"Created {len(final_metadata)} chunks from raw documents.")
    return final_metadata

def process_json_sources(source_json_paths: List[str]) -> List[Dict[str, Any]]:
    """Loads chunks and metadata from one or more pre-processed JSON files."""
    print(f"--- Processing pre-processed JSON sources: {source_json_paths} ---")
    all_metadata = []
    for json_path in source_json_paths:
        if not os.path.exists(json_path):
            print(f"Warning: Source file not found at '{json_path}'. Skipping.")
            continue
        
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        for item in data:
            meta = item.get('metadata', {})
            meta['text_chunk'] = item.get('text_chunk', '')
            all_metadata.append(meta)

    print(f"Loaded {len(all_metadata)} chunks from JSON files.")
    return all_metadata

def build_index(output_name: str, metadata_list: List[Dict[str, Any]]):
    """Builds and saves a FAISS index and metadata file with L2 normalization."""
    if not metadata_list:
        print("Error: No metadata provided. Nothing to index.")
        return

    all_chunk_texts = [item['text_chunk'] for item in metadata_list]

    print(f"Loading embedding model '{EMBEDDING_MODEL}'...")
    model = SentenceTransformer(EMBEDDING_MODEL)

    print(f"Embedding {len(all_chunk_texts)} chunks for '{output_name}'...")
    embeddings = model.encode(all_chunk_texts, show_progress_bar=True)
    embeddings = np.array(embeddings).astype('float32')

    # --- KEY CHANGE: NORMALIZE VECTORS ---
    print("Normalizing vectors for improved search consistency.")
    faiss.normalize_L2(embeddings)
    # ------------------------------------

    print("Building FAISS index...")
    index = faiss.IndexFlatIP(embeddings.shape[1]) # Using Inner Product for normalized vectors
    index.add(embeddings)
    print(f"Index built successfully with {index.ntotal} vectors.")

    os.makedirs(VECTOR_STORE_PATH, exist_ok=True)
    
    index_path = os.path.join(VECTOR_STORE_PATH, f"{output_name}.index")
    metadata_path = os.path.join(VECTOR_STORE_PATH, f"{output_name}_metadata.pkl")

    faiss.write_index(index, index_path)
    print(f"Successfully saved FAISS index to '{index_path}'")
    
    with open(metadata_path, "wb") as f:
        pickle.dump(metadata_list, f)
    print(f"Successfully saved metadata to '{metadata_path}'")
    print("--- Indexing Complete ---")


def main():
    parser = argparse.ArgumentParser(description="Build a FAISS index for a specified knowledge base.")
    parser.add_argument("--name", type=str, required=True, help="The base name for the output index files.")
    
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--source_dir", type=str, help="Path to a directory of raw documents to process.")
    group.add_argument("--source_json", type=str, nargs='+', help="Path to one or more pre-processed JSON chunk files.")

    args = parser.parse_args()

    if args.source_dir:
        metadata = process_raw_documents(args.source_dir)
    elif args.source_json:
        metadata = process_json_sources(args.source_json)
    
    build_index(args.name, metadata)

if __name__ == "__main__":
    main()

