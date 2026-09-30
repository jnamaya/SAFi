"""The ONLY place that knows how to parse raw, unreliable string/JSON output
from different LLMs. Faculty callers should never touch a model's bytes."""
from __future__ import annotations
import json
import re
import logging
from typing import List, Dict, Any, Tuple, Optional, TYPE_CHECKING

# Vestigial: `logging` is imported unconditionally above, so this block is a
# no-op left over from an earlier import structure. Kept because the type
# hints below quote it as "logging.Logger".
if TYPE_CHECKING:
    import logging

def robust_json_parse(raw_text: str, log: "logging.Logger") -> Dict[str, Any]:
    """First valid JSON object in a raw text string, or an error dict.

    Success and failure are both dicts: on failure the caller gets
    {"error", "raw_content"} and can branch on the "error" key rather than
    handling an exception. Escalating repairs run in order of destructiveness.
    """
    obj = {}
    if not raw_text:
        return {"error": "Empty input"}

    json_text = raw_text 

    # A ```json fence is unwrapped BEFORE brace-scanning, or the `{` in a
    # prose preamble gets taken as the start of the object.
    if "```" in raw_text:
        parts = raw_text.split("```")   # [preamble, code, postamble]
        if len(parts) >= 3:
            candidate = parts[1]
            if candidate.startswith("json"):
                candidate = candidate[4:]
            json_text = candidate.strip()
            
    start = json_text.find('{')
    end = json_text.rfind('}')
    
    if start != -1 and end != -1 and end > start:
        json_text = json_text[start:end+1]
    
    try:
        obj = json.loads(json_text)
        return obj
    except json.JSONDecodeError:
        pass

    # Sanitized retry: newline flattening, trailing commas, whitespace runs.
    try:
        sanitized = json_text.replace("\r", " ").replace("\n", " ")
        sanitized = re.sub(r",\s*([}\]])", r"\1", sanitized) 
        sanitized = re.sub(r"\s{2,}", " ", sanitized).strip()
        
        obj = json.loads(sanitized)
        return obj
    except json.JSONDecodeError:
        pass

    # Invalid-escape repair.
    # Models embed LaTeX inside JSON strings — \( t \), \alpha, \[ ... \] —
    # and those backslash sequences are not legal JSON escapes, so one math
    # marker kills the whole parse (observed leaking Intellect reflections to
    # the frontend). Double any backslash that doesn't start a valid JSON
    # escape and retry.
    try:
        repaired = re.sub(r'\\(?!["\\/bfnrtu])', r'\\\\', sanitized)
        obj = json.loads(repaired)
        return obj
    except json.JSONDecodeError:
        log.warning(f"Robust JSON parse failed. Content start: {json_text[:100]}...")
        return {"error": "JSONDecodeError", "raw_content": raw_text}

# --- faculty parsers ----------------------------------------------------------

def parse_intellect_response(raw_text: str, log: "logging.Logger") -> Tuple[str, str, Optional[Dict[str, Any]]]:
    """Split the Intellect's "Answer---REFLECTION---{...}" output.

    The strategies below are tried in order; each is more permissive than the
    last, so an earlier one must never accept a worse parse. Returns
    (answer, reflection, gemini_raw_turn_or_None).
    """
    answer = ""
    reflection = ""
    delimiter_text = "---REFLECTION---"

    clean_text = raw_text.strip()

    # Normalize delimiter variants produced by models that drop the leading or trailing dashes
    # e.g. Mistral outputs "REFLECTION---" instead of "---REFLECTION---"
    for variant in (r"\bREFLECTION---", r"---REFLECTION\b"):
        if re.search(variant, clean_text) and delimiter_text not in clean_text:
            clean_text = re.sub(variant, delimiter_text, clean_text)
            break

    # --- Strategy 1: explicit delimiter ---
    if delimiter_text in clean_text:
        parts = clean_text.split(delimiter_text)
        answer = parts[0].strip()
        json_part_raw = parts[-1].strip()
        
        json_obj = robust_json_parse(json_part_raw, log)
        if "error" not in json_obj:
            ref_val = json_obj.get("reflection")
            reflection = str(ref_val) if ref_val else "Parsed reflection from delimiter."
            return answer, reflection, json_obj.get("_gemini_raw_turn")
    
    # --- Strategy 2: implicit reflection JSON, no delimiter ---
    # Non-recursive and good enough for the flat objects agents emit: find the
    # "reflection" key, then walk back to the nearest '{' before it and treat
    # everything from there as the object. The LAST such block wins, since a
    # chatty model may mention the word earlier in its prose.
    last_brace_idx = clean_text.rfind("}")
    if last_brace_idx != -1:
        # 2a. markdown block
        code_block_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", clean_text, re.DOTALL | re.IGNORECASE)
        if code_block_match:
            json_candidate = code_block_match.group(1)
            json_obj = robust_json_parse(json_candidate, log)
            if "error" not in json_obj and "reflection" in json_obj:
                reflection = str(json_obj["reflection"])
                answer = clean_text[:code_block_match.start()].strip()
                # A delimiter survived Strategy 1 only because its JSON failed
                # to parse; strip it from the answer rather than showing it.
                answer = answer.replace(delimiter_text, "").strip()
                return answer, reflection, json_obj.get("_gemini_raw_turn")

        # 2b. raw JSON at end of text
        ref_key_match = re.search(r'["\']reflection["\']\s*:', clean_text)
        if ref_key_match:
            start_search = clean_text.rfind("{", 0, ref_key_match.start() + 1)
            if start_search != -1:
                json_candidate = clean_text[start_search:]
                json_obj = robust_json_parse(json_candidate, log)
                if "error" not in json_obj:
                     reflection = str(json_obj.get("reflection", "Parsed implicit JSON."))
                     answer = clean_text[:start_search].strip()
                     answer = answer.replace(delimiter_text, "").strip()
                     return answer, reflection, json_obj.get("_gemini_raw_turn")

    # --- Strategy 3a: salvage an unparseable reflection blob ---
    # A "reflection": key is present but Strategies 1/2 couldn't parse its
    # JSON (malformed beyond even escape repair). NEVER ship the blob to the
    # user — it can contain internal governance coaching from reflexion
    # retries. Cut the answer at the blob's opening brace and keep the raw
    # blob text as the reflection. An empty remaining answer is returned
    # as-is so run_intellect's contentless-answer retry resamples the model.
    ref_key_match = re.search(r'["\']reflection["\']\s*:', clean_text)
    if ref_key_match:
        blob_start = clean_text.rfind("{", 0, ref_key_match.start() + 1)
        if blob_start != -1:
            answer = clean_text[:blob_start].replace(delimiter_text, "").strip()
            reflection = clean_text[blob_start:].strip()
            log.warning("parse_intellect_response: Strategy 3 salvage — stripped unparseable reflection blob from answer.")
            return answer.replace("\\n", "\n"), reflection, None

    # --- Strategy 3b: raw text fallback ---
    answer = re.sub(r'-*REFLECTION-*', '', clean_text).strip()
    log.info("parse_intellect_response: Strategy 3 fallback — model omitted reflection format.")

    if not answer:
        answer = "[Model returned empty answer]"

    return answer.replace("\\n", "\n"), "", None

def parse_will_response(raw_text: str, log: "logging.Logger") -> Tuple[str, str]:
    """Parse the Will's {"decision": ..., "reason": ...}.

    JSON first, regex second, and an unreadable answer fails CLOSED to
    "violation" — the Will's default is the safe direction, not the neutral one.
    """
    obj = robust_json_parse(raw_text, log)
    
    decision = ""
    reason = ""

    if "error" not in obj:
        decision = str(obj.get("decision") or obj.get("Decision") or "").strip().lower()
        reason = (obj.get("reason") or obj.get("Reason") or "").strip()
    
    # Regex fallback when JSON failed or yielded empty keys.
    if not decision or "error" in obj:
        log.info("JSON parse failed for Will. Attempting Regex fallback.")
        
        d_match = re.search(r'(?:["\']?decision["\']?|\bdecision\b)\s*[:=]\s*["\']?(\w+)["\']?', raw_text, re.IGNORECASE)
        r_match = re.search(r'(?:["\']?reason["\']?|\breason\b)\s*[:=]\s*["\']?([^"}\n\r]+)["\']?', raw_text, re.IGNORECASE)
        
        if d_match:
            decision = d_match.group(1).lower()
        if r_match:
            reason = r_match.group(1).strip()

    if decision not in {"approve", "violation"}:
        # Last resort, still fail-safe: any hint of a block is a block.
        if "violation" in raw_text.lower() or "block" in raw_text.lower():
            decision = "violation"
        elif "approve" in raw_text.lower():
            decision = "approve"
        else:
            decision = "violation" # Fail safe
            if not reason:
                reason = "Internal Error: Model output unreadable. Blocking for safety."

    if not reason:
        # A model that decided but would not format may have chattered instead.
        # Only short text is accepted as the reason; a long one is prose the
        # user should see, not a justification to attribute to the Will.
        clean_text = raw_text.replace("{", "").replace("}", "").strip()
        if len(clean_text) < 200:
            reason = clean_text
        else:
            reason = "Decision explained by Will policies (reason missing in parsed output)."
        
    return decision, reason

def parse_conscience_response(raw_text: str, log: "logging.Logger") -> List[Dict[str, Any]]:
    """Parse the Conscience's {"evaluations": [...]}. Never raises: the caller
    must always have a scorable entry."""
    obj = robust_json_parse(raw_text, log)
    
    if "error" in obj:
        # The model may have returned the bare list instead of the wrapper.
        list_match = re.search(r"\[.*\]", raw_text, re.DOTALL)
        if list_match:
            try:
                possible_list = json.loads(list_match.group(0))
                if isinstance(possible_list, list):
                    return possible_list
            except:
                pass
        # Return a neutral evaluation so Spirit has a scorable entry and
        # doesn't fall back to "Ledger missing". Score 0.0 (neutral) is
        # safer than 1.0 (which would reward a failed evaluation).
        log.warning(f"parse_conscience_response: JSON parse failed; returning neutral evaluation. Raw: {raw_text[:120]!r}")
        return [{
            "value": "Evaluation Quality",
            "score": 0.0,
            "reason": "Conscience returned a non-JSON response; neutral score applied. Check model output above."
        }]
    
    evaluations = obj.get("evaluations", [])
    
    if not evaluations and isinstance(obj, list):
        evaluations = obj

    if not isinstance(evaluations, list):
        log.error(f"Conscience 'evaluations' was not a list. Got: {type(evaluations)}")
        return [{"error": f"Conscience 'evaluations' was not a list."}]

    return evaluations