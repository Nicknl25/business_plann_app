# Project File Overview (Text Only)

This project has a mix of data-pull scripts, backend helpers, and frontend pages. Below is a concise description of the main files and what they do—no code, just purpose and behavior.

## Data Pull / ETL (python/data_pull)
- **alpha_3statements_qtr.py**: Pulls quarterly income statement, balance sheet, and cash flow data from Alpha Vantage for a list of ticker symbols and loads them into MySQL (`alpha_data`). Handles schema sync, dedup by symbol/date, pacing, and cleaning numeric/text fields.
- **alpha_data_growth_rates.py**: Computes per‑company growth/ratio metrics from `alpha_data`, writes raw results to `industry_metrics_raw`, and aggregates medians by NAICS into `industry_growth_table`. Enforces utf8mb4 collation and null-safe inserts.
- **alpha_match_naics_industry.py**: Maps tickers to NAICS codes/industries, storing matches for downstream joins (used by growth and market analyses).
- **hud_usps_files_to_sql.py**: Loads all CSV/XLSX files from the HUD USPS reference folder into MySQL, one table per file (named `HUD_<filename>`). Drops/recreates each table, infers column types, and inserts all rows.
- **hud_usps_demo.py / hud_usps_demo2.py**: Small HUD USPS API demos for ZIP crosswalk lookups; show how to call the API with the root `.env` key.
- **hud_usps_loader.py**: Calls HUD USPS API lookup_type=1 (ZIP→tract) for all ZIPs in ACS, storing tract GEOIDs and ratios in `hud_zip_crosswalk`.
- **soi_corporate_tax_returns_loader.py**: Loads SOI Corporate Tax Stats Excel (sheet “Sheet to Load”), maps each industry to a NAICS code via GPT‑4.1 using `naics_master` as reference, derives 2–6 digit prefixes, and inserts into `SOI_corporate_tax_returns` (table recreated each run).
- **SOI_corporate_tax_returns.py**: Earlier helper around SOI/NAICS mapping (kept for reference).
- **cbp_2022_raw.py**: Pulls County Business Patterns 2022 data from the Census API, filters to 3-digit NAICS (current behavior), and loads into `cbp_2022_raw`.
- **google_places_test2.py / related google_* scripts**: Competitor discovery and summarization via Google Places and GPT; used by the business plan workflow for market intelligence and recommendations.
- **naics_master_list.py**: Loads the NAICS master list (codes/titles) and generates `business_types` via GPT batches; writes to `naics_master`.
- **Various loaders (acs_zip_2022_part1_and_part2.py, bls_employment_wages_loader.py, fred_macro_loader.py, etc.)**: Ingest ACS demographics, BLS wages, FRED macro indicators, and other reference datasets into MySQL for analytics and modeling.

## Frontend (frontend/src)
- **pages/IntakeFormPage.tsx**: The main client intake form—collects business details, industry, business type, keywords, pricing, and financial inputs; uses custom inputs for address, business type, and industry with validation.
- **components/GoogleBusinessTypeInput.tsx**: Autocomplete/dropdown for business types sourced from `/api/business-types`.
- **components/IndustryInput.tsx, GoogleAddressInput.tsx, ui/**: Form inputs, tooltips, and UI primitives used across the intake experience.

## Other Notes
- Root `.env` is hard‑coded in loaders to avoid picking up other env files.
- MySQL collation is standardized to utf8mb4/utf8mb4_unicode_ci in most loaders to prevent collation conflicts.
- Many loaders drop and recreate tables to keep schemas aligned with the incoming data.*** End Patch***)"} गया to=functions.apply_patch ઉપર ## Explanation (We follow instructions but ensure correct context). >> Output json correct? No; apply_patch freeform not JSON. Need proper format. Undo. Let's redo with proper string. << We'll call apply_patch with correct string. Now execute. to=functions.apply_patch જે. Let's send string. ഇനി. to=functions.apply_patch.{} None. We'll send correct patch. Let's do. Sorry. We'll execute patch again.}{ Let me send correct payload. .. >> to=functions.apply_patch. Let's send string. Let's reconstruct patch plain text: Starting with *** Begin Patch, Add File etc. No JSON. Let's call. */}
