import os
import json
import requests
import folium
from urllib.parse import quote_plus
from pathlib import Path
from dotenv import load_dotenv
from openai import OpenAI

# ==============================================================
# CONFIG — SET BUSINESS TYPE HERE
# ==============================================================

BUSINESS_TYPE = "Acting School"     # <--- change this to ANY business type
LOCATION = "Orange Park, FL"        # <--- city, ZIP, address, etc.
RADIUS_METERS = 8000                # search radius (meters)


# ==============================================================
# LOAD ROOT .ENV
# ==============================================================

PROJECT_ROOT_NAME = "Business Plan Generator"

def get_root():
    for parent in Path(__file__).resolve().parents:
        if parent.name == PROJECT_ROOT_NAME:
            return parent
    raise FileNotFoundError("Project root not found")

ROOT = get_root()
load_dotenv(ROOT / ".env", override=True)

OPENAI_KEY = os.getenv("OPENAI_API_KEY")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

if not OPENAI_KEY:
    raise Exception("Missing OPENAI_API_KEY in .env")
if not GOOGLE_API_KEY:
    raise Exception("Missing GOOGLE_API_KEY in .env")

client = OpenAI(api_key=OPENAI_KEY)


# ==============================================================
# GPT: Business type → Google search keywords
# ==============================================================

def get_google_keywords(biz_type):
    prompt = f"""
Convert the following business type into Google Places search keywords.

Business Type: "{biz_type}"

Output rules:
- Return ONLY a JSON array (no text outside the array)
- Include 3–6 keyword phrases that someone would type into Google.

Example:
["acting school", "drama school", "acting classes"]
"""

    resp = client.responses.create(
        model="gpt-4.1",
        input=prompt,
        max_output_tokens=200
    )

    raw = resp.output_text.strip()

    try:
        return json.loads(raw)
    except:
        s, e = raw.find("["), raw.rfind("]")
        return json.loads(raw[s:e+1])


# ==============================================================
# GEOCODING FUNCTION (SAFE, URL-ENCODED)
# ==============================================================

def geocode_location(location):
    encoded = quote_plus(location)

    url = f"https://maps.googleapis.com/maps/api/geocode/json?address={encoded}&key={GOOGLE_API_KEY}"
    data = requests.get(url).json()

    if not data.get("results"):
        raise Exception(f"Geocoding failed for '{location}'. "
                        f"Response: {json.dumps(data, indent=2)}")

    loc = data["results"][0]["geometry"]["location"]
    return loc["lat"], loc["lng"]


# ==============================================================
# GOOGLE TEXT SEARCH
# ==============================================================

def google_text_search(keyword, lat, lng, radius):
    url = (
        "https://maps.googleapis.com/maps/api/place/nearbysearch/json"
        f"?location={lat},{lng}"
        f"&radius={radius}"
        f"&keyword={quote_plus(keyword)}"
        f"&key={GOOGLE_API_KEY}"
    )
    return requests.get(url).json()


# ==============================================================
# BUILD FOLIUM MAP
# ==============================================================

def build_map(center_lat, center_lng, competitors, biz_type):
    m = folium.Map(location=[center_lat, center_lng], zoom_start=12)

    for comp in competitors:
        lat = comp["lat"]
        lng = comp["lng"]
        name = comp["name"]
        address = comp.get("address", "")
        rating = comp.get("rating", "N/A")

        popup = f"<b>{name}</b><br>{address}<br>Rating: {rating}"

        folium.Marker(
            [lat, lng],
            tooltip=name,
            popup=popup,
            icon=folium.Icon(color="red", icon="info-sign")
        ).add_to(m)

    filename = f"google_map_{biz_type.replace(' ', '_').lower()}.html"
    m.save(filename)
    print(f"\nMap saved as {filename}\n")


# ==============================================================
# MAIN
# ==============================================================

if __name__ == "__main__":
    print(f"\n=== Competitor Map for: {BUSINESS_TYPE} ===")

    # Step 1 — GPT generates search keywords
    keywords = get_google_keywords(BUSINESS_TYPE)
    print("\nGoogle Search Keywords:", keywords)

    # Step 2 — Geocode center
    lat, lng = geocode_location(LOCATION)
    print(f"\nCenter location: {lat}, {lng}")

    # Step 3 — Gather competitors from Google Places
    competitors = []
    seen = set()

    for kw in keywords:
        print(f"\nSearching for: {kw}")
        results = google_text_search(kw, lat, lng, RADIUS_METERS)

        for r in results.get("results", []):
            pid = r["place_id"]

            if pid in seen:
                continue
            seen.add(pid)

            competitors.append({
                "name": r["name"],
                "address": r.get("vicinity"),
                "rating": r.get("rating"),
                "lat": r["geometry"]["location"]["lat"],
                "lng": r["geometry"]["location"]["lng"],
                "keyword": kw
            })

    print(f"\nTotal unique competitors found: {len(competitors)}")

    # Step 4 — Map competitors
    build_map(lat, lng, competitors, BUSINESS_TYPE)
