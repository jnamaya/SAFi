import json
import re
import os

def create_chunks(text, chunk_size=4):
    """Splits a list of verses into chunks of a specified size."""
    for i in range(0, len(text), chunk_size):
        yield text[i:i + chunk_size]

def parse_bible_to_json(input_file, output_file):
    """
    Parses a Bible text file (CPDV), extracts the translation,
    ensures correct biblical book order, and saves it as an enhanced JSON
    file for a RAG system.
    """
    print(f"--- Starting to process {input_file} ---")

    if not os.path.exists(input_file):
        print(f"FATAL ERROR: Input file not found at '{input_file}'")
        return

    # Define the canonical order of the books for the final output.
    book_order = [
        "Genesis", "Exodus", "Leviticus", "Numbers", "Deuteronomy", "Joshua", "Judges", "Ruth",
        "1 Samuel", "2 Samuel", "1 Kings", "2 Kings", "1 Chronicles", "2 Chronicles", "Ezra",
        "Nehemiah", "Tobit", "Judith", "Esther", "Job", "Psalm", "Proverbs", "Ecclesiastes",
        "Song of Solomon", "The Wisdom of Solomon", "Sirach (Ecclesiasticus)", "Isaiah", "Jeremiah", "Lamentations",
        "Baruch", "Ezekiel", "Daniel", "Hosea", "Joel", "Amos", "Obadiah", "Jonah", "Micah",
        "Nahum", "Habakkuk", "Zephaniah", "Haggai", "Zechariah", "Malachi",
        "Matthew", "Mark", "Luke", "John", "Acts", "Romans", "1 Corinthians", "2 Corinthians",
        "Galatians", "Ephesians", "Philippians", "Colossians", "1 Thessalonians", "2 Thessalonians",
        "1 Timothy", "2 Timothy", "Titus", "Philemon", "Hebrews", "James", "1 Peter", "2 Peter",
        "1 John", "2 John", "3 John", "Jude", "Revelation"
    ]
    
    # Map names found in the text file to the canonical names in book_order.
    book_name_mapping = {
        "Wisdom": "The Wisdom of Solomon",
        "Sirach": "Sirach (Ecclesiasticus)"
    }

    bible_data = {}
    # This improved regex correctly handles book names that may start with numbers.
    verse_pattern = re.compile(r'^(.+?)\s(\d+):(\d+)\t(.*)')

    try:
        with open(input_file, 'r', encoding='utf-8') as f:
            for line in f:
                # Skip any metadata or source lines that might be in the file.
                if line.startswith('[source:'):
                    continue
                    
                verse_match = verse_pattern.match(line)
                if verse_match:
                    book, chapter, verse, text = verse_match.groups()
                    book = book.strip()
                    
                    # Normalize the book name using a more flexible mapping search.
                    canonical_book = book
                    for file_name, canon_name in book_name_mapping.items():
                        if file_name in book:
                            canonical_book = canon_name
                            break

                    if canonical_book not in bible_data:
                        bible_data[canonical_book] = {}
                    if chapter not in bible_data[canonical_book]:
                        bible_data[canonical_book][chapter] = []
                    
                    bible_data[canonical_book][chapter].append((int(verse), text.strip()))

        all_chunks = []
        for book in book_order:
            if book not in bible_data:
                print(f"Warning: Book '{book}' not found in the input file.")
                continue

            for chapter in sorted(bible_data[book].keys(), key=int):
                # Sort verses by verse number to ensure correct order before chunking.
                verses = sorted(bible_data[book][chapter], key=lambda x: x[0])
                
                for chunk_of_verses in create_chunks(verses):
                    start_verse_num = chunk_of_verses[0][0]
                    end_verse_num = chunk_of_verses[-1][0]
                    
                    citation = f"Citation: {book} chapter {chapter}, verses {start_verse_num} to {end_verse_num}."
                    verse_text = " ".join([f"[{v[0]}] {v[1]}" for v in chunk_of_verses])
                    full_text_chunk = f"{citation} {verse_text}"

                    chunk_data = {
                        "text_chunk": full_text_chunk,
                        "metadata": {
                            "source": "bible", "translation": "Catholic Public Domain Version", "book": str(book),
                            "chapter": int(chapter), "start_verse": start_verse_num, "end_verse": end_verse_num
                        }
                    }
                    all_chunks.append(chunk_data)

        # Ensure the output directory exists before trying to write the file.
        output_dir = os.path.dirname(output_file)
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)

        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(all_chunks, f, indent=2, ensure_ascii=False)
            
        print(f"--- Successfully created {len(all_chunks)} enhanced chunks in correct biblical order. ---")
        print(f"--- Output saved to {output_file} ---")

    except Exception as e:
        print(f"An unexpected error occurred: {e}")

if __name__ == '__main__':
    # You can change the input and output file paths here.
    # The script will look for 'cpdv.txt' in the same directory it is run from.
    parse_bible_to_json('cpdv.txt', 'cpdv_chunks.json')

