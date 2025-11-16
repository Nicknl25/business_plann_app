import os
import requests

# -----------------------------------------
# SIMPLE, CLEAN GOOGLE PLACES TEST SCRIPT
# -----------------------------------------

# Try loading .env if present
from dotenv import load_dotenv
load_dotenv()

API_KEY = os.getenv("GOOGLE_PLACES_API_KEY")

# ---- Debug Key ----
print("DEBUG: GOOGLE_PLACES_API_KEY =", API_KEY)

if not API_KEY:
    raise SystemExit("❌ ERROR: GOOGLE_PLACES_API_KEY not found in .env")

def test_places_simple():
    # Coordinates for Times Square for testing
    lat = 40.7580 
    lng = -73.9855
    keyword = "Natural Resources and Mining"
    radius = 1500  # 1.5km
    
    # Build URL
    url = (
        "https://maps.googleapis.com/maps/api/place/nearbysearch/json"
        f"?location={lat},{lng}"
        f"&radius={radius}"
        f"&keyword={keyword}"
        f"&key={API_KEY}"
    )

    print("\nDEBUG: Request URL:")
    print(url)

    # Call API
    resp = requests.get(url)
    data = resp.json()

    print("\n---- RAW RESPONSE ----")
    print("Status:", data.get("status"))
    print("Total Results:", len(data.get("results", [])))

    print("\n---- SAMPLE RESULTS ----")
    for place in data.get("results", [])[:5]:
        print("Name:", place.get("name"))
        print("Rating:", place.get("rating"))
        print("Reviews:", place.get("user_ratings_total"))
        print("Address:", place.get("vicinity"))
        print("Price Level:", place.get("price_level"))
        print("---")

if __name__ == "__main__":
    test_places_simple()
