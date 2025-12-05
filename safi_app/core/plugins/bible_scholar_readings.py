import logging
import httpx
from bs4 import BeautifulSoup
from typing import Optional, Dict, Any, Tuple

async def _fetch_readings_from_source(log: logging.Logger) -> Dict[str, Any]:
    """
    Internal helper to scrape the readings source.
    Returns a dictionary with 'date' and 'passages' or an 'error'.
    """
    try:
        url = "https://beholdvancouver.org/services/daily-mass-readings"
        # FIX: More robust User-Agent
        headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, headers=headers, follow_redirects=True)
            resp.raise_for_status()
        
        html_content = resp.text
        soup = BeautifulSoup(html_content, "html.parser")
        
        page_title = soup.find("h1", class_="page-title")
        reading_date = page_title.get_text(strip=True) if page_title else "Daily Readings"
        
        container = soup.find("div", class_="page-body")
        
        if not container:
            log.warning(f"BeholdVancouver scrape found no 'page-body' container.")
            return {"error": "I tried to fetch the readings, but couldn't find the content on the page."}

        elements = container.find_all(['h4', 'div'])
        full_passages = []
        current_title = ""
        current_citation = ""
        allowed_titles = ["First Reading", "Second Reading", "Gospel"]

        for el in elements:
            classes = el.get('class', [])
            
            if 'secondary-font' in classes and 'mb-2' in classes:
                current_title = el.get_text(strip=True)
            
            elif el.name == 'h4' and 'mb-4' in classes:
                current_citation = el.get_text(strip=True)
            
            elif 'tertiary-font' in classes:
                if current_title in allowed_titles and current_citation:
                    # We scrape the text but will DISCARD it later,
                    # as we only want the citation for the RAG.
                    text = el.get_text(separator="\n", strip=True)
                    full_passages.append({
                        "title": current_title,
                        "citation": current_citation,
                        "text": text # This text will be discarded
                    })
                    current_title = ""
                    current_citation = ""
        
        if not full_passages:
            log.warning(f"BeholdVancouver scrape found 'page-body' but no readings.")
            return {"error": "I tried to fetch the daily readings, but the page formatting seemed to be empty."}

        log.info(f"Successfully fetched {len(full_passages)} passages from BeholdVancouver for {reading_date}.")
        return {
            "date": reading_date,
            "full_passages": full_passages,
            "url": url
        }

    except httpx.TimeoutException as e:
        log.error(f"Timeout while fetching readings from BeholdVancouver: {e}")
        return {"error": "I tried to fetch the readings, but the request timed out. Please try again."}
    except httpx.HTTPError as e:
        log.error(f"HTTP error while fetching readings: {e}")
        return {"error": f"I encountered a network error while fetching the readings: {str(e)}"}
    except Exception as e:
        log.exception(f"Unexpected error fetching readings from BeholdVancouver")
        return {"error": f"I tried to fetch the readings, but an unexpected error occurred: {str(e)}"}


async def handle_bible_scholar_commands(
    user_prompt: str, 
    active_profile_name: str, 
    log: logging.Logger
) -> Tuple[str, Optional[Dict[str, Any]]]:
    """
    Checks for 'bible scholar' profile-specific commands.
    If a command is detected, it returns a generic data payload
    for faculties.py to consume.
    
    Returns the ORIGINAL user_prompt and a dictionary of fetched data (or None).
    """
    
    # This plugin only runs for 'the bible scholar'
    if active_profile_name != "the bible scholar":
        return user_prompt, None

    original_user_prompt = user_prompt
    prompt_command = user_prompt.strip().lower()

    individual_reading_commands = ["first reading", "second reading", "gospel", "gospel reading"]
    
    data_payload = None

    if any(cmd in prompt_command for cmd in individual_reading_commands):
        log.info(f"Individual reading request detected: '{user_prompt}'")
        
        scraped_data = await _fetch_readings_from_source(log)
        
        if "error" in scraped_data:
            data_payload = {"plugin_error": scraped_data["error"]}
        else:
            # Find the specific reading the user asked for
            requested_reading_key = None
            if "first reading" in prompt_command:
                requested_reading_key = "First Reading"
            elif "second reading" in prompt_command:
                requested_reading_key = "Second Reading"
            elif "gospel" in prompt_command:
                requested_reading_key = "Gospel"

            found_passage = None
            if requested_reading_key:
                for passage in scraped_data.get("full_passages", []):
                    if passage.get("title") == requested_reading_key:
                        found_passage = passage
                        break
            
            if found_passage:
                # *** THIS IS THE KEY CHANGE ***
                # We build a GENERIC payload. We do NOT pass the
                # external 'text' field, forcing the RAG to do the work.
                data_payload = {
                    # Generic key to override the RAG search query
                    "rag_query_override": found_passage.get("citation"),
                    
                    # Generic key for a string to inject into the prompt
                    "preformatted_context_string": f"CONTEXT: The user is asking for the '{found_passage.get('title')}' for {scraped_data.get('date', 'today')}, which is {found_passage.get('citation')}. The RAG system has been provided with this text."
                }
            else:
                error_msg = f"I found the readings for today, but couldn't find a specific '{requested_reading_key}'."
                data_payload = {"plugin_error": error_msg}

    # If no command matched, data_payload is still None
    # Return the original prompt and the data payload (or None)
    return original_user_prompt, data_payload