import { Sparkles } from "lucide-react";

export default function WhatToExpectNextInfo() {
  return (
    <section className="rounded-xl border border-slate-800/60 bg-slate-950/40 p-4 text-xs text-slate-300">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-medium text-slate-100">
            What to expect next
          </h3>
          <p className="mt-1 max-w-3xl text-slate-300">
            After you submit this form, we&apos;ll review your details and confirm
            fit, scope, and timing. No payment is required to complete the
            intake.
          </p>
        </div>
        <div className="mt-0.5 animate-glow">
          <span className="relative inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-2xl bg-sky-500/10 text-sky-300 ring-1 ring-sky-500/30 shadow-glow animate-slowspin">
            <Sparkles className="h-4 w-4" />
            <span className="absolute inset-0 -z-10 rounded-2xl bg-sky-500/15 blur-xl" />
          </span>
        </div>
      </div>

      <ul className="mt-3 space-y-1.5 text-slate-200">
        <li>- Review and alignment on goals and audience.</li>
        <li>- Clarifying questions where needed.</li>
        <li>- Confirmation of timeline and next steps.</li>
      </ul>

      <p className="mt-3 text-slate-400">
        The more specific you are, the more precise and compelling your finished
        plan can be.
      </p>
    </section>
  );
}
