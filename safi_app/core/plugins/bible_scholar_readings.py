import logging
import httpx
from bs4 import BeautifulSoup
from typing import Optional, Dict, Any, Tuple

async def handle_bible_scholar_commands(
    user_prompt: str, 
    active_profile_name: str, 
    log: logging.Logger
) -> Tuple[str, Optional[Dict[str, Any]]]:
    """
    Checks for 'bible scholar' profile-specific commands (like 'daily readings')
    and fetches data from an external source if a command is detected.
    
    Returns the (potentially modified) user_prompt and any fetched readings data.
    """
    
    last_readings_data = None
    original_user_prompt = user_prompt # Keep a copy
    
    # We check for a specific command keyword
    prompt_command = user_prompt.strip().lower()

    # Enhanced: Support multiple command variations
    daily_readings_commands = ["daily readings synthesis", "readings synthesis", "mass readings synthesis", "synthesis"]
    individual_reading_commands = ["first reading", "second reading", "gospel", "gospel reading"]
    
    # --- Handle individual reading requests ---
    if any(cmd in prompt_command for cmd in individual_reading_commands):
        
        if active_profile_name == "the bible scholar":
            log.info(f"Individual reading request detected: '{user_prompt}'")
            
            try:
                url = "https://beholdvancouver.org/services/daily-mass-readings"
                headers = {
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
                }

                async with httpx.AsyncClient(timeout=15.0) as client:
                    resp = await client.get(url, headers=headers, follow_redirects=True)
                    resp.raise_for_status()
                
                html_content = resp.text
                soup = BeautifulSoup(html_content, "html.parser")
                
                # Extract the date
                page_title = soup.find("h1", class_="page-title")
                reading_date = page_title.get_text(strip=True) if page_title else "Daily Readings"
                
                container = soup.find("div", class_="page-body")
                
                if not container:
                    log.warning(f"BeholdVancouver scrape found no 'page-body' container.")
                    user_prompt = "I tried to fetch the reading, but couldn't find the content on the page."
                else:
                    elements = container.find_all(['h4', 'div'])
                    current_title = ""
                    current_citation = ""
                    found_reading = None
                    
                    # Determine which reading the user wants
                    requested_reading = None
                    if "first reading" in prompt_command:
                        requested_reading = "First Reading"
                    elif "second reading" in prompt_command:
                        requested_reading = "Second Reading"
                    elif "gospel" in prompt_command:
                        requested_reading = "Gospel"
                    
                    for el in elements:
                        classes = el.get('class', [])
                        
                        if 'secondary-font' in classes and 'mb-2' in classes:
                            current_title = el.get_text(strip=True)
                        
                        elif el.name == 'h4' and 'mb-4' in classes:
                            current_citation = el.get_text(strip=True)
                        
                        elif 'tertiary-font' in classes:
                            if current_title == requested_reading and current_citation:
                                text = el.get_text(separator="\n", strip=True)
                                found_reading = {
                                    "title": current_title,
                                    "citation": current_citation,
                                    "text": text
                                }
                                break  # Found what we need, stop searching
                            
                            current_title = ""
                            current_citation = ""
                    
                    if found_reading:
                        # Format the individual reading with appropriate title
                        formatted_output = f"{found_reading['title']} - {reading_date}\n\n"
                        formatted_output += found_reading['citation']
                        
                        user_prompt = formatted_output
                        log.info(f"Successfully fetched {requested_reading} from BeholdVancouver.")
                    else:
                        user_prompt = f"I couldn't find the {requested_reading} for today. The page structure may have changed."
            
            except httpx.TimeoutException:
                log.error(f"Timeout while fetching reading from BeholdVancouver")
                user_prompt = "I tried to fetch the reading, but the request timed out. Please try again."
            except httpx.HTTPError as e:
                log.error(f"HTTP error while fetching reading: {e}")
                user_prompt = f"I encountered a network error while fetching the reading: {str(e)}"
            except Exception as e:
                log.exception(f"Unexpected error fetching reading from BeholdVancouver")
                user_prompt = f"I tried to fetch the reading, but an unexpected error occurred: {str(e)}"
        
        else:
            log.info(f"Reading request '{user_prompt}' detected, but active profile is '{active_profile_name}'. Passing through to Intellect.")
            # If not the bible scholar, we don't modify the prompt
            return original_user_prompt, None
    
    # --- Handle request for all readings (citations only) ---
    elif prompt_command in daily_readings_commands:
        
        if active_profile_name == "the bible scholar":
            
            log.info(f"'{user_prompt}' command detected for '{active_profile_name}'. Fetching from beholdvancouver.org...")
            
            try:
                url = "https://beholdvancouver.org/services/daily-mass-readings"
                
                headers = {
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
                } 

                async with httpx.AsyncClient(timeout=15.0) as client:
                    resp = await client.get(url, headers=headers, follow_redirects=True)
                    resp.raise_for_status()
                
                html_content = resp.text
                soup = BeautifulSoup(html_content, "html.parser")
                
                # Extract the date from the page title
                page_title = soup.find("h1", class_="page-title")
                reading_date = page_title.get_text(strip=True) if page_title else "Daily Readings"
                
                container = soup.find("div", class_="page-body")
                
                if not container:
                    log.warning(f"BeholdVancouver scrape found no 'page-body' container. URL: {url}")
                    user_prompt = "I tried to fetch the daily readings, but couldn't find the main content on the page."
                else:
                    elements = container.find_all(['h4', 'div'])
                    readings = []
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
                                # Store without the title label, just the citation
                                readings.append(current_citation)
                                
                                text = el.get_text(separator="\n", strip=True)
                                full_passages.append({
                                    "title": current_title,
                                    "citation": current_citation,
                                    "text": text
                                })
                                
                                current_title = ""
                                current_citation = ""
                    
                    if not readings:
                        log.warning(f"BeholdVancouver scrape found the 'page-body' but no readings inside.")
                        user_prompt = "I tried to fetch the daily readings, but the page formatting seemed to be empty."
                    else:
                        formatted_output = f"📖 {reading_date}\n\n"
                        for reading in readings:
                            formatted_output += f"• {reading}\n"
                        formatted_output += "\nPlease provide a scholarly synthesis of these three passages."
                        
                        user_prompt = formatted_output
                        
                        last_readings_data = {
                            "date": reading_date,
                            "citations": readings,
                            "full_passages": full_passages,
                            "url": url
                        }
                        
                        log.info(f"Successfully fetched {len(readings)} reading citations from BeholdVancouver for {reading_date}.")

            except httpx.TimeoutException:
                log.error(f"Timeout while fetching daily readings from BeholdVancouver")
                user_prompt = "I tried to fetch the daily readings, but the request timed out. Please try again."
            except httpx.HTTPError as e:
                log.error(f"HTTP error while fetching daily readings: {e}")
                user_prompt = f"I encountered a network error while fetching the daily readings: {str(e)}"
            except Exception as e:
                log.exception(f"Unexpected error fetching daily readings from BeholdVancouver")
                user_prompt = f"I tried to fetch the daily readings, but an unexpected error occurred: {str(e)}"
        
        else:
            log.info(f"'{user_prompt}' command detected, but active profile is '{active_profile_name}'. Skipping API call.")
            # If not the bible scholar, we don't modify the prompt
            return original_user_prompt, None

    else:
        # No command detected, return the original prompt
        return original_user_prompt, None

    # If we reached here, a command was processed (or failed)
    # user_prompt variable holds the new prompt (or error message)
    # last_readings_data holds the data if successful
    return user_prompt, last_readings_data