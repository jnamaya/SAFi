import csv
import re
import json

def parse_bible_for_rag(
    filepath: str,
    translation_to_use: str = "Douay-Rheims Bible",
    chunk_size: int = 4,
    chunk_overlap: int = 1
) -> list[dict]:
    """
    Parses a tab-separated Bible TXT file, creates structured data,
    and generates overlapping chunks for an efficient RAG system.

    Args:
        filepath: The path to the bibles.txt file.
        translation_to_use: The column name of the Bible translation to use as the canonical source.
        chunk_size: The number of verses to include in each chunk.
        chunk_overlap: The number of verses to overlap between consecutive chunks.

    Returns:
        A list of dictionaries, where each dictionary is an annotated text chunk.
    """
    
    # Regular expression to parse "Book Chapter:Verse"
    verse_regex = re.compile(r"([\w\s]+)\s(\d+):(\d+)")

    parsed_verses = []
    print(f"--- Starting Bible Parse ---")
    print(f"Using canonical translation: '{translation_to_use}'")

    try:
        # The fix is to add errors='ignore' to handle non-utf-8 characters in the source file.
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            # Use csv.reader with tab delimiter for TSV files
            reader = csv.reader(f, delimiter='\t')
            header = next(reader)
            
            if translation_to_use not in header:
                raise ValueError(f"Translation '{translation_to_use}' not found in file header. Available: {header}")
            
            translation_index = header.index(translation_to_use)

            for row in reader:
                if not row:
                    continue
                
                # Step 1 & 2: Parse the verse reference and extract text
                verse_ref = row[0]
                match = verse_regex.match(verse_ref)
                
                if not match:
                    continue
                    
                book, chapter, verse_num = match.groups()
                text = row[translation_index].strip()
                
                if not text: # Skip empty verses
                    continue

                parsed_verses.append({
                    "book": book.strip(),
                    "chapter": int(chapter),
                    "verse": int(verse_num),
                    "text": text
                })

    except FileNotFoundError:
        print(f"Error: File not found at {filepath}")
        return []

    print(f"Successfully parsed {len(parsed_verses)} verses.")

    # Step 3: Create overlapping chunks
    annotated_chunks = []
    step = chunk_size - chunk_overlap
    
    for i in range(0, len(parsed_verses) - chunk_size + 1, step):
        chunk_verses = parsed_verses[i:i + chunk_size]
        
        # Ensure the chunk is within the same book and chapter for context
        first_verse = chunk_verses[0]
        last_verse = chunk_verses[-1]
        if first_verse["book"] != last_verse["book"] or first_verse["chapter"] != last_verse["chapter"]:
            continue

        # Combine the text of the verses into a single chunk
        combined_text = " ".join(
            f"[{v['verse']}] {v['text']}" for v in chunk_verses
        )
        
        # Create the metadata for the chunk
        chunk_metadata = {
            "source": "bible",
            "translation": translation_to_use,
            "book": first_verse["book"],
            "chapter": first_verse["chapter"],
            "start_verse": first_verse["verse"],
            "end_verse": last_verse["verse"]
        }
        
        annotated_chunks.append({
            "text_chunk": combined_text,
            "metadata": chunk_metadata
        })

    print(f"Created {len(annotated_chunks)} overlapping chunks.")
    print(f"--- Bible Parse Complete ---")
    return annotated_chunks

if __name__ == '__main__':
    # --- CONFIGURATION ---
    # Make sure 'bibles.txt' is in the same directory as this script,
    # or provide the full path to the file.
    BIBLE_FILE_PATH = 'bibles.txt' 
    
    # Generate the annotated chunks
    chunks = parse_bible_for_rag(BIBLE_FILE_PATH)
    
    # Save the processed data to a JSON file for later use
    if chunks:
        output_filename = 'bible_chunks_for_rag.json'
        with open(output_filename, 'w', encoding='utf-8') as f:
            json.dump(chunks, f, indent=2, ensure_ascii=False)
        
        print(f"\nSuccessfully saved processed chunks to '{output_filename}'")
        
        # Print the first 2 chunks as an example
        print("\n--- Example of the first 2 processed chunks ---")
        print(json.dumps(chunks[:2], indent=2))

