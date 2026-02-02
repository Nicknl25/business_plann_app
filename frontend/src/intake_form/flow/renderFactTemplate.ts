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
  "initial_assets",
  "initial_equity",
  "total_debt_outstanding",
  "annual_interest_payment",
  "annual_principal_payment",
  "owner_compensation",
  "cash_on_hand",
]);

const COUNT_FIELDS = new Set(["units_per_week_capacity", "current_num_employees"]);

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
  if (field === "initial_lease") return formatLease(value);
  if (COUNT_FIELDS.has(field)) return formatNumber(value, { money: false });
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
  const shared = ctx.sharedContext || {};
  const ops = (shared as any).operating_model || {};
  const lobModels = Array.isArray(ops?.lob_models) ? ops.lob_models : [];

  const productFieldValues = new Map<string, unknown[]>();
  if (lobModels.length > 0) {
    const fields = [
      "unit_name",
      "unit_description",
      "unit_cadence",
      "units_per_week_capacity",
      "units_per_period_capacity",
      "unit_price",
    ];
    const products: any[] = [];
    for (const lob of lobModels) {
      const lobProducts = Array.isArray(lob?.products) ? lob.products : [];
      for (const product of lobProducts) {
        if (product && typeof product === "object") {
          products.push(product);
        }
      }
    }
    for (const field of fields) {
      productFieldValues.set(
        field,
        products.map((product) => (product as any)?.[field])
      );
    }
  }

  const fieldCounters = new Map<string, number>();

  return String(text).replace(FACT_PATTERN, (_match, key: string) => {
    const resolved = resolveFactValue(key, ctx);
    if (!resolved) return "";

    if (resolved.group === "ops" && productFieldValues.has(resolved.field)) {
      const raw = resolved.value;
      const rawStr = raw === null || raw === undefined ? "" : String(raw).trim();
      if (!rawStr) {
        const values = productFieldValues.get(resolved.field) || [];
        const idx = fieldCounters.get(resolved.field) || 0;
        if (idx < values.length) {
          fieldCounters.set(resolved.field, idx + 1);
          return formatFact(resolved.group, resolved.field, values[idx]);
        }
      }
    }

    return formatFact(resolved.group, resolved.field, resolved.value);
  });
}
