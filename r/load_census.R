library(httr2)
library(jsonlite)
library(dplyr)
library(dotenv)

# Load environment variables
dotenv::load_dot_env("../.env")
census_api_key <- Sys.getenv("CENSUS_API_KEY")

if (census_api_key == "") {
  stop("Census API key not found. Check .env file.")
}

# Function: Pull population + median income for a city
load_census_data <- function(state_fips, city_name) {
  
  url <- paste0(
    "https://api.census.gov/data/2022/acs/acs5",
    "?get=NAME,B01003_001E,B19013_001E",
    "&for=place:*",
    "&in=state:", state_fips,
    "&key=", census_api_key
  )
  
  resp <- request(url) |> req_perform()
  raw_data <- resp |> resp_body_json(simplifyVector = TRUE)
  
  df <- as.data.frame(raw_data)
  names(df) <- df[1,]
  df <- df[-1,]
  
  df <- df %>%
    filter(grepl(city_name, NAME, ignore.case = TRUE)) %>%
    mutate(
      population = as.numeric(B01003_001E),
      median_income = as.numeric(B19013_001E)
    ) %>%
    select(NAME, population, median_income)
  
  return(df)
}

# ------- TEST RUN -------
# Austin, Texas (state FIPS = 48)
result <- load_census_data(state_fips = "48", city_name = "Austin")

# Save JSON to your pipeline folder
print("----- CENSUS API TEST RESULTS -----")
print(result)

