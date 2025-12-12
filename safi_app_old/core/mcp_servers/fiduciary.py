"""
Fiduciary MCP Server
Exposes financial data tools using yfinance.
"""
import yfinance as yf
import json
import logging
from typing import Dict, Any

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("fiduciary_mcp")

async def get_stock_price(ticker: str) -> str:
    """
    Fetches the current price and basic info for a ticker.
    """
    logger.info(f"Fiduciary MCP: Fetching price for {ticker}")
    try:
        t = yf.Ticker(ticker)
        info = t.info
        
        # Fallback for price
        current_price = info.get("regularMarketPrice")
        if current_price is None:
            # Try history
            hist = t.history(period="1d")
            if not hist.empty:
                current_price = float(hist["Close"].iloc[-1])

        data = {
            "symbol": info.get("symbol", ticker),
            "company_name": info.get("longName") or info.get("shortName"),
            "current_price": current_price,
            "currency": info.get("currency", "USD"),
            "market_cap": info.get("marketCap"),
            "pe_ratio": info.get("trailingPE"),
            "52_week_high": info.get("fiftyTwoWeekHigh"),
            "52_week_low": info.get("fiftyTwoWeekLow"),
        }
        return json.dumps(data)
    except Exception as e:
        logger.error(f"Error fetching data for {ticker}: {e}")
        return json.dumps({"error": str(e)})

async def get_company_news(ticker: str) -> str:
    """
    Fetches news for a company.
    """
    logger.info(f"Fiduciary MCP: Fetching news for {ticker}")
    try:
        t = yf.Ticker(ticker)
        news = t.news
        return json.dumps(news[:5]) # Return top 5
    except Exception as e:
        return json.dumps({"error": str(e)})

async def get_earnings_history(ticker: str) -> str:
    """
    Fetches earnings history.
    """
    logger.info(f"Fiduciary MCP: Fetching earnings for {ticker}")
    try:
        t = yf.Ticker(ticker)
        # return json string of last 4 quarters if available
        # yfinance earnings methods vary by version, robust check:
        cal = t.calendar
        earnings = t.earnings_dates
        
        data = {}
        if earnings is not None and not earnings.empty:
             # Take top 4 recent entries
             data["earnings_dates"] = earnings.head(4).astype(str).to_dict()
        
        if cal:
             data["calendar"] = cal

        return json.dumps(data)
    except Exception as e:
        return json.dumps({"error": str(e)})

async def get_analyst_recommendations(ticker: str) -> str:
    """
    Fetches analyst recommendations.
    """
    logger.info(f"Fiduciary MCP: Fetching analyst recs for {ticker}")
    try:
        t = yf.Ticker(ticker)
        recs = t.recommendations
        if recs is not None and not recs.empty:
            # Recs is often a dataframe
            return recs.tail(5).to_json(orient="index")
        return json.dumps({"message": "No specific recommendations found."})
    except Exception as e:
        return json.dumps({"error": str(e)})
