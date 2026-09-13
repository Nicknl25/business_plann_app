import React from "react";

/**
 * Coherence panel — renders the viability-gap state the backend stamps
 * under financials_json._coherence. The chat narrates; this panel
 * renders. Option buttons only compose a natural sentence and send it
 * through the normal turn — the intent router interprets it like any
 * client reply (no parallel path, no phrase coupling).
 */

type CoherenceState = {
  status?: string;
  gap_open?: number;
  gap_initial?: number;
  eval?: {
    passed?: boolean;
    gap_quarterly?: number;
    q11?: Record<string, number>;
    thresholds?: Record<string, unknown>;
  };
  early_eval?: { stable_fail?: boolean; q11?: Record<string, number> };
  eval_flat?: { passed?: boolean | null; q11?: Record<string, number> };
  round?: {
    key?: string;
    options?: Array<{
      id?: string;
      label?: string;
      recommended?: boolean;
      closes_display?: string;
      why?: string;
      prices?: Array<{ product?: string; to?: number }>;
      product?: string;
    }>;
    offer_only?: boolean;
    terminal?: boolean;
  };
  accepted_with_gap?: number;
  client_floors?: Record<string, boolean>;
  intake_commitments?: Record<string, string>;
  path?: {
    target_q?: number;
    coherent_as_stated?: boolean;
    feasible?: boolean;
    stated?: { first_positive_ni_q?: number | null; points?: Record<string, { revenue?: number; ni_margin?: number }> };
    limit?: { first_positive_ni_q?: number | null };
  };
  configuration?: { label?: string; first_positive_ni_q?: number | null; moves?: string[] };
  roadmap?: {
    corner_gap_display?: string;
    milestones?: Array<{ key?: string; title?: string; detail?: string }>;
  };
};

function money(v: unknown): string {
  const n = Number(v);
  if (!Number.isFinite(n)) return "—";
  const sign = n < 0 ? "−$" : "$";
  return sign + Math.abs(Math.round(n)).toLocaleString("en-US");
}

function pct(v: unknown): string {
  const n = Number(v);
  if (!Number.isFinite(n)) return "—";
  return (n * 100).toFixed(1) + "%";
}

export default function CoherencePanel({
  state,
  disabled,
  onSend,
}: {
  state: CoherenceState | null | undefined;
  disabled: boolean;
  onSend: (text: string) => void;
}) {
  if (!state || typeof state !== "object") return null;
  const status = String(state.status || "");
  const q11 = state.eval?.q11 || {};

  if (!status) {
    if (state.early_eval?.stable_fail) {
      return (
        <div className="rounded-md border border-amber-500/40 bg-amber-500/5 p-3 text-xs text-amber-200/90">
          Heads-up: with the costs captured so far, a mature quarter already spends more
          than it brings in. We&apos;ll work through it together before the intake wraps up.
        </div>
      );
    }
    return null;
  }

  if (status === "converged") {
    const thresholds = (state.eval?.thresholds || {}) as Record<string, unknown>;
    {/* CW-022 #6: the CW-003 framing rule reaches the panel too — this is
        the STRESS-POINT figure (strongest believable growth), never "a
        typical quarter"; today's-scale figure shown alongside when the
        gate computed it. */}
    const flatQ11 = (state.eval_flat?.q11 || {}) as Record<string, unknown>;
    const flatEbitda = typeof flatQ11.ebitda === "number" ? (flatQ11.ebitda as number) : null;
    return (
      <div className="rounded-md border border-emerald-500/40 bg-emerald-500/5 p-3 text-xs text-emerald-200/90">
        <div className="font-semibold text-emerald-300">
          Clears every structural test we can run right now
        </div>
        <div className="mt-1 text-emerald-100/80">
          At the strongest believable version of this business — a stress test, not a
          forecast — a mature quarter keeps about {money(q11.ebitda)} ({pct(q11.ebitda_margin)} of
          revenue), against the range judged believable for this kind of business.
          {flatEbitda !== null && flatEbitda >= 0 && (
            <> At today&apos;s scale, before any growth, the same structure keeps about{" "}
            {money(flatEbitda)} a quarter.</>
          )}
          {flatEbitda !== null && flatEbitda < 0 && (
            <> At today&apos;s scale the structure doesn&apos;t yet cover its costs — the
            growth path is what closes that.</>
          )}
          {" "}The full build shapes the quarter-by-quarter path and runs its own final checks.
        </div>
        {/* Anchor disclosure: the stress figure is anchored on STATED revenue,
            so driver-level corrections legitimately may not move it while the
            judged floor/ceiling do (CW-006 read that stillness as a freeze).
            Showing the anchor and the band makes each re-evaluation visible. */}
        <div className="mt-1 text-[11px] text-emerald-200/60 tabular-nums">
          Anchored on the annual revenue you stated; believable band{" "}
          {pct(thresholds.band_low)}–{pct(thresholds.band_high)} judged for your kind of
          business.
        </div>
      </div>
    );
  }

  // A-162: the round's doors, in every status that carries a round. A draft
  // is never left with no buttons.
  const roundOptions = state.round?.options || [];
  const roundOfferOnly = Boolean(state.round?.offer_only);
  const doors =
    roundOptions.length > 0 ? (
      <div className="space-y-1.5">
        <div className="text-slate-400">
          {state.round?.terminal
            ? "Where to from here — every door is open:"
            : roundOfferOnly
              ? "Opportunities on the table:"
              : "Your options — every one inside the believable range:"}
        </div>
        {roundOptions.slice(0, 4).map((o, i) => (
          <button
            key={o.id || i}
            type="button"
            disabled={disabled || roundOfferOnly}
            onClick={() =>
              onSend(`Let's go with option ${i + 1} — ${String(o.label || "").trim()}.`)
            }
            className={
              "w-full rounded border p-2 text-left transition " +
              (o.recommended
                ? "border-sky-500/50 bg-sky-500/10 hover:bg-sky-500/20"
                : "border-slate-800/80 bg-slate-950/40 hover:border-sky-500/40") +
              (disabled || roundOfferOnly ? " cursor-default opacity-70" : " cursor-pointer")
            }
          >
            <div className="flex items-center justify-between gap-2">
              <span className="font-medium text-slate-200">
                {i + 1}. {String(o.label || o.product || "option")}
                {o.recommended ? (
                  <span className="ml-2 rounded-full border border-sky-500/40 px-1.5 text-[10px] uppercase tracking-wide text-sky-300">
                    suggested
                  </span>
                ) : null}
              </span>
              {o.closes_display ? (
                <span className="whitespace-nowrap tabular-nums text-emerald-300">
                  closes ≈ {o.closes_display}
                </span>
              ) : null}
            </div>
            {o.why ? <div className="mt-1 text-xs text-slate-400">{String(o.why)}</div> : null}
          </button>
        ))}
        {!disabled && !state.round?.terminal ? (
          <div className="flex justify-end">
            <button
              type="button"
              onClick={() => onSend("Let's pause this for now — I'd like to pick it up later.")}
              className="text-[11px] text-slate-500 underline-offset-2 hover:text-slate-300 hover:underline"
            >
              Save it for now
            </button>
          </div>
        ) : null}
      </div>
    ) : null;

  if (status === "accepted_as_is") {
    const openGap = Number(state.accepted_with_gap);
    return (
      <div className="rounded-md border border-amber-500/40 bg-amber-500/5 p-3 text-xs space-y-2">
        <div className="section-label text-amber-300/80">Submitted as it stands</div>
        <div className="text-slate-300">
          You chose to go ahead with these numbers.{" "}
          {Number.isFinite(openGap) && openGap > 0
            ? `A mature quarter is still ${money(openGap)} short of the lender test; the full build shows that plainly.`
            : "The full build runs on exactly these figures."}
        </div>
      </div>
    );
  }

  if (status === "roadmap") {
    const miles = state.roadmap?.milestones || [];
    return (
      <div className="rounded-md border border-rose-500/40 bg-rose-500/5 p-3 text-xs text-rose-100/90 space-y-2">
        <div className="font-semibold text-rose-300">
          Roadmap first — no plan ships that says the business fails
        </div>
        <div className="text-rose-100/70">
          Even the most favorable believable version comes up about{" "}
          {state.roadmap?.corner_gap_display || "—"} a quarter short. What would have to
          become true:
        </div>
        {miles.map((m, i) => (
          <div key={m.key || i} className="rounded border border-rose-500/20 bg-slate-950/40 p-2">
            <div className="font-medium text-rose-200">{m.title}</div>
            <div className="text-slate-400">{m.detail}</div>
          </div>
        ))}
        <div className="text-slate-400">
          Everything stays saved — when reality moves, the same arithmetic reruns.
        </div>
        {doors}
      </div>
    );
  }

  // walking / parked — the gap hero + the live round
  const floorNames: Record<string, string> = {
    rent: "rent", payroll: "the team", marketing: "marketing", gna: "other operating costs", cogs: "direct costs",
    pricing: "your prices", volume: "your volumes", new_lines: "new lines of revenue", cost_structure: "your cost structure",
  };
  const heldLevers = Object.entries(state.client_floors || {})
    .filter(([, v]) => Boolean(v))
    .map(([k]) => floorNames[k] || k);
  const gapOpen = Number(state.gap_open);
  const gapInitial = Number(state.gap_initial);
  const closedPct =
    Number.isFinite(gapOpen) && Number.isFinite(gapInitial) && gapInitial > 0
      ? Math.max(0, Math.min(100, Math.round((1 - gapOpen / gapInitial) * 100)))
      : 0;

  return (
    <div className="rounded-md border border-sky-500/40 bg-sky-500/5 p-3 text-xs space-y-3">
      <div>
        <div className="section-label text-sky-300/80">The gap — once the business is running</div>
        <div className="mt-1 flex items-baseline gap-2">
          <span className="text-2xl font-semibold tabular-nums text-rose-300">
            {money(gapOpen)}
          </span>
          <span className="text-slate-400">a quarter between this and a plan that works</span>
        </div>
        <div className="mt-2 h-1.5 overflow-hidden rounded bg-slate-800/80">
          <div
            className="h-full rounded bg-gradient-to-r from-sky-500 to-emerald-400 transition-all duration-700"
            style={{ width: `${closedPct}%` }}
          />
        </div>
        <div className="mt-1 flex justify-between text-[11px] text-slate-500 tabular-nums">
          <span>{closedPct}% closed</span>
          <span>{money(gapOpen)} to go</span>
        </div>
      </div>

      <div className="grid grid-cols-3 gap-2">
        <div className="rounded border border-slate-800/80 bg-slate-950/40 p-2">
          <div className="text-[10px] uppercase tracking-wide text-slate-500">Coming in</div>
          <div className="font-semibold tabular-nums text-slate-200">{money(q11.revenue)}</div>
        </div>
        <div className="rounded border border-slate-800/80 bg-slate-950/40 p-2">
          <div className="text-[10px] uppercase tracking-wide text-slate-500">Going out</div>
          <div className="font-semibold tabular-nums text-slate-200">
            {money(Number(q11.revenue) - Number(q11.ebitda))}
          </div>
        </div>
        <div className="rounded border border-slate-800/80 bg-slate-950/40 p-2">
          <div className="text-[10px] uppercase tracking-wide text-slate-500">Quarter keeps</div>
          <div
            className={
              "font-semibold tabular-nums " +
              (Number(q11.ebitda) >= 0 ? "text-emerald-300" : "text-rose-300")
            }
          >
            {money(q11.ebitda)}
          </div>
        </div>
      </div>

      {state.path ? (
        <div className="text-[11px] text-slate-400">
          On the five-year path, as stated: net income{" "}
          {state.path.stated?.first_positive_ni_q ? `turns positive at Q${state.path.stated.first_positive_ni_q}` : "does not turn positive"}
          {state.path.feasible === false ? " - and no lever inside its believable limit changes that by Q11" : ""}
          {state.configuration?.label ? ` · chosen: ${state.configuration.label}` : ""}
        </div>
      ) : null}
      {heldLevers.length > 0 ? (
        <div className="text-[11px] text-slate-500">
          Held as you asked: {heldLevers.join(", ")}. If one of those can move after all, just say so and it comes back
          into the options.
          {Object.entries(state.intake_commitments || {})
            .filter(([k]) => Boolean((state.client_floors || {})[k]))
            .map(([k, why]) => (
              <span key={k}> {floorNames[k] || k}: {why}.</span>
            ))}
        </div>
      ) : null}

      {doors}
    </div>
  );
}
