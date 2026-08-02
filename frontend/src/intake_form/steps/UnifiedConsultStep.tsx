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
import CoherencePanel from "./CoherencePanel";
import type { IntakeValues } from "../schema";

type ChatMessage = {
  role: "user" | "assistant";
  content: string;
};

type ParsedRevenueTable = {
  intro: string;
  headers: string[];
  rows: string[][];
  outro: string;
};

type DraftMeta = {
  status: string;
  activeFocus: string;
  opsConfirmed: boolean;
  marketConfirmed: boolean;
  peopleConfirmed: boolean;
  financialsConfirmed: boolean;
  planningStage: string;
  planningStatus: string;
};

const STAGE_HINT_PREFIX =
  "Based on the start date you provided, I'm treating this as";

function stripStageHint(content: string): string {
  const lines = content.split(/\r?\n/);
  const filtered = lines.filter((line) => !line.trim().startsWith(STAGE_HINT_PREFIX));
  return filtered.join("\n").trim();
}

function formatDollars(value: unknown): string | null {
  if (value === null || value === undefined) return null;
  const raw = String(value).replace(/,/g, "").trim();
  if (!raw) return null;
  const num = Number(raw);
  if (!Number.isFinite(num) || num <= 0) return null;
  return `$${Math.round(num).toLocaleString("en-US")}`;
}

function stripMarkdownBold(value: string): string {
  return value.replace(/\*\*(.*?)\*\*/g, "$1").trim();
}

function parsePipeTableLine(line: string): string[] {
  const trimmed = line.trim();
  if (!trimmed.startsWith("|")) return [];
  return trimmed
    .split("|")
    .slice(1, -1)
    .map((cell) => stripMarkdownBold(cell.trim()));
}

function isPipeSeparatorRow(line: string): boolean {
  const cells = parsePipeTableLine(line);
  return cells.length > 0 && cells.every((cell) => /^:?-{3,}:?$/.test(cell.replace(/\s+/g, "")));
}

function parseFinancialsRevenueTable(content: string): ParsedRevenueTable | null {
  if (!content.includes("Year 1 revenue:") || !content.includes("|")) return null;

  const lines = content.split(/\r?\n/);
  const tableStart = lines.findIndex((line) => line.trim().startsWith("|"));
  if (tableStart < 0 || tableStart + 1 >= lines.length) return null;
  if (!isPipeSeparatorRow(lines[tableStart + 1] || "")) return null;

  let tableEnd = tableStart;
  while (tableEnd < lines.length && lines[tableEnd].trim().startsWith("|")) {
    tableEnd += 1;
  }

  const headerCells = parsePipeTableLine(lines[tableStart] || "");
  if (headerCells.length === 0) return null;

  const bodyRows = lines
    .slice(tableStart + 2, tableEnd)
    .map(parsePipeTableLine)
    .filter((row) => row.length > 0);

  if (bodyRows.length === 0) return null;

  const intro = lines.slice(0, tableStart).join("\n").trim();
  const outro = lines.slice(tableEnd).join("\n").trim();

  return {
    intro,
    headers: headerCells,
    rows: bodyRows,
    outro,
  };
}

function renderMessageText(
  content: string,
  sharedContext: any,
  business: { name: string; address: string; startDate: string }
) {
  return renderFactTemplate(content, {
    sharedContext,
    business,
  });
}

function normalizeDraftMeta(body: any): DraftMeta {
  return {
    status: String(body?.draft_status || ""),
    activeFocus: String(body?.active_focus || ""),
    opsConfirmed: Boolean(body?.ops_confirmed),
    marketConfirmed: Boolean(body?.market_confirmed),
    peopleConfirmed: Boolean(body?.people_confirmed),
    financialsConfirmed: Boolean(body?.financials_confirmed),
    planningStage: String(body?.planning_stage || ""),
    planningStatus: String(body?.planning_status || ""),
  };
}

/**
 * Post-submit plan-build strip: backend truth from the polled draft
 * (planning_status mirrors the run, including failure). The banner said
 * "building your plan" once and could silently go false (CW-006: the run
 * failed while the screen kept the promise) - this strip keeps the claim
 * tied to live state. Failure wording is calm and TRUE: the supervisor
 * reruns failed builds automatically.
 */
function PlanBuildStrip({ meta }: { meta: DraftMeta | null }) {
  const status = String(meta?.planningStatus || "").toLowerCase();
  if (!status || !["running", "pending", "completed", "failed"].includes(status)) {
    return null;
  }
  if (status === "completed") {
    return (
      <div className="rounded-md border border-emerald-500/30 bg-emerald-500/5 p-3 text-xs text-emerald-200/90">
        Plan build complete - we'll review it and follow up with next steps.
      </div>
    );
  }
  if (status === "failed") {
    return (
      <div className="rounded-md border border-amber-500/40 bg-amber-500/5 p-3 text-xs text-amber-100/90">
        The plan build hit a snag on our side. It retries automatically - nothing is
        needed from you, and we'll follow up either way.
      </div>
    );
  }
  return (
    <div className="flex items-center gap-2 rounded-md border border-sky-500/40 bg-sky-500/5 p-3 text-xs text-sky-100/90">
      <span className="relative flex h-2 w-2">
        <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-sky-400 opacity-75" />
        <span className="relative inline-flex h-2 w-2 rounded-full bg-sky-400" />
      </span>
      Building your plan now...
    </div>
  );
}

export default function UnifiedConsultStep() {
  const form = useFormContext<IntakeValues>();
  const formApiRef = useRef(form);
  useEffect(() => {
    formApiRef.current = form;
  }, [form]);
  const {
    planStarted,
    spectateDraftId,
    setDraftId,
    setClientId,
    draftId,
    clientId,
    refreshSharedContext,
    sharedContext,
    sharedContextError,
    setConsultDone,
    draftMutation,
  } = useIntakeFlow();
  // Spectator mode: watch an existing draft (e.g. a dual-agent runner conversation)
  // read-only. This tab must never create a session, POST a message, or write the
  // watched draft's identity/business facts into this browser's sessionStorage.
  const isSpectating = Boolean(spectateDraftId);

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
  const businessNameInputRef = useRef<HTMLInputElement | null>(null);
  const businessStartDateInputRef = useRef<HTMLInputElement | null>(null);
  const businessAddressInputRef = useRef<HTMLInputElement | null>(null);
  const lastDraftBusinessRef = useRef({
    name: "",
    address: "",
    startDate: "",
    street: "",
    city: "",
    state: "",
    zip: "",
    country: "",
  });

  const [draftMeta, setDraftMeta] = useState<DraftMeta | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [draftError, setDraftError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [draftSyncing, setDraftSyncing] = useState(false);
  const [sending, setSending] = useState(false);
  const [inputValue, setInputValue] = useState("");
  const [coherence, setCoherence] = useState<any>(null);

  const visibleMessages = useMemo(() => {
    const next: ChatMessage[] = [];
    for (const message of messages) {
      if (message.role === "assistant") {
        const cleaned = stripStageHint(message.content);
        if (!cleaned) {
          continue;
        }
        next.push({ ...message, content: cleaned });
        continue;
      }
      next.push(message);
    }
    return next;
  }, [messages]);

  const detailsComplete = useMemo(() => {
    const hasAddress =
      Boolean(address && address.trim()) &&
      [addressStreet, addressCity, addressState, addressZip, addressCountry].every(
        (v) => Boolean(v && v.trim())
      );
    return Boolean(businessName && businessName.trim()) && hasAddress && Boolean(businessStartDate && businessStartDate.trim());
  }, [address, addressCity, addressCountry, addressState, addressStreet, addressZip, businessName, businessStartDate]);

  const detailsCompleteForChat = useMemo(() => {
    const hasCoreDetails =
      Boolean(businessName && businessName.trim()) &&
      Boolean(address && address.trim()) &&
      Boolean(businessStartDate && businessStartDate.trim());
    if (messages.length > 0) return hasCoreDetails;
    return detailsComplete;
  }, [address, businessName, businessStartDate, detailsComplete, messages.length]);

  const roleLabel = useCallback((role: "user" | "assistant") => (role === "user" ? "client" : "consultant"), []);

  const scrollToBottom = useCallback(() => {
    const el = chatContainerRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, []);

  const refreshDraft = useCallback(async (options?: { preserveError?: boolean }) => {
    const effectiveDraftId = String(
      spectateDraftId || draftId || consultStorage.getDraftId() || ""
    ).trim();
    if (!effectiveDraftId) return;

    const preserveError = Boolean(options?.preserveError);
    if (!preserveError) {
      setDraftError(null);
    }
    setDraftSyncing(true);
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

      try {
        const formApi = formApiRef.current;
        const nextBusinessName = String(body?.business_name || "").trim();
        const nextAddress = String(body?.business_address || "").trim();
        const nextStartDate = String(body?.business_start_date || "").trim();
        const nextStreet = String(body?.address_street || "").trim();
        const nextCity = String(body?.address_city || "").trim();
        const nextState = String(body?.address_state || "").trim();
        const nextZip = String(body?.address_zip || "").trim();
        const nextCountry = String(body?.address_country || "").trim();

        const activeEl = typeof document !== "undefined" ? document.activeElement : null;
        const nameFocused = Boolean(
          businessNameInputRef.current && activeEl === businessNameInputRef.current
        );
        const addressFocused = Boolean(
          businessAddressInputRef.current && activeEl === businessAddressInputRef.current
        );
        const startDateFocused = Boolean(
          businessStartDateInputRef.current && activeEl === businessStartDateInputRef.current
        );

        const lastBusiness = lastDraftBusinessRef.current;

        const currentName = String(formApi.getValues("businessName") || "").trim();
        const currentAddress = String(formApi.getValues("address") || "").trim();
        const currentStartDate = String(formApi.getValues("businessStartDate") || "").trim();

        const canSyncName = !currentName || currentName === String(lastBusiness.name || "").trim();
        const canSyncAddress =
          !currentAddress || currentAddress === String(lastBusiness.address || "").trim();
        const canSyncStartDate =
          !currentStartDate || currentStartDate === String(lastBusiness.startDate || "").trim();

        if (nextBusinessName && nextBusinessName !== currentName && canSyncName && !nameFocused) {
          formApi.setValue("businessName", nextBusinessName, { shouldDirty: false });
        }
        const backendAddressChanged = Boolean(nextAddress && nextAddress !== String(lastBusiness.address || "").trim());
        if (nextAddress && nextAddress !== currentAddress && canSyncAddress && !addressFocused) {
          formApi.setValue("address", nextAddress, { shouldDirty: false });
        }
        if (nextStartDate && nextStartDate !== currentStartDate && canSyncStartDate && !startDateFocused) {
          formApi.setValue("businessStartDate", nextStartDate, { shouldDirty: false });
        }

        const currentStreet = String(formApi.getValues("addressStreet") || "").trim();
        const currentCity = String(formApi.getValues("addressCity") || "").trim();
        const currentState = String(formApi.getValues("addressState") || "").trim();
        const currentZip = String(formApi.getValues("addressZip") || "").trim();
        const currentCountry = String(formApi.getValues("addressCountry") || "").trim();
        const hasCurrentParts = Boolean(
          currentStreet && currentCity && currentState && currentZip && currentCountry
        );
        const hasNextParts = Boolean(nextStreet && nextCity && nextState && nextZip && nextCountry);
        const canSyncParts =
          !hasCurrentParts ||
          (currentStreet === String(lastBusiness.street || "").trim() &&
            currentCity === String(lastBusiness.city || "").trim() &&
            currentState === String(lastBusiness.state || "").trim() &&
            currentZip === String(lastBusiness.zip || "").trim() &&
            currentCountry === String(lastBusiness.country || "").trim());

        if (hasNextParts && canSyncAddress && canSyncParts && !addressFocused) {
          formApi.setValue("addressStreet", nextStreet, { shouldDirty: false });
          formApi.setValue("addressCity", nextCity, { shouldDirty: false });
          formApi.setValue("addressState", nextState, { shouldDirty: false });
          formApi.setValue("addressZip", nextZip, { shouldDirty: false });
          formApi.setValue("addressCountry", nextCountry, { shouldDirty: false });
        } else if (backendAddressChanged && canSyncAddress && !addressFocused && !hasNextParts) {
          formApi.setValue("addressStreet", "", { shouldDirty: false });
          formApi.setValue("addressCity", "", { shouldDirty: false });
          formApi.setValue("addressState", "", { shouldDirty: false });
          formApi.setValue("addressZip", "", { shouldDirty: false });
          formApi.setValue("addressCountry", "", { shouldDirty: false });
        }

        if (!isSpectating) {
          if (nextBusinessName && canSyncName) consultStorage.setBusinessName(nextBusinessName);
          if (nextAddress && canSyncAddress) consultStorage.setAddress(nextAddress);
          if (nextStartDate && canSyncStartDate) consultStorage.setBusinessStartDate(nextStartDate);
          if (hasNextParts && canSyncAddress && canSyncParts) {
            consultStorage.setAddressParts({
              street: nextStreet,
              city: nextCity,
              state: nextState,
              zip: nextZip,
              country: nextCountry,
            });
          } else if (backendAddressChanged && canSyncAddress && !hasNextParts) {
            consultStorage.clearAddressParts();
          }
        }

        lastDraftBusinessRef.current = {
          name: nextBusinessName,
          address: nextAddress,
          startDate: nextStartDate,
          street: nextStreet,
          city: nextCity,
          state: nextState,
          zip: nextZip,
          country: nextCountry,
        };
      } catch {
        // ignore hydration errors
      }

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

      try {
        const rawFin = body?.financials_json;
        const fin =
          rawFin && typeof rawFin === "object"
            ? rawFin
            : rawFin
              ? JSON.parse(String(rawFin))
              : null;
        setCoherence(fin && typeof fin === "object" ? fin._coherence || null : null);
      } catch {
        // ignore — panel simply stays hidden
      }
    } catch (err) {
      setDraftError(err instanceof Error ? err.message : String(err));
    } finally {
      setDraftSyncing(false);
    }
  }, [draftId, isSpectating, setConsultDone, spectateDraftId]);

  const syncNow = useCallback(
    async (options?: { preserveError?: boolean }) => {
      const preserveError = Boolean(options?.preserveError);
      await Promise.all([
        refreshDraft({ preserveError }),
        refreshSharedContext({ silent: true }),
      ]);
    },
    [refreshDraft, refreshSharedContext]
  );

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
    if (isSpectating) return;
    if (!planStarted) return;
    const effectiveDraftId = String(draftId || consultStorage.getDraftId() || "").trim();
    if (effectiveDraftId) return;
    void createSession();
  }, [createSession, draftId, isSpectating, planStarted]);

  useEffect(() => {
    if (isSpectating) return;
    if (!planStarted) return;

    const storedName = String(consultStorage.getBusinessName() || "").trim();
    const storedAddress = String(consultStorage.getAddress() || "").trim();
    const storedStartDate = String(consultStorage.getBusinessStartDate() || "").trim();
    const storedStreet = String(consultStorage.getAddressStreet() || "").trim();
    const storedCity = String(consultStorage.getAddressCity() || "").trim();
    const storedState = String(consultStorage.getAddressState() || "").trim();
    const storedZip = String(consultStorage.getAddressZip() || "").trim();
    const storedCountry = String(consultStorage.getAddressCountry() || "").trim();

    const currentName = String(form.getValues("businessName") || "").trim();
    const currentAddress = String(form.getValues("address") || "").trim();
    const currentStartDate = String(form.getValues("businessStartDate") || "").trim();

    if (!currentName && storedName) {
      form.setValue("businessName", storedName, { shouldDirty: false });
    }
    if (!currentAddress && storedAddress) {
      form.setValue("address", storedAddress, { shouldDirty: false });
    }
    if (!currentStartDate && storedStartDate) {
      form.setValue("businessStartDate", storedStartDate, { shouldDirty: false });
    }

    const currentStreet = String(form.getValues("addressStreet") || "").trim();
    const currentCity = String(form.getValues("addressCity") || "").trim();
    const currentState = String(form.getValues("addressState") || "").trim();
    const currentZip = String(form.getValues("addressZip") || "").trim();
    const currentCountry = String(form.getValues("addressCountry") || "").trim();
    const hasCurrentParts = Boolean(currentStreet && currentCity && currentState && currentZip && currentCountry);
    const hasStoredParts = Boolean(storedStreet && storedCity && storedState && storedZip && storedCountry);

    if (!hasCurrentParts && hasStoredParts) {
      form.setValue("addressStreet", storedStreet, { shouldDirty: false });
      form.setValue("addressCity", storedCity, { shouldDirty: false });
      form.setValue("addressState", storedState, { shouldDirty: false });
      form.setValue("addressZip", storedZip, { shouldDirty: false });
      form.setValue("addressCountry", storedCountry, { shouldDirty: false });
    }
  }, [form, isSpectating, planStarted]);

  useEffect(() => {
    if (!planStarted && !isSpectating) return;
    if (!spectateDraftId && !draftId && !consultStorage.getDraftId()) return;
    void refreshDraft();
  }, [draftId, isSpectating, planStarted, refreshDraft, spectateDraftId]);

  useEffect(() => {
    if (isSpectating || !planStarted) return;
    const raw = String(businessName || "").trim();
    if (raw) consultStorage.setBusinessName(raw);
  }, [businessName, isSpectating, planStarted]);

  useEffect(() => {
    if (isSpectating || !planStarted) return;
    const raw = String(address || "").trim();
    if (raw) consultStorage.setAddress(raw);
  }, [address, isSpectating, planStarted]);

  useEffect(() => {
    if (isSpectating || !planStarted) return;
    const raw = String(businessStartDate || "").trim();
    if (raw) consultStorage.setBusinessStartDate(raw);
  }, [businessStartDate, isSpectating, planStarted]);

  useEffect(() => {
    if (isSpectating || !planStarted) return;
    const street = String(addressStreet || "").trim();
    const city = String(addressCity || "").trim();
    const state = String(addressState || "").trim();
    const zip = String(addressZip || "").trim();
    const country = String(addressCountry || "").trim();
    if (!street || !city || !state || !zip || !country) return;
    consultStorage.setAddressParts({ street, city, state, zip, country });
  }, [addressCity, addressCountry, addressState, addressStreet, addressZip, isSpectating, planStarted]);

  const syncEligibilityRef = useRef({
    planStarted: false,
    hasDraft: false,
    busy: false,
  });
  useEffect(() => {
    syncEligibilityRef.current = {
      planStarted: planStarted || isSpectating,
      hasDraft: Boolean(spectateDraftId || draftId || consultStorage.getDraftId()),
      busy: Boolean(loading || sending || draftSyncing),
    };
  }, [draftId, draftSyncing, isSpectating, loading, planStarted, sending, spectateDraftId]);

  const syncNowRef = useRef<() => void>(() => {});
  useEffect(() => {
    syncNowRef.current = () => {
      void syncNow({ preserveError: true });
    };
  }, [syncNow]);

  useEffect(() => {
    if (!planStarted && !isSpectating) return;

    const maybeSync = () => {
      const state = syncEligibilityRef.current;
      if (!state.planStarted || !state.hasDraft || state.busy) return;
      syncNowRef.current();
    };

    const handleVisibility = () => {
      if (document.visibilityState !== "visible") return;
      maybeSync();
    };

    window.addEventListener("focus", maybeSync);
    window.addEventListener("online", maybeSync);
    document.addEventListener("visibilitychange", handleVisibility);
    return () => {
      window.removeEventListener("focus", maybeSync);
      window.removeEventListener("online", maybeSync);
      document.removeEventListener("visibilitychange", handleVisibility);
    };
  }, [isSpectating, planStarted]);

  // Live follow for EVERY tab (CW-005): the screen's only draft reads used
  // to be mount/send/focus — after the conversation ended there was no event
  // left, so submit status, the stepper, and the coherence panel all froze
  // on the last cached snapshot. Poll while visible: spectators every 2s,
  // client tabs every 5s — and keep polling after completion and submit,
  // because that is exactly when the backend state moves without the user
  // sending anything (the post-intake run).
  useEffect(() => {
    if (!planStarted && !isSpectating) return;

    const intervalMs = isSpectating ? 2000 : 5000;
    const id = window.setInterval(() => {
      if (document.visibilityState !== "visible") return;
      const state = syncEligibilityRef.current;
      if (!state.hasDraft || state.busy) return;
      syncNowRef.current();
    }, intervalMs);
    return () => window.clearInterval(id);
  }, [isSpectating, planStarted]);

  // Mutation -> re-read: anything that mutates the draft outside the chat
  // path (submit is the big one) calls notifyDraftMutation; re-read now.
  useEffect(() => {
    if (!draftMutation) return;
    const state = syncEligibilityRef.current;
    if (!state.hasDraft) return;
    syncNowRef.current();
  }, [draftMutation]);

  useEffect(() => {
    scrollToBottom();
  }, [messages, scrollToBottom]);

  async function startConsultIfNeeded() {
    const effectiveDraftId = String(draftId || consultStorage.getDraftId() || "").trim();
    if (!effectiveDraftId) return;
    if (!detailsCompleteForChat) return;
    if (messages.length > 0) return;

    const draftValues = form.getValues();
    const payloadBusinessName = String(draftValues.businessName || "").trim();
    const payloadAddress = String(draftValues.address || "").trim();
    const payloadStartDate = String(draftValues.businessStartDate || "").trim();
    const payloadStreet = String(draftValues.addressStreet || "").trim();
    const payloadCity = String(draftValues.addressCity || "").trim();
    const payloadState = String(draftValues.addressState || "").trim();
    const payloadZip = String(draftValues.addressZip || "").trim();
    const payloadCountry = String(draftValues.addressCountry || "").trim();
    const hasAllParts = Boolean(
      payloadStreet && payloadCity && payloadState && payloadZip && payloadCountry
    );
    if (payloadAddress && !hasAllParts) {
      setDraftError(
        "Please select a full address from suggestions (street, city, state, ZIP, country)."
      );
      return;
    }

    setSending(true);
    setDraftError(null);
    try {
      const res = await apiClient.post(
        "/api/intake-consult",
        {
          draft_id: effectiveDraftId,
          client_id: clientId || undefined,
          message: "",
          business_name: payloadBusinessName,
          address: payloadAddress,
          business_start_date: payloadStartDate,
          address_street: payloadStreet,
          address_city: payloadCity,
          address_state: payloadState,
          address_zip: payloadZip,
          address_country: payloadCountry,
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
      await syncNow();
      window.setTimeout(() => chatInputRef.current?.focus(), 0);
    } catch (err) {
      setDraftError(err instanceof Error ? err.message : String(err));
      await syncNow({ preserveError: true });
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

    const draftValues = form.getValues();
    const payloadBusinessName = String(draftValues.businessName || "").trim();
    const payloadAddress = String(draftValues.address || "").trim();
    const payloadStartDate = String(draftValues.businessStartDate || "").trim();
    const payloadStreet = String(draftValues.addressStreet || "").trim();
    const payloadCity = String(draftValues.addressCity || "").trim();
    const payloadState = String(draftValues.addressState || "").trim();
    const payloadZip = String(draftValues.addressZip || "").trim();
    const payloadCountry = String(draftValues.addressCountry || "").trim();
    const hasAllParts = Boolean(
      payloadStreet && payloadCity && payloadState && payloadZip && payloadCountry
    );
    if (payloadAddress && !hasAllParts) {
      setDraftError(
        "Please select a full address from suggestions (street, city, state, ZIP, country)."
      );
      return;
    }

    setSending(true);
    setDraftError(null);
    try {
      const res = await apiClient.post(
        "/api/intake-consult",
        {
          draft_id: effectiveDraftId,
          client_id: clientId || undefined,
          message: msg,
          business_name: payloadBusinessName,
          address: payloadAddress,
          business_start_date: payloadStartDate,
          address_street: payloadStreet,
          address_city: payloadCity,
          address_state: payloadState,
          address_zip: payloadZip,
          address_country: payloadCountry,
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
      await syncNow();
      // Settle re-read: some backend stamps land a beat after the turn
      // response (coherence state, run mirrors). One delayed re-read keeps
      // the panel honest without waiting for the next user action.
      window.setTimeout(() => {
        const state = syncEligibilityRef.current;
        if (state.hasDraft && !state.busy) syncNowRef.current();
      }, 2500);
      window.setTimeout(() => chatInputRef.current?.focus(), 0);
    } catch (err) {
      setDraftError(err instanceof Error ? err.message : String(err));
      await syncNow({ preserveError: true });
    } finally {
      setSending(false);
    }
  }

  const activeStep = useMemo(() => {
    if (!draftMeta) return null;
    const focus = String(draftMeta.activeFocus || "").trim().toLowerCase();
    if (["ops", "market", "people", "financials"].includes(focus)) return focus;
    if (draftMeta.status === "completed") return null;
    if (!draftMeta.opsConfirmed) return "ops";
    if (!draftMeta.marketConfirmed) return "market";
    if (!draftMeta.peopleConfirmed) return "people";
    if (!draftMeta.financialsConfirmed) return "financials";
    return null;
  }, [draftMeta]);

  const progressSteps = useMemo(
    () => [
      { key: "ops", label: "Operations", done: Boolean(draftMeta?.opsConfirmed) },
      { key: "market", label: "Target Market", done: Boolean(draftMeta?.marketConfirmed) },
      { key: "people", label: "Human Resources", done: Boolean(draftMeta?.peopleConfirmed) },
      { key: "financials", label: "Financials", done: Boolean(draftMeta?.financialsConfirmed) },
    ],
    [draftMeta]
  );

  const syncInProgress = Boolean(loading || sending || draftSyncing);
  const syncHasError = Boolean(draftError || sharedContextError);
  // The refresh button is ALWAYS usable (when a draft exists): the old gate
  // enabled it only on error, which meant silently-stale data could never
  // be manually refreshed.
  const canReconnect = Boolean((planStarted || isSpectating) && !syncInProgress);
  const syncLabel = syncInProgress ? "Updating…" : syncHasError ? "Reconnect" : "Up to date";

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
            disabled={!canReconnect}
            onClick={canReconnect ? () => void syncNow() : undefined}
            className="disabled:opacity-100"
          >
            <RefreshCw className={`mr-2 h-3.5 w-3.5 ${syncInProgress ? "animate-spin" : ""}`} />
            {syncLabel}
          </Button>
        </div>
      </CardHeader>

      <CardContent className="space-y-4">
        {isSpectating ? (
          <div className="flex items-center gap-2 rounded-md border border-amber-500/40 bg-amber-500/10 p-3 text-xs text-amber-100">
            <span className="relative flex h-2 w-2">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-amber-400 opacity-75" />
              <span className="relative inline-flex h-2 w-2 rounded-full bg-amber-400" />
            </span>
            <span>
              Watching live run (read-only) — draft{" "}
              <span className="font-mono text-amber-200">
                {String(spectateDraftId || "").slice(0, 8)}…
              </span>
            </span>
          </div>
        ) : null}

        {!planStarted && !isSpectating ? (
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
            {({ ref, ...field }) => (
              <FormItem>
                <FormControl>
                  <Input
                    {...field}
                    ref={(el) => {
                      ref(el);
                      businessNameInputRef.current = el;
                    }}
                    placeholder="Business name"
                    autoComplete="off"
                    disabled={isSpectating}
                  />
                </FormControl>
                <FormMessage>{form.formState.errors.businessName?.message}</FormMessage>
              </FormItem>
            )}
          </FormField>

          <FormField name="businessStartDate" control={form.control}>
            {({ ref, ...field }) => (
              <FormItem>
                <FormControl>
                  <Input
                    {...field}
                    ref={(el) => {
                      ref(el);
                      businessStartDateInputRef.current = el;
                    }}
                    type="date"
                    disabled={isSpectating}
                  />
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
                      ref={(el) => {
                        ref(el);
                        businessAddressInputRef.current = el;
                      }}
                      placeholder="Business address (select a full address from suggestions)"
                      disabled={isSpectating}
                    />
                  </FormControl>
                  <FormMessage>{form.formState.errors.address?.message}</FormMessage>
                </FormItem>
              )}
            </FormField>
          </div>
        </div>

        {messages.length === 0 && !isSpectating ? (
          <div className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-slate-800/80 bg-slate-950/40 p-3 text-xs text-slate-300">
            <div className="min-w-0">
              {detailsComplete
                ? "Ready when you are. Start the consultation to begin."
                : "Enter your business name, full address, and start date to begin."}
            </div>
            <Button
              type="button"
              size="sm"
              disabled={!planStarted || loading || sending || !detailsCompleteForChat}
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
        {visibleMessages.length === 0 ? (
          <div className="text-slate-400">
            {sending ? "Starting consultation..." : "Conversation will appear here."}
          </div>
        ) : (
          <>
            {visibleMessages.map((m, idx) => (
              <div
                key={idx}
                className={`rounded-md border px-3 py-2 leading-relaxed ${
                  m.role === "assistant"
                      ? "border-slate-700/60 bg-slate-900/40"
                      : "border-slate-800/70 bg-slate-950/30"
                  }`}
                  data-msg-role={m.role}
                >
                  <span className="text-slate-400">{roleLabel(m.role)}:</span>{" "}
                  {(() => {
                    const business = {
                      name: String(businessName || ""),
                      address: String(address || ""),
                      startDate: String(businessStartDate || ""),
                    };

                    if (m.role !== "assistant") {
                      return <span className="whitespace-pre-wrap">{m.content}</span>;
                    }

                    const parsedRevenueTable = parseFinancialsRevenueTable(m.content);
                    if (!parsedRevenueTable) {
                      return (
                        <span className="whitespace-pre-wrap">
                          {renderMessageText(m.content, sharedContext, business)}
                        </span>
                      );
                    }

                    return (
                      <div className="mt-1 space-y-3">
                        {parsedRevenueTable.intro ? (
                          <div className="whitespace-pre-wrap">
                            {renderMessageText(parsedRevenueTable.intro, sharedContext, business)}
                          </div>
                        ) : null}

                        <div className="overflow-x-auto">
                          <table className="min-w-full border-collapse text-left text-[11px] text-slate-200">
                            <thead>
                              <tr className="border-b border-slate-700/70 text-slate-300">
                                {parsedRevenueTable.headers.map((header) => (
                                  <th key={header} className="px-3 py-2 font-medium">
                                    {header}
                                  </th>
                                ))}
                              </tr>
                            </thead>
                            <tbody>
                              {parsedRevenueTable.rows.map((row, rowIdx) => (
                                <tr
                                  key={`row-${idx}-${rowIdx}`}
                                  className="border-b border-slate-800/60 last:border-b-0"
                                >
                                  {parsedRevenueTable.headers.map((_, cellIdx) => {
                                    const cell = row[cellIdx] || "";
                                    const isTotalRow = cellIdx === 0 && /total/i.test(cell);
                                    const isRevenueCol = cellIdx === parsedRevenueTable.headers.length - 1;
                                    return (
                                      <td
                                        key={`cell-${idx}-${rowIdx}-${cellIdx}`}
                                        className={`px-3 py-2 align-top ${isRevenueCol ? "text-right" : ""} ${
                                          isTotalRow || isRevenueCol ? "font-medium" : ""
                                        }`}
                                      >
                                        {cell}
                                      </td>
                                    );
                                  })}
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>

                        {parsedRevenueTable.outro ? (
                          <div className="whitespace-pre-wrap">
                            {renderMessageText(parsedRevenueTable.outro, sharedContext, business)}
                          </div>
                        ) : null}
                      </div>
                    );
                  })()}
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

        {(() => {
          const peopleCap = (sharedContext as any)?.people_capability;
          const people = Array.isArray(peopleCap?.people) ? peopleCap.people : [];
          const roles = Array.isArray(peopleCap?.inferred_roles) ? peopleCap.inferred_roles : [];
          if (people.length === 0 && roles.length === 0) return null;
          return (
            <div className="rounded-md border border-slate-800/80 bg-slate-950/40 p-3 text-xs text-slate-200">
              <div className="mb-2 text-slate-300">People summary (from saved data)</div>
              {people.length > 0 ? (
                <div className="space-y-2">
                  {people.map((person: any, idx: number) => {
                    const name = String(person?.full_name || "").trim();
                    const title = String(person?.role_title || "").trim();
                    const wage = formatDollars(person?.annual_wage);
                    if (!name && !title && !wage) return null;
                    const headerParts = [name, title].filter(Boolean).join(" — ");
                    return (
                      <div key={`person-${idx}`} className="space-y-1">
                        <div>{headerParts || "Key person"}</div>
                        {wage ? (
                          <div className="text-slate-400">Estimated annual compensation: {wage}</div>
                        ) : null}
                      </div>
                    );
                  })}
                </div>
              ) : null}
              {roles.length > 0 ? (
                <div className={people.length > 0 ? "mt-3 space-y-2" : "space-y-2"}>
                  {roles.map((role: any, idx: number) => {
                    const title = String(role?.role_title || "").trim();
                    const wage = formatDollars(role?.annual_wage);
                    const timingRaw = role?.months_until_hire;
                    const timingNum =
                      timingRaw === null || timingRaw === undefined || Number.isNaN(Number(timingRaw))
                        ? null
                        : Number(timingRaw);
                    if (!title && !wage && timingNum === null) return null;
                    return (
                      <div key={`role-${idx}`} className="space-y-1">
                        <div>{title || "Future role"}</div>
                        {wage ? (
                          <div className="text-slate-400">Est. wage: {wage} / year</div>
                        ) : null}
                        {timingNum !== null ? (
                          <div className="text-slate-400">Timing: ~{timingNum} months</div>
                        ) : null}
                      </div>
                    );
                  })}
                </div>
              ) : null}
            </div>
          );
        })()}

        <CoherencePanel
          state={coherence}
          disabled={isSpectating || sending || loading}
          onSend={(text) => void sendMessage(text)}
        />

        <PlanBuildStrip meta={draftMeta} />

        {draftMeta &&
        draftMeta.status === "in_progress" &&
        draftMeta.opsConfirmed &&
        draftMeta.marketConfirmed &&
        draftMeta.peopleConfirmed &&
        draftMeta.financialsConfirmed &&
        !draftMeta.planningStatus ? (
          <div className="rounded-md border border-sky-500/30 bg-sky-500/5 p-3 text-xs text-sky-100/90">
            Finishing your latest change - submit unlocks as soon as it's confirmed.
          </div>
        ) : null}

        {isSpectating ? (
          <div className="rounded-md border border-slate-800/80 bg-slate-950/40 p-3 text-xs text-slate-400">
            Read-only view — the conversation is driven by the automated run. Replies are
            disabled so watching can never alter the test.
          </div>
        ) : (
        <div className="flex gap-2">
          <Input
            ref={chatInputRef}
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            disabled={!planStarted || sending || loading || !detailsCompleteForChat || !draftId}
            placeholder={
              !detailsCompleteForChat
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
            disabled={!planStarted || sending || loading || !detailsCompleteForChat || !draftId || !inputValue.trim()}
            onClick={() => void sendMessage(inputValue)}
          >
            Send
          </Button>
        </div>
        )}
      </CardContent>
    </Card>
  );
}
