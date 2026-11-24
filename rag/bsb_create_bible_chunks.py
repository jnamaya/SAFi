import json
import re
import os
import uuid

def create_chunks(verses, chunk_size=5, chunk_overlap=2):
    
    step_size = chunk_size - chunk_overlap
    
    if step_size < 1:
        step_size = 1

    for i in range(0, len(verses), step_size):
        chunk = verses[i:i + chunk_size]
        if not chunk:
            continue
            
        verse_numbers = [v[0] for v in chunk]
        verse_texts = [v[1] for v in chunk]
        
        full_text_chunk = " ".join(verse_texts)
        start_verse_num = verse_numbers[0]
        end_verse_num = verse_numbers[-1]
        
        yield full_text_chunk, start_verse_num, end_verse_num

def parse_bible_to_json(input_file, output_file):
    print(f"--- Starting to process {input_file} ---")

    if not os.path.exists(input_file):
        print(f"FATAL ERROR: Input file not found at '{input_file}'")
        return

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
        for book in book_order:
            if book not in bible_data:
                print(f"Warning: Book '{book}' not found in input file. Skipping.")
                continue
            
            sorted_chapters = sorted(bible_data[book].keys())
            
            for chapter in sorted_chapters:
                chapter_verses = bible_data[book][chapter]
                chapter_verses.sort(key=lambda x: x[0])
                
                for (full_text_chunk, start_verse_num, end_verse_num) in create_chunks(chapter_verses, chunk_size=5, chunk_overlap=2):
                    
                    reference = f"{book} {chapter}:{start_verse_num}-{end_verse_num}"
                    
                    
                    chunk_data = {
                        "id": str(uuid.uuid4()),
                        "reference": reference,
                        "text_chunk": full_text_chunk,
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
    parse_bible_to_json('bsb.txt', 'bsb_chunks.json')
