import { zodResolver } from "@hookform/resolvers/zod";
import { motion } from "framer-motion";
import { Sparkles } from "lucide-react";
import { useForm } from "react-hook-form";
import PageShell from "../components/PageShell";
import { Form } from "../components/ui/Form";
import { IntakeFlowProvider } from "./flow/IntakeFlowContext";
import { defaultValues, intakeSchema, type IntakeValues } from "./schema";
import BusinessOverviewStep from "./steps/BusinessOverviewStep";
import ClientInformationStep from "./steps/ClientInformationStep";
import FinancialsStep from "./steps/FinancialsStep";
import PeopleCapabilityStep from "./steps/PeopleCapabilityStep";
import SubmitStep, { useSubmitIntakeHandlers } from "./steps/SubmitStep";
import TargetMarketStep from "./steps/TargetMarketStep";

function IntakeFormInner() {
  const form = useForm<IntakeValues>({
    resolver: zodResolver(intakeSchema),
    defaultValues,
    mode: "onBlur",
  });

  const { handleInvalid, handleSubmit } = useSubmitIntakeHandlers(form);

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
            This intake form gives us the context we need to craft a
            lender-ready business plan tailored to your goals, industry, and
            numbers. Expect ~15â€“20 minutes to complete.
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
        <BusinessOverviewStep />

        <div className="grid gap-5 md:grid-cols-2">
          <ClientInformationStep />
          <PeopleCapabilityStep />
        </div>

        <TargetMarketStep />
        <FinancialsStep />
        <SubmitStep />
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

