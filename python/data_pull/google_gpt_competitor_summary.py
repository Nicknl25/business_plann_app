import os
import requests
from dotenv import load_dotenv
from openai import OpenAI
import json

# -----------------------------------------------------------
# LOAD ROOT .env
# -----------------------------------------------------------
ROOT_ENV_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", ".env")
)
load_dotenv(ROOT_ENV_PATH)

GOOGLE_API_KEY = os.getenv("GOOGLE_PLACES_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

if not GOOGLE_API_KEY:
    raise ValueError("Google key missing in .env (GOOGLE_PLACES_API_KEY)")
if not OPENAI_API_KEY:
    raise ValueError("OpenAI key missing in .env (OPENAI_API_KEY)")

client = OpenAI(api_key=OPENAI_API_KEY)

# -----------------------------------------------------------
# CONFIG
# -----------------------------------------------------------
ZIP_CODE = "32065"
SEARCH_TERM = "coffee shop"
RADIUS_METERS = 5000  # 5km search

# -----------------------------------------------------------
# STEP 1 — Geocode ZIP → lat/lng
# -----------------------------------------------------------
geocode_url = (
    "https://maps.googleapis.com/maps/api/geocode/json"
    f"?address={ZIP_CODE}&key={GOOGLE_API_KEY}"
)
geo_resp = requests.get(geocode_url).json()

if not geo_resp.get("results"):
    raise ValueError("Could not geocode ZIP.")

location = geo_resp["results"][0]["geometry"]["location"]
lat, lng = location["lat"], location["lng"]

# -----------------------------------------------------------
# STEP 2 — Google Places Nearby Search
# -----------------------------------------------------------
nearby_url = (
    "https://maps.googleapis.com/maps/api/place/nearbysearch/json"
    f"?location={lat},{lng}"
    f"&radius={RADIUS_METERS}"
    f"&keyword={SEARCH_TERM}"
    f"&key={GOOGLE_API_KEY}"
)

nearby_resp = requests.get(nearby_url).json()
places = nearby_resp.get("results", [])

competitors = []

for p in places:
    comp = {
        "name": p.get("name"),
        "address": p.get("vicinity"),
        "lat": p.get("geometry", {}).get("location", {}).get("lat"),
        "lng": p.get("geometry", {}).get("location", {}).get("lng"),
        "rating": p.get("rating"),
        "review_count": p.get("user_ratings_total"),
        "types": p.get("types"),
        "business_status": p.get("business_status"),
    }
    competitors.append(comp)

# -----------------------------------------------------------
# STEP 3 — GPT-5 Analysis Based on REAL Data
# -----------------------------------------------------------
prompt = f"""
You are an expert business plan analyst.

The following is REAL Google Places competitor data for coffee shops in ZIP {ZIP_CODE}.
Use ONLY this data. Do NOT invent facts, numbers, or businesses.

DATA:
{json.dumps(competitors, indent=2)}

Using this dataset, create a comprehensive but concise
**Competitive Landscape Summary** for a business plan.

Your analysis MUST include:

1. Total number of competitors (count them from the data)
2. Types of competitors (chains, independents, cafés, quick-serve)
3. Price positioning (infer from categories/review patterns WITHOUT using price_level)
4. Customer sentiment (infer from rating + review_count patterns)
5. Strengths & weaknesses of local competitors
6. Gaps/opportunities a new entrant can fill
7. Any notable risks
8. A final overall assessment

Do NOT hallucinate any business names.
Do NOT use outside knowledge.
Ground EVERYTHING in the dataset above.
"""

response = client.chat.completions.create(
    model="gpt-5.1",
    messages=[
        {"role": "system", "content": "You are an expert market research analyst."},
        {"role": "user", "content": prompt}
    ],
    temperature=0.2,
)

print("\n================= GPT COMPETITOR SUMMARY =================\n")
print(response.choices[0].message.content)
print("\n===========================================================\n")
