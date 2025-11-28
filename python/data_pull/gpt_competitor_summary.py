import os
from dotenv import load_dotenv
from openai import OpenAI

# -----------------------------------------------------------
# LOAD ROOT .env
# -----------------------------------------------------------
ROOT_ENV_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", ".env")
)
load_dotenv(ROOT_ENV_PATH)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

if not OPENAI_API_KEY:
    raise ValueError("ERROR: OPENAI_API_KEY missing in root .env")

client = OpenAI(api_key=OPENAI_API_KEY)

# -----------------------------------------------------------
# CONFIG
# -----------------------------------------------------------
ZIP_CODE = "32065"
INDUSTRY = "coffee shops"

# -----------------------------------------------------------
# GPT PROMPT
# -----------------------------------------------------------
prompt = f"""
You are a market research analyst specializing in competitive analysis for business plans.

Provide a concise but high-value summary of the competitive landscape for **{INDUSTRY}** in ZIP code **{ZIP_CODE}**.

Your summary MUST include:

1. Estimated number of competitors
2. Common types of competitors (chains, independents, specialty shops)
3. Typical price ranges and positioning
4. Average consumer sentiment and recurring review themes
5. Strengths/weaknesses of local competitors
6. Typical differentiators in this market
7. Any observable trends (e.g., demand growth, premiumization, rising competition)
8. Opportunities for a new entrant
9. Risks a new business should plan for

Write it as if it is going into the “Competitive Landscape” section of a professional business plan.

Do NOT make up specific business names. Keep it general but data-backed.
"""

# -----------------------------------------------------------
# GPT CALL
# -----------------------------------------------------------
response = client.chat.completions.create(
    model="gpt-5.1",
    messages=[
        {"role": "system", "content": "You are an expert business plan analyst."},
        {"role": "user", "content": prompt}
    ],
    temperature=0.2,
)

# -----------------------------------------------------------
# PRINT RESULT
# -----------------------------------------------------------
print("\n================== COMPETITOR SUMMARY ==================\n")
print(response.choices[0].message.content)
print("\n=========================================================\n")
