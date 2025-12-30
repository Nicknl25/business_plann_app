import { motion } from "framer-motion";
import { useIntakeFlow } from "../flow/IntakeFlowContext";

import type { FieldErrors, UseFormReturn } from "react-hook-form";
import apiClient from "../../apiClient";
import { Button } from "../../components/ui/Button";
import { consultStorage } from "../flow/consultStorage";
import {
  parseNumberFromString,
  serverFieldToFormField,
  type IntakeValues,
} from "../schema";

export function useSubmitIntakeHandlers(form: UseFormReturn<IntakeValues>) {
  const {
    clientId,
    draftId,
    consultDone,
    opsConfirmed,
    targetMarketDone,
    targetMarketConfirmed,
    peopleDone,
    peopleConfirmed,
    financialsDone,
    financialsConfirmed,
    setSubmitLoading,
    setSubmitError,
    setSubmitSuccess,
  } = useIntakeFlow();

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

      if (!opsConfirmed) {
        setSubmitError("Confirm Business overview before submitting.");
        return;
      }

      if (!targetMarketDone) {
        setSubmitError(
          "Complete the target market conversation before submitting."
        );
        return;
      }

      if (!targetMarketConfirmed) {
        setSubmitError("Confirm Customers & positioning before submitting.");
        return;
      }
      if (!peopleDone) {
        setSubmitError(
          "Complete the People & Capability conversation before submitting."
        );
        return;
      }

      if (!peopleConfirmed) {
        setSubmitError("Confirm People & Capability before submitting.");
        return;
      }

      if (!financialsDone) {
        setSubmitError("Complete the financials conversation before submitting.");
        return;
      }

      if (!financialsConfirmed) {
        setSubmitError("Confirm Financials before submitting.");
        return;
      }

      const businessStartDate = values.businessStartDate;

      const financialsPayload = {
        draft_id: draftId,
        business_name: values.businessName,
        description: null,
        address: values.address || null,
        // What you offer (removed from UI for now)
        product_keywords: null,
        first_name: values.firstName,
        last_name: values.lastName,
        email_address: values.emailAddress,
        phone_number: values.phoneNumber || null,
        how_did_you_hear: values.howDidYouHear || null,
        business_start_date: businessStartDate,
        current_revenue: parseNumberFromString(values.currentRevenue),
        current_cogs: parseNumberFromString(values.currentCogs),
        expected_revenue_growth_pct_next_year: parseNumberFromString(
          values.expectedRevenueGrowthPctNextYear
        ),
        tax_rate: parseNumberFromString(values.taxRate),
        marketing_expense: parseNumberFromString(values.marketingExpense),
        r_and_d_expense: parseNumberFromString(values.rAndDExpense),
        sga_expense: parseNumberFromString(values.sgaExpense),
        other_operating_expense: parseNumberFromString(values.otherOperatingExpense),
        monthly_rent_expense: parseNumberFromString(values.monthlyRentExpense),
        other_monthly_debt_payments: parseNumberFromString(
          values.otherMonthlyDebtPayments
        ),
        current_payroll: parseNumberFromString(values.currentPayroll),
        current_num_employees: parseNumberFromString(values.currentNumEmployees),
        planned_num_employees_5yrs: parseNumberFromString(values.plannedNumEmployees5yrs),
        current_capex: parseNumberFromString(values.currentCapex),
        planned_capex_5yr: parseNumberFromString(values.plannedCapex5yr),
        ar_balance: parseNumberFromString(values.arBalance),
        ap_balance: parseNumberFromString(values.apBalance),
        inventory_balance: parseNumberFromString(values.inventoryBalance),
        total_debt_outstanding: parseNumberFromString(values.totalDebtOutstanding),
        annual_interest_payment: parseNumberFromString(values.annualInterestPayment),
        annual_principal_payment: parseNumberFromString(values.annualPrincipalPayment),
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

        const contentType = (res.headers && res.headers["content-type"]) || "";
        const body: any = res.data;

        if (!contentType.includes("application/json")) {
          const text = typeof body === "string" ? body : JSON.stringify(body || "");
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

  return { handleInvalid, handleSubmit };
}

export default function SubmitStep({
  onRequestSubmit,
}: {
  onRequestSubmit?: () => void;
}) {
  const {
    consultDone,
    opsConfirmed,
    submitLoading,
    submitError,
    submitSuccess,
    targetMarketDone,
    targetMarketConfirmed,
    peopleDone,
    peopleConfirmed,
    financialsDone,
    financialsConfirmed,
  } = useIntakeFlow();

  return (
    <>
      <motion.div
        className="flex flex-col gap-4 rounded-3xl border border-slate-800/80 bg-slate-950/90 px-6 py-5 text-xs text-slate-300 shadow-soft sm:flex-row sm:items-center sm:justify-between"
        initial={{ opacity: 0, y: 14 }}
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
          type="button"
          size="lg"
          className="group rounded-full px-6 text-xs sm:text-sm"
          disabled={
            !consultDone ||
            !opsConfirmed ||
            !targetMarketDone ||
            !targetMarketConfirmed ||
            !peopleDone ||
            !peopleConfirmed ||
            !financialsDone ||
            !financialsConfirmed ||
            submitLoading ||
            Boolean(submitSuccess)
          }
          onClick={() => {
            if (submitLoading) return;
            if (submitSuccess) return;
            onRequestSubmit?.();
          }}
        >
          {submitLoading ? "Submitting..." : submitSuccess ? "Submitted" : "Submit intake"}
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
    </>
  );
}
