"""
Defines all robust parsing and sanitization logic.

This file is the ONLY place that knows how to parse the raw, messy,
and unreliable string/JSON outputs from different LLMs.

By centralizing this logic, we can improve parsing in one place
and it benefits all faculties.
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
    
    This function attempts multiple strategies to extract a valid JSON
    object from text that may be prefixed or suffixed with garbage.

    Args:
        raw_text: The raw string response from the LLM.
        log: A logger instance to report failures.

    Returns:
        A dictionary, or a dictionary with an "error" key on failure.
    """
    obj = {}
    json_text = raw_text # Default to raw text
    
    # 1. Find the first '{' and last '}'
    start = raw_text.find('{')
    end = raw_text.rfind('}')
    
    if start != -1 and end != -1 and end > start:
        json_text = raw_text[start:end+1]
    
    # 2. Try to parse directly
    try:
        obj = json.loads(json_text)
        return obj
    except json.JSONDecodeError:
        pass # If it fails, proceed to sanitization
    # 3. Sanitize and retry
    try:
        sanitized = json_text.replace("\r", " ").replace("\n", " ")
        sanitized = re.sub(r",\s*([}\]])", r"\1", sanitized) # Fix trailing commas
        sanitized = re.sub(r"\s{2,}", " ", sanitized).strip()
        obj = json.loads(sanitized)
        return obj
    except json.JSONDecodeError as e:
        log.error(f"Robust JSON parse failed: {e} | content={sanitized[:500]}")
        return {"error": "JSONDecodeError", "raw_content": raw_text}

# --- Specific Parsers for Each Faculty ---

def parse_intellect_response(raw_text: str, log: "logging.Logger") -> Tuple[str, str]:
    """
    Parses the "Answer---REFLECTION---{...}" format from Intellect.
    
    This function uses a 3-priority fallback system to be resilient
    to models that fail to follow formatting instructions.
    """
    answer = ""
    reflection = ""
    delimiter_text = "---REFLECTION---"

    if delimiter_text in raw_text:
        # --- Priority 1: Model used the delimiter correctly ---
        log.debug("Parsing Intellect response using delimiter.")
        parts = raw_text.split(delimiter_text)
        answer = parts[0].strip()
        
        json_part_raw = parts[-1] # Get the text *after* the last delimiter
        json_obj = robust_json_parse(json_part_raw, log)
        reflection = json_obj.get("reflection", "Parsed reflection from delimiter.").strip()

    else:
        # --- Priority 2: Model "forgot" delimiter but still sent JSON ---
        log.warning(f"Intellect model did not use delimiter. Attempting JSON salvage.")
        
        # Use regex to find JSON
        json_match = re.search(r"\{[\s\S]*\}", raw_text)

        if json_match:
            json_part_raw = json_match.group(0).strip()
            answer = raw_text[:json_match.start()].strip() # Everything BEFORE the JSON
            
            json_obj = robust_json_parse(json_part_raw, log)
            reflection = json_obj.get("reflection", "Parsed reflection from regex search.").strip()

            if not answer:
                answer = f"[Answer missing, model only sent JSON: {json_part_raw}]"

        else:
            # --- Priority 3: Model sent raw text (This is the fallback you saw) ---
            log.warning(f"No JSON or delimiter found in Intellect response. Salvaging raw text.")
            answer = raw_text.strip()
            reflection = "Salvaged raw output; model failed to format."

    # Final check to prevent empty answers
    if not answer.strip():
        answer = "[Model returned an empty answer]"
        reflection = reflection or "Model returned empty answer."

    return answer.replace("\\n", "\n"), reflection.replace("\\n", "\n")

def parse_will_response(raw_text: str, log: "logging.Logger") -> Tuple[str, str]:
    """
    Parses the {"decision": "...", "reason": "..."} format from Will.

    Args:
        raw_text: The raw string response from the Will model.
        log: A logger instance.

    Returns:
        A tuple of (decision, reason). Guarantees a valid decision.
    """
    obj = robust_json_parse(raw_text, log)
    
    if "error" in obj:
        # If parsing fails, default to a violation
        return ("violation", "Internal evaluation error (JSON parse failed)")
        
    decision = str(obj.get("decision") or "").strip().lower()
    reason = (obj.get("reason") or "").strip()
    
    if decision not in {"approve", "violation"}:
        decision = "violation"
        
    if not reason:
        reason = "Decision explained by Will policies and the active value set."
        
    return decision, reason

def parse_conscience_response(raw_text: str, log: "logging.Logger") -> List[Dict[str, Any]]:
    """
    Parses the {"evaluations": [...]} format from Conscience.

    Args:
        raw_text: The raw string response from the Conscience model.
        log: A logger instance.

    Returns:
        A list of evaluation dictionaries. Returns an empty list on failure.
    """
    obj = robust_json_parse(raw_text, log)
    
    if "error" in obj:
        return [] # Return an empty list if parsing failed
    
    evaluations = obj.get("evaluations", [])
    if not isinstance(evaluations, list):
        log.error(f"Conscience 'evaluations' was not a list. Got: {type(evaluations)}")
        return []

    return evaluations