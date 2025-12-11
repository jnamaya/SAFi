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
    if not raw_text:
        return {"error": "Empty input"}

    json_text = raw_text 
    
    # 0. STRIP MARKDOWN (Priority)
    # If the model wrapped output in ```json ... ```, extract that inner content first.
    # This avoids catching `{` in the preamble.
    if "```" in raw_text:
        # Try to find ```json ... ``` or just ``` ... ```
        # We split by ``` and take the second element (the code block)
        parts = raw_text.split("```")
        if len(parts) >= 3:
            # parts[0] = preamble, parts[1] = code, parts[2] = postamble
            candidate = parts[1]
            # Strip language identifier if present (e.g. "json\n{...}")
            if candidate.startswith("json"):
                candidate = candidate[4:]
            json_text = candidate.strip()
            
    # 1. Find the first '{' and last '}'
    start = json_text.find('{')
    end = json_text.rfind('}')
    
    if start != -1 and end != -1 and end > start:
        json_text = json_text[start:end+1]
    
    # 2. Try to parse directly
    try:
        obj = json.loads(json_text)
        return obj
    except json.JSONDecodeError:
        pass # Go to sanitization

    # 3. Sanitize and retry
    try:
        # Sanitize common errors:
        # - Remove newlines and carriage returns (turns multiline JSON into single line)
        sanitized = json_text.replace("\r", " ").replace("\n", " ")
        # - Fix trailing commas (e.g., "key": "value",})
        sanitized = re.sub(r",\s*([}\]])", r"\1", sanitized) 
        # - Consolidate excess whitespace
        sanitized = re.sub(r"\s{2,}", " ", sanitized).strip()
        
        obj = json.loads(sanitized)
        return obj
    except json.JSONDecodeError:
        # 4. Deep Fallback: Quote Repair
        # Sometimes models produce: {"reason": "The user said "hello""} -> invalid
        try:
            # Extremely simple heuristic: assume keys are valid, try to ignore quotes in values?
            # Actually, hard to fix generically. We log and return error.
            pass
        except Exception:
            pass

        log.warning(f"Robust JSON parse failed. Content start: {json_text[:100]}...")
        return {"error": "JSONDecodeError", "raw_content": raw_text}

# --- Specific Parsers for Each Faculty ---

def parse_intellect_response(raw_text: str, log: "logging.Logger") -> Tuple[str, str]:
    """
    Parses the "Answer---REFLECTION---{...}" format from Intellect.
    """
    answer = ""
    reflection = ""
    delimiter_text = "---REFLECTION---"

    # --- Run the original robust parsing on the raw_text ---
    if delimiter_text in raw_text:
        # --- Priority 1: Model used the delimiter correctly ---
        parts = raw_text.split(delimiter_text)
        answer = parts[0].strip()
        
        json_part_raw = parts[-1]
        json_obj = robust_json_parse(json_part_raw, log)
        
        # Handle non-string reflection fields
        ref_val = json_obj.get("reflection")
        if isinstance(ref_val, (dict, list)):
             reflection = json.dumps(ref_val, ensure_ascii=False)
        else:
             reflection = str(ref_val if ref_val is not None else "Parsed reflection from delimiter.").strip()

    else:
        # --- Priority 2: Model "forgot" delimiter but sent JSON ---
        # Use regex to find JSON
        json_match = re.search(r"\{[\s\S]*\}", raw_text) # [\s\S] matches newlines

        if json_match:
            json_part_raw = json_match.group(0).strip()
            answer = raw_text[:json_match.start()].strip() # Everything BEFORE the JSON
            
            json_obj = robust_json_parse(json_part_raw, log)
            
            ref_val = json_obj.get("reflection")
            if isinstance(ref_val, (dict, list)):
                 reflection = json.dumps(ref_val, ensure_ascii=False)
            else:
                 reflection = str(ref_val if ref_val is not None else "Parsed reflection from regex search.").strip()

            if not answer:
                answer = f"[Answer missing, model only sent JSON: {json_part_raw}]"

        else:
            # --- Priority 3: Model sent raw text ---
            answer = raw_text.strip()
            reflection = "Salvaged raw output; model failed to format."

    if not answer.strip():
        answer = "[Model returned an empty answer]"
        reflection = "Model returned empty answer."

    return answer.replace("\\n", "\n"), reflection.replace("\\n", "\n")

def parse_will_response(raw_text: str, log: "logging.Logger") -> Tuple[str, str]:
    """
    Parses the {"decision": "...", "reason": "..."} format from Will.
    
    Includes Regex fallback for when the model outputs plain text or invalid JSON.
    """
    # 1. Try Standard JSON Parsing
    obj = robust_json_parse(raw_text, log)
    
    decision = ""
    reason = ""

    if "error" not in obj:
        # Case-insensitive key lookup
        decision = str(obj.get("decision") or obj.get("Decision") or "").strip().lower()
        reason = (obj.get("reason") or obj.get("Reason") or "").strip()
    
    # 2. Fallback: Regex Search if JSON failed or produced empty keys
    if not decision or "error" in obj:
        log.info("JSON parse failed for Will. Attempting Regex fallback.")
        
        # Look for "decision": "value" OR decision: value
        d_match = re.search(r'(?:["\']?decision["\']?|\bdecision\b)\s*[:=]\s*["\']?(\w+)["\']?', raw_text, re.IGNORECASE)
        # Look for "reason": "value" OR reason: value
        # Captures until end of line or next quote
        r_match = re.search(r'(?:["\']?reason["\']?|\breason\b)\s*[:=]\s*["\']?([^"}\n\r]+)["\']?', raw_text, re.IGNORECASE)
        
        if d_match:
            decision = d_match.group(1).lower()
        if r_match:
            reason = r_match.group(1).strip()

    # 3. Validate and Default
    if decision not in {"approve", "violation"}:
        # Aggressive check: if "violation" or "block" appears anywhere, assume violation
        if "violation" in raw_text.lower() or "block" in raw_text.lower():
            decision = "violation"
        elif "approve" in raw_text.lower():
            decision = "approve"
        else:
            decision = "violation" # Fail safe
            if not reason:
                reason = "Internal Error: Model output unreadable. Blocking for safety."

    if not reason:
        # If we have a decision but no reason, try to grab the whole text as reason
        # assuming the model just chattered without formatting.
        clean_text = raw_text.replace("{", "").replace("}", "").strip()
        if len(clean_text) < 200:
            reason = clean_text
        else:
            reason = "Decision explained by Will policies (reason missing in parsed output)."
        
    return decision, reason

def parse_conscience_response(raw_text: str, log: "logging.Logger") -> List[Dict[str, Any]]:
    """
    Parses the {"evaluations": [...]} format from Conscience.
    """
    # Find and parse the JSON blob
    obj = robust_json_parse(raw_text, log)
    
    if "error" in obj:
        # Try to salvage a list if the root object failed but a list exists
        # e.g. model returned just [...] instead of {"evaluations": [...]}
        list_match = re.search(r"\[.*\]", raw_text, re.DOTALL)
        if list_match:
            try:
                possible_list = json.loads(list_match.group(0))
                if isinstance(possible_list, list):
                    return possible_list
            except:
                pass
        return [{"error": "Internal evaluation error (JSON parse failed)"}]
    
    evaluations = obj.get("evaluations", [])
    
    # Handle case where model returns just the list directly
    if not evaluations and isinstance(obj, list):
        evaluations = obj

    if not isinstance(evaluations, list):
        log.error(f"Conscience 'evaluations' was not a list. Got: {type(evaluations)}")
        return [{"error": f"Conscience 'evaluations' was not a list."}]

    return evaluations