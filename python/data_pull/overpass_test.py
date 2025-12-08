import requests
import json
import sys
import math

# -------------------------------------------------------
# Overpass API mirrors (fastest ones)
# -------------------------------------------------------
OVERPASS_SERVERS = [
    "https://overpass.kumi.systems/api/interpreter",
    "https://lz4.overpass-api.de/api/interpreter",
    "https://overpass.openstreetmap.fr/api/interpreter"
]

# -------------------------------------------------------
# Coordinates of the target address
# 3168 Tower Oaks Dr, Orange Park FL 32065
# -------------------------------------------------------
HOME_LAT = 30.170829
HOME_LON = -81.806331

# -------------------------------------------------------
# Query: All coffee shops in ZIP 32065 (bounding box)
# -------------------------------------------------------
# NOTE: You were using a TOO SMALL bounding box,
# so I expanded it to the PROPER 32065 coverage.
query = """
[out:json];
(
  node["amenity"="cafe"](30.110,-81.865,30.205,-81.740);
  node["shop"="coffee"](30.110,-81.865,30.205,-81.740);
  node["amenity"="fast_food"]["cuisine"="coffee"](30.110,-81.865,30.205,-81.740);
);
out center;
"""

# -------------------------------------------------------
# Function: try each Overpass server until one succeeds
# -------------------------------------------------------
def run_overpass_query(query):
    for url in OVERPASS_SERVERS:
        print(f"\nTrying Overpass server: {url}")

        try:
            response = requests.post(url, data={"data": query}, timeout=60)

            if response.status_code == 200:
                print("Success! Got data.\n")
                return response.json()

            else:
                print(f"Server returned status {response.status_code}")

        except Exception as e:
            print(f"Error: {e}")

    # If all servers fail:
    print("\nAll Overpass servers are busy or unreachable.")
    sys.exit(1)


# -------------------------------------------------------
# Distance calculation (Haversine formula)
# -------------------------------------------------------
def haversine(lat1, lon1, lat2, lon2):
    R = 3958.8  # miles
    dLat = math.radians(lat2 - lat1)
    dLon = math.radians(lon2 - lon1)
    lat1 = math.radians(lat1)
    lat2 = math.radians(lat2)

    a = (math.sin(dLat / 2)**2 +
         math.cos(lat1) * math.cos(lat2) * math.sin(dLon / 2)**2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return R * c


# -------------------------------------------------------
# Run the query
# -------------------------------------------------------
data = run_overpass_query(query)

elements = data.get("elements", [])
print(f"Total matches from OSM: {len(elements)}\n")

# -------------------------------------------------------
# Print results WITH distance
# -------------------------------------------------------
print("Coffee Shops in ZIP 32065 (from OSM) + Distance:\n")

for el in elements:
    tags = el.get("tags", {})
    name = tags.get("name", "Unnamed")

    lat = el.get("lat") or el.get("center", {}).get("lat")
    lon = el.get("lon") or el.get("center", {}).get("lon")

    distance = haversine(HOME_LAT, HOME_LON, lat, lon)

    print(f"Name: {name}")
    print(f"Distance from home: {round(distance, 2)} miles")
    print(f"Tags: {tags}")
    print(f"Coordinates: {lat}, {lon}")
    print("-" * 50)
