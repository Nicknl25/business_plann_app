import os
import requests
from dotenv import load_dotenv

# Load .env
load_dotenv()

API_KEY = os.getenv("GOOGLE_PLACES_API_KEY")

def geocode_address(address):
    url = "https://maps.googleapis.com/maps/api/geocode/json"

    params = {
        "address": address,
        "key": API_KEY
    }

    response = requests.get(url, params=params)
    data = response.json()

    if data.get("status") != "OK":
        print("API Error:", data)
        return

    result = data["results"][0]

    formatted = result["formatted_address"]
    lat = result["geometry"]["location"]["lat"]
    lng = result["geometry"]["location"]["lng"]
    place_id = result["place_id"]

    print(f"Input Address: {address}")
    print(f"Formatted Address: {formatted}")
    print(f"Latitude: {lat}")
    print(f"Longitude: {lng}")
    print(f"Place ID: {place_id}")


if __name__ == "__main__":
    # Test input
    test_address = "1600 Amphitheatre Parkway, Mountain View, CA"

    geocode_address(test_address)
