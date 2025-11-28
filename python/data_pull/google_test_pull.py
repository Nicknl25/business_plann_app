import os
import requests
from dotenv import load_dotenv

# ------------------------------------------------------------
# FORCE LOAD ROOT .env ONLY
# ------------------------------------------------------------
ROOT_ENV_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), '..', '..', '.env')
)
load_dotenv(ROOT_ENV_PATH)

GOOGLE_API_KEY = os.getenv("GOOGLE_PLACES_API_KEY")

if not GOOGLE_API_KEY:
    raise ValueError("ERROR: GOOGLE_PLACES_API_KEY not found in root .env")

# ------------------------------------------------------------
# CONFIGURATION – MODIFY THESE FOR TESTING
# ------------------------------------------------------------

CLIENT_ZIP = "32207"          # Test ZIP – change to any zip code
SEARCH_RADIUS_METERS = 5000   # 5km radius
SEARCH_KEYWORD = "coffee shop"  # Change based on industry

# ------------------------------------------------------------
# STEP 1 — Convert ZIP → lat/lng (Geocoding API)
# ------------------------------------------------------------
geo_url = (
    f"https://maps.googleapis.com/maps/api/geocode/json"
    f"?address={CLIENT_ZIP}&key={GOOGLE_API_KEY}"
)

geo_resp = requests.get(geo_url).json()

if not geo_resp["results"]:
    raise ValueError("Could not geocode ZIP. Try another ZIP code.")

location = geo_resp["results"][0]["geometry"]["location"]
lat, lng = location["lat"], location["lng"]

print("\n--- ZIP GEOCODED ---")
print("Lat:", lat)
print("Lng:", lng)

# ------------------------------------------------------------
# STEP 2 — Google Places Nearby Search
# ------------------------------------------------------------
nearby_url = (
    "https://maps.googleapis.com/maps/api/place/nearbysearch/json"
    f"?location={lat},{lng}"
    f"&radius={SEARCH_RADIUS_METERS}"
    f"&keyword={SEARCH_KEYWORD}"
    f"&key={GOOGLE_API_KEY}"
)

nearby_resp = requests.get(nearby_url).json()
places = nearby_resp.get("results", [])

print(f"\n--- FOUND {len(places)} COMPETITORS NEAR '{SEARCH_KEYWORD}' ---\n")

# ------------------------------------------------------------
# STEP 3 — For each place, pull full PLACE DETAILS
# ------------------------------------------------------------
DETAIL_FIELDS = (
    "name,"
    "formatted_address,"
    "formatted_phone_number,"
    "geometry,"
    "rating,"
    "user_ratings_total,"
    "price_level,"
    "opening_hours,"
    "business_status,"
    "website,"
    "editorial_summary"
)

for i, place in enumerate(places, start=1):
    place_id = place["place_id"]

    details_url = (
        "https://maps.googleapis.com/maps/api/place/details/json"
        f"?place_id={place_id}"
        f"&fields={DETAIL_FIELDS}"
        f"&key={GOOGLE_API_KEY}"
    )

    details_resp = requests.get(details_url).json()
    details = details_resp.get("result", {})

    print(f"\n================ COMPETITOR {i} ================")

    print("Name:", details.get("name"))
    print("Address:", details.get("formatted_address"))
    print("Phone:", details.get("formatted_phone_number"))
    print("Website:", details.get("website"))
    print("Business Status:", details.get("business_status"))
    print("Rating:", details.get("rating"))
    print("Total Reviews:", details.get("user_ratings_total"))
    print("Price Level:", details.get("price_level"))

    # Lat/Lng
    if "geometry" in details:
        loc = details["geometry"]["location"]
        print("Lat:", loc.get("lat"))
        print("Lng:", loc.get("lng"))

    # Hours (if available)
    hours = details.get("opening_hours", {}).get("weekday_text")
    if hours:
        print("Hours:")
        for h in hours:
            print("  ", h)

    # Editorial Summary
    if "editorial_summary" in details:
        print("Summary:", details["editorial_summary"].get("overview"))

print("\n--- DONE ---\n")
