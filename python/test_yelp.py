import os
import requests
from dotenv import load_dotenv

# Load .env
load_dotenv()

API_KEY = os.getenv("YELP_API_KEY")

def search_yelp(term, location, limit=5):
    url = "https://api.yelp.com/v3/businesses/search"

    headers = {
        "Authorization": f"Bearer {API_KEY}"
    }

    params = {
        "term": term,
        "location": location,
        "limit": limit,
    }

    response = requests.get(url, headers=headers, params=params)
    data = response.json()

    # Error check
    if response.status_code != 200:
        print("Error:", data)
        return

    businesses = data.get("businesses", [])
    if not businesses:
        print("No businesses found.")
        return

    print(f"Results for '{term}' in '{location}':\n")

    for b in businesses:
        name = b.get("name")
        rating = b.get("rating")
        reviews = b.get("review_count")
        distance = round(b.get("distance", 0) * 0.000621371, 2)  # meters → miles
        lat = b["coordinates"].get("latitude")
        lng = b["coordinates"].get("longitude")

        print(f"Name: {name}")
        print(f"Rating: {rating} ⭐")
        print(f"Reviews: {reviews}")
        print(f"Distance: {distance} miles")
        print(f"Coordinates: ({lat}, {lng})")
        print("-" * 40)


if __name__ == "__main__":
    # Test it out
    search_yelp(term="coffee", location="New York, NY", limit=3)
