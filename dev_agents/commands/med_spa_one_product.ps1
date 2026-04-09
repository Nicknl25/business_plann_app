$repoRoot = Split-Path -Parent $PSScriptRoot
$repoRoot = Split-Path -Parent $repoRoot
Set-Location $repoRoot

$pythonExe = Join-Path $repoRoot ".venv\Scripts\python.exe"
$scriptPath = Join-Path $repoRoot "Test Files\run_live_args_intake_1_product.py"
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$OutputEncoding = [Console]::OutputEncoding

$argsList = @(
  $scriptPath,
  "Create a business scenario for a med spa with one core product.",
  "--business-start-date", "8/5/2024",
  "--set", "bootstrap.business_name=Precision Aesthetics Lab",
  "--set", "bootstrap.address=2100 McKinney Ave, Dallas, TX 75201, USA",
  "--set", "bootstrap.address_street=2100 McKinney Ave",
  "--set", "bootstrap.address_city=Dallas",
  "--set", "bootstrap.address_state=TX",
  "--set", "bootstrap.address_zip=75201",
  "--set", "bootstrap.address_country=USA",
  "--set", "ops.business_description=Precision Aesthetics Lab provides advanced non-surgical aesthetic treatments with a focus on high-ticket procedures delivered in a clinical studio setting.",
  "--set", "ops.customer_type=Primarily individual consumers.",
  "--set", "ops.products_confirmed=Yes, track that as one product.",
  "--set", "ops.legal_entity=LLC.",
  "--set", "ops.delivery_method=All treatments are performed in person at the studio.",
  "--set", "ops.fulfillment_confirmation=Yes, that is accurate.",
  "--set", "ops.sales_channel=Clients primarily book through paid ads and online scheduling.",
  "--set", "ops.geography=Dallas metro area with some clients traveling from surrounding regions.",
  "--set", "ops.growth_lever=Growth is driven by increasing provider utilization and adding additional providers over time.",
  "--set", "ops.competitive_advantage=A highly specialized treatment offering with tight scheduling that maximizes provider output.",
  "--set", "ops.goal_12_months=Reach about 70 treatment sessions per week within 12 months.",
  "--set", "ops.confirmation=Yes, that's correct.",
  "--set", "market.gender=Mostly female but open to all.",
  "--set", "market.age_range=Adults aged 30 to 65.",
  "--set", "market.income_range=Household income of 60000 and above.",
  "--set", "market.education=Mixed education levels.",
  "--set", "market.profile_detail_choice=Skip household and housing.",
  "--set", "market.employment_mix=Mix of professionals and service workers.",
  "--set", "market.confirmation=Yes, that looks right.",
  "--set", "people.owner_background=The founder is a licensed nurse practitioner with 6 years of experience in aesthetics.",
  "--set", "people.other_key_people=No additional staff at launch.",
  "--set", "people.confirmation=Yes, that looks right.",
  "--set", "financials.revenue_setup=This Year-1 revenue setup feels aggressive but workable.",
  "--set", "financials.cogs=Use 22% COGS.",
  "--set", "financials.payroll=Only owner payroll in Year 1.",
  "--set", "financials.payroll_detail=No additional hires initially.",
  "--set", "financials.monthly_rent_expense=Use 9500 for monthly rent expense.",
  "--set", "financials.other_operating_expense=Use 4000 for other operating expense.",
  "--set", "financials.other_monthly_debt_payments=Use 1500 for other monthly debt payments.",
  "--set", "financials.cash_on_hand=Use 15000 for cash on hand.",
  "--set", "financials.ar_balance=Use 2000 for accounts receivable.",
  "--set", "financials.ap_balance=Use 12000 for accounts payable.",
  "--set", "financials.inventory_balance=Use 15000 for inventory balance.",
  "--set", "financials.current_capex=Use 60000 for current capex.",
  "--set", "financials.initial_assets=Use 180000 for initial assets.",
  "--set", "financials.initial_lease=Use 2500 for monthly lease beyond main rent.",
  "--set", "financials.initial_equity=Use 50000 for initial equity.",
  "--set", "financials.total_debt_outstanding=Use 120000 for total debt outstanding.",
  "--set", "financials.annual_interest_payment=Use 9000 for annual interest payment.",
  "--set", "financials.annual_principal_payment=Use 18000 for annual principal payment.",
  "--set", "financials.owner_compensation=Use 120000 for owner compensation.",
  "--set", "financials.cash_strategy=Reinvest. I want to put extra cash back into hiring, expansion, and growth.",
  "--set", "financials.confirmation=Yes, that's right.",
  "--set", "product1.name=Advanced aesthetic treatment",
  "--set", "product1.aliases=procedure,session,treatment",
  "--set", "product1.unit_definition=One unit is one completed advanced aesthetic treatment session.",
  "--set", "product1.capacity=I can handle up to 55 treatment sessions per week at full capacity.",
  "--set", "product1.utilization=Use 88% utilization in Year 1.",
  "--set", "product1.price=Use 875 as the average price per treatment."
)

& $pythonExe @argsList
exit $LASTEXITCODE
