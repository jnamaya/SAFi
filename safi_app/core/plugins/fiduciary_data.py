import logging
import re
import yfinance as yf
from typing import Optional, Dict, Any, Tuple, List
from datetime import datetime
from openai import AsyncOpenAI
import json
import os

# --- START FIX ---
# Define a cache location everyone can write to
cache_dir = "/var/www/safi/cache/py-yfinance-cache"

# Create it if it doesn't exist
if not os.path.exists(cache_dir):
    try:
        os.makedirs(cache_dir)
    except OSError as e:
        # Log this, but don't crash the app
        print(f"Warning: Could not create cache directory '{cache_dir}'. Reason: {e}")

# Tell yfinance to use this location INSTEAD of the default
try:
    yf.set_tz_cache_location(cache_dir)
except Exception as e:
     print(f"Warning: Failed to set yfinance cache location. Reason: {e}")
# --- END FIX ---


# Regex for simple natural prompts like "price of apple" or "stock info for AAPL"
ENTITY_REGEXES = [
    r"\bprice of\s+([A-Za-z\s\.&,-]+)",    # "price of apple"
    r"\bstock of\s+([A-Za-z\s\.&,-]+)",    # "stock of tesla"
    r"\bhow is\s+([A-Za-z\s\.&,-]+)\s+doing",  # "how is apple doing"
    r"\bupdate on\s+([A-Za-z\s\.&,-]+)",   # "update on microsoft"
    r"\b([A-Z]{1,5})\b",                   # Simple ticker like "AAPL", "GOOGL"
]

# Simple map for very common names -> tickers as a fast path
COMMON_NAME_TO_TICKER = {
    "apple": "AAPL",
    "apple inc": "AAPL",
    "microsoft": "MSFT",
    "google": "GOOGL",
    "alphabet": "GOOGL",
    "tesla": "TSLA",
    "amazon": "AMZN",
    "meta": "META",
    "facebook": "META",
    "coinbase": "COIN",
    "coinbase global": "COIN",
}


async def _extract_entities_with_llm_and_regex(
    user_prompt: str,
    groq_client: Optional[AsyncOpenAI],
    log: logging.Logger,
) -> List[str]:
    """
    Tries to extract company entities from the user's natural language prompt.
    Uses a mix of regex heuristics and a lightweight LLM call as backup.
    """
    log.info(f"--- Fiduciary Plugin: Extracting entities from prompt: {user_prompt} ---")
    entities = set()

    # --- 1) Regex-based extraction for obvious patterns ---
    for pattern in ENTITY_REGEXES:
        for match in re.findall(pattern, user_prompt, flags=re.IGNORECASE):
            candidate = match.strip(" .,!?:;\"'").lower()
            # Filter out obviously generic words that are not entities
            if len(candidate) < 2:
                continue
            if candidate in ["stock", "price", "market", "today"]:
                continue
            entities.add(candidate)

    if entities:
        log.info(f"--- Fiduciary Plugin: Regex found entities: {entities} ---")

    # --- 2) If regex had no luck, fall back to LLM extraction ---
    if not entities and groq_client:
        try:
            extraction_prompt = (
                "You are helping an investment assistant identify which companies "
                "or tickers the user is asking about.\n"
                f"User prompt: {user_prompt}\n\n"
                "Reply with a JSON list of company names or ticker symbols mentioned, "
                "for example: [\"Apple\", \"TSLA\"] or [\"AAPL\"]. "
                "If the user only speaks in general terms (e.g., 'the market'), "
                "return an empty list []."
            )

            resp = await groq_client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=[{"role": "user", "content": extraction_prompt}],
                temperature=0.0,
                max_tokens=128,
            )
            content = resp.choices[0].message.content
            log.info(f"LLM Entity Extraction Raw Response: {content}")

            # Try to parse as JSON list
            try:
                parsed = json.loads(content)
                if isinstance(parsed, list):
                    for item in parsed:
                        if isinstance(item, str):
                            cleaned = item.strip(" .,!?:;\"'").lower()
                            if cleaned:
                                entities.add(cleaned)
            except json.JSONDecodeError:
                # If the model didn't return JSON, attempt a fallback heuristic:
                rough_matches = re.findall(r"[A-Za-z][A-Za-z\s\.&,-]+", content or "", flags=re.IGNORECASE)
                for match in rough_matches:
                    cleaned = match.strip(" .,!?:;\"'").lower()
                    if cleaned and len(cleaned) > 1:
                        entities.add(cleaned)

        except Exception as e:
            log.error(f"--- Fiduciary Plugin: LLM entity extraction failed: {e} ---")

    # Finally, return as a list (may still be empty)
    final_entities = list(entities)
    log.info(f"--- Fiduciary Plugin: Final detected entities: {final_entities} ---")
    return final_entities


async def _find_tickers_for_entities(
    entities: List[str],
    groq_client: Optional[AsyncOpenAI],
    log: logging.Logger,
) -> Dict[str, str]:
    """
    Takes a list of textual entities (e.g. "apple") and returns a dict
    {ticker: original_entity}. Uses a mix of common-name mapping and a
    lightweight LLM query.
    """
    tickers_to_fetch = {}

    for entity in entities:
        # 1) Check simple dictionary for common names
        lower_entity = entity.lower()
        if lower_entity in COMMON_NAME_TO_TICKER:
            ticker = COMMON_NAME_TO_TICKER[lower_entity]
            log.info(f"--- Fiduciary Plugin: Using common ticker '{ticker}' for entity '{entity}' ---")
            tickers_to_fetch[ticker] = entity
            continue

        # 2) If we have a short uppercase string, it might already be a ticker
        if entity.isupper() and 1 < len(entity) <= 5 and entity.isalpha():
            # Sanity check with yfinance
            try:
                t = yf.Ticker(entity)
                info = t.info
                if info and "regularMarketPrice" in info:
                    log.info(f"--- Fiduciary Plugin: Treating '{entity}' as a direct ticker. ---")
                    tickers_to_fetch[entity] = entity
                    continue
            except Exception:
                pass  # If direct ticker check fails, fall through to LLM

        # 3) Fallback to LLM-based ticker lookup if available
        if groq_client:
            ticker = await _find_ticker_with_llm(entity, groq_client, log)
            if ticker:
                tickers_to_fetch[ticker] = entity
        else:
            log.warning(f"--- Fiduciary Plugin: No Groq client, cannot resolve ticker for '{entity}'. ---")

    log.info(f"--- Fiduciary Plugin: Final ticker mapping: {tickers_to_fetch} ---")
    return tickers_to_fetch


async def _find_ticker_with_llm(
    entity_name: str,
    groq_client: Optional[AsyncOpenAI],
    log: logging.Logger,
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
    Fetches and formats data for a single ticker, trying hard to always get a price:
    - Prefer real-time regularMarketPrice from info
    - If missing, fall back to the last available close from recent history
    """
    log.info(f"--- Fiduciary Plugin: Fetching yfinance data for '{ticker_to_fetch}' (from '{entity_name}')... ---")
    try:
        t = yf.Ticker(ticker_to_fetch)

        # Try to get metadata info, but don't bail just because something is missing
        try:
            info = t.info or {}
        except Exception as e_info:
            log.warning(f"--- Fiduciary Plugin: t.info failed for {ticker_to_fetch}: {e_info} ---")
            info = {}

        confirmed_symbol = info.get("symbol", ticker_to_fetch)

        # 1) Price and previous close: real time first, then fallback to history
        current_price = info.get("regularMarketPrice")
        previous_close = info.get("previousClose")
        price_source = "real_time" if current_price is not None else None

        hist_for_changes = None

        if current_price is None or previous_close is None:
            try:
                # Use a small window; 5 trading days is usually enough to get last and prev
                hist_for_changes = t.history(period="5d", interval="1d")
                if not hist_for_changes.empty and "Close" in hist_for_changes.columns:
                    closes = hist_for_changes["Close"].dropna()
                    if current_price is None and len(closes) >= 1:
                        current_price = float(closes.iloc[-1])
                        price_source = "last_close"
                        log.info(f"--- Fiduciary Plugin: Using last close as current price for {confirmed_symbol}: {current_price} ---")
                    if previous_close is None and len(closes) >= 2:
                        previous_close = float(closes.iloc[-2])
            except Exception as e_hist_small:
                log.warning(f"--- Fiduciary Plugin: history(5d) failed for {confirmed_symbol}: {e_hist_small} ---")

        # If we still have no price at all, we really have nothing meaningful
        if current_price is None:
            log.error(f"--- Fiduciary Plugin: No current or historical price available for {confirmed_symbol}. ---")
            return None

        if price_source is None:
            price_source = "unknown"

        # 2) Build the main data dict, even if some fields are missing
        safe_data: Dict[str, Any] = {
            "Company Name": info.get("longName") or info.get("shortName"),
            "Ticker Symbol": confirmed_symbol,
            "Current Price": current_price,
            "Previous Close": previous_close,
            "Price Source": price_source,  # "real_time" or "last_close" or "unknown"
            "Day's Range": None,
            "Day Low": info.get("dayLow"),
            "Day High": info.get("dayHigh"),
            "52-Week Range": None,
            "52 Week Low": info.get("fiftyTwoWeekLow"),
            "52 Week High": info.get("fiftyTwoWeekHigh"),
            "Volume": info.get("volume"),
            "Average Volume": info.get("averageVolume"),
            "Market Cap": info.get("marketCap"),
            "P/E Ratio (TTM)": info.get("trailingPE"),
            "Beta (5Y Monthly)": info.get("beta"),
            "Analyst Target Price": info.get("targetMeanPrice"),
            "Sector": info.get("sector"),
            "Industry": info.get("industry"),
        }

        # Fill derived string ranges
        low = safe_data["Day Low"]
        high = safe_data["Day High"]
        if low is not None and high is not None:
            safe_data["Day's Range"] = f"{low} - {high}"

        wk_low = safe_data["52 Week Low"]
        wk_high = safe_data["52 Week High"]
        if wk_low is not None and wk_high is not None:
            safe_data["52-Week Range"] = f"{wk_low} - {wk_high}"

        # 3) Short-term performance: reuse the 5d history if we have it, else fetch 1 month
        change_5d = None
        change_1m = None

        try:
            if hist_for_changes is None:
                hist_for_changes = t.history(period="1mo", interval="1d")

            if not hist_for_changes.empty and "Close" in hist_for_changes.columns:
                closes = hist_for_changes["Close"].dropna()
                if len(closes) >= 2:
                    last_close = float(closes.iloc[-1])

                    # 5D change: compare with price 5 trading days ago if possible
                    if len(closes) >= 6:
                        past_5 = float(closes.iloc[-6])
                        if past_5:
                            change_5d = (last_close - past_5) / past_5 * 100.0

                    # 1M change: compare last vs first in the window
                    first_close = float(closes.iloc[0])
                    if first_close:
                        change_1m = (last_close - first_close) / first_close * 100.0
        except Exception as e_hist_long:
            log.warning(f"--- Fiduciary Plugin: Unable to compute 5D/1M change for {confirmed_symbol}: {e_hist_long} ---")

        if change_5d is not None:
            safe_data["5D Change (%)"] = change_5d
        if change_1m is not None:
            safe_data["1M Change (%)"] = change_1m

        # 4) Optional: next earnings date
        earnings_date = info.get("earningsDate")
        next_earnings_str = None
        if earnings_date:
            try:
                if isinstance(earnings_date, (list, tuple)) and earnings_date:
                    ed0 = earnings_date[0]
                else:
                    ed0 = earnings_date
                next_earnings_str = str(ed0)
            except Exception:
                next_earnings_str = str(earnings_date)

        if next_earnings_str:
            safe_data["Next Earnings Date"] = next_earnings_str

        log.info(f"--- Fiduciary Plugin: Successfully fetched data for {confirmed_symbol} "
                 f"(price_source={price_source}). ---")
        return safe_data

    except Exception as e:
        log.error(f"--- Fiduciary Plugin: Error fetching data for entity '{entity_name}' "
                  f"(as {ticker_to_fetch}): {e} ---")
        return None



# --- NEW HELPER FUNCTION ---
def _format_stock_data_as_markdown(stock_data: Dict[str, Any]) -> str:
    """
    Turns the yfinance data dictionary into a Markdown table.
    This logic was moved from faculties.py to be generic.
    """
    stock_table_md = f"## {stock_data.get('Company Name', 'N/A')} ({stock_data.get('Ticker Symbol', 'N/A')})\n"
    stock_table_md += f"| Metric | Value |\n"
    stock_table_md += f"| --- | --- |\n"
    
    # Filter to a key set of metrics for context, to avoid overwhelming the prompt
    metrics_to_show = [
        "Current Price", "Previous Close", "Day's Range", "52-Week Range",
        "Volume", "Average Volume", "Market Cap", "P/E Ratio (TTM)",
        "Beta (5Y Monthly)", "Analyst Target Price",
        "Sector"
    ]
    
    for key in metrics_to_show:
        value = stock_data.get(key)
        if value is not None:
            # Format numbers nicely
            if isinstance(value, (int, float)):
                if key == "Dividend Yield":
                    value = f"{value * 100:.2f}%"
                elif key in ["P/E Ratio (TTM)", "Beta (5Y Monthly)"]:
                    value = f"{value:.2f}"
                elif key in ["Volume", "Average Volume", "Market Cap"]:
                    value = f"{value:,}"
                elif key in ["Current Price", "Previous Close", "Analyst Target Price"]:
                    value = f"${value:,.2f}"
            stock_table_md += f"| {key} | {value} |\n"
    return stock_table_md + "\n"
# --- END NEW HELPER FUNCTION ---


def _format_stock_snapshot_as_markdown(stock_data: Dict[str, Any]) -> str:
    """
    Builds a richer, sectioned markdown summary for a single stock.
    This is meant to support the structured narrative the Fiduciary persona uses.
    """
    company = stock_data.get("Company Name", "N/A")
    ticker = stock_data.get("Ticker Symbol", "N/A")
    today_str = datetime.now().strftime("%A, %b %d, %Y")

    current_price = stock_data.get("Current Price")
    previous_close = stock_data.get("Previous Close")
    day_range = stock_data.get("Day's Range")
    volume = stock_data.get("Volume")
    avg_volume = stock_data.get("Average Volume")
    market_cap = stock_data.get("Market Cap")
    pe_ratio = stock_data.get("P/E Ratio (TTM)")
    beta = stock_data.get("Beta (5Y Monthly)")
    analyst_target = stock_data.get("Analyst Target Price")
    sector = stock_data.get("Sector")
    industry = stock_data.get("Industry")
    change_5d = stock_data.get("5D Change (%)")
    change_1m = stock_data.get("1M Change (%)")
    next_earnings = stock_data.get("Next Earnings Date")

    # Helper to format numbers for inline bullets
    def fmt_price(v):
        return "N/A" if v is None else f"${v:,.2f}"

    def fmt_int(v):
        return "N/A" if v is None else f"{int(v):,}"

    def fmt_pct(v):
        return "N/A" if v is None else f"{v:+.2f}%"

    def fmt_mc(v):
        return "N/A" if v is None else f"{v:,}"

    lines: List[str] = []

    # Header line
    lines.append(f"## {company} ({ticker}) snapshot - {today_str}\n")

    # Price and trading section
    lines.append("### Price and trading\n")
    if current_price is not None or previous_close is not None:
        lines.append(f"- Current price: {fmt_price(current_price)}")
        if previous_close is not None:
            lines.append(f", compared with previous close of {fmt_price(previous_close)}.\n")
        else:
            lines.append(".\n")
    if day_range:
        lines.append(f"- Day's trading range: {day_range}.\n")
    if volume is not None or avg_volume is not None:
        vol_str = fmt_int(volume)
        avg_vol_str = fmt_int(avg_volume)
        lines.append(f"- Volume: {vol_str}")
        if avg_volume is not None:
            lines.append(f", vs average daily volume of {avg_vol_str}.\n")
        else:
            lines.append(".\n")
    if market_cap is not None:
        lines.append(f"- Market cap: {fmt_mc(market_cap)}.\n")
    if pe_ratio is not None:
        lines.append(f"- P/E ratio (TTM): {pe_ratio:.2f}.\n")
    if beta is not None:
        lines.append(f"- Beta (5Y monthly): {beta:.2f}.\n")

    # Short-term context section
    if change_5d is not None or change_1m is not None:
        lines.append("\n### Short-term context\n")
        if change_5d is not None:
            lines.append(f"- 5-day change: {fmt_pct(change_5d)} (approximate, based on recent closes).\n")
        if change_1m is not None:
            lines.append(f"- 1-month change: {fmt_pct(change_1m)} (approximate, based on last month of trading).\n")

    # Fundamentals & business profile (lightweight)
    if sector or industry:
        lines.append("\n### Business profile\n")
        if sector:
            lines.append(f"- Sector: {sector}.\n")
        if industry:
            lines.append(f"- Industry: {industry}.\n")

    # Forward-looking sentiment section
    if analyst_target is not None or next_earnings is not None:
        lines.append("\n### Forward-looking markers\n")
        if analyst_target is not None:
            lines.append(f"- Analyst consensus target price: {fmt_price(analyst_target)}.\n")
        if next_earnings:
            lines.append(f"- Next reported earnings date (if available): {next_earnings}.\n")

    lines.append("\n")

    return "".join(lines)



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

    # 1. Extract entities from the user's prompt (company names, tickers, etc.)
    entities_to_find = await _extract_entities_with_llm_and_regex(
        user_prompt=user_prompt,
        groq_client=groq_client,
        log=log,
    )

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

    # --- REFACTORED LOGIC ---
    # 4. Format all fetched data into a single markdown string
    
    context_string_parts = [
        "CONTEXT: I have fetched the following financial data as requested:\n"
    ]
    
    for stock_data in all_stock_data:
        # First, a structured snapshot with sections like "Price and trading", "Short-term context", etc.
        context_string_parts.append(
            _format_stock_snapshot_as_markdown(stock_data)
        )
        # Then, a compact table of key metrics as a quick reference.
        context_string_parts.append(
            _format_stock_data_as_markdown(stock_data)
        )
    
    final_context_string = "\n".join(context_string_parts)

    # 5. Return the generic payload
    final_payload = {
        "preformatted_context_string": final_context_string
    }
    
    log.info(f"--- Fiduciary Plugin: Returning 'preformatted_context_string' for {len(all_stock_data)} ticker(s). ---")
    return user_prompt, final_payload
    # --- END REFACTORED LOGIC ---
