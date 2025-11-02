import json
import re
import os
import uuid  # <-- Import uuid for unique chunk IDs

def create_chunks(verses, chunk_size=5, chunk_overlap=2):
    """
    Splits a list of (verse_number, verse_text) tuples into overlapping chunks.

    Args:
        verses (list): A list of (verse_number, verse_text) tuples for a chapter.
        chunk_size (int): The number of verses in each chunk.
        chunk_overlap (int): The number of verses to overlap between chunks.

    Yields:
        tuple: (full_text_chunk, start_verse_num, end_verse_num)
    """
    
    # Calculate the step size (how many verses to jump forward for each new chunk)
    # If chunk_size is 5 and overlap is 2, the step is 3 (chunks are 1-5, 4-8, 7-11)
    step_size = chunk_size - chunk_overlap
    
    # Ensure step_size is at least 1 to avoid infinite loops
    if step_size < 1:
        step_size = 1

    for i in range(0, len(verses), step_size):
        chunk = verses[i:i + chunk_size]
        if not chunk:
            continue
            
        # Extract data for the chunk
        verse_numbers = [v[0] for v in chunk]
        verse_texts = [v[1] for v in chunk]
        
        full_text_chunk = " ".join(verse_texts)
        start_verse_num = verse_numbers[0]
        end_verse_num = verse_numbers[-1]
        
        # Yield all the data needed to build the JSON object
        yield full_text_chunk, start_verse_num, end_verse_num

def parse_bible_to_json(input_file, output_file):
    """
    Parses a Bible text file (BSB), ensures correct biblical book order,
    and saves it as an enhanced JSON file with overlapping chunks for a RAG system.
    """
    print(f"--- Starting to process {input_file} ---")

    if not os.path.exists(input_file):
        print(f"FATAL ERROR: Input file not found at '{input_file}'")
        return

    # Define the canonical order of the books (66 books).
    book_order = [
        "Genesis", "Exodus", "Leviticus", "Numbers", "Deuteronomy", "Joshua", "Judges", "Ruth",
        "1 Samuel", "2 Samuel", "1 Kings", "2 Kings", "1 Chronicles", "2 Chronicles", "Ezra",
        "Nehemiah", "Esther", "Job", "Psalm", "Proverbs", "Ecclesiastes",
        "Song of Solomon", "Isaiah", "Jeremiah", "Lamentations", "Ezekiel", "Daniel", 
        "Hosea", "Joel", "Amos", "Obadiah", "Jonah", "Micah", "Nahum", "Habakkuk", 
        "Zephaniah", "Haggai", "Zechariah", "Malachi",
        "Matthew", "Mark", "Luke", "John", "Acts", "Romans", "1 Corinthians", "2 Corinthians",
        "Galatians", "Ephesians", "Philippians", "Colossians", "1 Thessalonians", "2 Thessalonians",
        "1 Timothy", "2 Timothy", "Titus", "Philemon", "Hebrews", "James", "1 Peter", "2 Peter",
        "1 John", "2 John", "3 John", "Jude", "Revelation"
    ]
    
    # Create a regex to capture the book, chapter, verse, and text.
    # This regex handles book names with or without a leading number (e.g., "1 Samuel" vs "Genesis")
    verse_regex = re.compile(r'^((\d\s)?[A-Za-z\s]+)\s(\d+):(\d+)\t(.+)$')
    
    bible_data = {}
    all_chunks = []

    try:
        print("--- Pass 1: Parsing file and organizing by book and chapter... ---")
        with open(input_file, 'r', encoding='utf-8') as f:
            for line in f:
                match = verse_regex.match(line.strip())
                if match:
                    book, _, chapter, verse, text = match.groups()
                    book = book.strip()
                    chapter = int(chapter)
                    verse = int(verse)
                    
                    if book not in bible_data:
                        bible_data[book] = {}
                    if chapter not in bible_data[book]:
                        bible_data[book][chapter] = []
                    
                    bible_data[book][chapter].append((verse, text))

        print("--- Pass 2: Generating overlapping chunks in correct biblical order... ---")
        # Process the books in the correct canonical order
        for book in book_order:
            if book not in bible_data:
                print(f"Warning: Book '{book}' not found in input file. Skipping.")
                continue
            
            # Sort chapters numerically
            sorted_chapters = sorted(bible_data[book].keys())
            
            for chapter in sorted_chapters:
                chapter_verses = bible_data[book][chapter]
                # Ensure verses are sorted by verse number, just in case
                chapter_verses.sort(key=lambda x: x[0])
                
                # Use the new create_chunks function with an overlap
                # We'll use a chunk_size of 5 and an overlap of 2
                # This means chunks will be (1-5), (4-8), (7-11), etc.
                for (full_text_chunk, start_verse_num, end_verse_num) in create_chunks(chapter_verses, chunk_size=5, chunk_overlap=2):
                    
                    # Create the formatted reference string, e.g., "Genesis 1:1-5"
                    reference = f"{book} {chapter}:{start_verse_num}-{end_verse_num}"
                    
                    # (Optional) Prepend the reference to the text for better embedding context.
                    # This helps the RAG model associate the text with its specific location.
                    # text_with_header = f"[{reference}]\n{full_text_chunk}"
                    
                    chunk_data = {
                        "id": str(uuid.uuid4()),  # <-- Added unique ID
                        "reference": reference,    # <-- Added simple reference
                        "text_chunk": full_text_chunk, # or use text_with_header
                        "metadata": {
                            "source": "bible", 
                            "translation": "Berean Standard Bible",
                            "book": str(book),
                            "chapter": int(chapter), 
                            "start_verse": int(start_verse_num), 
                            "end_verse": int(end_verse_num)
                        }
                    }
                    all_chunks.append(chunk_data)

        # Ensure the output directory exists before trying to write the file.
        output_dir = os.path.dirname(output_file)
        if output_dir and not os.path.exists(output_dir):
            os.makedirs(output_dir, exist_ok=True)

        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(all_chunks, f, indent=2, ensure_ascii=False)
            
        print(f"--- Successfully created {len(all_chunks)} overlapping chunks. ---")
        print(f"--- Output saved to {output_file} ---")

    except FileNotFoundError:
        print(f"FATAL ERROR: Input file not found at '{input_file}'")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")

if __name__ == '__main__':
    # Use the 'bsb.txt' file as input and create 'bsb_chunks.json' as output
    parse_bible_to_json('bsb.txt', 'bsb_chunks.json')
