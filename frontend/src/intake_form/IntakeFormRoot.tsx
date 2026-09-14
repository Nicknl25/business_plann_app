import { zodResolver } from "@hookform/resolvers/zod";
import { motion } from "framer-motion";
import { Sparkles } from "lucide-react";
import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { useSearchParams } from "react-router-dom";
import PageShell from "../components/PageShell";
import { Form } from "../components/ui/Form";
import { IntakeFlowProvider } from "./flow/IntakeFlowContext";
import { useIntakeFlow } from "./flow/IntakeFlowContext";
import { defaultValues, intakeSchema, type IntakeValues } from "./schema";
import SubmitStep, { useSubmitIntakeHandlers } from "./steps/SubmitStep";
import UnifiedConsultStep from "./steps/UnifiedConsultStep";
import ClientInformationModal from "./components/ClientInformationModal";
import WhatToExpectNextInfo from "./components/WhatToExpectNextInfo";

function IntakeFormInner() {
  const form = useForm<IntakeValues>({
    resolver: zodResolver(intakeSchema),
    defaultValues,
    mode: "onBlur",
  });

  const [searchParams, setSearchParams] = useSearchParams();
  const { handleInvalid, handleSubmit } = useSubmitIntakeHandlers(form);
  const {
    submitLoading,
    setPlanStarted,
    spectateDraftId,
    setSpectateDraftId,
    setSubmitError,
  } = useIntakeFlow();
  const [clientInfoOpen, setClientInfoOpen] = useState(false);
  const isSpectating = Boolean(spectateDraftId);

  const clientInfoFields: (keyof IntakeValues)[] = [
    "firstName",
    "lastName",
    "emailAddress",
    "phoneNumber",
    "howDidYouHear",
  ];

  const allFieldNames = Object.keys(defaultValues) as (keyof IntakeValues)[];
  const nonClientFields = allFieldNames.filter(
    (k) => !clientInfoFields.includes(k)
  );

  async function beginSubmitFlow() {
    const ok = await form.trigger(nonClientFields as any);
    if (!ok) {
      handleInvalid(form.formState.errors);
      return;
    }
    setClientInfoOpen(true);
  }

  async function confirmClientInfoAndSubmit() {
    const ok = await form.trigger(clientInfoFields as any);
    if (!ok) {
      // Never dead-end silently: the modal stays open and the fields show
      // their validation messages, but say so explicitly too.
      setSubmitError("Please fix the highlighted contact fields and try again.");
      return;
    }
    setSubmitError(null);
    setClientInfoOpen(false);
    await form.handleSubmit(
      (values) => handleSubmit(values),
      (errors) => handleInvalid(errors)
    )();
  }

  // REACHING THE FORM STARTS THE INTAKE (Nick 2026-09-14). CW-070 opened
  // /business-plan-form directly, the plan-started flag was only set by the
  // "Start Your Plan" link's ?start=1, and the Start consultation button stayed
  // disabled with every field valid - an hour lost to a door nobody had written
  // down. Arriving here is the intent to start; only a spectator tab (?watch=)
  // is not starting anything. ?start=1 is still accepted and tidied away.
  useEffect(() => {
    if (String(searchParams.get("watch") || "").trim()) return;
    setPlanStarted(true);
    if (searchParams.get("start") !== "1") return;
    const next = new URLSearchParams(searchParams);
    next.delete("start");
    setSearchParams(next, { replace: true });
  }, [searchParams, setPlanStarted, setSearchParams]);

  // ?watch=<draft_id> puts this tab in read-only spectator mode on that draft.
  // The param stays in the URL so a refresh keeps watching the same run.
  useEffect(() => {
    const watchParam = String(searchParams.get("watch") || "").trim();
    setSpectateDraftId(watchParam || null);
  }, [searchParams, setSpectateDraftId]);

  return (
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
            This intake form gives us the context we need to craft a lender-ready
            business plan tailored to your goals, industry, and numbers. Expect
            ~15-20 minutes to complete.
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
        <UnifiedConsultStep />

        {!isSpectating ? (
          <div id="submit-intake-section" className="space-y-6">
            <WhatToExpectNextInfo />
            <SubmitStep onRequestSubmit={beginSubmitFlow} />
          </div>
        ) : null}

        {!isSpectating ? (
          <ClientInformationModal
            open={clientInfoOpen}
            submitting={submitLoading}
            onClose={() => setClientInfoOpen(false)}
            onConfirm={confirmClientInfoAndSubmit}
          />
        ) : null}
      </Form>
    </div>
  );
}

export default function IntakeFormRoot() {
  return (
    <PageShell>
      <IntakeFlowProvider>
        <IntakeFormInner />
      </IntakeFlowProvider>
    </PageShell>
  );
}
