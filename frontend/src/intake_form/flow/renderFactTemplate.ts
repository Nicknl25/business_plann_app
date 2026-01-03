import type { IntakeSharedContext } from "./IntakeFlowContext";

export type FactBusinessContext = {
  name: string;
  address: string;
  startDate: string;
};

export type FactRenderContext = {
  sharedContext: IntakeSharedContext;
  business: FactBusinessContext;
};

const FACT_PATTERN = /\{\{fact:([A-Za-z0-9_.-]+)\}\}/g;

const OPS_MONEY_FIELDS = new Set([
  "unit_price",
  "starting_revenue",
  "initial_assets",
  "initial_equity",
  "total_debt_outstanding",
]);

const FIN_MONEY_FIELDS = new Set([
  "current_revenue",
  "current_cogs",
  "other_operating_expense",
  "monthly_rent_expense",
  "other_monthly_debt_payments",
  "current_payroll",
  "current_capex",
  "ar_balance",
  "ap_balance",
  "inventory_balance",
  "total_debt_outstanding",
  "annual_interest_payment",
  "annual_principal_payment",
  "owner_compensation",
  "cash_on_hand",
]);

const COUNT_FIELDS = new Set(["units_per_week_capacity", "current_num_employees"]);

function formatMarketIncomeIntent(value: unknown): string {
  if (!Array.isArray(value) || value.length === 0) return "";
  const mins: number[] = [];
  const maxs: number[] = [];
  for (const item of value) {
    if (!item || typeof item !== "object") continue;
    const record = item as any;
    const minVal = toNumber(record.income_min);
    const maxVal = toNumber(record.income_max);
    if (minVal !== null) mins.push(minVal);
    if (maxVal !== null) maxs.push(maxVal);
  }
  if (mins.length === 0 || maxs.length === 0) return "";
  return `${formatNumber(Math.min(...mins), { money: true })}–${formatNumber(Math.max(...maxs), { money: true })}`;
}

function formatMarketGenderAgeIntent(value: unknown): string {
  if (!Array.isArray(value) || value.length === 0) return "";
  const mins: number[] = [];
  const maxs: number[] = [];
  const genderFocuses = new Set<string>();
  for (const item of value) {
    if (!item || typeof item !== "object") continue;
    const record = item as any;
    const gender = String(record.gender_focus || "").trim().toLowerCase();
    if (gender) genderFocuses.add(gender);
    const ageMin = toNumber(record.age_min);
    const ageMax = toNumber(record.age_max);
    if (ageMin !== null) mins.push(ageMin);
    if (ageMax !== null) maxs.push(ageMax);
  }
  if (mins.length === 0 || maxs.length === 0) return "";

  let genderLabel = "all genders";
  if (genderFocuses.has("all") || (genderFocuses.has("female") && genderFocuses.has("male"))) {
    genderLabel = "all genders";
  } else if (genderFocuses.has("female")) {
    genderLabel = "women";
  } else if (genderFocuses.has("male")) {
    genderLabel = "men";
  }

  const ageMinStr = formatNumber(Math.min(...mins), { money: false });
  const ageMaxStr = formatNumber(Math.max(...maxs), { money: false });
  return `${genderLabel} ages ${ageMinStr}–${ageMaxStr}`;
}

function toNumber(value: unknown): number | null {
  if (value === null || value === undefined) return null;
  if (typeof value === "number" && Number.isFinite(value)) return value;
  const raw = String(value).trim();
  if (!raw) return null;
  const parsed = Number(raw.replace(/,/g, ""));
  return Number.isFinite(parsed) ? parsed : null;
}

function formatNumber(value: unknown, { money }: { money: boolean }): string {
  const num = toNumber(value);
  if (num === null) return money ? "$0" : "0";
  const isInt = Math.abs(num - Math.round(num)) < 1e-9;
  const core = isInt
    ? Math.round(num).toLocaleString("en-US")
    : num
        .toLocaleString("en-US", { maximumFractionDigits: 2 })
        .replace(/\.0+$/, "")
        .replace(/(\.\d+?)0+$/, "$1");
  return money ? `$${core}` : core;
}

function formatLease(value: unknown): string {
  if (value === null || value === undefined) return "none";
  const raw = String(value).trim();
  if (!raw) return "none";
  const [amountRaw, periodRaw] = raw.split(",", 2).map((p) => (p ?? "").trim());
  const amount = toNumber(amountRaw);
  const period = String(periodRaw || "").trim();
  if (!amount || amount <= 1e-9) {
    return !period || period.toLowerCase() === "none" ? "none" : `$0/${period}`;
  }
  const money = formatNumber(amount, { money: true });
  if (!period || period.toLowerCase() === "none") return money;
  return `${money}/${period}`;
}

function resolveFactValue(
  key: string,
  ctx: FactRenderContext
): { group: string; field: string; value: unknown } | null {
  const raw = String(key || "").trim();
  const parts = raw.split(".");
  if (!raw || parts.length !== 2) return null;
  const [group, field] = parts as [string, string];

  if (group === "business") {
    const value =
      field === "name"
        ? ctx.business.name
        : field === "address"
          ? ctx.business.address
          : field === "start_date"
            ? ctx.business.startDate
            : undefined;
    return { group, field, value };
  }

  const shared = ctx.sharedContext || {};
  const map =
    group === "ops"
      ? (shared as any).operating_model
      : group === "market"
        ? (shared as any).target_market
        : group === "people"
          ? (shared as any).people_capability
          : group === "financials"
            ? (shared as any).financials
            : null;
  if (!map || typeof map !== "object") return { group, field, value: undefined };
  return { group, field, value: (map as any)[field] };
}

function formatFact(group: string, field: string, value: unknown): string {
  if (group === "market" && field === "income_intent") return formatMarketIncomeIntent(value);
  if (group === "market" && field === "gender_age_intent") return formatMarketGenderAgeIntent(value);
  if (field === "initial_lease") return formatLease(value);
  if (COUNT_FIELDS.has(field)) return formatNumber(value, { money: false });
  if (group === "ops" && field === "unit_price" && (value === null || value === undefined || value === "")) {
    return "";
  }
  if (group === "ops" && OPS_MONEY_FIELDS.has(field)) return formatNumber(value, { money: true });
  if (group === "financials" && FIN_MONEY_FIELDS.has(field))
    return formatNumber(value, { money: true });

  if (typeof value === "number") return formatNumber(value, { money: false });
  if (Array.isArray(value)) {
    return value.map((v) => String(v ?? "").trim()).filter(Boolean).join(", ");
  }
  if (value && typeof value === "object") return "";
  return String(value ?? "").trim();
}

export function renderFactTemplate(text: string, ctx: FactRenderContext): string {
  if (!text) return text;
  return String(text).replace(FACT_PATTERN, (_match, key: string) => {
    const resolved = resolveFactValue(key, ctx);
    if (!resolved) return "";
    return formatFact(resolved.group, resolved.field, resolved.value);
  });
}
