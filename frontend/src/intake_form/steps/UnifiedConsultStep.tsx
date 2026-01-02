import { CheckCircle2, Circle, ClipboardList, RefreshCw } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useFormContext } from "react-hook-form";
import apiClient from "../../apiClient";
import { Button } from "../../components/ui/Button";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/Card";
import { FormControl, FormField, FormItem, FormMessage } from "../../components/ui/Form";
import { Input } from "../../components/ui/Input";
import GoogleAddressInput from "../../components/GoogleAddressInput";
import { useIntakeFlow } from "../flow/IntakeFlowContext";
import { consultStorage } from "../flow/consultStorage";
import { renderFactTemplate } from "../flow/renderFactTemplate";
import type { IntakeValues } from "../schema";

type ChatMessage = { role: "user" | "assistant"; content: string };

type DraftMeta = {
  status: string;
  activeFocus: string;
  opsConfirmed: boolean;
  marketConfirmed: boolean;
  peopleConfirmed: boolean;
  financialsConfirmed: boolean;
  consistencyPassed: boolean;
};

function normalizeDraftMeta(body: any): DraftMeta {
  return {
    status: String(body?.draft_status || ""),
    activeFocus: String(body?.active_focus || ""),
    opsConfirmed: Boolean(body?.ops_confirmed),
    marketConfirmed: Boolean(body?.market_confirmed),
    peopleConfirmed: Boolean(body?.people_confirmed),
    financialsConfirmed: Boolean(body?.financials_confirmed),
    consistencyPassed: Boolean(body?.consistency_passed),
  };
}

export default function UnifiedConsultStep() {
  const form = useFormContext<IntakeValues>();
  const {
    planStarted,
    setDraftId,
    setClientId,
    draftId,
    clientId,
    refreshSharedContext,
    sharedContext,
    setConsultDone,
  } = useIntakeFlow();

  const businessName = form.watch("businessName");
  const address = form.watch("address");
  const addressStreet = form.watch("addressStreet");
  const addressCity = form.watch("addressCity");
  const addressState = form.watch("addressState");
  const addressZip = form.watch("addressZip");
  const addressCountry = form.watch("addressCountry");
  const businessStartDate = form.watch("businessStartDate");

  const chatContainerRef = useRef<HTMLDivElement | null>(null);
  const chatInputRef = useRef<HTMLInputElement | null>(null);

  const [draftMeta, setDraftMeta] = useState<DraftMeta | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [draftError, setDraftError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [sending, setSending] = useState(false);
  const [inputValue, setInputValue] = useState("");

  const detailsComplete = useMemo(() => {
    const hasAddress =
      Boolean(address && address.trim()) &&
      [addressStreet, addressCity, addressState, addressZip, addressCountry].every(
        (v) => Boolean(v && v.trim())
      );
    return Boolean(businessName && businessName.trim()) && hasAddress && Boolean(businessStartDate && businessStartDate.trim());
  }, [address, addressCity, addressCountry, addressState, addressStreet, addressZip, businessName, businessStartDate]);

  const roleLabel = useCallback((role: "user" | "assistant") => (role === "user" ? "client" : "consultant"), []);

  const scrollToBottom = useCallback(() => {
    const el = chatContainerRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, []);

  const refreshDraft = useCallback(async () => {
    const effectiveDraftId = String(draftId || consultStorage.getDraftId() || "").trim();
    if (!effectiveDraftId) return;

    setDraftError(null);
    try {
      const res = await apiClient.get("/api/intake-consult/draft", {
        params: { draft_id: effectiveDraftId },
        validateStatus: () => true,
      });
      if (res.status < 200 || res.status >= 300) {
        const body: any = res.data;
        throw new Error(
          body && typeof body === "object" && body.detail
            ? String(body.detail)
            : `Draft error: ${res.status} ${res.statusText}`
        );
      }

      const body: any = res.data;
      setDraftMeta(normalizeDraftMeta(body));
      setConsultDone(String(body?.draft_status || "") === "completed");

      const rawMessages = body?.messages_json;
      if (rawMessages) {
        try {
          const parsed = JSON.parse(String(rawMessages));
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
    } catch (err) {
      setDraftError(err instanceof Error ? err.message : String(err));
    }
  }, [draftId, setConsultDone]);

  const createSession = useCallback(async () => {
    setDraftError(null);
    setLoading(true);
    try {
      consultStorage.clear();
      const res = await apiClient.post(
        "/api/intake-consult/session",
        {},
        { validateStatus: () => true, headers: { "Content-Type": "application/json" } }
      );
      if (res.status < 200 || res.status >= 300) {
        const body: any = res.data;
        throw new Error(
          body && typeof body === "object" && body.detail
            ? String(body.detail)
            : `Session error: ${res.status} ${res.statusText}`
        );
      }
      const body: any = res.data;
      const nextDraftId = String(body?.draft_id || "").trim();
      const nextClientId = String(body?.client_id || "").trim();
      if (!nextDraftId || !nextClientId) throw new Error("Session did not return draft_id/client_id.");

      consultStorage.set(nextDraftId, nextClientId);
      setDraftId(nextDraftId);
      setClientId(nextClientId);
      setMessages([]);
      setDraftMeta(null);
      setInputValue("");
      await refreshSharedContext({ silent: true });
    } catch (err) {
      setDraftError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [refreshSharedContext, setClientId, setDraftId]);

  useEffect(() => {
    if (!planStarted) return;
    const effectiveDraftId = String(draftId || consultStorage.getDraftId() || "").trim();
    if (effectiveDraftId) return;
    void createSession();
  }, [createSession, draftId, planStarted]);

  useEffect(() => {
    if (!planStarted) return;
    if (!draftId && !consultStorage.getDraftId()) return;
    void refreshDraft();
  }, [draftId, planStarted, refreshDraft]);

  useEffect(() => {
    scrollToBottom();
  }, [messages, scrollToBottom]);

  async function startConsultIfNeeded() {
    const effectiveDraftId = String(draftId || consultStorage.getDraftId() || "").trim();
    if (!effectiveDraftId) return;
    if (!detailsComplete) return;
    if (messages.length > 0) return;

    setSending(true);
    setDraftError(null);
    try {
      const res = await apiClient.post(
        "/api/intake-consult",
        {
          draft_id: effectiveDraftId,
          client_id: clientId || undefined,
          message: "",
          business_name: String(businessName || "").trim(),
          address: String(address || "").trim(),
          business_start_date: String(businessStartDate || "").trim(),
          address_street: String(addressStreet || "").trim(),
          address_city: String(addressCity || "").trim(),
          address_state: String(addressState || "").trim(),
          address_zip: String(addressZip || "").trim(),
          address_country: String(addressCountry || "").trim(),
        },
        { validateStatus: () => true, headers: { "Content-Type": "application/json" } }
      );
      if (res.status < 200 || res.status >= 300) {
        const body: any = res.data;
        throw new Error(
          body && typeof body === "object" && body.detail
            ? String(body.detail)
            : `Consult error: ${res.status} ${res.statusText}`
        );
      }
      await refreshDraft();
      await refreshSharedContext({ silent: true });
      window.setTimeout(() => chatInputRef.current?.focus(), 0);
    } catch (err) {
      setDraftError(err instanceof Error ? err.message : String(err));
    } finally {
      setSending(false);
    }
  }

  async function sendMessage(raw: string) {
    const effectiveDraftId = String(draftId || consultStorage.getDraftId() || "").trim();
    if (!effectiveDraftId) {
      setDraftError("Missing draft id. Reload and start the intake again.");
      return;
    }
    const msg = String(raw || "").trim();
    if (!msg) return;

    setSending(true);
    setDraftError(null);
    try {
      const res = await apiClient.post(
        "/api/intake-consult",
        {
          draft_id: effectiveDraftId,
          client_id: clientId || undefined,
          message: msg,
          business_name: String(businessName || "").trim(),
          address: String(address || "").trim(),
          business_start_date: String(businessStartDate || "").trim(),
          address_street: String(addressStreet || "").trim(),
          address_city: String(addressCity || "").trim(),
          address_state: String(addressState || "").trim(),
          address_zip: String(addressZip || "").trim(),
          address_country: String(addressCountry || "").trim(),
        },
        { validateStatus: () => true, headers: { "Content-Type": "application/json" } }
      );
      if (res.status < 200 || res.status >= 300) {
        const body: any = res.data;
        throw new Error(
          body && typeof body === "object" && body.detail
            ? String(body.detail)
            : `Consult error: ${res.status} ${res.statusText}`
        );
      }
      setInputValue("");
      await refreshDraft();
      await refreshSharedContext({ silent: true });
      window.setTimeout(() => chatInputRef.current?.focus(), 0);
    } catch (err) {
      setDraftError(err instanceof Error ? err.message : String(err));
    } finally {
      setSending(false);
    }
  }

  const activeStep = useMemo(() => {
    if (!draftMeta) return null;
    const focus = String(draftMeta.activeFocus || "").trim().toLowerCase();
    if (["ops", "market", "people", "financials", "consistency"].includes(focus)) return focus;
    if (draftMeta.status === "completed") return null;
    if (!draftMeta.opsConfirmed) return "ops";
    if (!draftMeta.marketConfirmed) return "market";
    if (!draftMeta.peopleConfirmed) return "people";
    if (!draftMeta.financialsConfirmed) return "financials";
    if (!draftMeta.consistencyPassed) return "consistency";
    return null;
  }, [draftMeta]);

  const progressSteps = useMemo(
    () => [
      { key: "ops", label: "Operations", done: Boolean(draftMeta?.opsConfirmed) },
      { key: "market", label: "Target Market", done: Boolean(draftMeta?.marketConfirmed) },
      { key: "people", label: "Human Resources", done: Boolean(draftMeta?.peopleConfirmed) },
      { key: "financials", label: "Financials", done: Boolean(draftMeta?.financialsConfirmed) },
      { key: "consistency", label: "Consistency", done: Boolean(draftMeta?.consistencyPassed) },
    ],
    [draftMeta]
  );

  return (
    <Card className="border border-slate-800/80 bg-slate-950/60 shadow-soft" id="intake-section-unified">
      <CardHeader className="flex flex-row items-start justify-between gap-3 border-0 pb-3">
        <div className="space-y-1">
          <CardTitle className="flex items-center gap-2 text-sm">
            <span className="inline-flex h-7 w-7 items-center justify-center rounded-xl bg-sky-500/15 text-sky-300 ring-1 ring-sky-500/40">
              <ClipboardList className="h-3.5 w-3.5" />
            </span>
            Intake consultation
          </CardTitle>
          <div className="text-xs text-slate-400">
            <div className="flex flex-wrap items-center gap-2">
              {progressSteps.map((step, idx) => {
                const isActive = Boolean(activeStep && activeStep === step.key);
                const isDone = Boolean(step.done);
                const iconClass = isDone
                  ? "text-emerald-300"
                  : isActive
                    ? "text-sky-300"
                    : "text-slate-600";
                const labelClass = isDone
                  ? "text-slate-200"
                  : isActive
                    ? "text-sky-200"
                    : "text-slate-500";
                return (
                  <div key={step.key} className="flex items-center gap-1">
                    {isDone ? (
                      <CheckCircle2 className={`h-3.5 w-3.5 ${iconClass}`} />
                    ) : (
                      <Circle className={`h-3.5 w-3.5 ${iconClass}`} />
                    )}
                    <span className={labelClass}>{step.label}</span>
                    {idx < progressSteps.length - 1 ? (
                      <span className="mx-1 text-slate-700">→</span>
                    ) : null}
                  </div>
                );
              })}
            </div>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <Button
            type="button"
            size="sm"
            variant="secondary"
            disabled={!planStarted || loading}
            onClick={() => void refreshDraft()}
          >
            <RefreshCw className="mr-2 h-3.5 w-3.5" />
            Refresh
          </Button>
        </div>
      </CardHeader>

      <CardContent className="space-y-4">
        {!planStarted ? (
          <div className="rounded-md border border-slate-800/80 bg-slate-950/40 p-3 text-xs text-slate-300">
            Click <span className="text-slate-100">Start Your Plan</span> to begin the intake.
          </div>
        ) : null}

        {draftError ? (
          <div className="rounded-md border border-rose-500/40 bg-rose-500/10 p-3 text-xs text-rose-100">
            {draftError}
          </div>
        ) : null}

        <div className="grid gap-3 md:grid-cols-2">
          <FormField name="businessName" control={form.control}>
            {(field) => (
              <FormItem>
                <FormControl>
                  <Input {...field} placeholder="Business name" autoComplete="off" />
                </FormControl>
                <FormMessage>{form.formState.errors.businessName?.message}</FormMessage>
              </FormItem>
            )}
          </FormField>

          <FormField name="businessStartDate" control={form.control}>
            {(field) => (
              <FormItem>
                <FormControl>
                  <Input {...field} type="date" />
                </FormControl>
                <FormMessage>{form.formState.errors.businessStartDate?.message}</FormMessage>
              </FormItem>
            )}
          </FormField>

          <div className="md:col-span-2">
            <FormField name="address" control={form.control}>
              {({ ref, ...field }) => (
                <FormItem>
                  <FormControl>
                    <GoogleAddressInput
                      {...field}
                      ref={ref}
                      placeholder="Business address (select a full address from suggestions)"
                    />
                  </FormControl>
                  <FormMessage>{form.formState.errors.address?.message}</FormMessage>
                </FormItem>
              )}
            </FormField>
          </div>
        </div>

        {messages.length === 0 ? (
          <div className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-slate-800/80 bg-slate-950/40 p-3 text-xs text-slate-300">
            <div className="min-w-0">
              {detailsComplete
                ? "Ready when you are. Start the consultation to begin."
                : "Enter your business name, full address, and start date to begin."}
            </div>
            <Button
              type="button"
              size="sm"
              disabled={!planStarted || loading || sending || !detailsComplete}
              onClick={() => void startConsultIfNeeded()}
            >
              Start consultation
            </Button>
          </div>
        ) : null}

        <div
          ref={chatContainerRef}
          className="max-h-80 space-y-2 overflow-auto rounded-md border border-slate-800/80 bg-slate-950/60 p-3 text-xs text-slate-200"
        >
          {messages.length === 0 ? (
            <div className="text-slate-400">
              {sending ? "Starting consultation..." : "Conversation will appear here."}
            </div>
          ) : (
            <>
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
                  {m.role === "assistant"
                    ? renderFactTemplate(m.content, {
                        sharedContext,
                        business: {
                          name: String(businessName || ""),
                          address: String(address || ""),
                          startDate: String(businessStartDate || ""),
                        },
                      })
                    : m.content}
                </div>
              ))}
              {sending ? (
                <div
                  className="whitespace-pre-wrap rounded-md border border-slate-700/60 bg-slate-900/40 px-3 py-2 text-slate-400 italic animate-pulse"
                  data-msg-role="assistant"
                >
                  <span className="text-slate-400">consultant:</span> Consultant is generating a response...
                </div>
              ) : null}
            </>
          )}
        </div>

        <div className="flex gap-2">
          <Input
            ref={chatInputRef}
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            disabled={!planStarted || sending || loading || !detailsComplete || !draftId}
            placeholder={
              !detailsComplete
                ? "Complete business details to begin..."
                : messages.length === 0
                  ? "Start the consultation first..."
                  : "Reply..."
            }
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                void sendMessage(inputValue);
              }
            }}
          />
          <Button
            type="button"
            disabled={!planStarted || sending || loading || !detailsComplete || !draftId || !inputValue.trim()}
            onClick={() => void sendMessage(inputValue)}
          >
            Send
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
