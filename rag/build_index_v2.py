import os
import faiss
import numpy as np
import pickle
import json
import argparse
from typing import List, Dict, Any
from collections import defaultdict

# --- ENVIRONMENT SETUP ---
# (Assuming these paths are correct for your environment)
CACHE_DIR = "/var/www/safi/cache"
os.environ["NLTK_DATA"] = CACHE_DIR
os.environ["SENTENCE_TRANSFORMERS_HOME"] = CACHE_DIR
os.environ["HF_HUB_CACHE"] = CACHE_DIR
os.makedirs(CACHE_DIR, exist_ok=True)
# ----------------------------->

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
                print(f"Partitioning file: {filename}")
                elements = partition(filename=filepath)
                print(f"Chunking by title for: {filename}")
                chunks = chunk_by_title(elements)
                
                for i, chunk in enumerate(chunks):
                    meta = {
                        "source": filename,
                        "chunk_id": f"{filename}-chunk-{i}"
                    }
                    # IMPORTANT: For this flow, we create a list of dicts 
                    # that INCLUDE the text_chunk.
                    docs_with_sources.append({
                        "text_chunk": str(chunk),
                        "metadata": meta
                    })
                print(f"Created {len(chunks)} chunks for {filename}")
            except Exception as e:
                print(f"Error processing file {filename}: {e}")
    
    print(f"--- Total raw chunks created: {len(docs_with_sources)} ---")
    return docs_with_sources


def load_from_json(source_json_paths: List[str]) -> (List[str], List[Dict[str, Any]]):
    """
    Loads text chunks and their full metadata from pre-processed JSON files.
    
    *** THIS IS THE MODIFIED FUNCTION V3 ***
    """
    all_texts = []
    all_metadata = []
    print(f"--- Loading from pre-processed JSON files: {source_json_paths} ---")
    
    for path in source_json_paths:
        if not os.path.exists(path):
            print(f"Warning: JSON file not found at '{path}'. Skipping.")
            continue
            
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            if not isinstance(data, list):
                print(f"Warning: JSON file '{path}' is not a list of objects. Skipping.")
                continue

            print(f"Processing {len(data)} chunks from {path}...")
            for item in data:
                text_chunk = item.get("text_chunk")
                
                if text_chunk:
                    all_texts.append(text_chunk)
                    
                    # Copy the entire item to be our metadata packet.
                    # This item ALREADY contains 'id', 'reference', 
                    # 'text_chunk', and the nested 'metadata' object.
                    meta_packet = item.copy()
                    
                    # *** BUG FIX ***
                    # We are NO LONGER removing the 'text_chunk'
                    # meta_packet.pop("text_chunk", None) # <-- THIS LINE IS REMOVED
                    
                    # Now, the metadata packet saved to the .pkl file
                    # will contain the text chunk, making it retrievable.
                    all_metadata.append(meta_packet)
                else:
                    print(f"Warning: Item in {path} missing 'text_chunk'. Skipping item.")
                    
        except json.JSONDecodeError:
            print(f"Error: Could not decode JSON from '{path}'. Skipping.")
        except Exception as e:
            print(f"An unexpected error occurred while processing {path}: {e}")
            
    print(f"--- Total JSON chunks loaded: {len(all_texts)} ---")
    return all_texts, all_metadata


def build_index(text_chunks: List[str], metadata_list: List[Dict[str, Any]], output_name: str):
    """Builds and saves a FAISS index and corresponding metadata."""
    if not text_chunks:
        print("Error: No text chunks to index.")
        return

    print(f"--- Building index '{output_name}' ---")
    try:
        print(f"Loading embedding model: {EMBEDDING_MODEL}")
        model = SentenceTransformer(EMBEDDING_MODEL, cache_folder=CACHE_DIR)
    except Exception as e:
        print(f"Fatal Error: Could not load SentenceTransformer model. {e}")
        print("Please ensure you have an internet connection or the model is cached.")
        return

    print("Encoding text chunks... This may take a while.")
    try:
        embeddings = model.encode(text_chunks, show_progress_bar=True)
        embeddings = np.array(embeddings).astype('float32') # FAISS requires float32
    except Exception as e:
        print(f"Fatal Error: Could not encode text chunks. {e}")
        return
        
    print("Building FAISS index...")
    index = faiss.IndexFlatIP(embeddings.shape[1]) 
    index.add(embeddings)
    print(f"Index built successfully with {index.ntotal} vectors.")

    os.makedirs(VECTOR_STORE_PATH, exist_ok=True)
    
    index_path = os.path.join(VECTOR_STORE_PATH, f"{output_name}.index")
    metadata_path = os.path.join(VECTOR_STORE_PATH, f"{output_name}_metadata.pkl")

    faiss.write_index(index, index_path)
    print(f"Successfully saved FAISS index to '{index_path}'")
    
    # Save the *full* metadata list (which now includes 'text_chunk')
    with open(metadata_path, "wb") as f:
        pickle.dump(metadata_list, f)
    print(f"Successfully saved metadata to '{metadata_path}'")
    print("--- Indexing Complete ---")


def main():
    parser = argparse.ArgumentParser(description="Build a FAISS index for a specified knowledge base.")
    parser.add_argument("--name", type=str, required=True, help="The base name for the output index files (e.g., 'bible_v1').")
    
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--source_dir", type=str, help="Path to a directory of raw documents to process.")
    group.add_argument("--source_json", type=str, nargs='+', help="Path to one or more pre-processed JSON chunk files (e.g., 'bsb_chunks.json').")

    args = parser.parse_args()

    all_texts = []
    all_metadata = []

    if args.source_dir:
        # This path now returns a list of dicts that include the text_chunk
        processed_data = process_raw_documents(args.source_dir)
        # We need to separate them for the build_index function
        all_texts = [item['text_chunk'] for item in processed_data]
        # And the metadata list *also* contains the text_chunk
        all_metadata = processed_data 
    
    elif args.source_json:
        # This path now correctly keeps 'text_chunk' in the metadata list
        all_texts, all_metadata = load_from_json(args.source_json)
    
    if all_texts and all_metadata:
        build_index(all_texts, all_metadata, args.name)
    else:
        print("No documents were processed or loaded. Exiting.")

if __name__ == "__main__":
    main()
