import logging
import re
import ssl
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
from bs4 import BeautifulSoup
from typing import Optional, Dict, Any, Tuple

_READING_LABELS = {
    "first reading": "First Reading",
    "reading 1": "First Reading",
    "reading i": "First Reading",
    "second reading": "Second Reading",
    "reading 2": "Second Reading",
    "reading ii": "Second Reading",
    "gospel": "Gospel",
    "gospel reading": "Gospel",
    "psalm": "Responsorial Psalm",
    "responsorial psalm": "Responsorial Psalm",
    "responsorial": "Responsorial Psalm",
}

_USCCB_RSS_URL = "https://bible.usccb.org/readings.rss"
_USCCB_TZ = ZoneInfo("America/New_York")

_USCCB_SSL_CONTEXT = ssl.create_default_context()
_USCCB_SSL_CONTEXT.set_ciphers(
    "ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:"
    "ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:"
    "ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305:"
    "AES128-GCM-SHA256:AES256-GCM-SHA384"
)

_DATE_SUFFIX_RE = re.compile(
    r"(?:^|\s+)of\s+((?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\b.*)$",
    re.IGNORECASE,
)

_CHAPTER_VERSE_RE = re.compile(r"(\d)\.(\d)")


def _normalize_citation(citation: str) -> str:
    return _CHAPTER_VERSE_RE.sub(r"\1:\2", citation).strip()


_READING_TRIGGERS = [
    "first reading", "second reading", "gospel reading", "responsorial psalm",
    "today's gospel", "todays gospel", "gospel for today",
    "today's psalm", "todays psalm", "psalm for today",
    "today's reading", "todays reading", "today's readings", "todays readings",
    "daily reading", "daily readings", "mass reading", "mass readings",
    "reading for today", "readings for today",
    "all the readings", "all readings", "the readings for",
]

_READING_SELECTORS = [
    ("first reading", "First Reading"),
    ("reading 1", "First Reading"),
    ("second reading", "Second Reading"),
    ("reading 2", "Second Reading"),
    ("responsorial psalm", "Responsorial Psalm"),
    ("psalm", "Responsorial Psalm"),
    ("gospel", "Gospel"),
]

_WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
_ISO_DATE_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")


def _requested_reading(prompt_lower: str) -> Optional[str]:
    for phrase, title in _READING_SELECTORS:
        if phrase in prompt_lower:
            return title
    return None


def _requested_date(prompt_lower: str, today=None):
    today = today or datetime.now(_USCCB_TZ).date()

    iso = _ISO_DATE_RE.search(prompt_lower)
    if iso:
        try:
            return date(int(iso.group(1)), int(iso.group(2)), int(iso.group(3)))
        except ValueError:
            pass

    if "tomorrow" in prompt_lower:
        return today + timedelta(days=1)
    if "yesterday" in prompt_lower:
        return today - timedelta(days=1)

    for i, name in enumerate(_WEEKDAYS):
        if name in prompt_lower:
            ahead = (i - today.weekday()) % 7
            return today + timedelta(days=ahead)
    return None

def _parse_usccb_item_description(description_html: str) -> list:
    soup = BeautifulSoup(description_html, "html.parser")
    full_passages = []
    for h4 in soup.find_all("h4"):
        link = h4.find("a")
        if not link:
            continue
        citation = link.get_text(" ", strip=True)
        label = h4.get_text(" ", strip=True)
        if citation and label.endswith(citation):
            label = label[: -len(citation)]
        title = _READING_LABELS.get(label.strip().lower())
        if title and citation:
            full_passages.append({
                "title": title,
                "citation": _normalize_citation(citation),
                "text": "",
            })
    return full_passages


async def _fetch_usccb_rss(log: logging.Logger, target_date=None) -> Optional[Dict[str, Any]]:
    headers = {
        "Accept": "application/rss+xml, application/xml, text/xml, */*",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    }
    async with httpx.AsyncClient(timeout=30.0, verify=_USCCB_SSL_CONTEXT) as client:
        resp = await client.get(_USCCB_RSS_URL, headers=headers, follow_redirects=True)
        resp.raise_for_status()

    if re.search(r"<!\s*(?:DOCTYPE|ENTITY)\b", resp.text, re.IGNORECASE):
        raise ValueError("Unsafe XML construct rejected in RSS feed")
    root = ET.fromstring(resp.text)
    now = datetime.now(_USCCB_TZ)
    day = target_date or now.date()
    date_code = day.strftime("%m%d%y")

    candidates = []
    for item in root.iter("item"):
        link = (item.findtext("link") or "").strip()
        if re.search(rf"/{date_code}(?:\.cfm)?(?:-|$)", link):
            candidates.append(item)
    if not candidates:
        log.warning("USCCB RSS feed had no item for %s (%s).", day.isoformat(), date_code)
        return None

    def _rank(item) -> int:
        link = (item.findtext("link") or "").strip()
        if re.search(rf"/{date_code}(?:\.cfm)?$", link):
            return 0
        if link.endswith("-Day"):
            return 1
        return 2

    for item in sorted(candidates, key=_rank):
        full_passages = _parse_usccb_item_description(item.findtext("description") or "")
        if full_passages:
            reading_date = f"{day:%A} {day:%B} {day.day}, {day.year}"
            log.info(f"Successfully fetched {len(full_passages)} passages from USCCB RSS for {reading_date}.")
            return {
                "date": reading_date,
                "full_passages": full_passages,
                "url": item.findtext("link") or _USCCB_RSS_URL,
            }

    log.warning("USCCB RSS items for today had no recognizable readings (feed format may have changed).")
    return None


async def _fetch_readings_from_source(log: logging.Logger, target_date=None) -> Dict[str, Any]:
    try:
        usccb = await _fetch_usccb_rss(log, target_date=target_date)
    except Exception as e:
        log.warning(f"USCCB RSS fetch failed ({type(e).__name__}: {e}); falling back to LivingWithChrist.")
        usccb = None

    if usccb and usccb.get("full_passages"):
        return usccb

    if target_date is not None and target_date != datetime.now(_USCCB_TZ).date():
        log.warning("USCCB had no readings for %s and the fallback source only serves today.",
                    target_date.isoformat())
        return {"error": f"I could not find the readings for {target_date:%A, %B %d, %Y}. "
                         "The authoritative source only publishes about ten days at a time."}

    log.warning("Falling back to LivingWithChrist readings source.")
    return await _fetch_livingwithchrist(log)


async def _fetch_livingwithchrist(log: logging.Logger) -> Dict[str, Any]:
    try:
        url = "https://readings.livingwithchrist.ca/"
        headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, headers=headers, follow_redirects=True)
            resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")

        full_passages = []
        reading_date = None
        current_title = None

        for el in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6"]):
            classes = el.get("class", []) or []
            text = el.get_text(" ", strip=True)
            label = _READING_LABELS.get(text.lower().strip())

            if label:
                current_title = label
                continue

            if "title-b" in classes:
                m = _DATE_SUFFIX_RE.search(text)
                if m and not reading_date:
                    reading_date = m.group(1).strip()
                citation = _normalize_citation(_DATE_SUFFIX_RE.sub("", text))
                if citation:
                    full_passages.append({
                        "title": current_title or "First Reading",
                        "citation": citation,
                        "text": "",
                    })
                current_title = None

            elif "title-c" in classes and current_title:
                full_passages.append({
                    "title": current_title,
                    "citation": _normalize_citation(text),
                    "text": "",
                })
                current_title = None

        if not full_passages:
            log.warning("LivingWithChrist scrape returned no recognizable readings (page structure may have changed).")
            return {"error": "I tried to fetch the daily readings, but the page formatting seemed to be empty."}

        reading_date = reading_date or "today"
        log.info(f"Successfully fetched {len(full_passages)} passages from LivingWithChrist for {reading_date}.")
        return {
            "date": reading_date,
            "full_passages": full_passages,
            "url": url
        }

    except httpx.TimeoutException as e:
        log.error(f"Timeout while fetching daily readings: {e}")
        return {"error": "I tried to fetch the readings, but the request timed out. Please try again."}
    except httpx.HTTPError as e:
        log.error(f"HTTP error while fetching daily readings: {e}")
        return {"error": f"I encountered a network error while fetching the readings: {str(e)}"}
    except Exception as e:
        log.exception("Unexpected error fetching daily readings")
        return {"error": f"I tried to fetch the readings, but an unexpected error occurred: {str(e)}"}


async def handle_bible_scholar_commands(
    user_prompt: str, 
    active_profile_name: str, 
    log: logging.Logger
) -> Tuple[str, Optional[Dict[str, Any]]]:

    if active_profile_name not in ["the bible scholar", "the_bible_scholar"]:
        return user_prompt, None

    original_user_prompt = user_prompt
    prompt_command = user_prompt.strip().lower()

    if not any(t in prompt_command for t in _READING_TRIGGERS):
        return original_user_prompt, None

    target_date = _requested_date(prompt_command)
    requested_reading_key = _requested_reading(prompt_command)
    log.info("Readings request detected: '%s' (reading=%s, date=%s)",
             user_prompt, requested_reading_key or "ALL",
             target_date.isoformat() if target_date else "today")

    scraped_data = await _fetch_readings_from_source(log, target_date=target_date)
    if "error" in scraped_data:
        return original_user_prompt, {"plugin_error": scraped_data["error"]}

    passages = [p for p in scraped_data.get("full_passages", []) if p.get("citation")]
    day_label = scraped_data.get("date", "today")

    if not passages:
        return original_user_prompt, {
            "plugin_error": f"I reached the readings source for {day_label} but it listed no readings."
        }

    if requested_reading_key:
        found = next((p for p in passages if p.get("title") == requested_reading_key), None)
        if found is None:
            available = ", ".join(p["title"] for p in passages)
            return original_user_prompt, {
                "plugin_error": (
                    f"{day_label} has no {requested_reading_key}. The readings for that day are: "
                    f"{available}. Tell the user which readings the day actually has."
                )
            }
        return original_user_prompt, {
            "rag_query_override": found["citation"],
            "preformatted_context_string": (
                f"CONTEXT: The user is asking for the '{found['title']}' for {day_label}, "
                f"which is {found['citation']}. The RAG system has been provided with this text."
            ),
        }

    manifest = "; ".join(f"{p['title']} — {p['citation']}" for p in passages)
    return original_user_prompt, {
        "rag_query_override": [p["citation"] for p in passages],
        "preformatted_context_string": (
            f"CONTEXT: The user is asking for ALL of the readings for {day_label}. "
            f"The day has {len(passages)}: {manifest}. The RAG system has been provided with "
            "the text of each one. Present every reading, in this order, each under its own "
            "heading with its citation. Do not omit any, and do not add readings the day "
            "does not have."
        ),
    }