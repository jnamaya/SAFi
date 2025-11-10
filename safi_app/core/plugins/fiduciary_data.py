import logging
import re
import yfinance as yf
from typing import Optional, Dict, Any, Tuple
from openai import AsyncOpenAI

# This regex is 100% correct for "price of apple"
TICKER_COMMAND_REGEX = re.compile(
    r'(?:stock info for|get quote for|price of|stock data for|info about|data on|info on)\s+\$?([A-Za-z0.9. -]{1,30})\s*(?:stock)?',
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

async def _find_ticker_with_llm(
    entity_name: str, 
    groq_client: AsyncOpenAI, 
    log: logging.Logger
) -> Optional[str]:
    if not groq_client:
        log.warning("LLM Ticker Finder: No Groq client provided. Skipping.")
        return None
    try:
        prompt = f"What is the official stock ticker symbol for the company '{entity_name}'? Respond with ONLY the ticker symbol and nothing else (e.g., 'AAPL', 'GOOGL', 'KO')."
        resp = await groq_client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            max_tokens=10
        )
        ticker = resp.choices[0].message.content.strip().upper()
        if 20 > len(ticker) > 0 and not " " in ticker:
            log.info(f"LLM Ticker Finder: Found ticker '{ticker}' for entity '{entity_name}'")
            return ticker
        else:
            log.warning(f"LLM Ticker Finder: Got invalid response '{ticker}' for '{entity_name}'")
            return None
    except Exception as e:
        log.error(f"LLM Ticker Finder: Error during API call: {e}")
        return None

async def handle_fiduciary_commands(
    user_prompt: str, 
    active_profile_name: str, 
    log: logging.Logger,
    groq_client: Optional[AsyncOpenAI] = None,
) -> Tuple[str, Optional[Dict[str, Any]]]:
    
    # ----------------------------------------------------
    # TEST STEP 1: IS THIS NEW FILE BEING EXECUTED AT ALL?
    # ----------------------------------------------------
    log.info("--- FIDUCIARY PLUGIN (BACKEND TEST V4): FILE LOADED ---")
    # ----------------------------------------------------

    # This plugin only runs for 'The Fiduciary'
    if active_profile_name != "the fiduciary":
        log.warning(f"--- Fiduciary Plugin: Exiting. Persona did not match. (Expected 'the fiduciary', got '{active_profile_name}') ---")
        return user_prompt, None

    # ----------------------------------------------------
    # TEST STEP 2: DID THE PERSONA CHECK PASS?
    # ----------------------------------------------------
    log.info("--- Fiduciary Plugin: Persona match confirmed. Checking regex... ---")
    # ----------------------------------------------------
    
    match = TICKER_COMMAND_REGEX.search(user_prompt)
    
    if not match:
        log.warning(f"--- Fiduciary Plugin: Exiting. Regex did not match prompt: '{user_prompt}' ---")
        return user_prompt, None

    # ----------------------------------------------------
    # TEST STEP 3: DID THE REGEX CHECK PASS?
    # ----------------------------------------------------
    log.info("--- Fiduciary Plugin: Regex match confirmed. Proceeding to fetch data. ---")
    # ----------------------------------------------------

    requested_entity = match.group(1).lower().strip()
    ticker_to_fetch = None

    ticker_to_fetch = COMMON_NAME_TO_TICKER.get(requested_entity)
    
    if not ticker_to_fetch and groq_client:
        log.info(f"'{requested_entity}' not in local dict. Querying LLM Ticker Finder.")
        ticker_to_fetch = await _find_ticker_with_llm(
            requested_entity, groq_client, log
        )
    
    if not ticker_to_fetch:
        ticker_to_fetch = requested_entity.upper()
    
    log.info(f"Fiduciary command detected: User asked for '{requested_entity}', looking up ticker '{ticker_to_fetch}'")

    try:
        ticker_obj = yf.Ticker(ticker_to_fetch)
        info = ticker_obj.info
        
        if not info or 'regularMarketPrice' not in info:
             raise ValueError(f"No valid data found for entity: {requested_entity} (as {ticker_to_fetch})")
        
        confirmed_symbol = info.get('symbol', ticker_to_fetch)

        safe_data = {
            "Company Name": info.get('longName'),
            "Ticker Symbol": confirmed_symbol,
            "Current Price": info.get('regularMarketPrice'),
            "Previous Close": info.get('previousClose'),
            "Day's Range": f"{info.get('dayLow', 'N/A')} - {info.get('dayHigh', 'N/A')}",
            "52-Week Range": f"{info.get('fiftyTwoWeekLow', 'N/A')} - {info.get('fiftyTwoWeekHigh', 'N/A')}",
            "Volume": info.get('volume'),
            "Market Cap": info.get('marketCap'),
            "P/E Ratio (TTM)": info.get('trailingPE'),
            "Dividend Yield": info.get('dividendYield')
        }
        
        log.info(f"Successfully fetched data for {confirmed_symbol}.")
        return user_prompt, {"stock_data": safe_data}

    except Exception as e:
        log.error(f"Error fetching data for entity '{requested_entity}' (as {ticker_to_fetch}): {e}")
        error_payload = {"plugin_error": f"I tried to look up '{requested_entity}' but couldn't find any data. It might be an invalid symbol."}
        return user_prompt, error_payload