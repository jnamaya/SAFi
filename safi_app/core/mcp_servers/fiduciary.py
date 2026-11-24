import yfinance as yf
import json
import logging
from typing import Dict, Any

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("fiduciary_mcp")

async def get_stock_price(ticker: str) -> str:
    logger.info(f"Fiduciary MCP: Fetching price for {ticker}")
    try:
        t = yf.Ticker(ticker)
        info = t.info
        
        current_price = info.get("regularMarketPrice")
        if current_price is None:
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
    logger.info(f"Fiduciary MCP: Fetching news for {ticker}")
    try:
        t = yf.Ticker(ticker)
        news = t.news
        return json.dumps(news[:5])
    except Exception as e:
        return json.dumps({"error": str(e)})

def _jsonable(value: Any) -> Any:
    return str(value)


async def get_earnings_history(ticker: str) -> str:
    logger.info(f"Fiduciary MCP: Fetching earnings for {ticker}")
    try:
        t = yf.Ticker(ticker)
        cal = t.calendar
        earnings = t.earnings_dates

        data = {}
        if earnings is not None and not earnings.empty:
            recent = earnings.head(4).astype(str)
            recent.index = recent.index.astype(str)
            data["earnings_dates"] = recent.to_dict()

        if cal:
            data["calendar"] = cal

        return json.dumps(data, default=_jsonable)
    except Exception as e:
        logger.error(f"Error fetching earnings for {ticker}: {e}")
        return json.dumps({"error": str(e)})

async def get_analyst_recommendations(ticker: str) -> str:
    logger.info(f"Fiduciary MCP: Fetching analyst recs for {ticker}")
    try:
        t = yf.Ticker(ticker)
        recs = t.recommendations
        if recs is not None and not recs.empty:
            return recs.tail(5).to_json(orient="index")
        return json.dumps({"message": "No specific recommendations found."})
    except Exception as e:
        return json.dumps({"error": str(e)})
