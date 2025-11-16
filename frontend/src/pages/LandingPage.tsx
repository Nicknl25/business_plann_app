import { motion } from "framer-motion";
import {
  ArrowRight,
  BarChart3,
  CheckCircle2,
  LineChart,
  Sparkles,
  Target,
  Workflow,
} from "lucide-react";
import { Link } from "react-router-dom";
import PageShell from "../components/PageShell";
import { Button } from "../components/ui/Button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "../components/ui/Card";

const howItWorks = [
  {
    title: "1. Intake & Clarity",
    icon: Target,
    body: "Answer a guided set of questions about your business, goals, and numbers in under 20 minutes.",
  },
  {
    title: "2. Strategy Blueprint",
    icon: Workflow,
    body: "We structure your inputs into a clear narrative with market positioning, revenue model, and execution roadmap.",
  },
  {
    title: "3. Investor-Ready Plan",
    icon: BarChart3,
    body: "Receive a polished, lender- and investor-ready business plan designed for real-world conversations.",
  },
  {
    title: "4. Iterate & Refine",
    icon: LineChart,
    body: "Easily update assumptions as your business evolves—no more rebuilding plans from scratch.",
  },
];

const reasons = [
  {
    title: "Built by operators & advisors",
    body: "We combine financial planning, lending insight, and founder experience into one streamlined process.",
  },
  {
    title: "Designed for modern fundraising",
    body: "From banks to angel investors, your plan is structured around what decision-makers actually want to see.",
  },
  {
    title: "Clarity, not templates",
    body: "This isn't a generic PDF. It's a tailored narrative and financial story about your specific business.",
  },
];

const testimonials = [
  {
    name: "Jordan M.",
    role: "Founder, Boutique Tax Firm",
    quote:
      "This turned months of planning into a week. Our banker called it the clearest small business plan they'd seen all quarter.",
  },
  {
    name: "Alicia P.",
    role: "Owner, Wellness Studio Collective",
    quote:
      "The structure, visuals, and assumptions made it easy to explain our vision—and even easier to refine it.",
  },
  {
    name: "Marcus L.",
    role: "E-commerce Entrepreneur",
    quote:
      "It felt like having a fractional CFO and strategist in the room without the six-figure price tag.",
  },
];

function LandingPage() {
  return (
    <PageShell>
      <div className="relative overflow-hidden">
        <div className="hero-orbit" />
        <div className="hero-grid absolute inset-0 opacity-70" />

        {/* Hero */}
        <section className="relative z-10 grid gap-10 pb-12 pt-2 md:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)] md:items-center lg:gap-14 lg:pb-16">
          <div className="space-y-6 md:space-y-7">
            <motion.div
              className="inline-flex items-center gap-2 rounded-full border border-sky-400/20 bg-slate-950/80 px-3 py-1 text-[11px] text-sky-200/90 shadow-soft backdrop-blur-xl"
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.05 }}
            >
              <span className="inline-flex h-4 w-4 items-center justify-center rounded-full bg-sky-500/20 text-sky-300">
                <Sparkles className="h-2.5 w-2.5" />
              </span>
              <span className="section-label text-[10px] text-sky-100/90">
                Premium business plans in days—not months
              </span>
            </motion.div>

            <motion.div
              className="space-y-4 md:space-y-5"
              initial={{ opacity: 0, y: 18 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.12 }}
            >
              <h1 className="text-balance text-3xl font-semibold tracking-tight text-slate-50 sm:text-4xl lg:text-5xl">
                Investor-grade business plans
                <span className="block bg-gradient-to-r from-sky-300 via-cyan-200 to-emerald-300 bg-clip-text text-transparent">
                  designed for real-world decisions.
                </span>
              </h1>
              <p className="max-w-xl text-sm leading-relaxed text-slate-300 md:text-[15px]">
                Business Plan Studio turns your ideas, numbers, and story into a
                banker- and investor-ready plan—built with the depth of an
                advisor and the polish of a modern SaaS product.
              </p>
            </motion.div>

            <motion.div
              className="flex flex-col gap-3 sm:flex-row sm:items-center"
              initial={{ opacity: 0, y: 18 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.18 }}
            >
              <div className="flex flex-col gap-3 sm:flex-row">
                <Button
                  asChild
                  size="lg"
                  className="group rounded-full px-6 text-xs sm:text-sm"
                >
                  <Link to="/business-plan-form">
                    Start your intake
                    <ArrowRight className="ml-1.5 h-3.5 w-3.5 transition-transform duration-200 group-hover:translate-x-0.5 group-hover:-translate-y-0.5" />
                  </Link>
                </Button>
                <Button
                  asChild
                  size="lg"
                  variant="secondary"
                  className="rounded-full px-5 text-xs sm:text-sm"
                >
                  <Link to="/pricing">View pricing</Link>
                </Button>
              </div>
              <p className="text-[11px] text-slate-400">
                Flat-fee plan, crafted by experts. No retainers, no surprise
                hours.
              </p>
            </motion.div>

            <motion.dl
              className="grid gap-4 text-[11px] text-slate-300 sm:grid-cols-3"
              initial={{ opacity: 0, y: 16 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.24 }}
            >
              <div className="rounded-xl border border-slate-800/80 bg-slate-950/80 px-4 py-3 shadow-soft">
                <dt className="text-[10px] uppercase tracking-[0.18em] text-slate-500">
                  Typical timeline
                </dt>
                <dd className="mt-1 text-sm font-semibold text-slate-100">
                  5–7 business days
                </dd>
              </div>
              <div className="rounded-xl border border-slate-800/80 bg-slate-950/80 px-4 py-3 shadow-soft">
                <dt className="text-[10px] uppercase tracking-[0.18em] text-slate-500">
                  Crafted plans
                </dt>
                <dd className="mt-1 text-sm font-semibold text-slate-100">
                  100+ small businesses
                </dd>
              </div>
              <div className="rounded-xl border border-slate-800/80 bg-slate-950/80 px-4 py-3 shadow-soft">
                <dt className="text-[10px] uppercase tracking-[0.18em] text-slate-500">
                  Ideal for
                </dt>
                <dd className="mt-1 text-sm font-semibold text-slate-100">
                  Banks, SBA, investors, landlords
                </dd>
              </div>
            </motion.dl>
          </div>

          <motion.div
            className="relative"
            initial={{ opacity: 0, y: 28 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.18 }}
          >
            <div className="glass-surface fade-border relative overflow-hidden rounded-3xl border border-slate-700/70 bg-slate-950/80 p-4 shadow-soft">
              <div className="absolute inset-x-0 top-0 h-32 bg-gradient-to-b from-sky-500/20 via-slate-900/30 to-transparent opacity-80" />
              <div className="relative space-y-4">
                <div className="flex items-center justify-between gap-4">
                  <div>
                    <p className="text-[11px] uppercase tracking-[0.18em] text-slate-400">
                      Plan overview
                    </p>
                    <p className="mt-1 text-sm font-semibold text-slate-50">
                      Business Plan Studio Snapshot
                    </p>
                  </div>
                  <span className="inline-flex items-center gap-1 rounded-full bg-emerald-500/10 px-2 py-1 text-[10px] font-medium text-emerald-300 ring-1 ring-emerald-500/40">
                    <CheckCircle2 className="h-3 w-3" />
                    Lender-ready
                  </span>
                </div>

                <div className="grid gap-3 text-[11px] text-slate-200">
                  <div className="flex items-center justify-between rounded-xl bg-slate-900/80 px-3 py-2">
                    <div>
                      <p className="text-[10px] uppercase tracking-[0.18em] text-slate-500">
                        Sections
                      </p>
                      <p className="mt-0.5 text-xs font-semibold text-slate-100">
                        Narrative + Financials
                      </p>
                    </div>
                    <span className="rounded-full bg-slate-800/80 px-2 py-1 text-[11px]">
                      Executive summary, market, strategy, forecasts
                    </span>
                  </div>
                  <div className="grid grid-cols-3 gap-2 text-[10px]">
                    <div className="rounded-lg bg-slate-900/80 px-2.5 py-2">
                      <p className="text-[9px] uppercase tracking-[0.16em] text-slate-500">
                        Financial view
                      </p>
                      <p className="mt-1 font-semibold text-slate-50">
                        3–5 year model
                      </p>
                    </div>
                    <div className="rounded-lg bg-slate-900/80 px-2.5 py-2">
                      <p className="text-[9px] uppercase tracking-[0.16em] text-slate-500">
                        Use cases
                      </p>
                      <p className="mt-1 font-semibold text-slate-50">
                        SBA, banks, leases
                      </p>
                    </div>
                    <div className="rounded-lg bg-slate-900/80 px-2.5 py-2">
                      <p className="text-[9px] uppercase tracking-[0.16em] text-slate-500">
                        Deliverable
                      </p>
                      <p className="mt-1 font-semibold text-slate-50">
                        PDF + working file
                      </p>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </motion.div>
        </section>

        {/* How it works */}
        <section className="relative z-10 space-y-6 py-10 md:py-12">
          <div className="flex items-center justify-between gap-4">
            <div>
              <p className="section-label text-[10px] text-sky-200/90">
                Workflow
              </p>
              <h2 className="mt-1 text-lg font-semibold tracking-tight text-slate-50 md:text-xl">
                How Business Plan Studio works
              </h2>
            </div>
          </div>

          <div className="grid gap-4 md:grid-cols-2">
            {howItWorks.map((step, index) => {
              const Icon = step.icon;
              return (
                <motion.div
                  key={step.title}
                  initial={{ opacity: 0, y: 18 }}
                  whileInView={{ opacity: 1, y: 0 }}
                  viewport={{ once: true, amount: 0.2 }}
                  transition={{ duration: 0.4, delay: index * 0.05 }}
                >
                  <Card className="h-full border border-slate-800/80 bg-slate-950/80">
                    <CardHeader className="flex flex-row items-start justify-between border-0 pb-2">
                      <div className="flex items-center gap-3">
                        <div className="flex h-8 w-8 items-center justify-center rounded-2xl bg-sky-500/15 text-sky-300 ring-1 ring-sky-500/40">
                          <Icon className="h-4 w-4" />
                        </div>
                        <CardTitle>{step.title}</CardTitle>
                      </div>
                      <span className="text-[11px] text-slate-500">
                        Step {index + 1}
                      </span>
                    </CardHeader>
                    <CardContent className="pt-1">
                      <CardDescription>{step.body}</CardDescription>
                    </CardContent>
                  </Card>
                </motion.div>
              );
            })}
          </div>
        </section>

        {/* Why choose us */}
        <section className="relative z-10 space-y-6 py-10 md:py-12">
          <div className="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
            <div>
              <p className="section-label text-[10px] text-sky-200/90">
                Why founders choose us
              </p>
              <h2 className="mt-1 text-lg font-semibold tracking-tight text-slate-50 md:text-xl">
                Built for lenders, investors, and execution.
              </h2>
            </div>
            <p className="max-w-md text-[11px] text-slate-400">
              Our team blends financial planning, lending expertise, and hands-on
              founder experience so your plan reads like it belongs in the
              boardroom—without losing the heart of your vision.
            </p>
          </div>

          <div className="grid gap-4 md:grid-cols-3">
            {reasons.map((item, index) => (
              <motion.div
                key={item.title}
                initial={{ opacity: 0, y: 20 }}
                whileInView={{ opacity: 1, y: 0 }}
                viewport={{ once: true, amount: 0.2 }}
                transition={{ duration: 0.4, delay: index * 0.06 }}
              >
                <Card className="h-full border border-slate-800/80 bg-slate-950/85">
                  <CardHeader className="border-0 pb-2">
                    <CardTitle>{item.title}</CardTitle>
                  </CardHeader>
                  <CardContent className="pt-1">
                    <CardDescription>{item.body}</CardDescription>
                  </CardContent>
                </Card>
              </motion.div>
            ))}
          </div>
        </section>

        {/* Testimonials */}
        <section className="relative z-10 space-y-6 py-10 md:py-12">
          <div className="flex items-center justify-between gap-4">
            <div>
              <p className="section-label text-[10px] text-sky-200/90">
                Testimonials
              </p>
              <h2 className="mt-1 text-lg font-semibold tracking-tight text-slate-50 md:text-xl">
                Perspectives from small business founders
              </h2>
            </div>
          </div>

          <div className="grid gap-4 md:grid-cols-3">
            {testimonials.map((item, index) => (
              <motion.div
                key={item.name}
                initial={{ opacity: 0, y: 18 }}
                whileInView={{ opacity: 1, y: 0 }}
                viewport={{ once: true, amount: 0.2 }}
                transition={{ duration: 0.4, delay: index * 0.06 }}
              >
                <Card className="h-full border border-slate-800/80 bg-slate-950/80">
                  <CardContent className="flex h-full flex-col gap-4 pt-4">
                    <p className="text-xs leading-relaxed text-slate-200">
                      “{item.quote}”
                    </p>
                    <div className="mt-auto text-[11px] text-slate-400">
                      <p className="font-medium text-slate-200">{item.name}</p>
                      <p>{item.role}</p>
                    </div>
                  </CardContent>
                </Card>
              </motion.div>
            ))}
          </div>
        </section>

        {/* Final CTA */}
        <section className="relative z-10 py-10 md:py-14">
          <motion.div
            className="glass-surface fade-border relative overflow-hidden px-6 py-7 md:px-8 md:py-8"
            initial={{ opacity: 0, y: 22 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true, amount: 0.4 }}
            transition={{ duration: 0.45 }}
          >
            <div className="absolute inset-x-0 top-0 h-24 bg-gradient-to-b from-sky-500/20 via-slate-900/10 to-transparent" />
            <div className="relative flex flex-col gap-6 md:flex-row md:items-center md:justify-between">
              <div className="space-y-2">
                <p className="section-label text-[10px] text-sky-100/90">
                  Ready when you are
                </p>
                <h2 className="text-lg font-semibold tracking-tight text-slate-50 md:text-xl">
                  Turn your ideas into a plan investors can underwrite.
                </h2>
                <p className="max-w-xl text-[11px] text-slate-300">
                  Start with the intake form. We'll guide you from raw thoughts
                  and numbers to a strategic, lender-ready business plan that
                  feels true to how you want to build.
                </p>
              </div>
              <div className="flex flex-col items-start gap-3 md:items-end">
                <Button
                  asChild
                  size="lg"
                  className="group rounded-full px-6 text-xs sm:text-sm"
                >
                  <Link to="/business-plan-form">
                    Begin the intake
                    <ArrowRight className="ml-1.5 h-3.5 w-3.5 transition-transform duration-200 group-hover:translate-x-0.5 group-hover:-translate-y-0.5" />
                  </Link>
                </Button>
                <p className="text-[10px] text-slate-400">
                  No payment required to begin. We'll review your details and
                  confirm next steps.
                </p>
              </div>
            </div>
          </motion.div>
        </section>
      </div>
    </PageShell>
  );
}

export default LandingPage;
