import requests
import json
import logging
import os
from typing import Dict, Any

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("google_maps_mcp")

GOOGLE_MAPS_API_KEY = os.environ.get("GOOGLE_MAPS_API_KEY")

async def find_places(query: str) -> str:
    logger.info(f"Google Maps MCP: Searching for '{query}'")
    
    if not GOOGLE_MAPS_API_KEY:
        return json.dumps({"error": "GOOGLE_MAPS_API_KEY not configured."})

    url = "https://places.googleapis.com/v1/places:searchText"
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": GOOGLE_MAPS_API_KEY,
        "X-Goog-FieldMask": "places.displayName,places.formattedAddress,places.rating,places.userRatingCount,places.businessStatus,places.googleMapsUri"
    }
    payload = {
        "textQuery": query,
        "maxResultCount": 5
    }

    try:
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()
        
        data = response.json()
        
        results = []
        if "places" in data:
            for place in data["places"]:
                results.append({
                    "name": place.get("displayName", {}).get("text"),
                    "address": place.get("formattedAddress"),
                    "rating": place.get("rating"),
                    "reviews": place.get("userRatingCount"),
                    "status": place.get("businessStatus"),
                    "map_link": place.get("googleMapsUri")
                })
        
        if not results:
            return json.dumps({"message": "No places found matching your query."})

        return json.dumps(results)

    except requests.exceptions.HTTPError as e:
        error_msg = e.response.text
        logger.error(f"Google Places API Error: {error_msg}")
        return json.dumps({"error": f"Maps API Error: {e.response.status_code} - {error_msg}"})
    except Exception as e:
        logger.error(f"Google Maps Unexpected Error: {e}")
        return json.dumps({"error": str(e)})
