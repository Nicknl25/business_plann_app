import os
import requests
import time
from pathlib import Path
from dotenv import load_dotenv

# ===========================
# LOAD ENV FROM ROOT
# ===========================

PROJECT_ROOT_NAME = "Business Plan Generator"

def get_project_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if parent.name == PROJECT_ROOT_NAME:
            return parent
    raise FileNotFoundError(f"Cannot locate project root '{PROJECT_ROOT_NAME}'")

def load_env():
    env_path = get_project_root() / ".env"
    load_dotenv(env_path, override=True)

load_env()

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

if not GOOGLE_API_KEY:
    raise Exception("Missing GOOGLE_API_KEY in .env")

# ===========================
# CONFIG
# ===========================

OVERPASS_SERVERS = [
    "https://overpass.kumi.systems/api/interpreter",
    "https://lz4.overpass-api.de/api/interpreter",
    "https://overpass.openstreetmap.fr/api/interpreter"
]

# Bounding box for ZIP 32065 (Oakleaf/Orange Park)
BBOX = (30.110, -81.865, 30.205, -81.740)  
# (south, west, north, east)

# ===========================
# RUN OVERPASS QUERY
# ===========================

def run_overpass(query):
    for url in OVERPASS_SERVERS:
        try:
            print(f"Trying Overpass server: {url}")
            r = requests.post(url, data={"data": query}, timeout=60)
            if r.status_code == 200:
                print("Overpass success!\n")
                return r.json()
            else:
                print("Status:", r.status_code)
        except Exception as e:
            print("Error:", e)
    raise Exception("All Overpass servers failed")

# ===========================
# BUILD QUERY FOR COFFEE SHOPS
# ===========================

query = f"""
[out:json];
(
  node["amenity"="cafe"]({BBOX[0]},{BBOX[1]},{BBOX[2]},{BBOX[3]});
  node["shop"="coffee"]({BBOX[0]},{BBOX[1]},{BBOX[2]},{BBOX[3]});
  node["amenity"="fast_food"]["cuisine"="coffee"]({BBOX[0]},{BBOX[1]},{BBOX[2]},{BBOX[3]});
);
out center;
"""

osm_data = run_overpass(query)
competitors = osm_data.get("elements", [])

print(f"Found {len(competitors)} competitors in OSM\n")

# ===========================
# GOOGLE PLACE SEARCH
# ===========================

def google_find_place(name, lat, lon):
    url = "https://maps.googleapis.com/maps/api/place/nearbysearch/json"
    params = {
        "location": f"{lat},{lon}",
        "radius": 150,
        "keyword": name,
        "key": GOOGLE_API_KEY
    }
    r = requests.get(url, params=params).json()
    if "results" in r and len(r["results"]) > 0:
        return r["results"][0]
    return None

# ===========================
# GOOGLE PLACE DETAILS
# ===========================

def google_place_details(place_id):
    url = "https://maps.googleapis.com/maps/api/place/details/json"
    params = {
        "place_id": place_id,
        "fields": "name,rating,user_ratings_total,reviews,formatted_address,price_level",
        "key": GOOGLE_API_KEY
    }
    r = requests.get(url, params=params).json()
    return r.get("result", {})

# ===========================
# BUILD COMPETITOR DATASET
# ===========================

full_competitors = []

for c in competitors:
    tags = c.get("tags", {})
    name = tags.get("name", "Unnamed")
    lat = c.get("lat") or c.get("center", {}).get("lat")
    lon = c.get("lon") or c.get("center", {}).get("lon")

    print(f"Processing: {name}")

    google_match = google_find_place(name, lat, lon)
    if not google_match:
        print("  No Google match.\n")
        continue

    place_id = google_match["place_id"]
    details = google_place_details(place_id)

    competitor_record = {
        "name": name,
        "lat": lat,
        "lon": lon,
        "google_rating": details.get("rating"),
        "google_reviews": details.get("user_ratings_total"),
        "review_texts": [rev.get("text") for rev in details.get("reviews", [])],
        "address": details.get("formatted_address"),
        "price_level": details.get("price_level"),
    }

    full_competitors.append(competitor_record)
    print("  Added competitor with Google data.\n")

    time.sleep(1)  # avoid Google rate limits

# ===========================
# PRINT RESULT
# ===========================

print("\n==================== FINAL COMPETITORS ====================\n")

for comp in full_competitors:
    print(f"Name: {comp['name']}")
    print(f"Rating: {comp['google_rating']}")
    print(f"Review Count: {comp['google_reviews']}")
    print(f"Address: {comp['address']}")
    print("Reviews:")
    for t in comp["review_texts"]:
        print(f"  - {t}")
    print("--------------------------------------------------\n")
