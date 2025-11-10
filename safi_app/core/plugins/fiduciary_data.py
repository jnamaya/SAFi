import logging
import re
import yfinance as yf
from typing import Optional, Dict, Any, Tuple, List
from openai import AsyncOpenAI
import json

# Regex for simple natural prompts like "price of apple" or "stock info for AAPL"
TICKER_COMMAND_REGEX = re.compile(
    r'(?:stock info for|get quote for|price of|stock data for|info about|data on|info on)\s+\$?([A-Za-z0-9.\- ]{1,30})\s*(?:stock)?',
    re.IGNORECASE
)

COMMON_NAME_TO_TICKER = {
    "apple": "AAPL",
    "google": "GOOGL",
    "alphabet": "GOOGL",
    "microsoft": "MSFT",
    "amazon": "AMZN",
    "tesla": "TSLA",
    "meta": "META",
    "facebook": "META",
    "nvidia": "NVDA"
}

# --- NEW ---
# Create a simple, dynamic regex of just the common names
# This is a new fallback check
SIMPLE_NAME_REGEX = re.compile(
    r'\b(' + r'|'.join(re.escape(k) for k in COMMON_NAME_TO_TICKER.keys()) + r')\b',
    re.IGNORECASE
)
# --- END NEW ---

async def _find_entities_with_llm(
    prompt: str,
    groq_client: AsyncOpenAI,
    log: logging.Logger
) -> List[str]:
    """
    NEW: Uses an LLM to find company/organization names in a prompt.
    NOW ASKS FOR A COMMA-SEPARATED LIST INSTEAD OF JSON for reliability.
    """
    log.info("--- Fiduciary Plugin: Running LLM Entity Extractor... ---")
    system_prompt = (
        "You are an entity extractor. Your job is to identify companies, organizations, "
        "or stock tickers mentioned in the user's prompt. "
        "Respond with a comma-separated list. "
        "Example: Apple, MSFT, the federal reserve"
        "If no entities are found, respond with the word 'None'."
    )
    
    try:
        resp = await groq_client.chat.completions.create(
            model="llama-3.1-8b-instant", # Use a fast model
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ],
            temperature=0.0,
            max_tokens=100 # Give it a bit more room
        )
        
        result_text = resp.choices[0].message.content.strip()
        
        if result_text.lower() == 'none' or not result_text:
            log.info("--- LLM Entity Extractor found: [] ---")
            return []

        # Parse the comma-separated list
        entities = [e.strip() for e in result_text.split(',') if e.strip()]
        
        log.info(f"--- LLM Entity Extractor found: {entities} ---")
        return entities

    except Exception as e:
        log.error(f"--- LLM Entity Extractor failed: {e} ---")
        return []

async def _find_ticker_with_llm(
    entity_name: str,
    groq_client: AsyncOpenAI,
    log: logging.Logger
) -> Optional[str]:
    """
    Finds a ticker for a single entity name.
    """
    if not groq_client:
        log.warning("LLM Ticker Finder: No Groq client provided. Skipping.")
        return None
        
    # First, check common names dict
    common_ticker = COMMON_NAME_TO_TICKER.get(entity_name.lower())
    if common_ticker:
        log.info(f"LLM Ticker Finder: Found '{common_ticker}' for '{entity_name}' in common dict.")
        return common_ticker
        
    try:
        # If not in dict, ask LLM
        prompt = (
            f"What is the official stock ticker symbol for the company '{entity_name}'? "
            f"If it's not a publicly traded company (e.g., 'the federal reserve'), respond with 'N/A'. "
            f"Otherwise, respond with ONLY the ticker symbol and nothing else (e.g., 'AAPL', 'GOOGL')."
        )
        resp = await groq_client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            max_tokens=10
        )
        ticker = resp.choices[0].message.content.strip().upper()
        
        if 0 < len(ticker) < 20 and " " not in ticker and "N/A" not in ticker:
            log.info(f"LLM Ticker Finder: Found ticker '{ticker}' for entity '{entity_name}'")
            return ticker
            
        log.warning(f"LLM Ticker Finder: Got non-ticker response '{ticker}' for '{entity_name}'")
        return None
    except Exception as e:
        log.error(f"LLM Ticker Finder: Error during API call: {e}")
        return None

async def _get_stock_data(ticker_to_fetch: str, entity_name: str, log: logging.Logger) -> Optional[Dict[str, Any]]:
    """
    Fetches and formats data for a single ticker.
    """
    log.info(f"--- Fiduciary Plugin: Fetching yfinance data for '{ticker_to_fetch}' (from '{entity_name}')... ---")
    try:
        t = yf.Ticker(ticker_to_fetch)
        info = t.info

        if not info or "regularMarketPrice" not in info:
            raise ValueError(f"No valid data found for entity: {entity_name} (as {ticker_to_fetch})")

        confirmed_symbol = info.get("symbol", ticker_to_fetch)

        # Build a safe, explicit field set
        safe_data = {
            "Company Name": info.get("longName") or info.get("shortName"),
            "Ticker Symbol": confirmed_symbol,
            "Current Price": info.get("regularMarketPrice"),
            "Previous Close": info.get("previousClose"),
            "Day's Range": f"{info.get('dayLow', 'N/A')} - {info.get('dayHigh', 'N/A')}",
            "Day Low": info.get('dayLow'), # Add raw numbers for orchestrator
            "Day High": info.get('dayHigh'),
            "52-Week Range": f"{info.get('fiftyTwoWeekLow', 'N/A')} - {info.get('fiftyTwoWeekHigh', 'N/A')}",
            "52 Week Low": info.get('fiftyTwoWeekLow'),
            "52 Week High": info.get('fiftyTwoWeekHigh'),
            "Volume": info.get("volume"),
            "Average Volume": info.get("averageVolume"),
            "Market Cap": info.get("marketCap"),
            "P/E Ratio (TTM)": info.get("trailingPE"),
            "Dividend Yield": info.get("dividendYield"),
            "Beta (5Y Monthly)": info.get("beta"),
            "Analyst Target Price": info.get("targetMeanPrice"), # Renamed key
            "Sector": info.get("sector"),
            "Industry": info.get("industry"),
        }

        log.info(f"--- Fiduciary Plugin: Successfully fetched data for {confirmed_symbol}. ---")
        return safe_data

    except Exception as e:
        log.error(f"--- Fiduciary Plugin: Error fetching data for entity '{entity_name}' (as {ticker_to_fetch}): {e} ---")
        return None


async def handle_fiduciary_commands(
    user_prompt: str,
    active_profile_name: str,
    log: logging.Logger,
    groq_client: Optional[AsyncOpenAI] = None,
) -> Tuple[str, Optional[Dict[str, Any]]]:

    log.info("--- FIDUCIARY PLUGIN (RAG-ENABLED): FILE LOADED ---")

    # Only run for The Fiduciary persona
    if active_profile_name != "the fiduciary":
        log.warning(f"--- Fiduciary Plugin: Exiting. Persona mismatch. ---")
        return user_prompt, None

    if not groq_client:
        log.warning("--- Fiduciary Plugin: Exiting. No Groq client provided for entity extraction. ---")
        return user_prompt, None

    # --- NEW RAG LOGIC ---
    # 1. Find all potential company names in the prompt.
    entities_to_find = await _find_entities_with_llm(user_prompt, groq_client, log)
    
    # --- FALLBACK 1: Check old Regex ---
    if not entities_to_find:
        match = TICKER_COMMAND_REGEX.search(user_prompt)
        if match:
            log.info("--- LLM Extractor found no entities, but Regex matched. Using Regex result. ---")
            entities_to_find = [match.group(1).strip()]
            
    # --- FALLBACK 2: Check simple keyword regex ---
    if not entities_to_find:
        match = SIMPLE_NAME_REGEX.search(user_prompt)
        if match:
            log.info("--- LLM and Regex failed, but Simple Name matched. Using Simple Name result. ---")
            entities_to_find = [match.group(1).strip()]

    if not entities_to_find:
        log.warning(f"--- Fiduciary Plugin: No entities found by LLM or Regexes. Exiting. ---")
        return user_prompt, None # No entities found

    # 2. Find tickers for all found entities.
    tickers_to_fetch = {} # Use dict to avoid duplicates {ticker: entity_name}
    for entity in entities_to_find:
        ticker = await _find_ticker_with_llm(entity, groq_client, log)
        if ticker and ticker not in tickers_to_fetch:
            tickers_to_fetch[ticker] = entity

    if not tickers_to_fetch:
        log.warning(f"--- Fiduciary Plugin: Found entities, but no valid tickers. Exiting. ---")
        return user_prompt, None

    # 3. Fetch data for all valid tickers.
    all_stock_data = []
    for ticker, entity_name in tickers_to_fetch.items():
        data = await _get_stock_data(ticker, entity_name, log)
        if data:
            all_stock_data.append(data)

    if not all_stock_data:
        log.warning(f"--- Fiduciary Plugin: Found tickers, but yfinance fetch failed for all. ---")
        error_payload = {
            "plugin_error": f"I tried to look up {', '.join(entities_to_find)} but couldn't find any valid stock data."
        }
        return user_prompt, error_payload

    # 4. Return the data payload.
    # If we only have one, return it as `stock_data` (object) for backward compatibility.
    # If we have multiple, return as `stock_data_list` (array).
    
    final_payload = {}
    if len(all_stock_data) == 1:
        final_payload["stock_data"] = all_stock_data[0]
        log.info(f"--- Fiduciary Plugin: Returning 'stock_data' (object) for 1 ticker. ---")
    else:
        final_payload["stock_data_list"] = all_stock_data
        log.info(f"--- Fiduciary Plugin: Returning 'stock_data_list' (array) for {len(all_stock_data)} tickers. ---")

    return user_prompt, final_payload