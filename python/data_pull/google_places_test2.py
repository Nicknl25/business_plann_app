import os
import requests
import json
import mysql.connector
from dotenv import load_dotenv
from openai import OpenAI

# ------------------------------------------------------------
# FORCE LOAD ROOT .env ONLY
# ------------------------------------------------------------
ROOT_ENV_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), '..', '..', '.env')
)
load_dotenv(ROOT_ENV_PATH)

GOOGLE_API_KEY = os.getenv("GOOGLE_PLACES_API_KEY")
OPENAI_KEY = os.getenv("OPENAI_API_KEY")
MYSQL_HOST = os.getenv("MYSQL_HOST")
MYSQL_USER = os.getenv("MYSQL_USER")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD")
MYSQL_DB = os.getenv("MYSQL_DB")
MYSQL_PORT = int(os.getenv("MYSQL_PORT", "3306"))

if not GOOGLE_API_KEY:
    raise ValueError("ERROR: GOOGLE_PLACES_API_KEY not found.")
if not OPENAI_KEY:
    raise ValueError("ERROR: OPENAI_API_KEY not found.")

client = OpenAI(api_key=OPENAI_KEY)

# ------------------------------------------------------------
# GPT FUNCTION TO GENERATE SEARCH CONFIG
# ------------------------------------------------------------
def get_search_config(client_keyword, zip_code, naics_code, population=None):
    prompt = f"""
The client provided this business type or keyword: "{client_keyword}"
NAICS context: {naics_code}
ZIP code: {zip_code}
ZIP population (ACS): {population if population is not None else "unknown"}

Generate optimal Google Maps search settings.

Return JSON with:
1. "radius_meters": ideal radius for competitor search (cap at 10 miles = 16093 meters).
2. "keywords": list of 5–10 optimized Google Maps search terms/phrases derived from the client keyword; these will be combined into one search string.

Rules:
- Keywords/phrases must be realistic, short, and closely related to the client intent.
- Radius should match how far customers normally travel, but NEVER exceed 10 miles (16093 meters).
- JSON only.
"""

    response = client.chat.completions.create(
        model="gpt-4.1",
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"}
    )

    return json.loads(response.choices[0].message.content)

# ------------------------------------------------------------
# HELPER: ZIP POPULATION FROM ACS TABLE (if available)
# ------------------------------------------------------------

def get_zip_population(z):
    try:
        conn = mysql.connector.connect(
            host=MYSQL_HOST,
            user=MYSQL_USER,
            password=MYSQL_PASSWORD,
            database=MYSQL_DB,
            port=MYSQL_PORT,
        )
        cur = conn.cursor()
        cur.execute(
            "SELECT B01001_001E FROM acs_zip_2022_part1 WHERE zcta = %s LIMIT 1",
            (z,),
        )
        row = cur.fetchone()
        cur.close()
        conn.close()
        return int(row[0]) if row and row[0] is not None else None
    except Exception:
        return None

# ------------------------------------------------------------
# USER INPUT — CLIENT PROVIDES ONE PHRASE
# ------------------------------------------------------------
CLIENT_ZIP = "32065"
CLIENT_KEYWORD = "hair cut"
CLIENT_NAICS = "812111"  # example NAICS context

zip_population = get_zip_population(CLIENT_ZIP)
config = get_search_config(CLIENT_KEYWORD, CLIENT_ZIP, CLIENT_NAICS, zip_population)

SEARCH_RADIUS_METERS = min(config["radius_meters"], 16093)  # cap at 10 miles
SEARCH_KEYWORDS = config["keywords"]

print("\n--- GPT CONFIG ---")
print(json.dumps(config, indent=2))

# ------------------------------------------------------------
# GEOCODE ZIP
# ------------------------------------------------------------
def geocode_zip(z):
    geo_url = (
        f"https://maps.googleapis.com/maps/api/geocode/json"
        f"?address={z}&key={GOOGLE_API_KEY}"
    )
    geo_resp = requests.get(geo_url).json()
    if not geo_resp["results"]:
        return None
    loc = geo_resp["results"][0]["geometry"]["location"]
    return loc["lat"], loc["lng"]

# ------------------------------------------------------------
# RUN SEARCHES FOR MAIN ZIP + ADJACENT ZIPS
# ------------------------------------------------------------
all_places = {}

SEARCH_ZIPS = [CLIENT_ZIP]

for z in SEARCH_ZIPS:
    coords = geocode_zip(z)
    if not coords:
        continue

    lat, lng = coords
    print(f"\n--- Searching ZIP {z} (lat={lat}, lng={lng}) ---")
    for kw in SEARCH_KEYWORDS:
        print(f"Keyword: {kw}")
        nearby_url = (
            "https://maps.googleapis.com/maps/api/place/nearbysearch/json"
            f"?location={lat},{lng}"
            f"&radius={SEARCH_RADIUS_METERS}"
            f"&keyword={kw}"
            f"&key={GOOGLE_API_KEY}"
        )

        resp = requests.get(nearby_url).json()
        results = resp.get("results", [])

        print(f"  → {len(results)} results for '{kw}'")

        for p in results:
            all_places[p["place_id"]] = p


print(f"\n--- TOTAL UNIQUE COMPETITORS FOUND: {len(all_places)} ---\n")

# ------------------------------------------------------------
# FETCH DETAILS
# ------------------------------------------------------------
DETAIL_FIELDS = (
    "name,formatted_address,formatted_phone_number,geometry,"
    "rating,user_ratings_total,price_level,opening_hours,"
    "business_status,website,editorial_summary"
)

for i, place in enumerate(all_places.values(), start=1):
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
    print("Rating:", details.get("rating"))
    print("Reviews:", details.get("user_ratings_total"))
    print("Phone:", details.get("formatted_phone_number"))
    print("Website:", details.get("website"))

print("\n--- DONE ---\n")
