import requests

API_KEY = "AIzaSyDyXr3Ez26m14XJ2XbNl1KxyYHNZVVQ1Mo"   # <--- PUT YOUR KEY HERE

# -----------------------------------------
# 1. Find a place (example: coffee shop near ZIP 32065)
# -----------------------------------------
nearby_url = "https://maps.googleapis.com/maps/api/place/nearbysearch/json"

nearby_params = {
    "location": "30.138,-81.778",   # center of ZIP 32065
    "radius": 5000,                 # 5km search radius
    "keyword": "coffee shop",
    "key": API_KEY
}

print("\n=== Searching Nearby Coffee Shops ===")
nearby_resp = requests.get(nearby_url, params=nearby_params).json()

if "results" not in nearby_resp or len(nearby_resp["results"]) == 0:
    print("No results found.")
    exit()

# Take first result
place = nearby_resp["results"][0]
name = place["name"]
place_id = place["place_id"]

print(f"Found: {name}")
print(f"Place ID: {place_id}\n")

# -----------------------------------------
# 2. Get detailed reviews
# -----------------------------------------
details_url = "https://maps.googleapis.com/maps/api/place/details/json"

detail_params = {
    "place_id": place_id,
    "fields": "name,rating,user_ratings_total,reviews,formatted_address",
    "key": API_KEY
}

print("=== Fetching Place Details ===")
detail_resp = requests.get(details_url, params=detail_params).json()

result = detail_resp.get("result", {})

print(f"Name: {result.get('name')}")
print(f"Address: {result.get('formatted_address')}")
print(f"Rating: {result.get('rating')}")
print(f"Total Reviews: {result.get('user_ratings_total')}\n")

# -----------------------------------------
# 3. Print Reviews
# -----------------------------------------
reviews = result.get("reviews", [])

print("=== Google Reviews ===\n")

if not reviews:
    print("No text reviews available.")
else:
    for i, rev in enumerate(reviews, start=1):
        print(f"Review #{i}")
        print(f"Author: {rev.get('author_name')}")
        print(f"Rating: {rev.get('rating')}")
        print(f"Text: {rev.get('text')}")
        print(f"Date: {rev.get('relative_time_description')}")
        print("-" * 50)
