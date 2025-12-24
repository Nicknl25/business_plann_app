import type React from "react";
import { zodResolver } from "@hookform/resolvers/zod";
import { motion } from "framer-motion";
import { ClipboardList, Sparkles } from "lucide-react";
import { useState } from "react";
import { useEffect } from "react";
import { useForm, type FieldErrors } from "react-hook-form";
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
import HelpTooltip from "../components/ui/HelpTooltip";
import { TOOLTIP_TEXT } from "../components/ui/tooltip";
import apiClient from "../apiClient";

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
  businessType: z
    .string()
    .min(2, "Please describe the type of business."),
  address: z.string().optional(),
  productKeywords: z.string().optional(),
  customerAgeRange: z
    .string()
    .min(1, "Age Range is required."),
  customerIncomeLevel: z
    .string()
    .min(1, "Income Level is required."),
  customerType: z
    .string()
    .min(1, "Customer Type is required."),
  firstName: z.string().min(1, "First Name is required."),
  lastName: z.string().min(1, "Last Name is required."),
  emailAddress: z
    .string()
    .email("Please enter a valid email address."),
  phoneNumber: z.string().optional(),
  howDidYouHear: z.string().optional(),
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
  taxRate: z.string().optional(),
  marketingExpense: z.string().optional(),
  rAndDExpense: z.string().optional(),
  sgaExpense: z.string().optional(),
  otherOperatingExpense: z.string().optional(),
  monthlyRentExpense: z.string().optional(),
  otherMonthlyDebtPayments: z.string().optional(),
  currentPayroll: z.string().optional(),
  currentNumEmployees: z.string().optional(),
  plannedNumEmployees5yrs: z.string().optional(),
  currentCapex: z.string().optional(),
  plannedCapex5yr: z.string().optional(),
  arBalance: z.string().optional(),
  apBalance: z.string().optional(),
  inventoryBalance: z.string().optional(),
  totalDebtOutstanding: z.string().optional(),
  annualInterestPayment: z.string().optional(),
  annualPrincipalPayment: z.string().optional(),
  ownerCompensation: z.string().optional(),
  cashOnHand: z.string().optional(),
})
  .superRefine((values, ctx) => {
    const nonNegativeNumericFields = [
      "currentRevenue",
      "currentCogs",
      "taxRate",
      "marketingExpense",
      "rAndDExpense",
      "sgaExpense",
      "otherOperatingExpense",
      "currentPayroll",
      "currentNumEmployees",
      "plannedNumEmployees5yrs",
      "currentCapex",
      "plannedCapex5yr",
      "arBalance",
      "apBalance",
      "inventoryBalance",
      "totalDebtOutstanding",
      "annualInterestPayment",
      "annualPrincipalPayment",
      "ownerCompensation",
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
    }
  });

type IntakeValues = z.infer<typeof intakeSchema>;

const serverFieldToFormField: Record<string, keyof IntakeValues> = {
  business_name: "businessName",
  business_type: "businessType",
  address: "address",
  customer_age_range: "customerAgeRange",
  customer_income_level: "customerIncomeLevel",
  customer_type: "customerType",
  first_name: "firstName",
  last_name: "lastName",
  email_address: "emailAddress",
  phone_number: "phoneNumber",
  how_did_you_hear: "howDidYouHear",
  founder_background: "founderBackground",
  business_start_date: "businessStartDate",
  current_revenue: "currentRevenue",
  current_cogs: "currentCogs",
  expected_revenue_growth_pct_next_year: "expectedRevenueGrowthPctNextYear",
  tax_rate: "taxRate",
  marketing_expense: "marketingExpense",
  r_and_d_expense: "rAndDExpense",
  sga_expense: "sgaExpense",
  other_operating_expense: "otherOperatingExpense",
  current_payroll: "currentPayroll",
  current_num_employees: "currentNumEmployees",
  planned_num_employees_5yrs: "plannedNumEmployees5yrs",
  current_capex: "currentCapex",
  planned_capex_5yr: "plannedCapex5yr",
  ar_balance: "arBalance",
  ap_balance: "apBalance",
  inventory_balance: "inventoryBalance",
  total_debt_outstanding: "totalDebtOutstanding",
  annual_interest_payment: "annualInterestPayment",
  annual_principal_payment: "annualPrincipalPayment",
  owner_compensation: "ownerCompensation",
  cash_on_hand: "cashOnHand",
};

const defaultValues: IntakeValues = {
  businessName: "",
  businessType: "",
  address: "",
  productKeywords: "",
  customerAgeRange: "",
  customerIncomeLevel: "",
  customerType: "",
  firstName: "",
  lastName: "",
  emailAddress: "",
  phoneNumber: "",
  howDidYouHear: "",
  founderBackground: "",
  businessStartDate: "",
  currentRevenue: "",
  currentCogs: "",
  expectedRevenueGrowthPctNextYear: "",
  taxRate: "",
  marketingExpense: "",
  rAndDExpense: "",
  sgaExpense: "",
  otherOperatingExpense: "",
  monthlyRentExpense: "",
  otherMonthlyDebtPayments: "",
  currentPayroll: "",
  currentNumEmployees: "",
  plannedNumEmployees5yrs: "",
  currentCapex: "",
  plannedCapex5yr: "",
  arBalance: "",
  apBalance: "",
  inventoryBalance: "",
  totalDebtOutstanding: "",
  annualInterestPayment: "",
  annualPrincipalPayment: "",
  ownerCompensation: "",
  cashOnHand: "",
};

function IntakeFormPage() {
  const form = useForm<IntakeValues>({
    resolver: zodResolver(intakeSchema),
    defaultValues,
    mode: "onBlur",
  });

  const consultStorage = {
    getDraftId: () => sessionStorage.getItem("intake_consult_draft_id"),
    getClientId: () => sessionStorage.getItem("intake_consult_client_id"),
    set: (draft_id: string, client_id: string) => {
      sessionStorage.setItem("intake_consult_draft_id", draft_id);
      sessionStorage.setItem("intake_consult_client_id", client_id);
    },
    clear: () => {
      sessionStorage.removeItem("intake_consult_draft_id");
      sessionStorage.removeItem("intake_consult_client_id");
    },
  };

  const [clientId, setClientId] = useState<string | null>(null);
  const [draftId, setDraftId] = useState<string | null>(null);
  const [consultMessages, setConsultMessages] = useState<
    { role: "user" | "assistant"; content: string }[]
  >([]);
  const [consultInput, setConsultInput] = useState("");
  const [consultDone, setConsultDone] = useState(false);
  const [consultLoading, setConsultLoading] = useState(false);
  const [consultError, setConsultError] = useState<string | null>(null);
  const [consultFinal, setConsultFinal] = useState<any | null>(null);
  const [submitLoading, setSubmitLoading] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [submitSuccess, setSubmitSuccess] = useState<{
    clientId: string;
    intakeSubmissionId?: string;
  } | null>(null);

  useEffect(() => {
    (async () => {
      const storedDraftId = consultStorage.getDraftId();
      const storedClientId = consultStorage.getClientId();
      if (!storedDraftId || !storedClientId) return;

      try {
        const res = await apiClient.get("/api/intake-consult/draft", {
          params: { draft_id: storedDraftId },
          validateStatus: () => true,
        });
        if (res.status < 200 || res.status >= 300) return;

        const body: any = res.data;
        setDraftId(String(body?.draft_id || storedDraftId));
        setClientId(String(body?.client_id || storedClientId));

        const draftStatus = String(body?.draft_status || "");
        if (draftStatus === "submitted") {
          consultStorage.clear();
          return;
        }
        const messagesJson = body?.messages_json;
        if (messagesJson) {
          try {
            const parsed = JSON.parse(String(messagesJson));
            if (Array.isArray(parsed)) {
              setConsultMessages(
                parsed
                  .filter((m) => m && typeof m === "object")
                  .map((m: any) => ({
                    role: m.role === "user" ? "user" : "assistant",
                    content: String(m.content || ""),
                  }))
              );
            }
          } catch {
            // ignore
          }
        }

        if (draftStatus === "completed") {
          setConsultDone(true);
          const modelJson = body?.operating_model_json;
          if (modelJson) {
            try {
              setConsultFinal(JSON.parse(String(modelJson)));
            } catch {
              setConsultFinal(null);
            }
          }
        }
      } catch {
        // ignore resume errors
      }
    })();
  }, []);

  function resetConsultSession() {
    consultStorage.clear();
    setClientId(null);
    setDraftId(null);
    setConsultMessages([]);
    setConsultInput("");
    setConsultDone(false);
    setConsultFinal(null);
    setConsultError(null);
  }

  async function startConsultConversation(nextDraftId: string, nextClientId: string) {
    setConsultError(null);
    setConsultMessages([]);
    setConsultInput("");
    setConsultDone(false);
    setConsultFinal(null);
    setConsultLoading(true);

    try {
      const { businessName, businessType } = form.getValues();
      const res = await apiClient.post(
        "/api/intake-consult",
        {
          draft_id: nextDraftId,
          client_id: nextClientId,
          business_name: businessName,
          business_type: businessType,
        },
        {
          validateStatus: () => true,
          headers: { "Content-Type": "application/json" },
        }
      );

      if (res.status < 200 || res.status >= 300) {
        const body = res.data;
        throw new Error(
          body && typeof body === "object" && body.detail
            ? String(body.detail)
            : `Consult error: ${res.status} ${res.statusText}`
        );
      }

      const body: any = res.data;
      setConsultDone(Boolean(body?.done));
      if (body?.done) {
        try {
          setConsultFinal(JSON.parse(String(body?.assistant_message || "{}")));
        } catch {
          setConsultFinal(null);
        }
      }
      setConsultMessages([
        { role: "assistant", content: String(body?.assistant_message || "") },
      ]);
    } catch (error) {
      setConsultError(error instanceof Error ? error.message : String(error));
    } finally {
      setConsultLoading(false);
    }
  }

  async function createConsultSession() {
    setConsultError(null);
    setConsultLoading(true);
    setSubmitError(null);
    setSubmitSuccess(null);

    try {
      resetConsultSession();
      const res = await apiClient.post(
        "/api/intake-consult/session",
        {},
        {
          validateStatus: () => true,
          headers: { "Content-Type": "application/json" },
        }
      );

      if (res.status < 200 || res.status >= 300) {
        const body = res.data;
        throw new Error(
          body && typeof body === "object" && body.detail
            ? String(body.detail)
            : `Session error: ${res.status} ${res.statusText}`
        );
      }

      const body: any = res.data;
      const nextDraftId = String(body?.draft_id || "").trim();
      const nextClientId = String(body?.client_id || "").trim();
      if (!nextDraftId || !nextClientId) {
        throw new Error("Session did not return draft_id/client_id.");
      }

      consultStorage.set(nextDraftId, nextClientId);
      setDraftId(nextDraftId);
      setClientId(nextClientId);
      await startConsultConversation(nextDraftId, nextClientId);
    } catch (error) {
      setConsultError(error instanceof Error ? error.message : String(error));
    } finally {
      setConsultLoading(false);
    }
  }

  async function sendConsultMessage(message: string) {
    if (!draftId || !clientId) return;

    setConsultError(null);
    setConsultLoading(true);

    try {
      const { businessName, businessType } = form.getValues();
      const res = await apiClient.post(
        "/api/intake-consult",
        {
          draft_id: draftId,
          client_id: clientId,
          message,
          business_name: businessName,
          business_type: businessType,
        },
        {
          validateStatus: () => true,
          headers: { "Content-Type": "application/json" },
        }
      );

      if (res.status < 200 || res.status >= 300) {
        const body = res.data;
        throw new Error(
          body && typeof body === "object" && body.detail
            ? String(body.detail)
            : `Consult error: ${res.status} ${res.statusText}`
        );
      }

      const body: any = res.data;
      setConsultDone(Boolean(body?.done));
      if (body?.done) {
        try {
          setConsultFinal(JSON.parse(String(body?.assistant_message || "{}")));
        } catch {
          setConsultFinal(null);
        }
      }
      setConsultMessages((prev) => [
        ...prev,
        { role: "assistant", content: String(body?.assistant_message || "") },
      ]);
    } catch (error) {
      setConsultError(error instanceof Error ? error.message : String(error));
    } finally {
      setConsultLoading(false);
    }
  }

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

  function handleSubmit(values: IntakeValues) {
    (async () => {
      setSubmitError(null);
      setSubmitSuccess(null);
      if (!draftId) {
        setSubmitError("Start and complete the consultant conversation first.");
        return;
      }

      if (!consultDone) {
        setSubmitError("Complete the consultant conversation before submitting.");
        return;
      }

      const businessStartDate = values.businessStartDate;

      const financialsPayload = {
        draft_id: draftId,
        business_name: values.businessName,
        business_type: values.businessType,
        description: null,
        address: values.address || null,
        // What you offer (removed from UI for now)
        product_keywords: null,
          customer_age_range: values.customerAgeRange,
          customer_income_level: values.customerIncomeLevel,
          customer_type: values.customerType,
          first_name: values.firstName,
        last_name: values.lastName,
        email_address: values.emailAddress,
        phone_number: values.phoneNumber || null,
        how_did_you_hear: values.howDidYouHear || null,
        founder_background: values.founderBackground,
        business_start_date: businessStartDate,
        current_revenue: parseNumberFromString(values.currentRevenue),
        current_cogs: parseNumberFromString(values.currentCogs),
        expected_revenue_growth_pct_next_year:
          parseNumberFromString(values.expectedRevenueGrowthPctNextYear),
        tax_rate: parseNumberFromString(values.taxRate),
        marketing_expense: parseNumberFromString(values.marketingExpense),
        r_and_d_expense: parseNumberFromString(values.rAndDExpense),
        sga_expense: parseNumberFromString(values.sgaExpense),
        other_operating_expense: parseNumberFromString(
          values.otherOperatingExpense
        ),
        monthly_rent_expense: parseNumberFromString(values.monthlyRentExpense),
        other_monthly_debt_payments: parseNumberFromString(
          values.otherMonthlyDebtPayments
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
        ar_balance: parseNumberFromString(values.arBalance),
        ap_balance: parseNumberFromString(values.apBalance),
        inventory_balance: parseNumberFromString(values.inventoryBalance),
        total_debt_outstanding: parseNumberFromString(
          values.totalDebtOutstanding
        ),
        annual_interest_payment: parseNumberFromString(
          values.annualInterestPayment
        ),
        annual_principal_payment: parseNumberFromString(
          values.annualPrincipalPayment
        ),
        owner_compensation: parseNumberFromString(values.ownerCompensation),
        cash_on_hand: parseNumberFromString(values.cashOnHand),
      };

      Object.values(serverFieldToFormField).forEach((fieldName) => {
        form.clearErrors(fieldName);
      });

      setSubmitLoading(true);
      try {
        const res = await apiClient.post("/api/financials", financialsPayload, {
          validateStatus: () => true,
          headers: { "Content-Type": "application/json" },
        });

        const contentType =
          (res.headers && res.headers["content-type"]) || "";
        const body: any = res.data;

        if (!contentType.includes("application/json")) {
          const text =
            typeof body === "string" ? body : JSON.stringify(body || "");
          throw new Error(
            `Unexpected response from /api/financials: ${res.status} ${res.statusText} ${text.slice(
              0,
              120
            )}`
          );
        }

        if (res.status < 200 || res.status >= 300) {
          if (body && typeof body === "object" && body.errors) {
            const unmapped: string[] = [];
            Object.entries(body.errors).forEach(([serverField, message]) => {
              const formField = serverFieldToFormField[serverField];
              if (formField) {
                form.setError(formField, {
                  type: "server",
                  message: String(message),
                });
              } else {
                unmapped.push(`${serverField}: ${String(message)}`);
              }
            });
            if (unmapped.length) {
              setSubmitError(unmapped.join(" | "));
            }
          } else {
            const detail =
              body && typeof body === "object"
                ? String(body.detail || body.error || JSON.stringify(body))
                : String(body);
            setSubmitError(detail);
            console.error("Error submitting financials:", body);
          }
          return;
        }

        console.log("Financials submitted successfully", body);
        const returnedClientId =
          body && typeof body === "object" ? String(body.client_id || "") : "";
        const intakeSubmissionId =
          body && typeof body === "object"
            ? String(body.intake_submission_id || "")
            : "";
        setSubmitSuccess({
          clientId: returnedClientId || (clientId || ""),
          intakeSubmissionId: intakeSubmissionId || undefined,
        });

        // Clear consult session so a new session starts clean.
        consultStorage.clear();
      } catch (error) {
        console.error("Error submitting financials:", error);
        setSubmitError(error instanceof Error ? error.message : String(error));
      } finally {
        setSubmitLoading(false);
      }

      console.log("Intake submission", values);
    })();
  }

  function handleInvalid(errors: FieldErrors<IntakeValues>) {
    setSubmitSuccess(null);
    setSubmitError("Please fix the highlighted fields and try again.");

    const firstField = Object.keys(errors || {})[0];
    if (!firstField) return;

    const el = document.querySelector(
      `[name="${CSS.escape(firstField)}"]`
    ) as HTMLElement | null;

    if (el && typeof el.scrollIntoView === "function") {
      el.scrollIntoView({ behavior: "smooth", block: "center" });
    }
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

        <Form
          form={form}
          onSubmit={(values) => {
            handleSubmit(values);
          }}
          onInvalid={handleInvalid}
          className="space-y-8"
        >
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

                  <FormField name="businessType" control={form.control}>
                    {(field) => (
                      <FormItem className="col-span-2 md:col-span-2">
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
                      <FormLabel>
                        Business address{" "}
                        <HelpTooltip
                          fieldName="address"
                          text={TOOLTIP_TEXT.businessAddress}
                        />
                      </FormLabel>
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



                <div className="col-span-2 space-y-3">
                  {!clientId ? (
                    <div className="flex flex-col gap-2">
                      <div className="text-xs text-slate-300">
                        Start the consultant conversation before submitting the
                        intake. GPT will ask operational questions and will
                        tell you when it's complete.
                      </div>
                      <Button
                        type="button"
                        size="sm"
                        disabled={consultLoading}
                        onClick={createConsultSession}
                      >
                        {consultLoading ? "Starting..." : "Start conversation"}
                      </Button>
                      {consultError ? (
                        <div className="rounded-md border border-rose-500/30 bg-rose-500/10 p-3 text-xs text-rose-200">
                          {consultError}
                        </div>
                      ) : null}
                    </div>
                   ) : (
                     <div className="space-y-2">
                       <div className="text-xs text-slate-300">
                         Reference code:{" "}
                         <span className="font-mono">{clientId}</span>
                       </div>

                       <div className="flex flex-wrap gap-2">
                         <Button
                           type="button"
                           size="sm"
                           variant="outline"
                           disabled={consultLoading || submitLoading}
                           onClick={createConsultSession}
                         >
                           Start new conversation
                         </Button>
                       </div>

                       {consultError ? (
                         <div className="rounded-md border border-rose-500/30 bg-rose-500/10 p-3 text-xs text-rose-200">
                           {consultError}
                        </div>
                      ) : null}

                      <div className="max-h-64 space-y-2 overflow-auto rounded-md border border-slate-800/80 bg-slate-950/60 p-3 text-xs text-slate-200">
                        {consultMessages.length === 0 ? (
                          <div className="text-slate-400">
                            {consultLoading
                              ? "Starting consultant conversation..."
                              : "Conversation will appear here."}
                          </div>
                        ) : (
                          consultMessages.map((m, idx) => (
                            <div key={idx} className="whitespace-pre-wrap">
                              <span className="text-slate-400">{m.role}:</span>{" "}
                              {m.content}
                            </div>
                          ))
                        )}
                      </div>

                      {consultDone ? (
                        <div className="rounded-md border border-emerald-500/30 bg-emerald-500/10 p-3 text-xs text-emerald-200">
                          Operational intake complete. Continue filling out the
                          rest of the form and click Submit intake.
                        </div>
                      ) : (
                        <div className="text-xs text-slate-400">
                          Complete this conversation to unlock submission.
                        </div>
                      )}

                      <div className="flex gap-2">
                        <Input
                          value={consultInput}
                          onChange={(e) => setConsultInput(e.target.value)}
                          onKeyDown={async (e) => {
                            if (e.key === "Enter") {
                              e.preventDefault();
                              if (consultLoading || consultDone) return;
                              const msg = consultInput.trim();
                              if (!msg) return;
                              setConsultInput("");
                              setConsultMessages((prev) => [
                                ...prev,
                                { role: "user", content: msg },
                              ]);
                              await sendConsultMessage(msg);
                            }
                          }}
                          placeholder={
                            consultDone
                              ? "Conversation completed."
                              : "Reply to the consultant..."
                          }
                          disabled={consultLoading || consultDone}
                        />
                        <Button
                          type="button"
                          size="sm"
                          disabled={
                            consultLoading || consultDone || !consultInput.trim()
                          }
                          onClick={async () => {
                            const msg = consultInput.trim();
                            setConsultInput("");
                            setConsultMessages((prev) => [
                              ...prev,
                              { role: "user", content: msg },
                            ]);
                            await sendConsultMessage(msg);
                          }}
                        >
                          Send
                        </Button>
                      </div>
                    </div>
                  )}
                </div>
              </CardContent>
            </Card>

            {/* Snapshot card */}
            <Card className="relative border border-slate-800/80 bg-slate-950/90">
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
                <div className="absolute top-4 right-4 animate-glow">
                  <span className="relative flex h-8 w-8 items-center justify-center rounded-2xl bg-sky-500/15 text-sky-400 ring-1 ring-sky-500/40 shadow-glow animate-slowspin">
                    <Sparkles className="h-4 w-4" />
                    <span className="absolute inset-0 -z-10 rounded-2xl bg-sky-500/15 blur-xl" />
                  </span>
                </div>
              </CardContent>
            </Card>
          </div>

          {/* Client information & founder background */}
          <div className="grid gap-5 md:grid-cols-2">
            <Card className="border border-slate-800/80 bg-slate-950/90">
              <CardHeader className="border-0 pb-3">
                <CardTitle className="text-sm">
                  Client Information
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <FormField name="firstName" control={form.control}>
                  {(field) => (
                    <FormItem>
                      <FormLabel>First Name</FormLabel>
                      <FormControl>
                        <Input
                          {...field}
                          type="text"
                          placeholder="Enter your first name"
                        />
                      </FormControl>
                      <FormMessage>
                        {form.formState.errors.firstName?.message}
                      </FormMessage>
                    </FormItem>
                  )}
                </FormField>

                <FormField name="lastName" control={form.control}>
                  {(field) => (
                    <FormItem>
                      <FormLabel>Last Name</FormLabel>
                      <FormControl>
                        <Input
                          {...field}
                          type="text"
                          placeholder="Enter your last name"
                        />
                      </FormControl>
                      <FormMessage>
                        {form.formState.errors.lastName?.message}
                      </FormMessage>
                    </FormItem>
                  )}
                </FormField>

                <FormField name="emailAddress" control={form.control}>
                  {(field) => (
                    <FormItem>
                      <FormLabel>Email Address</FormLabel>
                      <FormControl>
                        <Input
                          {...field}
                          type="email"
                          placeholder="you@example.com"
                        />
                      </FormControl>
                      <FormMessage>
                        {form.formState.errors.emailAddress?.message}
                      </FormMessage>
                    </FormItem>
                  )}
                </FormField>

                <FormField name="phoneNumber" control={form.control}>
                  {(field) => (
                    <FormItem>
                      <FormLabel>
                        Phone Number{" "}
                        <span className="text-slate-400">(optional)</span>
                      </FormLabel>
                      <FormControl>
                        <Input
                          {...field}
                          type="text"
                          placeholder="Optional"
                        />
                      </FormControl>
                      <FormMessage>
                        {form.formState.errors.phoneNumber?.message}
                      </FormMessage>
                    </FormItem>
                  )}
                </FormField>

                <FormField name="howDidYouHear" control={form.control}>
                  {(field) => (
                    <FormItem>
                      <FormLabel>How did you hear about us?</FormLabel>
                      <FormControl>
                        <select
                          name={field.name}
                          value={(field.value as string) || ""}
                          onChange={(event) =>
                            field.onChange(event.target.value)
                          }
                          onBlur={field.onBlur}
                          className="mt-1 flex h-9 w-full rounded-md border border-slate-700/80 bg-slate-900/80 px-3 text-xs text-slate-50 shadow-sm transition-all placeholder:text-slate-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400/70 focus-visible:ring-offset-1 focus-visible:ring-offset-slate-950"
                        >
                          <option value="">Select an option</option>
                          <option value="Twitter">Twitter</option>
                          <option value="TikTok">TikTok</option>
                          <option value="YouTube">YouTube</option>
                          <option value="Other">Other</option>
                        </select>
                      </FormControl>
                      <FormMessage>
                        {form.formState.errors.howDidYouHear?.message}
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
                      <FormLabel>
                        Founder background{" "}
                        <HelpTooltip
                          side="bottom"
                          fieldName="founderBackground"
                          text={TOOLTIP_TEXT.founderBackground}
                        />
                      </FormLabel>
                      <FormControl>
                        <Textarea
                          {...field}
                          rows={12}
                          className="min-h-[320px]"
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

          {/* Customers */}
          <div className="grid gap-5 md:grid-cols-2">
            <Card className="border border-slate-800/80 bg-slate-950/90">
              <CardHeader className="border-0 pb-3">
                <CardTitle className="text-sm">
                  Customers &amp; positioning
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <FormField name="customerAgeRange" control={form.control}>
                  {(field) => (
                    <FormItem>
                      <FormLabel>Age Range</FormLabel>
                      <FormControl>
                        <select
                          name={field.name}
                          value={(field.value as string) || ""}
                          onChange={(event) => field.onChange(event.target.value)}
                          onBlur={field.onBlur}
                          className="mt-1 flex h-9 w-full rounded-md border border-slate-700/80 bg-slate-900/80 px-3 text-xs text-slate-50 shadow-sm transition-all placeholder:text-slate-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400/70 focus-visible:ring-offset-1 focus-visible:ring-offset-slate-950"
                        >
                          <option value="">Select an age range</option>
                          <option value="18–24">18–24</option>
                          <option value="25–34">25–34</option>
                          <option value="35–44">35–44</option>
                          <option value="45–54">45–54</option>
                          <option value="55–64">55–64</option>
                          <option value="65+">65+</option>
                          <option value="All adults (18+)">
                            All adults (18+)
                          </option>
                          <option value="Families with children">
                            Families with children
                          </option>
                        </select>
                      </FormControl>
                      <FormMessage>
                        {form.formState.errors.customerAgeRange?.message}
                      </FormMessage>
                    </FormItem>
                  )}
                </FormField>

                <FormField name="customerIncomeLevel" control={form.control}>
                  {(field) => (
                    <FormItem>
                      <FormLabel>Income Level</FormLabel>
                      <FormControl>
                        <select
                          name={field.name}
                          value={(field.value as string) || ""}
                          onChange={(event) => field.onChange(event.target.value)}
                          onBlur={field.onBlur}
                          className="mt-1 flex h-9 w-full rounded-md border border-slate-700/80 bg-slate-900/80 px-3 text-xs text-slate-50 shadow-sm transition-all placeholder:text-slate-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400/70 focus-visible:ring-offset-1 focus-visible:ring-offset-slate-950"
                        >
                          <option value="">Select an income level</option>
                          <option value="Low income (<$40k)">
                            Low income (&lt;$40k)
                          </option>
                          <option value="Middle income ($40k–$85k)">
                            Middle income ($40k–$85k)
                          </option>
                          <option value="Upper-middle income ($85k–$150k)">
                            Upper-middle income ($85k–$150k)
                          </option>
                          <option value="High income ($150k+)">
                            High income ($150k+)
                          </option>
                          <option value="All income levels">
                            All income levels
                          </option>
                        </select>
                      </FormControl>
                      <FormMessage>
                        {form.formState.errors.customerIncomeLevel?.message}
                      </FormMessage>
                    </FormItem>
                  )}
                </FormField>

                <FormField name="customerType" control={form.control}>
                  {(field) => (
                    <FormItem>
                      <FormLabel>Customer Type</FormLabel>
                      <FormControl>
                        <select
                          name={field.name}
                          value={(field.value as string) || ""}
                          onChange={(event) => field.onChange(event.target.value)}
                          onBlur={field.onBlur}
                          className="mt-1 flex h-9 w-full rounded-md border border-slate-700/80 bg-slate-900/80 px-3 text-xs text-slate-50 shadow-sm transition-all placeholder:text-slate-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400/70 focus-visible:ring-offset-1 focus-visible:ring-offset-slate-950"
                        >
                          <option value="">Select a customer type</option>
                          <option value="Consumers (B2C)">Consumers (B2C)</option>
                          <option value="Small businesses (B2B – under 50 employees)">
                            Small businesses (B2B – under 50 employees)
                          </option>
                          <option value="Mid-size businesses (B2B – 50 to 500 employees)">
                            Mid-size businesses (B2B – 50 to 500 employees)
                          </option>
                          <option value="Large enterprises (B2B – 500+ employees)">
                            Large enterprises (B2B – 500+ employees)
                          </option>
                          <option value="Nonprofits">Nonprofits</option>
                          <option value="Government / Municipal">
                            Government / Municipal
                          </option>
                          <option value="Schools / Education">
                            Schools / Education
                          </option>
                          <option value="Families with children">
                            Families with children
                          </option>
                          <option value="Seniors">Seniors</option>
                          <option value="Young professionals">
                            Young professionals
                          </option>
                          <option value="Homeowners">Homeowners</option>
                          <option value="Renters">Renters</option>
                        </select>
                      </FormControl>
                      <FormMessage>
                        {form.formState.errors.customerType?.message}
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
                        <FormLabel>
                          Current Revenue{" "}
                          <HelpTooltip
                            fieldName="currentRevenue"
                            text="Enter your current annual revenue. Use 0 if you are pre-revenue."
                          />
                        </FormLabel>
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
                        <FormLabel>
                          Cost of Goods Sold (COGS){" "}
                          <HelpTooltip
                            fieldName="currentCogs"
                            text={TOOLTIP_TEXT.cogs}
                          />
                        </FormLabel>
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
                        <FormLabel>
                          Expected Revenue Growth (%){" "}
                          <HelpTooltip
                            fieldName="expectedRevenueGrowthPctNextYear"
                            text={TOOLTIP_TEXT.expectedRevenueGrowth}
                          />
                        </FormLabel>
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

                  <FormField name="taxRate" control={form.control}>
                    {(field) => (
                      <FormItem>
                        <FormLabel>
                          Tax Rate{" "}
                          <HelpTooltip
                            fieldName="taxRate"
                            text={TOOLTIP_TEXT.taxRate}
                          />
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
                              handleNumericBlur(event, "taxRate");
                            }}
                          />
                        </FormControl>
                        <FormMessage>
                          {form.formState.errors.taxRate?.message}
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
                        <FormLabel>
                          Marketing Expense{" "}
                          <HelpTooltip
                            fieldName="marketingExpense"
                            text={TOOLTIP_TEXT.marketingExpense}
                          />
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

                  <FormField name="rAndDExpense" control={form.control}>
                    {(field) => (
                      <FormItem>
                        <FormLabel>
                          Research &amp; Development (R&amp;D){" "}
                          <HelpTooltip
                            fieldName="rAndDExpense"
                            text={TOOLTIP_TEXT.rAndDExpense}
                          />
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
                              handleNumericBlur(event, "rAndDExpense");
                            }}
                          />
                        </FormControl>
                        <FormMessage>
                          {form.formState.errors.rAndDExpense?.message}
                        </FormMessage>
                      </FormItem>
                    )}
                  </FormField>

                  <FormField name="sgaExpense" control={form.control}>
                    {(field) => (
                      <FormItem>
                        <FormLabel>
                          SG&amp;A Expense{" "}
                          <HelpTooltip
                            fieldName="sgaExpense"
                            text={TOOLTIP_TEXT.sgAndAExpense}
                          />
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
                        <FormLabel>
                          Other Operating Expense{" "}
                          <HelpTooltip
                            fieldName="otherOperatingExpense"
                            text={TOOLTIP_TEXT.otherOpExpense}
                          />
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

                  <FormField
                    name="monthlyRentExpense"
                    control={form.control}
                  >
                    {(field) => (
                      <FormItem>
                        <FormLabel>
                          Monthly Rent / Lease Expense{" "}
                          <HelpTooltip
                            fieldName="monthlyRentExpense"
                            text={TOOLTIP_TEXT.rentLeaseExpense}
                          />
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
                                "monthlyRentExpense"
                              );
                            }}
                          />
                        </FormControl>
                        <FormMessage>
                          {form.formState.errors.monthlyRentExpense?.message}
                        </FormMessage>
                      </FormItem>
                    )}
                  </FormField>

                  <FormField
                    name="otherMonthlyDebtPayments"
                    control={form.control}
                  >
                    {(field) => (
                      <FormItem>
                        <FormLabel>
                          Other Monthly Debt Payments{" "}
                          <HelpTooltip
                            fieldName="otherMonthlyDebtPayments"
                            text={TOOLTIP_TEXT.otherDebtPayments}
                          />
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
                                "otherMonthlyDebtPayments"
                              );
                            }}
                          />
                        </FormControl>
                        <FormMessage>
                          {
                            form.formState.errors.otherMonthlyDebtPayments
                              ?.message
                          }
                        </FormMessage>
                      </FormItem>
                    )}
                  </FormField>

                  <FormField name="currentPayroll" control={form.control}>
                    {(field) => (
                      <FormItem>
                        <FormLabel>
                          Current Payroll{" "}
                          <HelpTooltip
                            fieldName="currentPayroll"
                            text={TOOLTIP_TEXT.currentPayroll}
                          />
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
                        <FormLabel>
                          Current Number of Employees{" "}
                          <HelpTooltip
                            fieldName="currentNumEmployees"
                            text={TOOLTIP_TEXT.currentEmployees}
                          />
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
                          Planned Number of Employees in 5 Years{" "}
                          <HelpTooltip
                            fieldName="plannedNumEmployees5yrs"
                            text={TOOLTIP_TEXT.plannedEmployees5Years}
                          />
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
                  Capital Expenditures &amp; Working Capital
                </div>
                <div className="grid gap-3">
                  <FormField name="currentCapex" control={form.control}>
                    {(field) => (
                      <FormItem>
                        <FormLabel>
                          Current Capex{" "}
                          <HelpTooltip
                            fieldName="currentCapex"
                            text={TOOLTIP_TEXT.currentCapex}
                          />
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
                        <FormLabel>
                          Planned Capex (5 Years){" "}
                          <HelpTooltip
                            fieldName="plannedCapex5yr"
                            text={TOOLTIP_TEXT.plannedCapex}
                          />
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

                  <FormField name="arBalance" control={form.control}>
                    {(field) => (
                      <FormItem>
                        <FormLabel>
                          Accounts Receivable Balance{" "}
                          <HelpTooltip
                            fieldName="arBalance"
                            text={TOOLTIP_TEXT.arBalance}
                          />
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
                              handleNumericBlur(event, "arBalance");
                            }}
                          />
                        </FormControl>
                        <FormMessage>
                          {form.formState.errors.arBalance?.message}
                        </FormMessage>
                      </FormItem>
                    )}
                  </FormField>

                  <FormField name="apBalance" control={form.control}>
                    {(field) => (
                      <FormItem>
                        <FormLabel>
                          Accounts Payable Balance{" "}
                          <HelpTooltip
                            fieldName="apBalance"
                            text={TOOLTIP_TEXT.apBalance}
                          />
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
                              handleNumericBlur(event, "apBalance");
                            }}
                          />
                        </FormControl>
                        <FormMessage>
                          {form.formState.errors.apBalance?.message}
                        </FormMessage>
                      </FormItem>
                    )}
                  </FormField>

                  <FormField name="inventoryBalance" control={form.control}>
                    {(field) => (
                      <FormItem>
                        <FormLabel>
                          Inventory Balance{" "}
                          <HelpTooltip
                            fieldName="inventoryBalance"
                            text={TOOLTIP_TEXT.inventoryBalance}
                          />
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
                              handleNumericBlur(event, "inventoryBalance");
                            }}
                          />
                        </FormControl>
                        <FormMessage>
                          {form.formState.errors.inventoryBalance?.message}
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
                        <FormLabel>
                          Total Debt Outstanding{" "}
                          <HelpTooltip
                            side="left"
                            fieldName="totalDebtOutstanding"
                            text={TOOLTIP_TEXT.totalDebtOutstanding}
                          />
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
                        <FormLabel>
                          Annual Interest Payment{" "}
                          <HelpTooltip
                            side="left"
                            fieldName="annualInterestPayment"
                            text={TOOLTIP_TEXT.annualInterest}
                          />
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
                        <FormLabel>
                          Annual Principal Payment{" "}
                          <HelpTooltip
                            side="left"
                            fieldName="annualPrincipalPayment"
                            text={TOOLTIP_TEXT.annualPrincipal}
                          />
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

                  <FormField
                    name="ownerCompensation"
                    control={form.control}
                  >
                    {(field) => (
                      <FormItem>
                        <FormLabel>
                          Owner Compensation (if applicable){" "}
                          <HelpTooltip
                            side="left"
                            fieldName="ownerCompensation"
                            text={TOOLTIP_TEXT.ownerCompensation}
                          />
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
                                "ownerCompensation"
                              );
                            }}
                          />
                        </FormControl>
                        <FormMessage>
                          {form.formState.errors.ownerCompensation?.message}
                        </FormMessage>
                      </FormItem>
                    )}
                  </FormField>

                  <FormField name="cashOnHand" control={form.control}>
                    {(field) => (
                      <FormItem>
                        <FormLabel>
                          Cash on Hand{" "}
                          <HelpTooltip
                            side="left"
                            fieldName="cashOnHand"
                            text={TOOLTIP_TEXT.cashOnHand}
                          />
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
              disabled={!consultDone || submitLoading}
            >
              {submitLoading ? "Submitting..." : "Submit intake"}
            </Button>
          </motion.div>

          {submitError ? (
            <div className="rounded-md border border-rose-500/30 bg-rose-500/10 p-3 text-xs text-rose-200">
              {submitError}
            </div>
          ) : null}

          {submitSuccess ? (
            <div className="rounded-md border border-emerald-500/30 bg-emerald-500/10 p-3 text-xs text-emerald-200">
              Intake submitted successfully. Reference code:{" "}
              <span className="font-mono">{submitSuccess.clientId}</span>
            </div>
          ) : null}

          {false ? (
            <Card className="border border-slate-800/80 bg-slate-950/90">
              <CardHeader className="border-0 pb-3">
                <CardTitle className="text-sm">
                  Let’s understand how your business operates
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                <div className="text-xs text-slate-300">
                  Reference code: <span className="font-mono">{clientId}</span>
                </div>

                {consultError ? (
                  <div className="rounded-md border border-rose-500/30 bg-rose-500/10 p-3 text-xs text-rose-200">
                    {consultError}
                  </div>
                ) : null}

                <div className="max-h-72 space-y-2 overflow-auto rounded-md border border-slate-800/80 bg-slate-950/60 p-3 text-xs text-slate-200">
                  {consultMessages.length === 0 ? (
                    <div className="text-slate-400">
                      {consultLoading
                        ? "Starting consultant conversation..."
                        : "Conversation will appear here."}
                    </div>
                  ) : (
                    consultMessages.map((m, idx) => (
                      <div key={idx} className="whitespace-pre-wrap">
                        <span className="text-slate-400">{m.role}:</span>{" "}
                        {m.content}
                      </div>
                    ))
                  )}
                </div>

                <div className="flex gap-2">
                  <Input
                    value={consultInput}
                    onChange={(e) => setConsultInput(e.target.value)}
                    placeholder={
                      consultDone
                        ? "Conversation completed."
                        : "Reply to the consultant..."
                    }
                    disabled={consultLoading || consultDone}
                  />
                  <Button
                    type="button"
                    size="sm"
                    disabled={
                      consultLoading || consultDone || !consultInput.trim()
                    }
                    onClick={async () => {
                      const msg = consultInput.trim();
                      setConsultInput("");
                      setConsultMessages((prev) => [
                        ...prev,
                        { role: "user", content: msg },
                      ]);
                      await sendConsultMessage(msg);
                    }}
                  >
                    Send
                  </Button>
                </div>
              </CardContent>
            </Card>
          ) : null}
        </Form>
      </div>
    </PageShell>
  );
}

export default IntakeFormPage;
