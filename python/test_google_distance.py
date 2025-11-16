import os
import requests
from dotenv import load_dotenv

# Load your .env file
load_dotenv()

API_KEY = os.getenv("GOOGLE_PLACES_API_KEY")

def get_distance(origin, destination):
    url = "https://maps.googleapis.com/maps/api/distancematrix/json"

    params = {
        "origins": origin,
        "destinations": destination,
        "units": "imperial",
        "key": API_KEY
    }

    response = requests.get(url, params=params)
    data = response.json()

    # Quick sanity check
    if data.get("status") != "OK":
        print("Error in API response:", data)
        return

    element = data["rows"][0]["elements"][0]

    if element.get("status") != "OK":
        print("No route found:", element)
        return

    distance = element["distance"]["text"]
    duration = element["duration"]["text"]

    print(f"Origin: {origin}")
    print(f"Destination: {destination}")
    print(f"Distance: {distance}")
    print(f"Duration: {duration}")


if __name__ == "__main__":
    # Test values — feel free to change
    origin_test = "New York, NY"
    destination_test = "Boston, MA"

    get_distance(origin_test, destination_test)
