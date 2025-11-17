import type React from "react";
import { zodResolver } from "@hookform/resolvers/zod";
import { motion } from "framer-motion";
import { ClipboardList, Sparkles } from "lucide-react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import PageShell from "../components/PageShell";
import { Button } from "../components/ui/Button";
import { Card, CardContent, CardHeader, CardTitle } from "../components/ui/Card";
import { Input } from "../components/ui/Input";
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "../components/ui/Form";
import { Textarea } from "../components/ui/Textarea";
import GoogleAddressInput from "../components/GoogleAddressInput";
import GoogleBusinessTypeInput from "../components/GoogleBusinessTypeInput";
import IndustryInput from "../components/IndustryInput";

const apiBase =
  ((import.meta as any).env &&
    (import.meta as any).env.VITE_API_BASE_URL) ||
  (((import.meta as any).env && (import.meta as any).env.DEV)
    ? "http://localhost:5000"
    : "");

function parseNumberFromString(
  value: string | undefined | null
): number | null {
  if (!value) return null;
  const normalized = value.replace(/,/g, "").trim();
  if (!normalized) return null;
  const parsed = Number(normalized);
  if (!Number.isFinite(parsed)) return null;
  return parsed;
}

const intakeSchema = z
  .object({
  businessName: z.string().min(2, "Please enter your business name."),
  industry: z.string().min(2, "Please describe your industry."),
  businessType: z
    .string()
    .min(2, "Please describe the type of business."),
  description: z
    .string()
    .min(20, "Give us a bit more detail about what you do."),
  address: z.string().optional(),
  productKeywords: z
    .string()
    .min(6, "List a few keywords that describe what you sell."),
  sellingMethod: z
    .string()
    .min(4, "Describe how you expect to sell your product or service."),
  targetCustomer: z
    .string()
    .min(10, "Describe your ideal customer or audience."),
  estimatedRevenue: z
    .string()
    .min(2, "Share a rough revenue estimate or range."),
  startupCosts: z
    .string()
    .min(2, "Share your estimated one-time startup costs."),
  monthlyCosts: z
    .string()
    .min(2, "Share your estimated ongoing monthly costs."),
  pricingModel: z
    .string()
    .min(4, "Describe your pricing model or structure."),
  founderBackground: z
    .string()
    .min(10, "Share your background and why you're starting this business."),
  // Financials section
  businessStartDate: z
    .string()
    .min(1, "Business Start Date is required."),
  currentRevenue: z
    .string()
    .min(1, "Current Revenue is required."),
  currentCogs: z.string().optional(),
  expectedRevenueGrowthPctNextYear: z.string().optional(),
  unitsSoldPerMonth: z.string().optional(),
  unitDefinition: z
    .string()
    .optional()
    .refine(
      (value) => value === undefined || !/\d/.test(value),
      "Define Your Unit cannot contain numbers."
    ),
  marketingExpense: z.string().optional(),
  sgaExpense: z.string().optional(),
  otherOperatingExpense: z.string().optional(),
  currentPayroll: z.string().optional(),
  currentNumEmployees: z.string().optional(),
  plannedNumEmployees5yrs: z.string().optional(),
  currentCapex: z.string().optional(),
  plannedCapex5yr: z.string().optional(),
  totalDebtOutstanding: z.string().optional(),
  annualInterestPayment: z.string().optional(),
  annualPrincipalPayment: z.string().optional(),
  cashOnHand: z.string().optional(),
})
  .superRefine((values, ctx) => {
    const nonNegativeNumericFields = [
      "currentRevenue",
      "currentCogs",
      "unitsSoldPerMonth",
      "marketingExpense",
      "sgaExpense",
      "otherOperatingExpense",
      "currentPayroll",
      "currentNumEmployees",
      "plannedNumEmployees5yrs",
      "currentCapex",
      "plannedCapex5yr",
      "totalDebtOutstanding",
      "annualInterestPayment",
      "annualPrincipalPayment",
      "cashOnHand",
    ] as const;

    nonNegativeNumericFields.forEach((fieldName) => {
      const raw = (values as any)[fieldName];
      if (!raw) return;
      const parsed = parseNumberFromString(raw);
      if (parsed === null) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: [fieldName],
          message: "Enter a valid number.",
        });
        return;
      }
      if (parsed < 0) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: [fieldName],
          message: "Value must be zero or greater.",
        });
      }
    });

    const revenue = parseNumberFromString(values.currentRevenue);
    if (revenue !== null && revenue > 0) {
      if (!values.currentCogs) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: ["currentCogs"],
          message:
            "Cost of Goods Sold is required when revenue is greater than zero.",
        });
      }
      if (!values.expectedRevenueGrowthPctNextYear) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: ["expectedRevenueGrowthPctNextYear"],
          message:
            "Expected Revenue Growth is required when revenue is greater than zero.",
        });
      }
      if (!values.unitsSoldPerMonth) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: ["unitsSoldPerMonth"],
          message:
            "Units Sold Per Month is required when revenue is greater than zero.",
        });
      }
      if (!values.unitDefinition) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: ["unitDefinition"],
          message:
            "Define Your Unit is required when revenue is greater than zero.",
        });
      }
    }
  });

type IntakeValues = z.infer<typeof intakeSchema>;

const serverFieldToFormField: Record<string, keyof IntakeValues> = {
  business_start_date: "businessStartDate",
  current_revenue: "currentRevenue",
  current_cogs: "currentCogs",
  expected_revenue_growth_pct_next_year: "expectedRevenueGrowthPctNextYear",
  units_sold_per_month: "unitsSoldPerMonth",
  marketing_expense: "marketingExpense",
  sga_expense: "sgaExpense",
  other_operating_expense: "otherOperatingExpense",
  current_payroll: "currentPayroll",
  current_num_employees: "currentNumEmployees",
  planned_num_employees_5yrs: "plannedNumEmployees5yrs",
  current_capex: "currentCapex",
  planned_capex_5yr: "plannedCapex5yr",
  total_debt_outstanding: "totalDebtOutstanding",
  annual_interest_payment: "annualInterestPayment",
  annual_principal_payment: "annualPrincipalPayment",
  cash_on_hand: "cashOnHand",
  unit_definition: "unitDefinition",
};

const defaultValues: IntakeValues = {
  businessName: "",
  industry: "",
  businessType: "",
  description: "",
  address: "",
  productKeywords: "",
  sellingMethod: "",
  targetCustomer: "",
  estimatedRevenue: "",
  startupCosts: "",
  monthlyCosts: "",
  pricingModel: "",
  founderBackground: "",
  businessStartDate: "",
  currentRevenue: "",
  currentCogs: "",
  expectedRevenueGrowthPctNextYear: "",
  unitsSoldPerMonth: "",
  unitDefinition: "",
  marketingExpense: "",
  sgaExpense: "",
  otherOperatingExpense: "",
  currentPayroll: "",
  currentNumEmployees: "",
  plannedNumEmployees5yrs: "",
  currentCapex: "",
  plannedCapex5yr: "",
  totalDebtOutstanding: "",
  annualInterestPayment: "",
  annualPrincipalPayment: "",
  cashOnHand: "",
};

function IntakeFormPage() {
  const form = useForm<IntakeValues>({
    resolver: zodResolver(intakeSchema),
    defaultValues,
    mode: "onBlur",
  });

  function formatNumericForDisplay(raw: string): string {
    const withoutCommas = raw.replace(/,/g, "");
    if (!withoutCommas.trim()) return "";

    const parts = withoutCommas.split(".");
    const integerPart = parts[0].replace(/[^\d]/g, "");
    const fractionalPart = parts[1]?.replace(/[^\d]/g, "") ?? "";

    if (!integerPart) {
      return fractionalPart ? `0.${fractionalPart}` : "";
    }

    const parsedInteger = Number(integerPart);
    if (!Number.isFinite(parsedInteger)) return "";

    const formattedInteger = parsedInteger.toLocaleString("en-US", {
      maximumFractionDigits: 0,
    });

    if (!fractionalPart) return formattedInteger;

    return `${formattedInteger}.${fractionalPart}`;
  }

  function handleNumericChange(
    event: React.ChangeEvent<HTMLInputElement>,
    onChange: (value: unknown) => void
  ) {
    const rawValue = event.target.value ?? "";
    const sanitized = rawValue.replace(/-/g, "");
    onChange(sanitized);
  }

  function handleNumericBlur(
    event: React.FocusEvent<HTMLInputElement>,
    fieldName: keyof IntakeValues
  ) {
    const rawValue = event.target.value ?? "";
    const withoutCommas = rawValue.replace(/,/g, "").trim();

    if (!withoutCommas) {
      form.setValue(fieldName, "", {
        shouldValidate: true,
        shouldDirty: true,
      });
      return;
    }

    const parsed = Number(withoutCommas);
    if (!Number.isFinite(parsed)) {
      form.setValue(fieldName, rawValue, {
        shouldValidate: true,
        shouldDirty: true,
      });
      return;
    }

    const nonNegative = parsed < 0 ? 0 : parsed;
    const formatted = formatNumericForDisplay(String(nonNegative));

    form.setValue(fieldName, formatted, {
      shouldValidate: true,
      shouldDirty: true,
    });
  }

  async function handleSubmit(values: IntakeValues) {
    const base =
      typeof apiBase === "string" && apiBase.length
        ? apiBase.replace(/\/$/, "")
        : "";
    const url = base ? `${base}/api/financials` : "/api/financials";

    const dateRaw = values.businessStartDate;
    let businessStartDateFormatted: string | null = null;
    if (dateRaw) {
      const [year, month, day] = dateRaw.split("-");
      if (year && month && day) {
        businessStartDateFormatted = `${month}-${day}-${year}`;
      }
    }

    const financialsPayload = {
      business_start_date: businessStartDateFormatted,
      current_revenue: parseNumberFromString(values.currentRevenue),
      current_cogs: parseNumberFromString(values.currentCogs),
      expected_revenue_growth_pct_next_year:
        values.expectedRevenueGrowthPctNextYear,
      units_sold_per_month: parseNumberFromString(values.unitsSoldPerMonth),
      marketing_expense: parseNumberFromString(values.marketingExpense),
      sga_expense: parseNumberFromString(values.sgaExpense),
      other_operating_expense: parseNumberFromString(
        values.otherOperatingExpense
      ),
      current_payroll: parseNumberFromString(values.currentPayroll),
      current_num_employees: parseNumberFromString(
        values.currentNumEmployees
      ),
      planned_num_employees_5yrs: parseNumberFromString(
        values.plannedNumEmployees5yrs
      ),
      current_capex: parseNumberFromString(values.currentCapex),
      planned_capex_5yr: parseNumberFromString(values.plannedCapex5yr),
      total_debt_outstanding: parseNumberFromString(
        values.totalDebtOutstanding
      ),
      annual_interest_payment: parseNumberFromString(
        values.annualInterestPayment
      ),
      annual_principal_payment: parseNumberFromString(
        values.annualPrincipalPayment
      ),
      cash_on_hand: parseNumberFromString(values.cashOnHand),
      unit_definition: values.unitDefinition,
    };

    Object.values(serverFieldToFormField).forEach((fieldName) => {
      form.clearErrors(fieldName);
    });

    try {
      const res = await fetch(url, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(financialsPayload),
      });

      const contentType = res.headers.get("content-type") || "";
      let body: any = null;

      if (contentType.includes("application/json")) {
        body = await res.json();
      } else {
        const text = await res.text();
        throw new Error(
          `Unexpected response from /api/financials: ${res.status} ${res.statusText} ${text.slice(
            0,
            120
          )}`
        );
      }

      if (!res.ok) {
        if (body && typeof body === "object" && body.errors) {
          Object.entries(body.errors).forEach(([serverField, message]) => {
            const formField = serverFieldToFormField[serverField];
            if (formField) {
              form.setError(formField, {
                type: "server",
                message: String(message),
              });
            }
          });
        } else {
          console.error("Error submitting financials:", body);
        }
        return;
      }

      console.log("Financials submitted successfully", body);
    } catch (error) {
      console.error("Error submitting financials:", error);
    }

    console.log("Intake submission", values);
  }

  return (
    <PageShell>
      <div className="space-y-8 md:space-y-10">
        <section className="space-y-3">
          <motion.div
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.4 }}
          >
            <div className="inline-flex items-center gap-2 rounded-full border border-sky-400/20 bg-slate-950/80 px-3 py-1 text-[11px] text-sky-200/90 shadow-soft backdrop-blur-xl">
              <Sparkles className="h-3 w-3" />
              <span className="section-label text-[10px] text-sky-100/90">
                Business Plan Intake
              </span>
            </div>
            <h1 className="mt-3 text-2xl font-semibold tracking-tight text-slate-50 md:text-3xl">
              Tell us about your business.
            </h1>
            <p className="mt-2 max-w-2xl text-sm leading-relaxed text-slate-300">
              This intake form gives us the context we need to craft a
              lender-ready business plan tailored to your goals, industry, and
              numbers. Expect ~15–20 minutes to complete.
            </p>
          </motion.div>
        </section>

        <Form form={form} onSubmit={handleSubmit} className="space-y-8">
          <div className="grid gap-5 md:grid-cols-[1.3fr_1fr]">
            {/* Business basics */}
            <Card className="border border-slate-800/80 bg-slate-950/90">
              <CardHeader className="border-0 pb-3">
                <CardTitle className="flex items-center gap-2 text-sm">
                  <span className="inline-flex h-7 w-7 items-center justify-center rounded-xl bg-sky-500/15 text-sky-300 ring-1 ring-sky-500/40">
                    <ClipboardList className="h-3.5 w-3.5" />
                  </span>
                  Business overview
                </CardTitle>
              </CardHeader>
              <CardContent className="grid gap-4 pt-1 md:grid-cols-2">
                <FormField name="businessName" control={form.control}>
                  {(field) => (
                    <FormItem className="col-span-2 md:col-span-2">
                      <FormLabel>Business name</FormLabel>
                      <FormControl>
                        <Input
                          {...field}
                          placeholder="Working or legal name of your business"
                        />
                      </FormControl>
                      <FormMessage>
                        {form.formState.errors.businessName?.message}
                      </FormMessage>
                    </FormItem>
                  )}
                </FormField>

                <FormField name="industry" control={form.control}>
                  {(field) => (
                    <FormItem>
                      <FormLabel>Industry</FormLabel>
                      <FormControl>
                        <IndustryInput
                          {...field}
                          placeholder="Select your industry"
                        />
                      </FormControl>
                      <FormMessage>
                        {form.formState.errors.industry?.message}
                      </FormMessage>
                    </FormItem>
                  )}
                </FormField>

                  <FormField name="businessType" control={form.control}>
                    {(field) => (
                      <FormItem>
                        <FormLabel>Type of Business</FormLabel>
                        <FormControl>
                          <GoogleBusinessTypeInput
                            {...field}
                            placeholder="E.g., coffee shop, trucking company, HVAC repair, childcare, bookkeeping"
                          />
                        </FormControl>
                        <FormMessage>
                          {form.formState.errors.businessType?.message}
                        </FormMessage>
                      </FormItem>
                    )}
                  </FormField>

                  <FormField name="address" control={form.control}>
                  {(field) => (
                    <FormItem>
                      <FormLabel>Business address</FormLabel>
                      <FormControl>
                        <GoogleAddressInput
                          {...field}
                          placeholder="If applicable, list your physical location"
                        />
                      </FormControl>
                      <FormMessage>
                        {form.formState.errors.address?.message}
                      </FormMessage>
                    </FormItem>
                  )}
                </FormField>

                <FormField name="description" control={form.control}>
                  {(field) => (
                    <FormItem className="col-span-2">
                      <FormLabel>Business description</FormLabel>
                      <FormControl>
                        <Textarea
                          {...field}
                          rows={4}
                          placeholder="In 3–5 sentences, describe what your business does and how it creates value."
                        />
                      </FormControl>
                      <FormMessage>
                        {form.formState.errors.description?.message}
                      </FormMessage>
                    </FormItem>
                  )}
                </FormField>
              </CardContent>
            </Card>

            {/* Snapshot card */}
            <Card className="border border-slate-800/80 bg-slate-950/90">
              <CardHeader className="border-0 pb-2">
                <CardTitle className="text-sm">What to expect next</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3 text-[11px] text-slate-300">
                <p>
                  After you submit this form, we'll review your details and
                  confirm fit, scope, and timing. No payment is required to
                  complete the intake.
                </p>
                <ul className="space-y-1.5">
                  <li>• Review and alignment on goals and audience.</li>
                  <li>• Clarifying questions where needed.</li>
                  <li>• Confirmation of timeline and next steps.</li>
                </ul>
                <p className="text-slate-400">
                  The more specific you are, the more precise and compelling
                  your finished plan can be.
                </p>
              </CardContent>
            </Card>
          </div>

          {/* Offering & customers */}
          <div className="grid gap-5 md:grid-cols-2">
            <Card className="border border-slate-800/80 bg-slate-950/90">
              <CardHeader className="border-0 pb-3">
                <CardTitle className="text-sm">What you offer</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <FormField name="productKeywords" control={form.control}>
                  {(field) => (
                    <FormItem>
                      <FormLabel>Product / service keywords</FormLabel>
                      <FormControl>
                        <Textarea
                          {...field}
                          rows={3}
                          placeholder="List key products or services, separated by commas."
                        />
                      </FormControl>
                      <FormMessage>
                        {form.formState.errors.productKeywords?.message}
                      </FormMessage>
                    </FormItem>
                  )}
                </FormField>

                <FormField name="sellingMethod" control={form.control}>
                  {(field) => (
                    <FormItem>
                      <FormLabel>Preferred selling method</FormLabel>
                      <FormControl>
                        <Textarea
                          {...field}
                          rows={3}
                          placeholder="Describe how you plan to sell: in-person, online, recurring, project-based, etc."
                        />
                      </FormControl>
                      <FormMessage>
                        {form.formState.errors.sellingMethod?.message}
                      </FormMessage>
                    </FormItem>
                  )}
                </FormField>
              </CardContent>
            </Card>

            <Card className="border border-slate-800/80 bg-slate-950/90">
              <CardHeader className="border-0 pb-3">
                <CardTitle className="text-sm">
                  Customers &amp; positioning
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <FormField name="targetCustomer" control={form.control}>
                  {(field) => (
                    <FormItem>
                      <FormLabel>Target customer</FormLabel>
                      <FormControl>
                        <Textarea
                          {...field}
                          rows={3}
                          placeholder="Who is your ideal customer? Include demographics, behaviors, and context."
                        />
                      </FormControl>
                      <FormMessage>
                        {form.formState.errors.targetCustomer?.message}
                      </FormMessage>
                    </FormItem>
                  )}
                </FormField>

                <FormField name="pricingModel" control={form.control}>
                  {(field) => (
                    <FormItem>
                      <FormLabel>Pricing model</FormLabel>
                      <FormControl>
                        <Textarea
                          {...field}
                          rows={3}
                          placeholder="Describe your pricing (e.g., flat-fee, tiered, hourly, subscription, retainers)."
                        />
                      </FormControl>
                      <FormMessage>
                        {form.formState.errors.pricingModel?.message}
                      </FormMessage>
                    </FormItem>
                  )}
                </FormField>
              </CardContent>
            </Card>
          </div>

          {/* Financials */}
          <Card className="border border-slate-800/80 bg-slate-950/90">
            <CardHeader className="border-0 pb-3">
              <CardTitle className="text-sm">Financials</CardTitle>
            </CardHeader>
            <CardContent className="space-y-6">
              <FormField name="businessStartDate" control={form.control}>
                {(field) => (
                  <FormItem>
                    <FormLabel>Business Start Date</FormLabel>
                    <FormControl>
                      <Input
                        type="date"
                        value={(field.value as string) || ""}
                        onChange={(event) => field.onChange(event.target.value)}
                      />
                    </FormControl>
                    <FormMessage>
                      {form.formState.errors.businessStartDate?.message}
                    </FormMessage>
                  </FormItem>
                )}
              </FormField>

              <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">

              <div className="space-y-3 rounded-lg border border-slate-800/80 bg-slate-950/80 p-4">
                <div className="text-[11px] font-semibold tracking-tight text-slate-200">
                  Revenue Model
                </div>
                <div className="grid gap-3">
                  <FormField name="currentRevenue" control={form.control}>
                    {(field) => (
                      <FormItem>
                        <FormLabel>Current Revenue</FormLabel>
                        <FormControl>
                          <Input
                            {...field}
                            type="text"
                            inputMode="decimal"
                            min={0}
                            placeholder="Enter current revenue"
                            onChange={(event) =>
                              handleNumericChange(event, field.onChange)
                            }
                            onBlur={(event) => {
                              field.onBlur();
                              handleNumericBlur(event, "currentRevenue");
                            }}
                          />
                        </FormControl>
                        <FormMessage>
                          {form.formState.errors.currentRevenue?.message}
                        </FormMessage>
                      </FormItem>
                    )}
                  </FormField>

                  <FormField name="currentCogs" control={form.control}>
                    {(field) => (
                      <FormItem>
                        <FormLabel>Cost of Goods Sold (COGS)</FormLabel>
                        <FormControl>
                          <Input
                            {...field}
                            type="text"
                            inputMode="decimal"
                            min={0}
                            placeholder="Required if revenue is greater than 0"
                            onChange={(event) =>
                              handleNumericChange(event, field.onChange)
                            }
                            onBlur={(event) => {
                              field.onBlur();
                              handleNumericBlur(event, "currentCogs");
                            }}
                          />
                        </FormControl>
                        <FormMessage>
                          {form.formState.errors.currentCogs?.message}
                        </FormMessage>
                      </FormItem>
                    )}
                  </FormField>

                  <FormField
                    name="expectedRevenueGrowthPctNextYear"
                    control={form.control}
                  >
                    {(field) => (
                      <FormItem>
                        <FormLabel>Expected Revenue Growth (%)</FormLabel>
                        <FormControl>
                          <Input
                            {...field}
                            type="text"
                            inputMode="decimal"
                            min={0}
                            max={100}
                            step={1}
                            placeholder="Required if revenue is greater than 0"
                            onChange={(event) =>
                              handleNumericChange(event, field.onChange)
                            }
                          />
                        </FormControl>
                        <FormMessage>
                          {
                            form.formState.errors
                              .expectedRevenueGrowthPctNextYear?.message
                          }
                        </FormMessage>
                      </FormItem>
                    )}
                  </FormField>

                  <FormField
                    name="unitsSoldPerMonth"
                    control={form.control}
                  >
                    {(field) => (
                      <FormItem>
                        <FormLabel>Units Sold Per Month</FormLabel>
                        <FormControl>
                          <Input
                            {...field}
                            type="text"
                            inputMode="decimal"
                            min={0}
                            placeholder="Required if revenue is greater than 0"
                            onChange={(event) =>
                              handleNumericChange(event, field.onChange)
                            }
                            onBlur={(event) => {
                              field.onBlur();
                              handleNumericBlur(event, "unitsSoldPerMonth");
                            }}
                          />
                        </FormControl>
                        <FormMessage>
                          {form.formState.errors.unitsSoldPerMonth?.message}
                        </FormMessage>
                      </FormItem>
                    )}
                  </FormField>

                  <FormField name="unitDefinition" control={form.control}>
                    {(field) => (
                      <FormItem>
                        <FormLabel>Define Your Unit</FormLabel>
                        <FormControl>
                          <Input
                            {...field}
                            type="text"
                            placeholder="E.g., billable hours, taxi rides, cups sold"
                          />
                        </FormControl>
                        <FormMessage>
                          {form.formState.errors.unitDefinition?.message}
                        </FormMessage>
                      </FormItem>
                    )}
                  </FormField>
                </div>
              </div>

              <div className="space-y-3 rounded-lg border border-slate-800/80 bg-slate-950/80 p-4">
                <div className="text-[11px] font-semibold tracking-tight text-slate-200">
                  Operating Expenses
                </div>
                <div className="grid gap-3">
                  <FormField name="marketingExpense" control={form.control}>
                    {(field) => (
                      <FormItem>
                        <FormLabel>Marketing Expense</FormLabel>
                        <FormControl>
                          <Input
                            {...field}
                            type="text"
                            inputMode="decimal"
                            min={0}
                            onChange={(event) =>
                              handleNumericChange(event, field.onChange)
                            }
                            onBlur={(event) => {
                              field.onBlur();
                              handleNumericBlur(event, "marketingExpense");
                            }}
                          />
                        </FormControl>
                        <FormMessage>
                          {form.formState.errors.marketingExpense?.message}
                        </FormMessage>
                      </FormItem>
                    )}
                  </FormField>

                  <FormField name="sgaExpense" control={form.control}>
                    {(field) => (
                      <FormItem>
                        <FormLabel>SG&amp;A Expense</FormLabel>
                        <FormControl>
                          <Input
                            {...field}
                            type="text"
                            inputMode="decimal"
                            min={0}
                            onChange={(event) =>
                              handleNumericChange(event, field.onChange)
                            }
                            onBlur={(event) => {
                              field.onBlur();
                              handleNumericBlur(event, "sgaExpense");
                            }}
                          />
                        </FormControl>
                        <FormMessage>
                          {form.formState.errors.sgaExpense?.message}
                        </FormMessage>
                      </FormItem>
                    )}
                  </FormField>

                  <FormField
                    name="otherOperatingExpense"
                    control={form.control}
                  >
                    {(field) => (
                      <FormItem>
                        <FormLabel>Other Operating Expense</FormLabel>
                        <FormControl>
                          <Input
                            {...field}
                            type="text"
                            inputMode="decimal"
                            min={0}
                            onChange={(event) =>
                              handleNumericChange(event, field.onChange)
                            }
                            onBlur={(event) => {
                              field.onBlur();
                              handleNumericBlur(
                                event,
                                "otherOperatingExpense"
                              );
                            }}
                          />
                        </FormControl>
                        <FormMessage>
                          {
                            form.formState.errors.otherOperatingExpense
                              ?.message
                          }
                        </FormMessage>
                      </FormItem>
                    )}
                  </FormField>

                  <FormField name="currentPayroll" control={form.control}>
                    {(field) => (
                      <FormItem>
                        <FormLabel>Current Payroll</FormLabel>
                        <FormControl>
                          <Input
                            {...field}
                            type="text"
                            inputMode="decimal"
                            min={0}
                            onChange={(event) =>
                              handleNumericChange(event, field.onChange)
                            }
                            onBlur={(event) => {
                              field.onBlur();
                              handleNumericBlur(event, "currentPayroll");
                            }}
                          />
                        </FormControl>
                        <FormMessage>
                          {form.formState.errors.currentPayroll?.message}
                        </FormMessage>
                      </FormItem>
                    )}
                  </FormField>

                  <FormField
                    name="currentNumEmployees"
                    control={form.control}
                  >
                    {(field) => (
                      <FormItem>
                        <FormLabel>Current Number of Employees</FormLabel>
                        <FormControl>
                          <Input
                            {...field}
                            type="text"
                            inputMode="decimal"
                            min={0}
                            onChange={(event) =>
                              handleNumericChange(event, field.onChange)
                            }
                            onBlur={(event) => {
                              field.onBlur();
                              handleNumericBlur(
                                event,
                                "currentNumEmployees"
                              );
                            }}
                          />
                        </FormControl>
                        <FormMessage>
                          {
                            form.formState.errors.currentNumEmployees
                              ?.message
                          }
                        </FormMessage>
                      </FormItem>
                    )}
                  </FormField>

                  <FormField
                    name="plannedNumEmployees5yrs"
                    control={form.control}
                  >
                    {(field) => (
                      <FormItem>
                        <FormLabel>
                          Planned Number of Employees in 5 Years
                        </FormLabel>
                        <FormControl>
                          <Input
                            {...field}
                            type="text"
                            inputMode="decimal"
                            min={0}
                            onChange={(event) =>
                              handleNumericChange(event, field.onChange)
                            }
                            onBlur={(event) => {
                              field.onBlur();
                              handleNumericBlur(
                                event,
                                "plannedNumEmployees5yrs"
                              );
                            }}
                          />
                        </FormControl>
                        <FormMessage>
                          {
                            form.formState.errors.plannedNumEmployees5yrs
                              ?.message
                          }
                        </FormMessage>
                      </FormItem>
                    )}
                  </FormField>
                </div>
              </div>

              <div className="space-y-3 rounded-lg border border-slate-800/80 bg-slate-950/80 p-4">
                <div className="text-[11px] font-semibold tracking-tight text-slate-200">
                  Capital Expenditures
                </div>
                <div className="grid gap-3">
                  <FormField name="currentCapex" control={form.control}>
                    {(field) => (
                      <FormItem>
                        <FormLabel>Current Capex</FormLabel>
                        <FormControl>
                          <Input
                            {...field}
                            type="text"
                            inputMode="decimal"
                            min={0}
                            onChange={(event) =>
                              handleNumericChange(event, field.onChange)
                            }
                            onBlur={(event) => {
                              field.onBlur();
                              handleNumericBlur(event, "currentCapex");
                            }}
                          />
                        </FormControl>
                        <FormMessage>
                          {form.formState.errors.currentCapex?.message}
                        </FormMessage>
                      </FormItem>
                    )}
                  </FormField>

                  <FormField name="plannedCapex5yr" control={form.control}>
                    {(field) => (
                      <FormItem>
                        <FormLabel>Planned Capex (5 Years)</FormLabel>
                        <FormControl>
                          <Input
                            {...field}
                            type="text"
                            inputMode="decimal"
                            min={0}
                            onChange={(event) =>
                              handleNumericChange(event, field.onChange)
                            }
                            onBlur={(event) => {
                              field.onBlur();
                              handleNumericBlur(event, "plannedCapex5yr");
                            }}
                          />
                        </FormControl>
                        <FormMessage>
                          {form.formState.errors.plannedCapex5yr?.message}
                        </FormMessage>
                      </FormItem>
                    )}
                  </FormField>
                </div>
              </div>

              <div className="space-y-3 rounded-lg border border-slate-800/80 bg-slate-950/80 p-4">
                <div className="text-[11px] font-semibold tracking-tight text-slate-200">
                  Debt &amp; Liquidity
                </div>
                <div className="grid gap-3">
                  <FormField
                    name="totalDebtOutstanding"
                    control={form.control}
                  >
                    {(field) => (
                      <FormItem>
                        <FormLabel>Total Debt Outstanding</FormLabel>
                        <FormControl>
                          <Input
                            {...field}
                            type="text"
                            inputMode="decimal"
                            min={0}
                            onChange={(event) =>
                              handleNumericChange(event, field.onChange)
                            }
                            onBlur={(event) => {
                              field.onBlur();
                              handleNumericBlur(
                                event,
                                "totalDebtOutstanding"
                              );
                            }}
                          />
                        </FormControl>
                        <FormMessage>
                          {
                            form.formState.errors.totalDebtOutstanding
                              ?.message
                          }
                        </FormMessage>
                      </FormItem>
                    )}
                  </FormField>

                  <FormField
                    name="annualInterestPayment"
                    control={form.control}
                  >
                    {(field) => (
                      <FormItem>
                        <FormLabel>Annual Interest Payment</FormLabel>
                        <FormControl>
                          <Input
                            {...field}
                            type="text"
                            inputMode="decimal"
                            min={0}
                            onChange={(event) =>
                              handleNumericChange(event, field.onChange)
                            }
                            onBlur={(event) => {
                              field.onBlur();
                              handleNumericBlur(
                                event,
                                "annualInterestPayment"
                              );
                            }}
                          />
                        </FormControl>
                        <FormMessage>
                          {
                            form.formState.errors.annualInterestPayment
                              ?.message
                          }
                        </FormMessage>
                      </FormItem>
                    )}
                  </FormField>

                  <FormField
                    name="annualPrincipalPayment"
                    control={form.control}
                  >
                    {(field) => (
                      <FormItem>
                        <FormLabel>Annual Principal Payment</FormLabel>
                        <FormControl>
                          <Input
                            {...field}
                            type="text"
                            inputMode="decimal"
                            min={0}
                            onChange={(event) =>
                              handleNumericChange(event, field.onChange)
                            }
                            onBlur={(event) => {
                              field.onBlur();
                              handleNumericBlur(
                                event,
                                "annualPrincipalPayment"
                              );
                            }}
                          />
                        </FormControl>
                        <FormMessage>
                          {
                            form.formState.errors.annualPrincipalPayment
                              ?.message
                          }
                        </FormMessage>
                      </FormItem>
                    )}
                  </FormField>

                  <FormField name="cashOnHand" control={form.control}>
                    {(field) => (
                      <FormItem>
                        <FormLabel>Cash on Hand</FormLabel>
                        <FormControl>
                          <Input
                            {...field}
                            type="text"
                            inputMode="decimal"
                            min={0}
                            onChange={(event) =>
                              handleNumericChange(event, field.onChange)
                            }
                            onBlur={(event) => {
                              field.onBlur();
                              handleNumericBlur(event, "cashOnHand");
                            }}
                          />
                        </FormControl>
                        <FormMessage>
                          {form.formState.errors.cashOnHand?.message}
                        </FormMessage>
                      </FormItem>
                    )}
                  </FormField>
                </div>
              </div>
              </div>
            </CardContent>
          </Card>

          {/* Financial snapshot & founder background */}
          <div className="grid gap-5 md:grid-cols-2">
            <Card className="border border-slate-800/80 bg-slate-950/90">
              <CardHeader className="border-0 pb-3">
                <CardTitle className="text-sm">
                  Financial snapshot (high level)
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <FormField name="estimatedRevenue" control={form.control}>
                  {(field) => (
                    <FormItem>
                      <FormLabel>Estimated annual revenue</FormLabel>
                      <FormControl>
                        <Textarea
                          {...field}
                          rows={2}
                          placeholder="Share your expected first-year or steady-state annual revenue (ranges are okay)."
                        />
                      </FormControl>
                      <FormMessage>
                        {form.formState.errors.estimatedRevenue?.message}
                      </FormMessage>
                    </FormItem>
                  )}
                </FormField>

                <FormField name="startupCosts" control={form.control}>
                  {(field) => (
                    <FormItem>
                      <FormLabel>Startup costs</FormLabel>
                      <FormControl>
                        <Textarea
                          {...field}
                          rows={2}
                          placeholder="List your one-time startup costs (build-out, equipment, launch, etc.)."
                        />
                      </FormControl>
                      <FormMessage>
                        {form.formState.errors.startupCosts?.message}
                      </FormMessage>
                    </FormItem>
                  )}
                </FormField>

                <FormField name="monthlyCosts" control={form.control}>
                  {(field) => (
                    <FormItem>
                      <FormLabel>Ongoing monthly costs</FormLabel>
                      <FormControl>
                        <Textarea
                          {...field}
                          rows={2}
                          placeholder="List key monthly costs (rent, payroll, software, marketing, etc.)."
                        />
                      </FormControl>
                      <FormMessage>
                        {form.formState.errors.monthlyCosts?.message}
                      </FormMessage>
                    </FormItem>
                  )}
                </FormField>
              </CardContent>
            </Card>

            <Card className="border border-slate-800/80 bg-slate-950/90">
              <CardHeader className="border-0 pb-3">
                <CardTitle className="text-sm">
                  Founder background &amp; story
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <FormField name="founderBackground" control={form.control}>
                  {(field) => (
                    <FormItem>
                      <FormLabel>Founder background</FormLabel>
                      <FormControl>
                        <Textarea
                          {...field}
                          rows={5}
                          placeholder="Share your experience, expertise, and why you are the right person or team to build this business."
                        />
                      </FormControl>
                      <FormMessage>
                        {form.formState.errors.founderBackground?.message}
                      </FormMessage>
                    </FormItem>
                  )}
                </FormField>
              </CardContent>
            </Card>
          </div>

          <motion.div
            className="flex flex-col items-start justify-between gap-4 border-t border-slate-800/80 pt-4 text-[11px] text-slate-400 md:flex-row md:items-center"
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.35 }}
          >
            <div>
              <p className="font-medium text-slate-100">
                Ready? Submit your intake for review.
              </p>
              <p className="mt-1 max-w-xl">
                We'll review your information, follow up with any clarifying
                questions, and outline next steps. No automatic billing or
                commitments from this form alone.
              </p>
            </div>
            <Button
              type="submit"
              size="lg"
              className="group rounded-full px-6 text-xs sm:text-sm"
            >
              Submit intake
            </Button>
          </motion.div>
        </Form>
      </div>
    </PageShell>
  );
}

export default IntakeFormPage;
