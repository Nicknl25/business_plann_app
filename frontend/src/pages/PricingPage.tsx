import { motion } from "framer-motion";
import { CheckCircle2, FileText, Sparkles } from "lucide-react";
import { Link } from "react-router-dom";
import PageShell from "../components/PageShell";
import { Button } from "../components/ui/Button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "../components/ui/Card";

const deliverables = [
  "Banker- and investor-ready business plan (PDF)",
  "Editable working plan file for future revisions",
  "Executive summary, market analysis, and positioning",
  "Business model, revenue drivers, and cost structure",
  "3–5 year high-level financials & assumptions summary",
  "Use-of-funds and funding requirements overview",
  "Tailored to your business type, stage, and audience",
];

function PricingPage() {
  return (
    <PageShell>
      <div className="space-y-10 md:space-y-12">
        <section className="space-y-4 text-center">
          <motion.div
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.4 }}
          >
            <p className="section-label text-[10px] text-sky-200/90">
              Transparent pricing
            </p>
            <h1 className="mt-1 text-2xl font-semibold tracking-tight text-slate-50 md:text-3xl">
              One flat fee. No hourly surprises.
            </h1>
            <p className="mx-auto mt-3 max-w-xl text-sm leading-relaxed text-slate-300">
              Whether you're preparing for a bank meeting, investor conversation,
              or landlord negotiation, you get a premium lender-ready business
              plan with no retainers and no hidden add-ons.
            </p>
          </motion.div>
        </section>

        <section className="mx-auto max-w-3xl">
          <motion.div
            initial={{ opacity: 0, y: 28 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.45, delay: 0.05 }}
          >
            <Card className="relative border border-sky-500/40 bg-slate-950/90 shadow-glow">
              <div className="pointer-events-none absolute inset-x-16 -top-24 h-40 rounded-full bg-sky-500/25 blur-3xl" />
              <CardHeader className="relative border-b border-slate-800/70 pb-4">
                <div className="mb-3 inline-flex items-center gap-2 rounded-full bg-slate-900/80 px-3 py-1 text-[11px] text-sky-200/90 ring-1 ring-sky-500/40">
                  <Sparkles className="h-3 w-3" />
                  <span>Best fit for 1–3 location small businesses</span>
                </div>
                <div className="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
                  <div className="text-left">
                    <CardTitle className="text-base md:text-lg">
                      Business Plan Studio — Flat Fee
                    </CardTitle>
                    <CardDescription className="mt-1 max-w-md">
                      A premium, lender-ready business plan designed for SBA,
                      traditional lenders, investors, and key stakeholders.
                    </CardDescription>
                  </div>
                  <div className="text-left md:text-right">
                    <div className="flex items-baseline gap-1 md:justify-end">
                      <span className="text-2xl font-semibold tracking-tight text-slate-50 md:text-3xl">
                        $750
                      </span>
                      <span className="text-xs text-slate-400">
                        one-time, per business
                      </span>
                    </div>
                    <p className="mt-1 text-[11px] text-slate-400">
                      Payment only after intake review &amp; fit confirmation.
                    </p>
                  </div>
                </div>
              </CardHeader>

              <CardContent className="relative grid gap-6 pt-5 md:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)] md:gap-7">
                <div className="space-y-4">
                  <div className="flex items-center gap-2 text-xs text-slate-300">
                    <div className="flex h-8 w-8 items-center justify-center rounded-xl bg-sky-500/15 text-sky-300 ring-1 ring-sky-500/40">
                      <FileText className="h-4 w-4" />
                    </div>
                    <div className="text-left">
                      <p className="text-[11px] font-medium text-slate-100">
                        What's included
                      </p>
                      <p className="text-[11px] text-slate-400">
                        Everything you need for a professional conversation with
                        banks, investors, or partners.
                      </p>
                    </div>
                  </div>

                  <ul className="grid gap-2 text-[11px] text-slate-200 md:grid-cols-2">
                    {deliverables.map((item) => (
                      <li key={item} className="flex items-start gap-2">
                        <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 text-emerald-400" />
                        <span>{item}</span>
                      </li>
                    ))}
                  </ul>
                </div>

                <div className="space-y-4 rounded-2xl border border-slate-800/80 bg-slate-950/90 p-4 shadow-soft">
                  <p className="text-[11px] font-medium tracking-tight text-slate-200">
                    Ideal if you're:
                  </p>
                  <ul className="space-y-2 text-[11px] text-slate-300">
                    <li>• Applying for SBA or bank financing</li>
                    <li>• Negotiating a commercial lease or build-out</li>
                    <li>• Aligning co-founders around one strategic plan</li>
                    <li>• Preparing for investor or advisory meetings</li>
                  </ul>
                  <div className="rounded-xl bg-slate-900/80 p-3 text-[11px] text-slate-300">
                    <p className="font-medium text-slate-100">
                      No surprise scope creep.
                    </p>
                    <p className="mt-1 text-slate-400">
                      If your situation requires more complex modeling or
                      multi-entity structure, we'll flag it before any payment is
                      made.
                    </p>
                  </div>
                </div>
              </CardContent>

              <CardFooter className="relative flex flex-col items-start gap-3 border-t border-slate-800/80 py-4 text-[11px] text-slate-300 md:flex-row md:items-center md:justify-between">
                <div>
                  <p className="font-medium text-slate-100">
                    Start with the intake. We'll take it from there.
                  </p>
                  <p className="mt-1 max-w-md text-slate-400">
                    You'll share details about your business, goals, and numbers.
                    We'll confirm fit, timeline, and deliverables before payment.
                  </p>
                </div>

                <motion.div
                  whileHover={{ scale: 1.03, y: -1 }}
                  whileTap={{ scale: 0.98, y: 0 }}
                  transition={{ type: "spring", stiffness: 260, damping: 18 }}
                >
                  <Button
                    asChild
                    size="lg"
                    className="rounded-full px-6 text-xs sm:text-sm"
                  >
                    <Link to="/business-plan-form">Begin intake form</Link>
                  </Button>
                </motion.div>
              </CardFooter>
            </Card>
          </motion.div>
        </section>
      </div>
    </PageShell>
  );
}

export default PricingPage;

