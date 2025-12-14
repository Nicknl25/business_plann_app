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
# Primary client inputs
CLIENT_ZIP = "32065"
CLIENT_KEYWORD = "hair cut"
CLIENT_NAICS = "812111"  # example NAICS context

# Candidate ZIPs to score (include the client ZIP; add more as needed)
CANDIDATE_ZIPS = [
    CLIENT_ZIP,
    # Add more candidate ZIPs here to compare locations, e.g.:
    # "32073", "32003"
]

# Pull population for each candidate ZIP
zip_populations = {z: get_zip_population(z) for z in CANDIDATE_ZIPS}

zip_population = zip_populations.get(CLIENT_ZIP)
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
# Per-ZIP competitor sets for scoring
zip_places = {z: {} for z in CANDIDATE_ZIPS}

for z in CANDIDATE_ZIPS:
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
            zip_places[z][p["place_id"]] = p


print(f"\n--- TOTAL UNIQUE COMPETITORS FOUND: {len(all_places)} ---\n")

# ------------------------------------------------------------
# SIMPLE LOCATION SCORING (demand vs competition)
# ------------------------------------------------------------
scores = []
for z in CANDIDATE_ZIPS:
    pop = zip_populations.get(z) or 0
    comp = len(zip_places[z])
    comp_per_10k = comp / (pop / 10000) if pop and pop > 0 else comp
    demand_score = pop / 10000  # simple scale
    score = demand_score - comp_per_10k
    scores.append((score, z, pop, comp, comp_per_10k))

scores.sort(reverse=True)

print("--- LOCATION SCORES ---")
for score, z, pop, comp, comp_per_10k in scores:
    print(f"ZIP {z}: score={score:.2f}, pop={pop}, competitors={comp}, comp_per_10k={comp_per_10k:.2f}")

# Recommend initial and expansion locations based on scores
if scores:
    best = scores[0]
    print("\n--- RECOMMENDED LOCATIONS ---")
    print(f"Open first: ZIP {best[1]} (score={best[0]:.2f}, pop={best[2]}, competitors={best[3]}, comp_per_10k={best[4]:.2f})")
    if len(scores) > 1:
        next_best = scores[1]
        print(f"Expand next: ZIP {next_best[1]} (score={next_best[0]:.2f}, pop={next_best[2]}, competitors={next_best[3]}, comp_per_10k={next_best[4]:.2f})")

# ------------------------------------------------------------
# FETCH DETAILS
# ------------------------------------------------------------
DETAIL_FIELDS = (
    "name,formatted_address,formatted_phone_number,geometry,"
    "rating,user_ratings_total,price_level,opening_hours,"
    "business_status,website,editorial_summary,reviews"
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
    print("Price level:", details.get("price_level"))
    print("Phone:", details.get("formatted_phone_number"))
    print("Website:", details.get("website"))

    # Extract a few review snippets
    review_texts = []
    for rev in details.get("reviews", [])[:5]:
        txt = rev.get("text")
        if txt:
            review_texts.append(txt.strip())

    if review_texts:
        prompt = f"""
You are advising a client on how to beat a nearby competitor.
Client keyword: "{CLIENT_KEYWORD}"
NAICS: {CLIENT_NAICS}
Competitor: "{details.get('name')}"
Competitor price_level (0=free, 1=cheap, 4=very expensive): {details.get('price_level')}
Client ZIP population (ACS): {zip_population if 'zip_population' in globals() and zip_population is not None else "unknown"}
You have these customer reviews for the competitor:
{json.dumps(review_texts, indent=2)}

Write a concise 3–5 sentence paragraph on how the client can outperform this competitor, focusing on clear opportunities from the reviews (including any price/value signals).
"""
        try:
            resp = client.chat.completions.create(
                model="gpt-4.1",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=400,
            )
            advice = (resp.choices[0].message.content or "").strip()
            print("\nAdvice to beat this competitor:")
            print(advice)
        except Exception as e:
            print(f"\nGPT advice error: {e}")

        # Additional storytelling + action plan tied to reviews
        prompt_story = f"""
You are advising a client on how to beat a nearby competitor.
Client keyword: "{CLIENT_KEYWORD}"
NAICS: {CLIENT_NAICS}
Competitor: "{details.get('name')}"
Competitor price_level (0=free, 1=cheap, 4=very expensive): {details.get('price_level')}
Client ZIP population (ACS): {zip_population if 'zip_population' in globals() and zip_population is not None else "unknown"}
Here are sample customer reviews for the competitor:
{json.dumps(review_texts, indent=2)}

Write two short sections:
1) 1–2 paragraphs telling the story of what customers are saying (highlights, patterns, sentiment).
2) 1–2 paragraphs with specific, actionable moves the client can take to win, explicitly tied to those review insights (including price/value positioning).
Be concise and practical.
"""
        try:
            resp2 = client.chat.completions.create(
                model="gpt-4.1",
                messages=[{"role": "user", "content": prompt_story}],
                temperature=0.3,
                max_tokens=600,
            )
            advice2 = (resp2.choices[0].message.content or "").strip()
            print("\nReview story + how to win:")
            print(advice2)
        except Exception as e:
            print(f"\nGPT storytelling error: {e}")

print("\n--- DONE ---\n")
