from __future__ import annotations
import json
import re
import logging
import uuid
from typing import List, Dict, Any, Tuple, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    import logging

def robust_json_parse(raw_text: str, log: "logging.Logger") -> Dict[str, Any]:
    obj = {}
    if not raw_text:
        return {"error": "Empty input"}

    json_text = raw_text.strip()

    if json_text.startswith("```"):
        m_fence = re.match(r"^```(?:json)?\s*(\{.*\})\s*```\s*$", json_text, re.DOTALL | re.IGNORECASE)
        if m_fence:
            json_text = m_fence.group(1).strip()
        else:
            json_text = re.sub(r"^```(?:json)?\s*", "", json_text, flags=re.IGNORECASE)
            json_text = re.sub(r"\s*```$", "", json_text).strip()
    elif not json_text.startswith("{") and "```" in json_text:
        m_block = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", json_text, re.DOTALL | re.IGNORECASE)
        if m_block:
            json_text = m_block.group(1).strip()

    if json_text.startswith("{"):
        end = json_text.rfind('}')
        if end != -1 and end < len(json_text) - 1:
            json_text = json_text[:end+1]
    else:
        start = json_text.find('{')
        end = json_text.rfind('}')
        if start != -1 and end != -1 and end > start:
            json_text = json_text[start:end+1]
    
    try:
        obj = json.loads(json_text, strict=False)
        return obj
    except (json.JSONDecodeError, TypeError):
        pass

    try:
        no_trailing_commas = re.sub(r",\s*([}\]])", r"\1", json_text)
        obj = json.loads(no_trailing_commas, strict=False)
        return obj
    except (json.JSONDecodeError, TypeError):
        pass

    try:
        repaired = re.sub(r'\\(?!["\\/bfnrtu])', r'\\\\', no_trailing_commas)
        obj = json.loads(repaired, strict=False)
        return obj
    except (json.JSONDecodeError, TypeError):
        pass

    try:
        sanitized = json_text.replace("\r", " ").replace("\n", " ")
        sanitized = re.sub(r",\s*([}\]])", r"\1", sanitized) 
        sanitized = re.sub(r"\s{2,}", " ", sanitized).strip()
        
        obj = json.loads(sanitized, strict=False)
        return obj
    except (json.JSONDecodeError, TypeError):
        pass

    try:
        repaired = re.sub(r'\\(?!["\\/bfnrtu])', r'\\\\', sanitized)
        obj = json.loads(repaired, strict=False)
        return obj
    except (json.JSONDecodeError, TypeError):
        log.warning(f"Robust JSON parse failed. Content start: {json_text[:100]}...")
        return {"error": "JSONDecodeError", "raw_content": raw_text}

def parse_intellect_response(raw_text: str, log: "logging.Logger") -> Tuple[str, str, Optional[Dict[str, Any]]]:
    answer = ""
    reflection = ""
    delimiter_text = "---REFLECTION---"

    clean_text = raw_text.strip()

    for variant in (r"\bREFLECTION---", r"---REFLECTION\b"):
        if re.search(variant, clean_text) and delimiter_text not in clean_text:
            clean_text = re.sub(variant, delimiter_text, clean_text)
            break

    if delimiter_text in clean_text:
        parts = clean_text.split(delimiter_text)
        answer = parts[0].strip()
        json_part_raw = parts[-1].strip()
        
        json_obj = robust_json_parse(json_part_raw, log)
        if "error" not in json_obj:
            ref_val = json_obj.get("reflection")
            reflection = str(ref_val) if ref_val else "Parsed reflection from delimiter."
            return answer, reflection, json_obj.get("_gemini_raw_turn")
    
    last_brace_idx = clean_text.rfind("}")
    if last_brace_idx != -1:
        code_block_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", clean_text, re.DOTALL | re.IGNORECASE)
        if code_block_match:
            json_candidate = code_block_match.group(1)
            json_obj = robust_json_parse(json_candidate, log)
            if "error" not in json_obj and "reflection" in json_obj:
                reflection = str(json_obj["reflection"])
                answer = clean_text[:code_block_match.start()].strip()
                answer = answer.replace(delimiter_text, "").strip()
                return answer, reflection, json_obj.get("_gemini_raw_turn")

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

    ref_key_match = re.search(r'["\']reflection["\']\s*:', clean_text)
    if ref_key_match:
        blob_start = clean_text.rfind("{", 0, ref_key_match.start() + 1)
        if blob_start != -1:
            answer = clean_text[:blob_start].replace(delimiter_text, "").strip()
            reflection = clean_text[blob_start:].strip()
            log.warning("parse_intellect_response: Strategy 3 salvage — stripped unparseable reflection blob from answer.")
            return answer.replace("\\n", "\n"), reflection, None

    answer = re.sub(r'-*REFLECTION-*', '', clean_text).strip()
    log.info("parse_intellect_response: Strategy 3 fallback — model omitted reflection format.")

    if not answer:
        answer = "[Model returned empty answer]"

    return answer.replace("\\n", "\n"), "", None

def parse_will_response(raw_text: str, log: "logging.Logger") -> Tuple[str, str]:
    obj = robust_json_parse(raw_text, log)
    
    decision = ""
    reason = ""

    if "error" not in obj:
        decision = str(obj.get("decision") or obj.get("Decision") or "").strip().lower()
        reason = (obj.get("reason") or obj.get("Reason") or "").strip()
    
    if not decision or "error" in obj:
        log.info("JSON parse failed for Will. Attempting Regex fallback.")
        
        d_match = re.search(r'(?:["\']?decision["\']?|\bdecision\b)\s*[:=]\s*["\']?(\w+)["\']?', raw_text, re.IGNORECASE)
        r_match = re.search(r'(?:["\']?reason["\']?|\breason\b)\s*[:=]\s*["\']?([^"}\n\r]+)["\']?', raw_text, re.IGNORECASE)
        
        if d_match:
            decision = d_match.group(1).lower()
        if r_match:
            reason = r_match.group(1).strip()

    if decision not in {"approve", "violation"}:
        if "violation" in raw_text.lower() or "block" in raw_text.lower():
            decision = "violation"
        elif "approve" in raw_text.lower():
            decision = "approve"
        else:
            decision = "violation"
            if not reason:
                reason = "Internal Error: Model output unreadable. Blocking for safety."

    if not reason:
        clean_text = raw_text.replace("{", "").replace("}", "").strip()
        if len(clean_text) < 200:
            reason = clean_text
        else:
            reason = "Decision explained by Will policies (reason missing in parsed output)."
        
    return decision, reason

def parse_conscience_response(raw_text: str, log: "logging.Logger") -> List[Dict[str, Any]]:
    obj = robust_json_parse(raw_text, log)
    
    if "error" in obj:
        list_match = re.search(r"\[.*\]", raw_text, re.DOTALL)
        if list_match:
            try:
                possible_list = json.loads(list_match.group(0))
                if isinstance(possible_list, list):
                    return possible_list
            except:
                pass
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


def parse_tool_calls_from_text(raw_text: str, log: Optional["logging.Logger"] = None) -> List[Dict[str, Any]]:
    if not raw_text or "<tool_call" not in raw_text:
        return []

    calls: List[Dict[str, Any]] = []
    pattern = re.compile(r"<tool_call>(.*?)(?:</tool_call>|$)", re.DOTALL | re.IGNORECASE)
    matches = pattern.findall(raw_text)

    for block in matches:
        block = block.strip()
        if not block:
            continue

        start = block.find("{")
        end = block.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                candidate = block[start:end + 1]
                data = json.loads(candidate)
                name = data.get("name") or data.get("function")
                args = data.get("arguments") or data.get("parameters") or {}
                if name:
                    calls.append({
                        "id": f"call_salvage_{uuid.uuid4().hex[:8]}",
                        "name": str(name),
                        "arguments": args if isinstance(args, dict) else {"raw": args},
                    })
                    continue
            except Exception:
                pass

        fn_match = re.search(
            r"<function(?:[ =:]|\s+name=)[\"']?([a-zA-Z0-9_\.\-]+)[\"']?>",
            block,
            re.IGNORECASE,
        )
        if fn_match:
            fn_name = fn_match.group(1)
            params: Dict[str, Any] = {}
            param_matches = re.finditer(
                r"<parameter(?:[ =:]|\s+name=)[\"']?([a-zA-Z0-9_\.\-]+)[\"']?>([\s\S]*?)(?:</parameter>|(?=<parameter)|(?=</function>)|$)",
                block,
                re.IGNORECASE,
            )
            for pm in param_matches:
                p_name = pm.group(1)
                p_val = pm.group(2).strip()
                if (p_val.startswith("{") and p_val.endswith("}")) or (
                    p_val.startswith("[") and p_val.endswith("]")
                ):
                    try:
                        p_val = json.loads(p_val)
                    except Exception:
                        pass
                params[p_name] = p_val

            calls.append({
                "id": f"call_salvage_{uuid.uuid4().hex[:8]}",
                "name": fn_name,
                "arguments": params,
            })

    if calls and log:
        log.info(f"parse_tool_calls_from_text: Successfully salvaged {len(calls)} tool call(s) from XML tags.")

    return calls


def salvage_tool_call_arguments(
    tool_name: str,
    raw_args: str,
    log: Optional["logging.Logger"] = None,
) -> Optional[Dict[str, Any]]:
    if not raw_args:
        return None

    norm_tool = (tool_name or "").strip().lower()

    if norm_tool in ("bash", "sh", "shell"):
        text = raw_args.strip()

        m_json_cmd = re.search(r'["\'](?:command|cmd)["\']\s*:\s*["\'](.*)["\']\s*\}?\s*$', text, re.DOTALL)
        if m_json_cmd:
            cmd = m_json_cmd.group(1).strip()
            if cmd:
                if log:
                    log.info("salvage_tool_call_arguments: salvaged command from broken JSON for '%s'", tool_name)
                return {"command": cmd}

        if "```" in text:
            m_fence = re.search(r"```(?:bash|sh|shell|zsh|dotenv|env)?\s*(.*?)\s*```", text, re.DOTALL | re.IGNORECASE)
            if m_fence:
                text = m_fence.group(1).strip()
            else:
                text = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", text).strip()
                text = re.sub(r"\s*```$", "", text).strip()

        text = re.sub(r"^(?:bash|sh|shell|zsh|dotenv|env)[\r\n\s]+", "", text, flags=re.IGNORECASE).strip()

        if text:
            if log:
                log.info("salvage_tool_call_arguments: salvaged raw shell script into {'command': ...} for '%s'", tool_name)
            return {"command": text}
        return None

    if norm_tool in ("read", "list", "read_file"):
        text = raw_args.strip()
        m_path = re.search(r'["\'](?:path|filePath)["\']\s*:\s*["\']([^"\']+)["\']', text)
        if m_path:
            return {"path": m_path.group(1).strip()}
        cleaned = text.strip("'\"` \t\r\n")
        if cleaned and "\n" not in cleaned and "{" not in cleaned and "}" not in cleaned:
            if log:
                log.info("salvage_tool_call_arguments: salvaged raw path for '%s'", tool_name)
            return {"path": cleaned}
        return None

    if norm_tool in ("glob", "glob_files"):
        text = raw_args.strip()
        m_pat = re.search(r'["\']pattern["\']\s*:\s*["\']([^"\']+)["\']', text)
        if m_pat:
            return {"pattern": m_pat.group(1).strip()}
        cleaned = text.strip("'\"` \t\r\n")
        if cleaned and "\n" not in cleaned and "{" not in cleaned:
            return {"pattern": cleaned}
        return None

    if norm_tool in ("grep", "grep_files"):
        text = raw_args.strip()
        m_pat = re.search(r'["\']pattern["\']\s*:\s*["\']([^"\']+)["\']', text)
        if m_pat:
            res: Dict[str, Any] = {"pattern": m_pat.group(1)}
            m_path = re.search(r'["\'](?:path|search_path)["\']\s*:\s*["\']([^"\']+)["\']', text)
            if m_path:
                res["path"] = m_path.group(1)
            return res
        cleaned = text.strip("'\"` \t\r\n")
        if cleaned and "\n" not in cleaned and "{" not in cleaned:
            return {"pattern": cleaned}
        return None

    if norm_tool in ("write", "write_file"):
        text = raw_args.strip()
        m_path = re.search(r'["\']?(?:filePath|path|file|filename)["\']?\s*[:=]\s*["\']?([^"\'\s,]+)["\']?', text)
        m_content = re.search(r'["\']?(?:content|body|text)["\']?\s*[:=]\s*["\'](.*)["\']\s*\}?\s*$', text, re.DOTALL)
        if m_path and m_content:
            if log:
                log.info("salvage_tool_call_arguments: salvaged write file parameters for '%s'", tool_name)
            return {
                "filePath": m_path.group(1).strip(),
                "content": m_content.group(1),
            }
        return None

    if norm_tool in ("edit", "edit_file"):
        text = raw_args.strip()
        m_path = re.search(r'["\']?(?:filePath|path|file|filename)["\']?\s*[:=]\s*["\']?([^"\'\s,]+)["\']?', text)
        m_old_new = re.search(
            r'["\']?(?:oldString|old_string|old_str|oldText|old)["\']?\s*[:=]\s*["\'](.*?)["\']\s*,\s*'
            r'["\']?(?:newString|new_string|new_str|newText|new)["\']?\s*[:=]\s*["\'](.*)["\']\s*\}?\s*$',
            text,
            re.DOTALL
        )
        if m_path and m_old_new:
            if log:
                log.info("salvage_tool_call_arguments: salvaged edit file parameters for '%s'", tool_name)
            return {
                "filePath": m_path.group(1).strip(),
                "oldString": m_old_new.group(1),
                "newString": m_old_new.group(2),
            }
        return None

    if norm_tool in ("websearch", "web_search"):
        text = raw_args.strip()
        m_q = re.search(r'["\']query["\']\s*:\s*["\'](.*)["\']\s*\}?\s*$', text, re.DOTALL)
        if m_q:
            return {"query": m_q.group(1).strip()}
        cleaned = text.strip("'\"` \t\r\n")
        if cleaned and "{" not in cleaned:
            return {"query": cleaned}
        return None

    if norm_tool in ("webfetch", "web_fetch"):
        text = raw_args.strip()
        m_u = re.search(r'["\']url["\']\s*:\s*["\'](.*)["\']\s*\}?\s*$', text, re.DOTALL)
        if m_u:
            return {"url": m_u.group(1).strip()}
        cleaned = text.strip("'\"` \t\r\n")
        if cleaned and "{" not in cleaned:
            return {"url": cleaned}
        return None

    if norm_tool == "skill":
        text = raw_args.strip()
        m_name = re.search(r'["\']name["\']\s*:\s*["\'](.*)["\']\s*\}?\s*$', text, re.DOTALL)
        if m_name:
            return {"name": m_name.group(1).strip()}
        cleaned = text.strip("'\"` \t\r\n")
        if cleaned and "{" not in cleaned:
            return {"name": cleaned}
        return None

    return None
