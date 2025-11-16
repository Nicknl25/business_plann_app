#!/usr/bin/env Rscript

suppressPackageStartupMessages({
  library(httr2)
  library(jsonlite)
  library(dplyr)
  library(dotenv)
})

# Load environment
if (file.exists("../.env")) {
  dotenv::load_dot_env("../.env")
} else if (file.exists(".env")) {
  dotenv::load_dot_env(".env")
}

bls_api_key <- Sys.getenv("BLS_API_KEY")
cat(
  "DEBUG: BLS_API_KEY nchar =",
  nchar(bls_api_key),
  "prefix =",
  substr(bls_api_key, 1, 4),
  "\n"
)

load_bls_series <- function(series_id, limit = 20,
                            start_year = NULL, end_year = NULL) {

  body <- list(
    seriesid = list(series_id),          # always JSON array
    registrationkey = bls_api_key
  )

  if (!is.null(start_year)) body$startyear <- as.character(start_year)
  if (!is.null(end_year))   body$endyear   <- as.character(end_year)

  # Build JSON exactly like the working curl example
  json_body <- jsonlite::toJSON(body, auto_unbox = TRUE, pretty = FALSE)

  cat(
    "DEBUG: BLS request body:\n",
    jsonlite::toJSON(body, auto_unbox = TRUE, pretty = TRUE),
    "\n"
  )

  resp <- request("https://api.bls.gov/publicAPI/v2/timeseries/data/") |>
    req_method("POST") |>
    req_headers("Content-Type" = "application/json") |>
    req_body_raw(json_body, type = "application/json") |>
    req_perform()

  data <- resp |> resp_body_json()

  # Debug — ALWAYS show these when testing
  print("DEBUG: BLS status and message")
  print(data$status)
  print(data$message)

  if (!identical(data$status, "REQUEST_SUCCEEDED")) {
    stop("❌ BLS request failed: ",
         paste(data$message, collapse = "; "))
  }

  raw <- data$Results$series[[1]]$data

  if (length(raw) == 0) {
    stop("❌ BLS returned ZERO rows for series_id = ", series_id,
         ". The series exists, but not in this dataset or date window.")
  }

  df <- bind_rows(raw) |> slice_head(n = limit)

  return(df)
}

# ---- TEST ----
test_series <- "CEU0500000003"  # Known-good BLS example series
df <- load_bls_series(test_series, limit = 12)

cat("\n----- BLS RESULTS -----\n")
print(df)
