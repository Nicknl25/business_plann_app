import requests
import json

URL = "https://www.sba.gov/data.json"

print("Requesting:", URL)
resp = requests.get(URL)

print("\nHTTP Status:", resp.status_code)

data = resp.json()

datasets = data.get("dataset", [])
print("\nTotal datasets found:", len(datasets))


# ---------------------------------------------
# 1. Print all dataset titles
# ---------------------------------------------
print("\n---- ALL DATASET TITLES ----")
for i, d in enumerate(datasets, 1):
    print(f"{i}. {d.get('title')}")
print("\n")


# ---------------------------------------------
# 2. Find first dataset with a JSON downloadURL
# ---------------------------------------------
json_url = None

for d in datasets:
    for dist in d.get("distribution", []):
        if dist.get("downloadURL") and dist.get("downloadURL").endswith(".json"):
            json_url = dist.get("downloadURL")
            dataset_title = d.get("title")
            break
    if json_url:
        break

print("Found JSON dataset:", dataset_title)
print("Download URL:", json_url)


# ---------------------------------------------
# 3. Download actual SBA data
# ---------------------------------------------
print("\nDownloading actual JSON data...")
resp2 = requests.get(json_url)

if resp2.status_code != 200:
    print("Failed to download:", resp2.status_code)
    print(resp2.text[:200])
    exit()

try:
    actual = resp2.json()
except Exception as e:
    print("Error parsing JSON:", e)
    print(resp2.text[:500])
    exit()

print("\n---- SAMPLE OF ACTUAL SBA JSON DATA ----")
if isinstance(actual, list):
    print("Type: list | length:", len(actual))
    print("Sample row:", actual[0])
elif isinstance(actual, dict):
    print("Type: dict | keys:", list(actual.keys()))
    # print a piece of it
    print(json.dumps({k: actual[k] for k in list(actual.keys())[:5]}, indent=2))
else:
    print("Unknown type:", type(actual))
