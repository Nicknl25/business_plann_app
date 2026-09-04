"""THE OBSERVATIONS - what the catalogue was built backward from (2026-08-30).

Nick: "Start by writing the observations a good consultant would make about
any business - thirty or forty of them, in plain English, the kind of line that
earns its place in a lender packet. Then derive what each one needs."

Each entry is one such line. The fact keys it needs are listed beside it, and
`build.py` exists to make those keys resolve. {braces} are fact tokens; a line
whose keys do not all resolve for a business is simply never written (rule 3).
Section is where the line belongs; class is what it would be tagged (rule 14).

The last block is the honest one: observations worth making that CANNOT be
made from what we hold, and why. Those are the gaps Nick asked to hear now.
"""
from __future__ import annotations

from typing import Dict, List, Tuple

# (id, section, class, sentence, required fact keys)
SENTENCES: Tuple[Dict[str, object], ...] = (
  # ---- MARKET & COMPETITION ----------------------------------------------
  {"id": "S01", "section": "market_and_industry", "class": "INFERRED",
   "text": "{market.competition_geo_label} has {market.establishments} establishments in {market.industry_scope_label} - one for every {market.residents_per_establishment} residents.",
   "needs": ["market.competition_geo_label", "market.establishments", "market.industry_scope_label", "market.residents_per_establishment"]},
  {"id": "S02", "core": True, "section": "competitive_landscape", "class": "INFERRED",
   "text": "{entity.business_name} is one of {market.establishments} establishments in {market.industry_scope_label} in {market.competition_geo_label}, a {market.client_share_of_establishments} share of the field.",
   "needs": ["market.industry_scope_label", "entity.business_name", "market.establishments", "market.competition_geo_label", "market.client_share_of_establishments"]},
  {"id": "S03", "section": "market_and_industry", "class": "INFERRED",
   "text": "The typical establishment in {market.industry_scope_label} employs {market.emp_per_establishment} people in {market.competition_geo_label}, against {industry.emp_per_establishment_national} nationally.",
   "needs": ["market.industry_scope_label", "market.emp_per_establishment", "market.competition_geo_label", "industry.emp_per_establishment_national"]},
  {"id": "S04", "section": "market_and_industry", "class": "INFERRED",
   "text": "Annual payroll per establishment in {market.industry_scope_label} runs {market.payroll_per_establishment} in {market.competition_geo_label} versus {industry.payroll_per_establishment_national} across the country.",
   "needs": ["market.industry_scope_label", "market.payroll_per_establishment", "market.competition_geo_label", "industry.payroll_per_establishment_national"]},
  {"id": "S05", "section": "competitive_landscape", "class": "INFERRED",
   "text": "{industry.share_firms_under_10_employees} of firms in the industry employ fewer than ten people - this is a trade of small operators.",
   "needs": ["industry.share_firms_under_10_employees"]},
  {"id": "S06", "core": True, "section": "operations_and_organisation", "class": "INFERRED",
   "text": "The metro's concentration of {market.top_occupation_title} is {market.top_occupation_loc_quotient} the national average, so the labour {entity.business_name} depends on is available locally.",
   "needs": ["market.top_occupation_title", "market.top_occupation_loc_quotient", "entity.business_name"]},
  {"id": "S07", "section": "market_and_industry", "class": "INFERRED",
   "text": "Statewide, {market.b2b_target_establishments_state} establishments operate in the industries {entity.business_name} sells to.",
   "needs": ["market.b2b_target_establishments_state", "entity.business_name"]},

  # ---- INDUSTRY DYNAMICS (BDS) --------------------------------------------
  {"id": "S08", "section": "market_and_industry", "class": "INFERRED",
   "text": "Of establishments that open in this industry, {industry.five_year_survival_rate} are still operating five years later.",
   "needs": ["industry.five_year_survival_rate"]},
  {"id": "S09", "section": "market_and_industry", "class": "INFERRED",
   "text": "The industry adds establishments at {industry.establishment_entry_rate} a year and loses them at {industry.establishment_exit_rate}.",
   "needs": ["industry.establishment_entry_rate", "industry.establishment_exit_rate"]},
  {"id": "S10", "section": "market_and_industry", "class": "INFERRED",
   "text": "Net job creation across the sector ran {industry.net_job_creation_rate} in {industry.bds_year} - employment in the trade is {industry.employment_direction}.",
   "needs": ["industry.net_job_creation_rate", "industry.bds_year", "industry.employment_direction"]},
  # THE SCOPE MOVED TO THE NOTE (Nick 2026-09-03): the sentence names the
  # business's own trade from the client's account; the statistical population
  # lives in the rate's note basis, one superscript away. "The trade group
  # that includes X" was a lookup key wearing prose - rule 4. floor_required
  # (Nick 2026-09-02): the RATE is the point.
  {"id": "S11", "core": True, "section": "the_business", "class": "INFERRED",
   "floor_required": ["industry.first_year_exit_rate"],
   "text": "First-year establishments in this trade close at a rate of {industry.first_year_exit_rate}; {entity.business_name} is in its {entity.years_operating} year of operation.",
   "needs": ["industry.first_year_exit_rate", "entity.business_name", "entity.years_operating"]},
  {"id": "S12", "section": "market_and_industry", "class": "INFERRED",
   "text": "Firms under five years old account for {industry.young_firm_employment_share} of the sector's employment.",
   "needs": ["industry.young_firm_employment_share"]},

  # ---- TRADE AREA (ACS) ---------------------------------------------------
  {"id": "S13", "core": True, "section": "market_and_industry", "class": "INFERRED",
   "text": "The trade area - {market.trade_area_name} - is home to {market.trade_area_households} households and {market.trade_area_population} residents.",
   "needs": ["market.trade_area_name", "market.trade_area_households", "market.trade_area_population"]},
  {"id": "S14", "core": True, "section": "market_and_industry", "class": "INFERRED",
   "text": "Median household income in the trade area is {market.trade_area_median_hh_income}, {market.trade_area_income_vs_state} the state median.",
   "needs": ["market.trade_area_median_hh_income", "market.trade_area_income_vs_state"]},
  {"id": "S15", "section": "market_and_industry", "class": "INFERRED",
   "text": "{market.share_households_in_target_income_band} of trade-area households earn above {entity.target_income_floor}, the band {entity.business_name} serves.",
   "needs": ["market.share_households_in_target_income_band", "entity.target_income_floor", "entity.business_name"]},
  {"id": "S16", "section": "market_and_industry", "class": "INFERRED",
   "text": "{market.share_population_in_target_age_band} of the trade-area population falls within the {entity.target_age_band} age range the business targets.",
   "needs": ["market.share_population_in_target_age_band", "entity.target_age_band"]},
  {"id": "S17", "section": "market_and_industry", "class": "INFERRED",
   "text": "In {market.competition_geo_label} there are {market.households_per_establishment} households for every establishment in {market.industry_scope_label}.",
   "needs": ["market.industry_scope_label", "market.competition_geo_label", "market.households_per_establishment"]},
  {"id": "S18", "section": "market_and_industry", "class": "INFERRED",
   "text": "{market.trade_area_bachelors_or_higher_share} of trade-area adults hold a bachelor's degree or higher.",
   "needs": ["market.trade_area_bachelors_or_higher_share"]},
  {"id": "S19", "section": "market_and_industry", "class": "INFERRED",
   "text": "The median home in the trade area is valued at {market.trade_area_median_home_value}.",
   "needs": ["market.trade_area_median_home_value"]},

  # ---- CLIENT VERSUS INDUSTRY ---------------------------------------------
  {"id": "S20", "section": "financial_plan", "class": "GROUNDED",
   "text": "{entity.business_name} projects a gross margin of {annual.gross_margin_y1} in Year 1, {annual.gross_margin_gap_pts_y1} {annual.gross_margin_gap_direction_y1} the industry benchmark of {industry.gross_margin_benchmark}.",
   "needs": ["entity.business_name", "annual.gross_margin_y1", "annual.gross_margin_gap_pts_y1", "annual.gross_margin_gap_direction_y1", "industry.gross_margin_benchmark"]},
  {"id": "S21", "section": "financial_plan", "class": "GROUNDED",
   "text": "Operating margin reaches {annual.operating_margin_y5} by Year 5, against an industry figure of {industry.operating_margin_benchmark}.",
   "needs": ["annual.operating_margin_y5", "industry.operating_margin_benchmark"]},
  {"id": "S22", "section": "financial_plan", "class": "GROUNDED",
   "text": "Net margin in Year 1 is {annual.net_margin_y1}, {annual.net_margin_gap_pts_y1} {annual.net_margin_gap_direction_y1} the {industry.net_margin_benchmark} typical of the industry.",
   "needs": ["annual.net_margin_y1", "annual.net_margin_gap_pts_y1", "annual.net_margin_gap_direction_y1", "industry.net_margin_benchmark"]},
  {"id": "S23", "section": "staffing_and_human_capital", "class": "GROUNDED",
   "text": "Revenue per employee is projected at {annual.revenue_per_fte_y1}, against {industry.revenue_per_fte_benchmark} for the industry.",
   "needs": ["annual.revenue_per_fte_y1", "industry.revenue_per_fte_benchmark"]},
  {"id": "S24", "section": "staffing_and_human_capital", "class": "GROUNDED",
   "text": "Payroll absorbs {annual.payroll_pct_revenue_y1} of revenue in Year 1, versus {industry.payroll_pct_benchmark} typical of the trade.",
   "needs": ["annual.payroll_pct_revenue_y1", "industry.payroll_pct_benchmark"]},
  {"id": "S25", "section": "staffing_and_human_capital", "class": "INFERRED",
   "text": "The {market.wage_check_title} role is paid {market.wage_check_client_wage}, {market.wage_check_direction} the {market.wage_check_area_label} median of {market.wage_check_area_median}.",
   "needs": ["market.wage_check_title", "market.wage_check_client_wage", "market.wage_check_direction", "market.wage_check_area_label", "market.wage_check_area_median"]},
  {"id": "S26", "section": "financial_plan", "class": "GROUNDED",
   "text": "Rent runs {annual.rent_pct_revenue_y1} of revenue against an industry norm of {industry.rent_pct_benchmark}.",
   "needs": ["annual.rent_pct_revenue_y1", "industry.rent_pct_benchmark"]},

  # ---- FINANCING (SBA 7(a)) -----------------------------------------------
  {"id": "S27", "section": "funding_request", "class": "INFERRED",
   "text": "Lenders approved {industry.sba_loan_count} SBA 7(a) loans to {industry.sba_scope_label} since {industry.sba_window_start} - median {industry.sba_median_amount} at {industry.sba_median_rate} over {industry.sba_median_term_months}.",
   "needs": ["industry.sba_loan_count", "industry.sba_scope_label", "industry.sba_window_start", "industry.sba_median_amount", "industry.sba_median_rate", "industry.sba_median_term_months"]},
  {"id": "S28", "section": "funding_request", "class": "INFERRED",
   "text": "{industry.sba_chargeoff_rate} of those loans have been charged off.",
   "needs": ["industry.sba_chargeoff_rate"]},
  {"id": "S29", "section": "funding_request", "class": "GROUNDED",
   "text": "The request of {entity.funding_request} sits at the {industry.sba_ask_percentile} percentile of comparable approvals.",
   "needs": ["entity.funding_request", "industry.sba_ask_percentile"]},
  {"id": "S30", "section": "financial_plan", "class": "GROUNDED",
   "text": "Projected debt-service coverage is {annual.dscr_y1} in Year 1, rising to {annual.dscr_y3} by Year 3.",
   "needs": ["annual.dscr_y1", "annual.dscr_y3"]},
  {"id": "S31", "section": "financial_plan", "class": "GROUNDED",
   "text": "Existing debt is fully retired in {annual.debt_retired_year}.",
   "needs": ["annual.debt_retired_year"]},

  # ---- MODEL-DERIVED ------------------------------------------------------
  {"id": "S32", "core": True, "section": "financial_plan", "class": "GROUNDED",
   "text": "Revenue grows from {annual.revenue_y1} in Year 1 to {annual.revenue_y5} in Year 5, a compound annual rate of {annual.revenue_cagr_y1_y5}.",
   "needs": ["annual.revenue_y1", "annual.revenue_y5", "annual.revenue_cagr_y1_y5"]},
  {"id": "S33", "section": "financial_plan", "class": "GROUNDED",
   "text": "{entity.business_name} covers its fixed costs from {quarterly.break_even}.",
   "needs": ["entity.business_name", "quarterly.break_even"]},
  {"id": "S34", "core": True, "section": "financial_plan", "class": "GROUNDED",
   "text": "Cash bottoms at {quarterly.cash_trough_amount} in {quarterly.cash_trough} - {annual.cash_trough_months_of_costs} of operating costs at that point.",
   "needs": ["quarterly.cash_trough_amount", "quarterly.cash_trough", "annual.cash_trough_months_of_costs"]},
  {"id": "S35", "core": True, "section": "products_and_services", "class": "GROUNDED",
   "text": "{annual.top_lob_name} contributes {annual.top_lob_revenue_share_y1} of Year-1 revenue and {annual.top_lob_gross_profit_share_y1} of gross profit.",
   "needs": ["annual.top_lob_name", "annual.top_lob_revenue_share_y1", "annual.top_lob_gross_profit_share_y1"]},
  {"id": "S36", "core": True, "section": "staffing_and_human_capital", "class": "GROUNDED",
   "text": "Headcount grows from {annual.headcount_y1} to {annual.headcount_y5} over the plan; payroll from {annual.payroll_y1} to {annual.payroll_y5}.",
   "needs": ["annual.headcount_y1", "annual.headcount_y5", "annual.payroll_y1", "annual.payroll_y5"]},
  {"id": "S37", "section": "financial_plan", "class": "GROUNDED",
   "text": "Capital deployed totals {annual.capex_total_y1_y5} across the five years, {annual.capex_y1} of it in Year 1.",
   "needs": ["annual.capex_total_y1_y5", "annual.capex_y1"]},
  {"id": "S38", "section": "financial_plan", "class": "GROUNDED",
   "text": "The business is profitable from {annual.first_profitable_year}.",
   "needs": ["annual.first_profitable_year"]},
  {"id": "S39", "section": "financial_plan", "class": "GROUNDED",
   "text": "Year-5 ending cash of {annual.cash_y5} represents {annual.cash_months_of_costs_y5} of operating costs.",
   "needs": ["annual.cash_y5", "annual.cash_months_of_costs_y5"]},
  {"id": "S40", "section": "financial_plan", "class": "GROUNDED",
   "text": "Owner's capital of {annual.owners_capital_y1} funds {annual.owners_capital_pct_assets_y1} of Year-1 assets.",
   "needs": ["annual.owners_capital_y1", "annual.owners_capital_pct_assets_y1"]},
  {"id": "S41", "section": "financial_plan", "class": "GROUNDED",
   "text": "Year-1 revenue of {annual.revenue_y1} is {annual.revenue_y1_vs_stated} the {entity.stated_current_revenue} the business reported at intake.",
   "needs": ["annual.revenue_y1", "annual.revenue_y1_vs_stated", "entity.stated_current_revenue"]},
  # ---- MARKETING & SALES (Part 1, 2026-08-30) -----------------------------
  {"id": "S43", "core": True, "section": "marketing_and_sales", "class": "GROUNDED",
   "text": "The plan spends {annual.marketing_y1} on marketing in Year 1 - {annual.marketing_pct_revenue_y1} of revenue - to win {annual.new_customers_y1} new customers at {annual.cac_y1} each.",
   "needs": ["annual.marketing_y1", "annual.marketing_pct_revenue_y1", "annual.new_customers_y1", "annual.cac_y1"]},
  {"id": "S44", "section": "marketing_and_sales", "class": "GROUNDED",
   "text": "{annual.retention_rate} of customers are expected to return each quarter, and repeat relationships supply {annual.repeat_share_y1} of Year-1 demand.",
   "needs": ["annual.retention_rate", "annual.repeat_share_y1"]},
  {"id": "S45", "section": "marketing_and_sales", "class": "GROUNDED",
   "text": "Marketing runs {annual.marketing_pct_revenue_y1} of revenue, against {industry.marketing_pct_benchmark} typical for the industry.",
   "needs": ["annual.marketing_pct_revenue_y1", "industry.marketing_pct_benchmark"]},
  {"id": "S46", "section": "marketing_and_sales", "class": "GROUNDED",
   "text": "The customer base grows from {annual.customers_y1} at the end of Year 1 to {annual.customers_y5} by Year 5.",
   "needs": ["annual.customers_y1", "annual.customers_y5"]},

  # ---- THE BUSINESS, two more legs (Part 1) --------------------------------
  {"id": "S47", "section": "the_business", "class": "GROUNDED",
   "text": "{entity.business_name} is a {entity.legal_entity} in its {entity.years_operating} year, operating {annual.lob_count} lines of business from {entity.city_state}.",
   "needs": ["entity.business_name", "entity.legal_entity", "entity.years_operating", "annual.lob_count", "entity.city_state"]},
  {"id": "S48", "section": "the_business", "class": "GROUNDED",
   "text": "The business enters the plan period with {entity.stated_current_revenue} in trailing annual revenue and a stated team of {entity.stated_employees}.",
   "needs": ["entity.stated_current_revenue", "entity.stated_employees"]},

  {"id": "S42", "section": "products_and_services", "class": "GROUNDED",
   "text": "Capacity utilisation on {annual.top_lob_name} starts at {annual.top_lob_utilization_y1} and reaches {annual.top_lob_utilization_y5} by Year 5.",
   "needs": ["annual.top_lob_name", "annual.top_lob_utilization_y1", "annual.top_lob_utilization_y5"]},
)


EXTRA_SENTENCES: Tuple[Dict[str, object], ...] = (
  # ---- ECONOMY WOVEN IN (Nick's ruling 1, 2026-08-31) ---------------------
  {"id": "S49", "section": "financial_plan", "class": "INFERRED",
   "text": "The projections assume the economic environment prevailing in {economy.period_label}: inflation running at {economy.inflation_rate} and a ten-year Treasury yield of {economy.ten_year_treasury}.",
   "needs": ["economy.period_label", "economy.inflation_rate", "economy.ten_year_treasury"]},
  {"id": "S50", "section": "funding_request", "class": "INFERRED",
   "text": "Those comparable loans were written across {industry.sba_window_label}; the ten-year Treasury stands at {economy.ten_year_treasury} as of {economy.treasury_as_of}, which is the environment a new facility would price in.",
   "needs": ["industry.sba_window_label", "economy.ten_year_treasury", "economy.treasury_as_of"]},
  {"id": "S51", "section": "risks_and_mitigations", "class": "INFERRED",
   "text": "Debt service runs until {annual.debt_retired_year}; with the ten-year Treasury at {economy.ten_year_treasury}, any refinancing or new borrowing would price off today's rate environment.",
   "needs": ["annual.debt_retired_year", "economy.ten_year_treasury"]},

  # ---- THE RATE SERIES WIRED (Nick's directive, 2026-08-31 evening) -------
  # Prose cites the LIVE series; the DCF constant stays the model's own
  # assumption, and the treasury guard caps the gap between the two.
  {"id": "S57", "section": "financial_plan", "class": "INFERRED",
   "text": "Short-term rates frame the borrowing side of that environment: the federal funds rate averaged {economy.fed_funds_rate} over {economy.rates_period_label} and two-year money {economy.two_year_treasury}, leaving the yield curve {economy.yield_curve_shape}.",
   "needs": ["economy.fed_funds_rate", "economy.rates_period_label",
             "economy.two_year_treasury", "economy.yield_curve_shape"]},
  {"id": "S58", "section": "staffing_and_human_capital", "class": "INFERRED",
   "text": "The hiring this plan assumes takes place in a labour market running {economy.unemployment_rate} unemployment as of {economy.rates_period_label} - the wage levels used here are set against that market, not against a loose one.",
   "needs": ["economy.unemployment_rate", "economy.rates_period_label"]},
  {"id": "S59", "section": "risks_and_mitigations", "class": "INFERRED",
   "text": "Input costs are a live exposure: producer prices moved {economy.ppi_change_yoy} over the past year, and the cost assumptions in this plan inherit that pressure rather than assuming it away.",
   "needs": ["economy.ppi_change_yoy"]},

  # ---- THE VALUATION, PROMOTED (ruling 2) ---------------------------------
  {"id": "S52", "section": "financial_plan", "class": "GROUNDED",
   "text": "On the assumptions recorded in the accompanying financial model, the business supports an estimated equity value of {entity.equity_value_dcf}; small businesses in this trade change hands at around {entity.exit_multiple_sde} seller's discretionary earnings, implying {entity.value_at_exit_multiple} on the plan's mature earnings.",
   "needs": ["entity.equity_value_dcf", "entity.exit_multiple_sde", "entity.value_at_exit_multiple"]},

  # ---- SENSITIVITY (depth item 1 - the quantified demand_response) --------
  {"id": "S53", "core": True, "section": "risks_and_mitigations", "class": "GROUNDED",
   "text": "If pricing were pushed to the top of the achievable range, the plan expects the business to retain between {annual.price_retained_low} and {annual.price_retained_high} of its unit volume.",
   "needs": ["annual.price_retained_low", "annual.price_retained_high"]},
  {"id": "S54", "section": "financial_plan", "class": "GROUNDED",
   "text": "Break-even holds under each of its variants: {annual.break_even_revenue_y1} of Year-1 revenue on an accounting basis and {annual.cash_break_even_revenue_y1} on a cash basis, leaving a margin of safety of {annual.margin_of_safety}.",
   "needs": ["annual.break_even_revenue_y1", "annual.cash_break_even_revenue_y1", "annual.margin_of_safety"]},
  {"id": "S55", "section": "financial_plan", "class": "GROUNDED",
   "text": "Were marketing spend cut back sharply, demand is expected to hold between {annual.marketing_demand_low} and {annual.marketing_demand_high} of plan, and modelled capacity supports up to {annual.volume_headroom_units} units against the volumes projected.",
   "needs": ["annual.marketing_demand_low", "annual.marketing_demand_high", "annual.volume_headroom_units"]},

  # ---- the BDS history sentence beside the new chart (depth item 4) -------
  {"id": "S56", "section": "market_and_industry", "class": "INFERRED",
   "text": "The industry's establishment count has been tracked since {industry.establishments_history_span}, giving the trend behind the entry and exit rates above.",
   "needs": ["industry.establishments_history_span"]},

  # ---- the tenure line for ESTABLISHED businesses (Nick 2026-09-01) -------
  # First-year exit is a shrug for a business in its sixth year. The writer
  # picks by age: S11 for years 1-3, S61 from year 5 on (the author's section
  # instructions carry the rule; both ride in the brief).
  {"id": "S61", "section": "the_business", "class": "INFERRED",
   "floor_required": ["industry.five_year_survival_rate"],
   "text": "Of establishments that open in this trade, {industry.five_year_survival_rate} are still operating five years later; {entity.business_name} is in its {entity.years_operating} year of operation.",
   "needs": ["industry.five_year_survival_rate", "entity.business_name", "entity.years_operating"]},

  # ---- THE DEPTH FACTS (Nick 2026-09-02): the stated today-position a
  # consultant would put in a company description. Templates are the
  # catalogue's derivation record - they no longer ship to the writer.
  {"id": "S64", "section": "the_business", "class": "GROUNDED",
   "text": "{entity.business_name} generates {entity.stated_revenue_per_employee} of revenue for each member of its stated team of {entity.stated_employees}.",
   "needs": ["entity.business_name", "entity.stated_revenue_per_employee", "entity.stated_employees"]},
  {"id": "S65", "section": "the_business", "class": "GROUNDED",
   "text": "{entity.business_name} has operated since {entity.founded_month_year}.",
   "needs": ["entity.business_name", "entity.founded_month_year"]},
  {"id": "S66", "section": "the_business", "class": "GROUNDED",
   "text": "{entity.business_name} holds {entity.stated_cash_on_hand} in cash and carries {entity.stated_debt_outstanding} of debt.",
   "needs": ["entity.business_name", "entity.stated_cash_on_hand", "entity.stated_debt_outstanding"]},

  # ---- digit-bearing identifiers as facts (Nick 2026-09-01): a stated
  # certification or ZIP is the client's own specificity - it rides in a
  # token, never gets steered around.
  {"id": "S62", "section": "the_business", "class": "GROUNDED",
   "text": "{entity.business_name} works to the {entity.stated_certifications} standard, part of how the business competes for its accounts.",
   "needs": ["entity.business_name", "entity.stated_certifications"]},
  # phrased without "around" - a spatial idiom the R16 hedge scan cannot
  # tell from a hedge when it lands beside the token (my own template bug,
  # caught live 2026-09-01)
  {"id": "S63", "section": "the_business", "class": "GROUNDED",
   "text": "{entity.business_name} serves customers in the {entity.coverage_zip} area of {entity.city_state} and the communities surrounding it.",
   "needs": ["entity.business_name", "entity.coverage_zip", "entity.city_state"]},
)
SENTENCES = SENTENCES + EXTRA_SENTENCES


# Observations a consultant would make that we CANNOT make, and why. These are
# the gaps to hear about now rather than discover in a document.
CANNOT_YET: Tuple[Dict[str, str], ...] = (
  {"observation": "There are N competitors within R miles of the premises, and the nearest is X miles away.",
   "why": "Needs named competitors with coordinates - Google Places, which is prototype-only and ToS-gated. CBP as loaded is STATE level (geo_id 0400000US..), so not even a county count exists."},
  {"observation": "Establishments per ten thousand residents IN THE TRADE AREA.",
   "why": "Same cause: CBP county/ZIP tables were never loaded. S01 is computed at STATE level and says so in its basis."},
  {"observation": "X% of LOCAL competitors employ fewer than ten people.",
   "why": "CBP as loaded carries no employment-size bands (lfo only). S05 uses BDS firm_size, which is NATIONAL by NAICS-4."},
  {"observation": "Revenue per establishment, local versus national.",
   "why": "CBP has payroll and employment, never revenue. IRS SOI has national business receipts per return at 243 rows - a different unit (tax returns) and not local. Payroll per establishment (S04) is the honest substitute."},
  {"observation": "Any market or industry line at all for crop or animal agriculture.",
   "why": "CBP has no NAICS 111/112 (only forestry/logging/fishing) and BDS misses the same codes. A mushroom farm gets S13-S19 (ACS, which is geographic) and nothing from S01-S05. The section degrades to inference and never says why."},
  {"observation": "How the client's PRICE POINT splits the income distribution.",
   "why": "A unit price is not an annual spend; translating one into the other needs purchase frequency, which intake does not capture. S15 uses the client's STATED target income floor instead, where one was given."},
  {"observation": "Seasonality: which quarters carry the revenue.",
   "why": "No monthly or quarterly series exists in any source we hold. CBP and BDS are annual; ACS is a 5-year estimate."},
  {"observation": "Local wage medians for a business outside a metro, or whose ZIP is a suburb.",
   "why": "OEWS metro rows carry area_title only (the `area` code is NULL on every row), so the metro join is by city name and state. A principal-city ZIP matches; a suburb usually does not, and falls back to the STATE cross-industry median, which S25 labels as such."},
  {"observation": "Industry growth or margin trend over time.",
   "why": "industry_growth_table is public-company derived, covers 46% of NAICS, and its own index marks 417 of 1,014 NAICS unusable. Deliberately not drawn on; the baseline lookup's point benchmarks are used instead."},
  {"observation": "A GROUNDED sentence citing 'U.S. Census Bureau, ACS 2022, Table B19013' - Nick's own example of a SOURCE note.",
   "why": "Ruling E confines SOURCE notes to post_intake_industry_baseline_lookup. ACS, CBP, BDS, SBA and OEWS facts are INFERRED + BASIS even though their table vintage is known. The vintage is carried on every such fact so the ruling can be widened without rebuilding anything - flagged as a conflict in the report."},
)


def sentences_for_section(section_key: str) -> List[Dict[str, object]]:
  return [s for s in SENTENCES if s["section"] == section_key]


def all_required_keys() -> List[str]:
  keys = set()
  for s in SENTENCES:
    keys.update(s["needs"])  # type: ignore[arg-type]
  return sorted(keys)
