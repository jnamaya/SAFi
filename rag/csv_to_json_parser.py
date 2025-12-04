import pandas as pd
import json
import os
import re

# --- CONFIGURATION ---
INPUT_EXCEL_FILE = "M365 Naming Conventions and Standardized Properties.xlsx"
OUTPUT_JSON_FILE = "naming_conventions.json"

def clean_text(val):
    """Standardizes text, handling NaNs and floats."""
    if pd.isna(val) or val == "":
        return ""
    return str(val).strip()

def parse_excel_sheets(excel_path):
    if not os.path.exists(excel_path):
        print(f"Error: File not found '{excel_path}'")
        return []

    print(f"--- Loading Excel file: {excel_path} ---")
    try:
        # Read all sheets at once. returns a dict of {sheet_name: dataframe}
        xls = pd.read_excel(excel_path, sheet_name=None, header=None)
    except Exception as e:
        print(f"Error reading Excel file: {e}")
        return []

    json_chunks = []

    for sheet_name, df in xls.items():
        # Skip Table of Contents
        if "TOC" in sheet_name or "Table of Contents" in sheet_name:
            continue

        print(f"Processing Sheet: {sheet_name}")
        
        # Convert entire sheet to string matrix to find the header
        # We search for a row that contains 'Property', 'Convention', or 'Type'
        header_row_index = -1
        headers = []
        
        for i, row in df.iterrows():
            row_str = " ".join([str(x).lower() for x in row if pd.notna(x)])
            # Heuristic keywords to identify the header row
            if "property" in row_str or "convention" in row_str or "admin role" in row_str or "auto-away type" in row_str or "computer type" in row_str:
                header_row_index = i
                # Create clean headers list, filtering out NaNs
                headers = [clean_text(x) for x in row]
                break
        
        if header_row_index == -1:
            print(f"  -> Warning: Could not find a recognizable header row in '{sheet_name}'. Skipping.")
            continue

        # Extract data rows (everything after the header)
        # We iterate explicitly to control formatting
        rows_content = []
        data_rows = df.iloc[header_row_index + 1:]

        for _, row in data_rows.iterrows():
            # Check if row is empty (all NaNs or empty strings)
            if row.dropna().empty:
                continue
            
            line_parts = []
            for h, val in zip(headers, row):
                # Only include cells that have a header AND a value
                if h and pd.notna(val) and str(val).strip():
                    clean_val = clean_text(val)
                    line_parts.append(f"{h}: {clean_val}")
            
            if line_parts:
                rows_content.append("- " + " | ".join(line_parts))

        # Create the Chunk for this sheet
        if rows_content:
            full_text = f"SECTION: {sheet_name}\n\n" + "\n".join(rows_content)
            
            chunk_obj = {
                "text_chunk": full_text,
                "source": INPUT_EXCEL_FILE,
                "section": sheet_name,
                "chunk_id": f"excel-{sheet_name.replace(' ', '-').lower()}"
            }
            json_chunks.append(chunk_obj)
            print(f"  -> Created chunk with {len(rows_content)} rows.")

    return json_chunks

def main():
    chunks = parse_excel_sheets(INPUT_EXCEL_FILE)
    
    if chunks:
        with open(OUTPUT_JSON_FILE, "w", encoding="utf-8") as f:
            json.dump(chunks, f, indent=2)
        print(f"\nSuccessfully created '{OUTPUT_JSON_FILE}' with {len(chunks)} chunks.")
        print(f"You can now run:\npython3 build_index_v2.py --name sop_index --source_json sop_chunks.json {OUTPUT_JSON_FILE}")
    else:
        print("\nNo chunks were created. Please check the Excel file format.")

if __name__ == "__main__":
    main()