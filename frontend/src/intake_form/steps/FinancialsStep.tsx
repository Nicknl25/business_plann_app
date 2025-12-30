import { useEffect, useMemo, useRef, useState } from "react";
import { useFormContext } from "react-hook-form";
import apiClient from "../../apiClient";
import { Button } from "../../components/ui/Button";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/Card";
import { Input } from "../../components/ui/Input";
import { useIntakeFlow } from "../flow/IntakeFlowContext";
import { decideConfirmation } from "../flow/confirmationIntent";
import { serverFieldToFormField, type IntakeValues } from "../schema";

type ChatMessage = { role: "user" | "assistant"; content: string };

const FINANCIAL_SERVER_FIELDS: (keyof typeof serverFieldToFormField)[] = [
  "current_revenue",
  "current_cogs",
  "expected_revenue_growth_pct_next_year",
  "tax_rate",
  "marketing_expense",
  "r_and_d_expense",
  "sga_expense",
  "other_operating_expense",
  "monthly_rent_expense",
  "other_monthly_debt_payments",
  "current_payroll",
  "current_num_employees",
  "planned_num_employees_5yrs",
  "current_capex",
  "planned_capex_5yr",
  "ar_balance",
  "ap_balance",
  "inventory_balance",
  "total_debt_outstanding",
  "annual_interest_payment",
  "annual_principal_payment",
  "owner_compensation",
  "cash_on_hand",
];

function formatNumberForField(value: unknown): string {
  if (value === null || value === undefined || value === "") return "";
  const num = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(num)) return "";
  const abs = Math.abs(num);
  const useDecimals = abs > 0 && abs < 1;
  return num.toLocaleString("en-US", {
    maximumFractionDigits: useDecimals ? 6 : 2,
  });
}

export default function FinancialsStep() {
  const form = useFormContext<IntakeValues>();
  const {
    planStarted,
    draftId,
    clientId,
    peopleConfirmed,
    editSection,
    setEditSection,
    financialsDone,
    setFinancialsDone,
    financialsConfirmed,
    setFinancialsConfirmed,
    resetCounter,
  } = useIntakeFlow();

  const didAutoStart = useRef(false);
  const [resumeChecked, setResumeChecked] = useState(false);
  const cardRef = useRef<HTMLDivElement | null>(null);
  const chatInputRef = useRef<HTMLInputElement | null>(null);
  const lastActive = useRef(false);
  const chatContainerRef = useRef<HTMLDivElement | null>(null);
  const prevMessagesLen = useRef(0);
  const prevLoading = useRef(false);

  const roleLabel = (role: "user" | "assistant") =>
    role === "user" ? "client" : "consultant";

  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [editConfirmPending, setEditConfirmPending] = useState(false);

  const businessContext = useMemo(() => {
    const { businessName, businessStartDate } = form.getValues();
    return {
      business_name: businessName,
      business_start_date: businessStartDate,
    };
  }, [form]);

  function applyFinancialsFromObject(obj: any) {
    if (!obj || typeof obj !== "object") return;
    FINANCIAL_SERVER_FIELDS.forEach((serverField) => {
      const formField = serverFieldToFormField[serverField];
      const raw = (obj as any)[serverField];
      const value = formatNumberForField(raw);
      form.setValue(formField, value as any, {
        shouldDirty: true,
        shouldValidate: true,
      });
    });
  }

  useEffect(() => {
    setMessages([]);
    setInput("");
    setLoading(false);
    setError(null);
    setEditConfirmPending(false);
    setFinancialsDone(false);
    didAutoStart.current = false;
    setResumeChecked(false);
  }, [resetCounter, setFinancialsDone]);

  const awaitingConfirmation = Boolean(financialsDone && !financialsConfirmed);
  const isActive = Boolean(peopleConfirmed && !financialsConfirmed);

  const CONFIRM_PROMPT = "Does this look right before we move on to Submit intake?";
  const CLARIFY_PROMPT =
    "Just to confirm - are we good to move on, or is there anything you want to change?";
  const editMode = editSection === "financials";

  function handleConfirmationReply(message: string) {
    const decision = decideConfirmation(message);
    if (decision === "proceed") {
      setFinancialsConfirmed(true);
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: "Great — you’re ready to submit your intake." },
      ]);
      return;
    }

    if (decision === "clarify") {
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: CLARIFY_PROMPT },
      ]);
      return;
    }

    setMessages((prev) =>
      prev.filter((m) => !(m.role === "assistant" && m.content === CONFIRM_PROMPT))
    );
    setFinancialsDone(false);
    void sendMessage(message, { reopen: true, editFinalize: editConfirmPending });
  }

  useEffect(() => {
    if (!planStarted) return;
    if (!isActive) {
      lastActive.current = false;
      return;
    }
    if (lastActive.current) return;
    lastActive.current = true;
    cardRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [isActive, planStarted]);

  useEffect(() => {
    if (!planStarted) return;
    if (!isActive) return;
    if (loading) return;
    if (!chatInputRef.current) return;
    const last = messages[messages.length - 1];
    if (!last || last.role !== "assistant") return;
    chatInputRef.current.focus();
  }, [isActive, loading, messages, planStarted]);

  useEffect(() => {
    if (!planStarted) return;
    if (!isActive) return;
    if (loading) return;
    if (!chatInputRef.current) return;

    const last = messages[messages.length - 1];
    if (!last || last.role !== "assistant") return;
    chatInputRef.current.focus();
  }, [financialsDone, isActive, loading, messages, planStarted]);

  useEffect(() => {
    if (!planStarted) return;
    const container = chatContainerRef.current;
    if (!container) return;

    const wasLoading = prevLoading.current;
    const isLoading = loading && !financialsDone;
    const prevLen = prevMessagesLen.current;

    if (isLoading) {
      container.scrollTop = container.scrollHeight;
    }

    if (messages.length > prevLen) {
      const last = messages[messages.length - 1];
      if (last?.role === "assistant") {
        const nodes = container.querySelectorAll<HTMLElement>(
          '[data-msg-role="assistant"]'
        );
        const el = nodes[nodes.length - 1];
        if (el) {
          container.scrollTop = Math.max(0, el.offsetTop - 4);
        }
      }
    }

    if (!isLoading && wasLoading) {
      const nodes = container.querySelectorAll<HTMLElement>(
        '[data-msg-role="assistant"]'
      );
      const el = nodes[nodes.length - 1];
      if (el) {
        const messageHeight = el.offsetHeight;
        const top = Math.max(0, el.offsetTop - 4);
        if (messageHeight <= container.clientHeight) {
          container.scrollTop = top;
        }
      }
    }

    prevMessagesLen.current = messages.length;
    prevLoading.current = isLoading;
  }, [financialsDone, loading, messages, planStarted]);

  useEffect(() => {
    if (!planStarted) return;
    if (!awaitingConfirmation) return;
    setMessages((prev) => {
      const already = prev.some(
        (m) => m.role === "assistant" && m.content === CONFIRM_PROMPT
      );
      if (already) return prev;
      return [...prev, { role: "assistant", content: CONFIRM_PROMPT }];
    });
  }, [awaitingConfirmation, planStarted]);

  useEffect(() => {
    if (!planStarted) return;
    if (!financialsConfirmed) return;
    setMessages((prev) =>
      prev.filter((m) => !(m.role === "assistant" && m.content === CONFIRM_PROMPT))
    );
    setEditConfirmPending(false);
  }, [financialsConfirmed, planStarted]);

  useEffect(() => {
    if (!planStarted) return;
    if (!financialsConfirmed) return;
    const el = document.getElementById("submit-intake-section");
    el?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [financialsConfirmed, planStarted]);

  useEffect(() => {
    if (!draftId || !clientId) return;
    if (!planStarted) return;
    if (!resumeChecked) return;
    if (!isActive) return;
    if (financialsDone) return;
    if (loading) return;
    if (messages.length > 0) return;
    if (didAutoStart.current) return;
    didAutoStart.current = true;
    void startConversation();
  }, [
    clientId,
    draftId,
    isActive,
    financialsDone,
    loading,
    messages.length,
    planStarted,
    resumeChecked,
  ]);

  useEffect(() => {
    if (!planStarted) return;
    if (!draftId) return;
    (async () => {
      try {
        const res = await apiClient.get("/api/financials-consult/draft", {
          params: { draft_id: draftId },
          validateStatus: () => true,
        });
        if (res.status >= 200 && res.status < 300) {
          const body: any = res.data;

          const draftStatus = String(body?.draft_status || "");
          const messagesJson = body?.messages_json;
          if (messagesJson) {
            try {
              const parsed = JSON.parse(String(messagesJson));
              if (Array.isArray(parsed)) {
                setMessages(
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
            setFinancialsDone(true);
            const finJson = body?.financials_json;
            if (finJson) {
              try {
                const parsed = JSON.parse(String(finJson));
                applyFinancialsFromObject(parsed);
              } catch {
                // ignore
              }
            }
          }
        }
      } catch {
        // ignore resume errors
      } finally {
        setResumeChecked(true);
      }
    })();
  }, [draftId, planStarted, setFinancialsDone]);

  async function startConversation(preface?: string) {
    if (!draftId || !clientId) return;
    setError(null);
    setLoading(true);
    setMessages(preface ? [{ role: "assistant", content: preface }] : []);
    setInput("");
    setFinancialsDone(false);

    try {
      const sessionRes = await apiClient.post(
        "/api/financials-consult/session",
        { draft_id: draftId },
        {
          validateStatus: () => true,
          headers: { "Content-Type": "application/json" },
        }
      );
      if (sessionRes.status < 200 || sessionRes.status >= 300) {
        const body = sessionRes.data;
        throw new Error(
          body && typeof body === "object" && body.detail
            ? String(body.detail)
            : `Financials session error: ${sessionRes.status} ${sessionRes.statusText}`
        );
      }

      const res = await apiClient.post(
        "/api/financials-consult",
        { draft_id: draftId, ...businessContext },
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
            : `Financials consult error: ${res.status} ${res.statusText}`
        );
      }

      const body: any = res.data;
      setFinancialsDone(Boolean(body?.done));
      setMessages((prev) => {
        const editFinalize = Boolean(options?.editFinalize) && Boolean(body?.done);
        const base = editFinalize
          ? prev.filter((m) => !(m.role === "assistant" && m.content === CONFIRM_PROMPT))
          : prev;
        const next: ChatMessage[] = [
          ...base,
          { role: "assistant" as const, content: String(body?.assistant_message || "") },
        ];
        if (body?.done) {
          if (editFinalize) {
            next.push({ role: "assistant" as const, content: CONFIRM_PROMPT });
          } else {
            const already = next.some(
              (m) => m.role === "assistant" && m.content === CONFIRM_PROMPT
            );
            if (!already) next.push({ role: "assistant" as const, content: CONFIRM_PROMPT });
          }
        }
        return next;
      });
      if (body?.done) {
        const finJson = body?.financials_json;
        if (finJson) {
          try {
            const parsed = JSON.parse(String(finJson));
            applyFinancialsFromObject(parsed);
          } catch {
            // ignore
          }
        }
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  async function sendMessage(message: string, options?: { reopen?: boolean; editFinalize?: boolean }) {
    if (!draftId || !clientId) return;
    setError(null);
    setLoading(true);

    try {
      const res = await apiClient.post(
        "/api/financials-consult",
        {
          draft_id: draftId,
          message,
          reopen: Boolean(options?.reopen),
          edit_finalize: Boolean(options?.editFinalize),
          ...businessContext,
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
            : `Financials consult error: ${res.status} ${res.statusText}`
        );
      }

      const body: any = res.data;
      setFinancialsDone(Boolean(body?.done));
      setMessages((prev) => {
        const next: ChatMessage[] = [
          ...prev,
          { role: "assistant" as const, content: String(body?.assistant_message || "") },
        ];
        if (body?.done) {
          const already = next.some(
            (m) => m.role === "assistant" && m.content === CONFIRM_PROMPT
          );
          if (!already) next.push({ role: "assistant" as const, content: CONFIRM_PROMPT });
        }
        return next;
      });
      if (body?.done) {
        const finJson = body?.financials_json;
        if (finJson) {
          try {
            const parsed = JSON.parse(String(finJson));
            applyFinancialsFromObject(parsed);
          } catch {
            // ignore
          }
        }
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  if (!planStarted) {
    return (
      <Card
        id="intake-section-financials"
        ref={cardRef}
        className="border border-slate-800/80 bg-slate-950/90"
      >
        <CardHeader className="border-0 pb-3">
          <CardTitle className="text-sm">Financials</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3 text-xs text-slate-300">
          <div className="rounded-md border border-slate-800/80 bg-slate-950/60 p-3">
            You&apos;ll work with the assistant to capture your baseline revenue,
            costs, expenses, debt, and liquidity inputs.
          </div>
          <div className="text-slate-400">
            Click <span className="text-slate-200">Start Your Plan</span> to begin.
          </div>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card
      id="intake-section-financials"
      ref={cardRef}
      className="border border-slate-800/80 bg-slate-950/90"
    >
      <CardHeader className="border-0 pb-3">
        <CardTitle className="text-sm">Financials</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="mt-2 space-y-3 rounded-md border border-slate-800/80 bg-slate-950/60 p-3">
          <div className="text-xs text-slate-300">
            Financials consultation: GPT will collect your baseline revenue, costs,
            expenses, debt, and liquidity inputs and populate the model fields.
          </div>

          {!peopleConfirmed ? (
            <div className="text-xs text-slate-400">
              Complete and confirm People &amp; capability first.
            </div>
          ) : messages.length === 0 && !awaitingConfirmation ? (
            <div className="text-xs text-slate-400">
              {loading
                ? "Starting financials consultation..."
                : "Preparing financials consultation..."}
            </div>
          ) : null}

          {loading && messages.length === 0 ? (
            <div className="text-xs text-slate-400 italic animate-pulse">
              Consultant is generating a response...
            </div>
          ) : null}

          {error ? (
            <div className="rounded-md border border-rose-500/30 bg-rose-500/10 p-3 text-xs text-rose-200">
              {error}
            </div>
          ) : null}

          {messages.length ? (
            <div
              ref={chatContainerRef}
              className="max-h-64 space-y-2 overflow-auto rounded-md border border-slate-800/80 bg-slate-950/60 p-3 text-xs text-slate-200"
            >
              {messages.map((m, idx) => (
                <div
                  key={idx}
                  className={`whitespace-pre-wrap rounded-md border px-3 py-2 leading-relaxed ${
                    m.role === "assistant"
                      ? "border-slate-700/60 bg-slate-900/40"
                      : "border-slate-800/70 bg-slate-950/30"
                  }`}
                  data-msg-role={m.role}
                >
                  <span className="text-slate-400">{roleLabel(m.role)}:</span>{" "}
                  {m.content}
                </div>
              ))}
              {loading && !financialsDone ? (
                <div
                  className="whitespace-pre-wrap rounded-md border border-slate-700/60 bg-slate-900/40 px-3 py-2 text-slate-400 italic animate-pulse"
                  data-msg-role="assistant"
                >
                  <span className="text-slate-400">consultant:</span> Consultant is
                  generating a response...
                </div>
              ) : null}
            </div>
          ) : null}

          {financialsConfirmed ? (
            <div className="rounded-md border border-emerald-500/30 bg-emerald-500/10 p-3 text-xs text-emerald-200">
              Financials confirmed.
            </div>
          ) : null}

          {isActive ? (
            <div className="flex gap-2">
              <Input
                ref={chatInputRef}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={async (e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    if (loading) return;
                    if (!awaitingConfirmation && messages.length === 0) return;
                    const msg = input.trim();
                    if (!msg) return;
                    setInput("");
                    setMessages((prev) => [...prev, { role: "user", content: msg }]);
                    if (awaitingConfirmation) {
                      handleConfirmationReply(msg);
                      return;
                    }
                    if (editMode) {
                      setEditSection(null);
                      setEditConfirmPending(true);
                      await sendMessage(msg, { reopen: true, editFinalize: true });
                      return;
                    }
                    await sendMessage(msg);
                  }
                }}
                placeholder={
                  awaitingConfirmation
                    ? "Reply to continue..."
                    : "Reply with a number or short answer..."
                }
                disabled={loading || (!awaitingConfirmation && messages.length === 0)}
              />
              <Button
                type="button"
                size="sm"
                disabled={
                  loading ||
                  (!awaitingConfirmation && messages.length === 0) ||
                  !input.trim()
                }
                onClick={async () => {
                  const msg = input.trim();
                  if (!msg) return;
                  setInput("");
                  setMessages((prev) => [...prev, { role: "user", content: msg }]);
                  if (awaitingConfirmation) {
                    handleConfirmationReply(msg);
                    return;
                  }
                  if (editMode) {
                    setEditSection(null);
                    setEditConfirmPending(true);
                    await sendMessage(msg, { reopen: true, editFinalize: true });
                    return;
                  }
                  await sendMessage(msg);
                }}
              >
                Send
              </Button>
            </div>
          ) : null}
        </div>
      </CardContent>
    </Card>
  );
}
