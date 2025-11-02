import json
import re
import os

def create_chunks(text, chunk_size=4):
    """Splits a list of verses into chunks of a specified size."""
    for i in range(0, len(text), chunk_size):
        yield text[i:i + chunk_size]

def parse_bible_to_json(input_file, output_file):
    """
    Parses a Bible text file (ASV), extracts the translation,
    ensures correct biblical book order, and saves it as an enhanced JSON
    file for a RAG system.
    """
    print(f"--- Starting to process {input_file} ---")

    if not os.path.exists(input_file):
        print(f"FATAL ERROR: Input file not found at '{input_file}'")
        return

    # Define the canonical order of the books for the ASV (66 books).
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
    
    bible_data = {}
    
    # CRITICAL: This regex assumes your input file format is:
    # [Book Name] [Chap]:[Verse][TAB][Verse Text]
    # Example: Genesis 1:1\tIn the beginning God created...
    # If your format is different (e.g., no TAB), this script will not work.
    verse_pattern = re.compile(r'^(.+?)\s(\d+):(\d+)\t(.*)')

    try:
        with open(input_file, 'r', encoding='utf-8') as f:
            for line in f:
                # Skip any metadata or source lines that might be in the file.
                # This is the line that had the syntax error before.
                if line.startswith('[source:'):
                    continue
                
                # Skip empty lines
                if not line.strip():
                    continue
                    
                verse_match = verse_pattern.match(line)
                if verse_match:
                    book, chapter, verse, text = verse_match.groups()
                    book = book.strip()
                    
                    if book not in bible_data:
                        bible_data[book] = {}
                    if chapter not in bible_data[book]:
                        bible_data[book][chapter] = []
                    
                    bible_data[book][chapter].append((int(verse), text.strip()))
                else:
                    # This is useful for debugging a bad file format
                    if len(line) > 50:
                        line_preview = line[:50] + "..."
                    else:
                        line_preview = line.strip()
                    if line_preview: # Only print if it's not just whitespace
                        print(f"Warning: Line did not match verse pattern: '{line_preview}'")


        all_chunks = []
        for book in book_order:
            if book not in bible_data:
                # This warning is helpful if the input file uses a slightly
                # different book name (e.g., "Psalms" vs "Psalm").
                print(f"Warning: Book '{book}' from book_order not found in the input file.")
                continue

            for chapter in sorted(bible_data[book].keys(), key=int):
                # Sort verses by verse number to ensure correct order before chunking.
                verses = sorted(bible_data[book][chapter], key=lambda x: x[0])
                
                if not verses: # Skip if chapter was empty
                    continue

                for chunk_of_verses in create_chunks(verses):
                    start_verse_num = chunk_of_verses[0][0]
                    end_verse_num = chunk_of_verses[-1][0]
                    
                    citation = f"Citation: {book} chapter {chapter}, verses {start_verse_num} to {end_verse_num}."
                    verse_text = " ".join([f"[{v[0]}] {v[1]}" for v in chunk_of_verses])
                    full_text_chunk = f"{citation} {verse_text}"

                    chunk_data = {
                        "text_chunk": full_text_chunk,
                        "metadata": {
                            "source": "bible", 
                            "translation": "American Standard Version",  # <-- Updated
                            "book": str(book),
                            "chapter": int(chapter), 
                            "start_verse": start_verse_num, 
                            "end_verse": end_verse_num
                        }
                    }
                    all_chunks.append(chunk_data)

        # Ensure the output directory exists before trying to write the file.
        output_dir = os.path.dirname(output_file)
        if output_dir and not os.path.exists(output_dir):
            os.makedirs(output_dir, exist_ok=True)

        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(all_chunks, f, indent=2, ensure_ascii=False)
            
        print(f"--- Successfully created {len(all_chunks)} enhanced chunks in correct biblical order. ---")
        print(f"--- Output saved to {output_file} ---")

    except FileNotFoundError:
        print(f"FATAL ERROR: Input file not found at '{input_file}'")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")

if __name__ == '__main__':
    # Changed to 'asv.txt' and 'asv_chunks.json'
    # The script will look for 'asv.txt' in the same directory it is run from.
    parse_bible_to_json('asv.txt', 'asv_chunks.json')
