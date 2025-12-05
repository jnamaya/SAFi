"""
Defines all robust parsing and sanitization logic.

This file is the ONLY place that knows how to parse the raw, messy,
and unreliable string/JSON outputs from different LLMs.
"""
from __future__ import annotations
import json
import re
import logging
from typing import List, Dict, Any, Tuple, Optional, TYPE_CHECKING

# Avoid circular import for type hint
if TYPE_CHECKING:
    import logging

def robust_json_parse(raw_text: str, log: "logging.Logger") -> Dict[str, Any]:
    """
    Parses the first valid JSON object found in a raw text string.
    
    This function is highly resilient to common LLM-generated JSON errors,
    such as trailing commas, newlines, and non-JSON text surrounding
    the object.

    Args:
        raw_text: The raw, potentially messy string from the LLM.
        log: The logger instance to use for errors.

    Returns:
        A dictionary, or an error dictionary if parsing fails.
    """
    obj = {}
    json_text = raw_text # Default to raw text
    
    # 1. Find the first '{' and last '}'
    # This is the most reliable way to extract a JSON blob
    # from a string that might contain other text.
    start = raw_text.find('{')
    end = raw_text.rfind('}')
    
    if start != -1 and end != -1 and end > start:
        json_text = raw_text[start:end+1]
    
    # 2. Try to parse directly
    try:
        obj = json.loads(json_text)
        return obj
    except json.JSONDecodeError:
        pass # Go to sanitization

    # 3. Sanitize and retry
    try:
        # Sanitize common errors:
        # - Remove newlines and carriage returns
        # - Fix trailing commas (e.g., "key": "value",})
        # - Consolidate excess whitespace
        sanitized = json_text.replace("\r", " ").replace("\n", " ")
        sanitized = re.sub(r",\s*([}\]])", r"\1", sanitized) # Fix trailing commas
        sanitized = re.sub(r"\s{2,}", " ", sanitized).strip()
        obj = json.loads(sanitized)
        return obj
    except json.JSONDecodeError as e:
        log.error(f"Robust JSON parse failed after sanitization: {e} | content={sanitized[:500]}")
        return {"error": "JSONDecodeError", "raw_content": raw_text}

# --- Specific Parsers for Each Faculty ---

def parse_intellect_response(raw_text: str, log: "logging.Logger") -> Tuple[str, str]:
    """
    Parses the "Answer---REFLECTION---{...}" format from Intellect.
    
    This function uses a 3-priority fallback system.
    """
    answer = ""
    reflection = ""
    delimiter_text = "---REFLECTION---"

    # --- Run the original robust parsing on the raw_text ---
    if delimiter_text in raw_text:
        # --- Priority 1: Model used the delimiter correctly ---
        log.info("Parsing Intellect response using delimiter.")
        parts = raw_text.split(delimiter_text)
        answer = parts[0].strip()
        
        json_part_raw = parts[-1]
        json_obj = robust_json_parse(json_part_raw, log)
        
        # FIX: Handle non-string reflection fields (e.g. nested dicts from Mistral)
        ref_val = json_obj.get("reflection")
        if isinstance(ref_val, (dict, list)):
             reflection = json.dumps(ref_val, ensure_ascii=False)
        else:
             reflection = str(ref_val if ref_val is not None else "Parsed reflection from delimiter.").strip()

    else:
        # --- Priority 2: Model "forgot" delimiter but sent JSON ---
        log.warning(f"Intellect model did not use delimiter. Searching for JSON...")
        
        # Use regex to find JSON
        json_match = re.search(r"\{[\s\S]*\}", raw_text) # [\s\S] matches newlines

        if json_match:
            log.info("Found salvaged JSON. Parsing.")
            json_part_raw = json_match.group(0).strip()
            answer = raw_text[:json_match.start()].strip() # Everything BEFORE the JSON
            
            json_obj = robust_json_parse(json_part_raw, log)
            
            # FIX: Handle non-string reflection fields
            ref_val = json_obj.get("reflection")
            if isinstance(ref_val, (dict, list)):
                 reflection = json.dumps(ref_val, ensure_ascii=False)
            else:
                 reflection = str(ref_val if ref_val is not None else "Parsed reflection from regex search.").strip()

            if not answer:
                answer = f"[Answer missing, model only sent JSON: {json_part_raw}]"

        else:
            # --- Priority 3: Model sent raw text ---
            log.warning(f"No JSON found in Intellect response. Salvaging raw text.")
            answer = raw_text.strip()
            reflection = "Salvaged raw output; model failed to format."

    if not answer.strip():
        answer = "[Model returned an empty answer]"
        reflection = "Model returned empty answer."

    return answer.replace("\\n", "\n"), reflection.replace("\\n", "\n")

def parse_will_response(raw_text: str, log: "logging.Logger") -> Tuple[str, str]:
    """
    Parses the {"decision": "...", "reason": "..."} format from Will.
    
    This parser is simple: it just finds the first valid JSON in the
    raw text and extracts the keys.
    """
    # Find and parse the JSON blob
    obj = robust_json_parse(raw_text, log)
    
    if "error" in obj:
        # This happens if robust_json_parse failed
        return ("violation", "Internal evaluation error (JSON parse failed)")
        
    decision = str(obj.get("decision") or "").strip().lower()
    reason = (obj.get("reason") or "").strip()
    
    if decision not in {"approve", "violation"}:
        decision = "violation" # Default to violation if decision is invalid
        
    if not reason:
        reason = "Decision explained by Will policies and the active value set."
        
    return decision, reason

def parse_conscience_response(raw_text: str, log: "logging.Logger") -> List[Dict[str, Any]]:
    """
    Parses the {"evaluations": [...]} format from Conscience.
    
    This parser is simple: it just finds the first valid JSON in the
    raw text and extracts the 'evaluations' key.
    """
    # Find and parse the JSON blob
    obj = robust_json_parse(raw_text, log)
    
    if "error" in obj:
        # This happens if robust_json_parse failed
        return [{"error": "Internal evaluation error (JSON parse failed)"}]
    
    evaluations = obj.get("evaluations", [])
    if not isinstance(evaluations, list):
        log.error(f"Conscience 'evaluations' was not a list. Got: {type(evaluations)}")
        return [{"error": f"Conscience 'evaluations' was not a list."}]

    return evaluations