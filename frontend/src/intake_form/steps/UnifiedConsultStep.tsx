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

type ModelDriverValue = {
  value?: any;
  unit?: string | null;
  time_basis?: string | null;
  rationale?: string | null;
};

type ModelCard = {
  version?: number;
  updated_at_ms?: number;
  drivers?: Record<string, ModelDriverValue>;
  derived?: Record<
    string,
    { value?: any; unit?: string | null; time_basis?: string | null; derivation?: string | null }
  >;
  lobs?: Array<{
    lob_key: string;
    lob_name?: string | null;
    drivers?: Record<string, ModelDriverValue>;
    derived?: Record<
      string,
      { value?: any; unit?: string | null; time_basis?: string | null; derivation?: string | null }
    >;
  }>;
};

type ModelCardProposal = {
  id: string;
  model: string;
  title?: string;
  lob_key?: string | null;
  lob_name?: string | null;
  updates?: Array<{ key: string; value: any; unit?: string | null; time_basis?: string | null; rationale?: string | null }>;
  derived?: Array<{ key: string; value: any; unit?: string | null; time_basis?: string | null; derivation?: string | null }>;
  created_at_ms?: number;
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
  const formApiRef = useRef(form);
  useEffect(() => {
    formApiRef.current = form;
  }, [form]);
  const {
    planStarted,
    setDraftId,
    setClientId,
    draftId,
    clientId,
    refreshSharedContext,
    sharedContext,
    sharedContextError,
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
  const businessNameInputRef = useRef<HTMLInputElement | null>(null);
  const businessAddressInputRef = useRef<HTMLInputElement | null>(null);
  const lastAutoSyncAtRef = useRef(0);
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
  const [modelSaving, setModelSaving] = useState(false);
  const [editingDriver, setEditingDriver] = useState<{
    model: string;
    lobKey: string;
    key: string;
    value: string;
    unit: string;
    timeBasis: string;
    rationale: string;
  } | null>(null);
  const [editingProposal, setEditingProposal] = useState<{
    proposalId: string;
    model: string;
    lobKey: string;
    lobName: string;
    monthlyBudget: string;
    primaryChannels: string;
    rationale: string;
  } | null>(null);

  const detailsComplete = useMemo(() => {
    const hasAddress =
      Boolean(address && address.trim()) &&
      [addressStreet, addressCity, addressState, addressZip, addressCountry].every(
        (v) => Boolean(v && v.trim())
      );
    return Boolean(businessName && businessName.trim()) && hasAddress;
  }, [address, addressCity, addressCountry, addressState, addressStreet, addressZip, businessName]);

  const detailsCompleteForChat = useMemo(() => {
    const hasCoreDetails =
      Boolean(businessName && businessName.trim()) &&
      Boolean(address && address.trim());
    if (messages.length > 0) return hasCoreDetails;
    return detailsComplete;
  }, [address, businessName, detailsComplete, messages.length]);

  const roleLabel = useCallback((role: "user" | "assistant") => (role === "user" ? "client" : "consultant"), []);

  const scrollToBottom = useCallback(() => {
    const el = chatContainerRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, []);

  const refreshDraft = useCallback(async (options?: { preserveError?: boolean }) => {
    const effectiveDraftId = String(draftId || consultStorage.getDraftId() || "").trim();
    if (!effectiveDraftId) return;

    const preserveError = Boolean(options?.preserveError);
    if (!preserveError) {
      setDraftError(null);
    }
    setDraftSyncing(true);
    try {
      const res = await apiClient.get("/api/intake-consult/draft", {
        params: { draft_id: effectiveDraftId },
        timeout: 15000,
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

        const lastBusiness = lastDraftBusinessRef.current;

        const currentName = String(formApi.getValues("businessName") || "").trim();
        const currentAddress = String(formApi.getValues("address") || "").trim();
        const currentStartDate = String(formApi.getValues("businessStartDate") || "").trim();

        const canSyncName = !currentName || currentName === String(lastBusiness.name || "").trim();
        const canSyncAddress =
          !currentAddress || currentAddress === String(lastBusiness.address || "").trim();

        if (nextBusinessName && nextBusinessName !== currentName && canSyncName && !nameFocused) {
          formApi.setValue("businessName", nextBusinessName, { shouldDirty: false });
        }
        const backendAddressChanged = Boolean(nextAddress && nextAddress !== String(lastBusiness.address || "").trim());
        if (nextAddress && nextAddress !== currentAddress && canSyncAddress && !addressFocused) {
          formApi.setValue("address", nextAddress, { shouldDirty: false });
        }
        if (nextStartDate && nextStartDate !== currentStartDate) {
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

        if (nextBusinessName && canSyncName) consultStorage.setBusinessName(nextBusinessName);
        if (nextAddress && canSyncAddress) consultStorage.setAddress(nextAddress);
        if (nextStartDate) consultStorage.setBusinessStartDate(nextStartDate);
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
    } catch (err) {
      setDraftError(err instanceof Error ? err.message : String(err));
    } finally {
      setDraftSyncing(false);
    }
  }, [draftId, setConsultDone]);

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
    if (!planStarted) return;
    const effectiveDraftId = String(draftId || consultStorage.getDraftId() || "").trim();
    if (effectiveDraftId) return;
    void createSession();
  }, [createSession, draftId, planStarted]);

  useEffect(() => {
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
  }, [form, planStarted]);

  useEffect(() => {
    if (!planStarted) return;
    if (!draftId && !consultStorage.getDraftId()) return;
    void refreshDraft();
  }, [draftId, planStarted, refreshDraft]);

  useEffect(() => {
    if (!planStarted) return;
    const raw = String(businessName || "").trim();
    if (raw) consultStorage.setBusinessName(raw);
  }, [businessName, planStarted]);

  useEffect(() => {
    if (!planStarted) return;
    const raw = String(address || "").trim();
    if (raw) consultStorage.setAddress(raw);
  }, [address, planStarted]);

  useEffect(() => {
    if (!planStarted) return;
    const raw = String(businessStartDate || "").trim();
    if (raw) consultStorage.setBusinessStartDate(raw);
  }, [businessStartDate, planStarted]);

  useEffect(() => {
    if (!planStarted) return;
    const street = String(addressStreet || "").trim();
    const city = String(addressCity || "").trim();
    const state = String(addressState || "").trim();
    const zip = String(addressZip || "").trim();
    const country = String(addressCountry || "").trim();
    if (!street || !city || !state || !zip || !country) return;
    consultStorage.setAddressParts({ street, city, state, zip, country });
  }, [addressCity, addressCountry, addressState, addressStreet, addressZip, planStarted]);

  const syncEligibilityRef = useRef({
    planStarted: false,
    hasDraft: false,
    busy: false,
  });
  useEffect(() => {
    syncEligibilityRef.current = {
      planStarted,
      hasDraft: Boolean(draftId || consultStorage.getDraftId()),
      busy: Boolean(loading || sending || draftSyncing),
    };
  }, [draftId, draftSyncing, loading, planStarted, sending]);

  const syncNowRef = useRef<() => void>(() => {});
  useEffect(() => {
    syncNowRef.current = () => {
      void syncNow({ preserveError: true });
    };
  }, [syncNow]);

  useEffect(() => {
    if (!planStarted) return;

    const maybeSync = () => {
      const state = syncEligibilityRef.current;
      if (!state.planStarted || !state.hasDraft || state.busy) return;
      const now = Date.now();
      if (now - lastAutoSyncAtRef.current < 4000) return;
      lastAutoSyncAtRef.current = now;
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
  }, [planStarted]);

  useEffect(() => {
    scrollToBottom();
  }, [messages, scrollToBottom]);

  async function startConsultIfNeeded() {
    const effectiveDraftId = String(draftId || consultStorage.getDraftId() || "").trim();
    if (!effectiveDraftId) return;
    if (!detailsCompleteForChat) return;
    if (messages.length > 0) return;

    setSending(true);
    setDraftError(null);
    try {
      const startDatePayload = String(businessStartDate || consultStorage.getBusinessStartDate() || "").trim();
      const res = await apiClient.post(
        "/api/intake-consult",
        {
          draft_id: effectiveDraftId,
          client_id: clientId || undefined,
          message: "",
          business_name: String(businessName || "").trim(),
          address: String(address || "").trim(),
          business_start_date: startDatePayload || undefined,
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

    setSending(true);
    setDraftError(null);
    try {
      const startDatePayload = String(businessStartDate || consultStorage.getBusinessStartDate() || "").trim();
      const res = await apiClient.post(
        "/api/intake-consult",
        {
          draft_id: effectiveDraftId,
          client_id: clientId || undefined,
          message: msg,
          business_name: String(businessName || "").trim(),
          address: String(address || "").trim(),
          business_start_date: startDatePayload || undefined,
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
      await syncNow();
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
  const canReconnect = Boolean(planStarted && syncHasError && !syncInProgress);
  const syncLabel = syncInProgress ? "Updating..." : syncHasError ? "Reconnect" : "Up to date";

  const modelCards = useMemo(() => {
    const cards = sharedContext?.model_cards;
    if (!cards || typeof cards !== "object") return null;
    return cards as Record<string, ModelCard>;
  }, [sharedContext]);

  const modelProposals = useMemo(() => {
    const raw = (modelCards as any)?.proposals;
    if (!raw) return [];
    try {
      const parsed = typeof raw === "string" ? JSON.parse(raw) : raw;
      if (!Array.isArray(parsed)) return [];
      return parsed
        .filter((p) => p && typeof p === "object")
        .map((p: any) => ({
          id: String(p.id || "").trim(),
          model: String(p.model || "").trim(),
          title: p.title ? String(p.title) : undefined,
          lob_key: p.lob_key == null ? null : String(p.lob_key || "").trim() || null,
          lob_name: p.lob_name == null ? null : String(p.lob_name || "").trim() || null,
          updates: Array.isArray(p.updates) ? p.updates : [],
          derived: Array.isArray(p.derived) ? p.derived : [],
          created_at_ms: typeof p.created_at_ms === "number" ? p.created_at_ms : undefined,
        }))
        .filter((p: ModelCardProposal) => Boolean(p.id && p.model));
    } catch {
      return [];
    }
  }, [modelCards]);

  const modelCardEntries = useMemo(() => {
    if (!modelCards) return [];
    const order: Array<{ key: string; label: string }> = [
      { key: "pricing", label: "Pricing" },
      { key: "marketing", label: "Marketing" },
      { key: "headcount", label: "Headcount" },
      { key: "fulfillment", label: "Fulfillment" },
      { key: "ops_concept", label: "Operating concept" },
    ];

    const entries: Array<{
      entryKey: string;
      modelKey: string;
      label: string;
      lobKey: string;
      drivers: Record<string, ModelDriverValue>;
      derived: Record<string, { value?: any; unit?: string | null; time_basis?: string | null; derivation?: string | null }>;
    }> = [];

    const normalizeDrivers = (obj: any) =>
      obj && typeof obj === "object" ? (obj as Record<string, ModelDriverValue>) : {};
    const normalizeDerived = (obj: any) =>
      obj && typeof obj === "object"
        ? (obj as Record<string, { value?: any; unit?: string | null; time_basis?: string | null; derivation?: string | null }>)
        : {};

    for (const model of order) {
      const card = (modelCards as any)[model.key] as ModelCard | undefined;
      if (!card) continue;
      const lobs = Array.isArray(card.lobs) ? card.lobs : null;
      if (lobs && lobs.length) {
        const nonCompany = lobs.filter((l) => String(l?.lob_key || "") !== "company_total");
        const company = lobs.find((l) => String(l?.lob_key || "") === "company_total") || null;

        for (const lob of nonCompany) {
          const lobKey = String(lob?.lob_key || "").trim();
          if (!lobKey) continue;
          const drivers = normalizeDrivers((lob as any)?.drivers);
          const derived = normalizeDerived((lob as any)?.derived);
          if (!Object.keys(drivers).length && !Object.keys(derived).length) continue;
          const lobLabel = String((lob as any)?.lob_name || "").trim() || lobKey;
          entries.push({
            entryKey: `${model.key}:${lobKey}`,
            modelKey: model.key,
            label: `${model.label} (${lobLabel})`,
            lobKey,
            drivers,
            derived,
          });
        }

        if (company && !nonCompany.length) {
          const drivers = normalizeDrivers((company as any)?.drivers);
          const derived = normalizeDerived((company as any)?.derived);
          if (Object.keys(drivers).length || Object.keys(derived).length) {
            entries.push({
              entryKey: `${model.key}:company_total`,
              modelKey: model.key,
              label: model.label,
              lobKey: "company_total",
              drivers,
              derived,
            });
          }
        }
      } else {
        const drivers = normalizeDrivers((card as any)?.drivers);
        const derived = normalizeDerived((card as any)?.derived);
        if (!Object.keys(drivers).length && !Object.keys(derived).length) continue;
        entries.push({
          entryKey: `${model.key}:company_total`,
          modelKey: model.key,
          label: model.label,
          lobKey: "company_total",
          drivers,
          derived,
        });
      }
    }

    return entries;
  }, [modelCards]);

  const openDriverEditor = useCallback((model: string, lobKey: string, key: string, driver: ModelDriverValue) => {
    setEditingDriver({
      model,
      lobKey: lobKey || "company_total",
      key,
      value: driver?.value == null ? "" : String(driver.value),
      unit: driver?.unit ? String(driver.unit) : "",
      timeBasis: driver?.time_basis ? String(driver.time_basis) : "",
      rationale: driver?.rationale ? String(driver.rationale) : "",
    });
  }, []);

  const cancelDriverEditor = useCallback(() => setEditingDriver(null), []);

  const submitDriverEdit = useCallback(async () => {
    const effectiveDraftId = String(draftId || consultStorage.getDraftId() || "").trim();
    if (!effectiveDraftId) {
      setDraftError("Missing draft id. Reload and start the intake again.");
      return;
    }
    if (!editingDriver) return;

    setModelSaving(true);
    setDraftError(null);
    try {
      const res = await apiClient.post(
        "/api/intake-consult/model-cards",
        {
          draft_id: effectiveDraftId,
          action: "edit",
          model: editingDriver.model,
          lob_key: editingDriver.lobKey,
          updates: [
            {
              key: editingDriver.key,
              value: editingDriver.value,
              unit: editingDriver.unit || null,
              time_basis: editingDriver.timeBasis || null,
              rationale: editingDriver.rationale || null,
            },
          ],
          derived: [],
          note: "ui_edit",
        },
        { validateStatus: () => true, headers: { "Content-Type": "application/json" } }
      );
      if (res.status < 200 || res.status >= 300) {
        const body: any = res.data;
        throw new Error(
          body && typeof body === "object" && body.detail
            ? String(body.detail)
            : `Model update error: ${res.status} ${res.statusText}`
        );
      }
      setEditingDriver(null);
      await syncNow();
      window.setTimeout(() => chatInputRef.current?.focus(), 0);
    } catch (err) {
      setDraftError(err instanceof Error ? err.message : String(err));
      await syncNow({ preserveError: true });
    } finally {
      setModelSaving(false);
    }
  }, [draftId, editingDriver, syncNow]);

  const acceptProposal = useCallback(
    async (proposal: ModelCardProposal) => {
      const effectiveDraftId = String(draftId || consultStorage.getDraftId() || "").trim();
      if (!effectiveDraftId) {
        setDraftError("Missing draft id. Reload and start the intake again.");
        return;
      }
      setModelSaving(true);
      setDraftError(null);
      try {
        const res = await apiClient.post(
          "/api/intake-consult/model-cards",
          {
            draft_id: effectiveDraftId,
            action: "accept",
            model: proposal.model,
            lob_key: proposal.lob_key || "company_total",
            lob_name: proposal.lob_name || null,
            updates: proposal.updates || [],
            derived: proposal.derived || [],
            proposal_id: proposal.id,
            note: "ui_accept",
          },
          { validateStatus: () => true, headers: { "Content-Type": "application/json" } }
        );
        if (res.status < 200 || res.status >= 300) {
          const body: any = res.data;
          throw new Error(
            body && typeof body === "object" && body.detail
              ? String(body.detail)
              : `Model accept error: ${res.status} ${res.statusText}`
          );
        }
        await syncNow();
        window.setTimeout(() => chatInputRef.current?.focus(), 0);
      } catch (err) {
        setDraftError(err instanceof Error ? err.message : String(err));
        await syncNow({ preserveError: true });
      } finally {
        setModelSaving(false);
      }
    },
    [draftId, syncNow]
  );

  const openProposalEditor = useCallback((proposal: ModelCardProposal) => {
    const updates = proposal.updates || [];
    const monthly = updates.find((u) => String(u.key) === "monthly_marketing_budget");
    const channels = updates.find((u) => String(u.key) === "primary_channels");
    setEditingProposal({
      proposalId: proposal.id,
      model: proposal.model,
      lobKey: proposal.lob_key || "company_total",
      lobName: proposal.lob_name ? String(proposal.lob_name) : "",
      monthlyBudget: monthly?.value == null ? "" : String(monthly.value),
      primaryChannels: channels?.value == null ? "" : String(channels.value),
      rationale: monthly?.rationale ? String(monthly.rationale) : "",
    });
  }, []);

  const cancelProposalEditor = useCallback(() => setEditingProposal(null), []);

  const submitProposalEdit = useCallback(async () => {
    const effectiveDraftId = String(draftId || consultStorage.getDraftId() || "").trim();
    if (!effectiveDraftId) {
      setDraftError("Missing draft id. Reload and start the intake again.");
      return;
    }
    if (!editingProposal) return;

    const monthlyRaw = String(editingProposal.monthlyBudget || "").trim();
    const monthly = Number(monthlyRaw.replace(/[$,]/g, ""));
    if (!Number.isFinite(monthly) || monthly < 0) {
      setDraftError("Monthly marketing budget must be a valid non-negative number.");
      return;
    }

    const annual = monthly * 12;

    setModelSaving(true);
    setDraftError(null);
    try {
      const res = await apiClient.post(
        "/api/intake-consult/model-cards",
          {
            draft_id: effectiveDraftId,
            action: "accept",
            model: editingProposal.model,
            lob_key: editingProposal.lobKey,
            lob_name: editingProposal.lobName || null,
            updates: [
              {
                key: "monthly_marketing_budget",
                value: monthly,
                unit: "USD",
              time_basis: "month",
              rationale: editingProposal.rationale || null,
            },
            {
              key: "primary_channels",
              value: editingProposal.primaryChannels || null,
              unit: null,
              time_basis: null,
              rationale: "Client-edited.",
            },
          ],
          derived: [
            {
              key: "year1_marketing_spend",
              value: annual,
              unit: "USD",
              time_basis: "year",
                derivation: "monthly_marketing_budget x 12",
            },
          ],
          proposal_id: editingProposal.proposalId,
          note: "ui_edit_accept",
        },
        { validateStatus: () => true, headers: { "Content-Type": "application/json" } }
      );
      if (res.status < 200 || res.status >= 300) {
        const body: any = res.data;
        throw new Error(
          body && typeof body === "object" && body.detail
            ? String(body.detail)
            : `Model update error: ${res.status} ${res.statusText}`
        );
      }
      setEditingProposal(null);
      await syncNow();
      window.setTimeout(() => chatInputRef.current?.focus(), 0);
    } catch (err) {
      setDraftError(err instanceof Error ? err.message : String(err));
      await syncNow({ preserveError: true });
    } finally {
      setModelSaving(false);
    }
  }, [draftId, editingProposal, syncNow]);

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
                      <span className="mx-1 text-slate-700">{">"}</span>
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
                  />
                </FormControl>
                <FormMessage>{form.formState.errors.businessName?.message}</FormMessage>
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
                : "Enter your business name and full address to begin."}
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

        {modelProposals.length || modelCardEntries.length ? (
          <div className="space-y-2 rounded-md border border-slate-800/80 bg-slate-950/40 p-3">
            <div className="flex items-center justify-between gap-2">
              <div className="text-xs text-slate-200">Model cards (drivers)</div>
              <div className="text-[11px] text-slate-500">
                {modelSaving ? "Saving..." : "Edit any driver to update the model immediately."}
              </div>
            </div>

            {modelProposals.length ? (
              <div className="space-y-2">
                <div className="text-[11px] text-slate-400">Pending proposals</div>
                {modelProposals.map((p) => {
                  const title = p.title || `${p.model} proposal`;
                  const lobLabel =
                    p.lob_name || p.lob_key ? String(p.lob_name || p.lob_key || "").trim() : "";
                  const monthly = (p.updates || []).find((u) => String(u.key) === "monthly_marketing_budget");
                  const annual = (p.derived || []).find((d) => String(d.key) === "year1_marketing_spend");
                  return (
                    <div key={p.id} className="rounded-md border border-slate-800/70 bg-slate-950/40 p-3">
                      <div className="flex flex-wrap items-start justify-between gap-2">
                        <div className="min-w-0">
                          <div className="text-xs text-slate-200">
                            {title}
                            {lobLabel ? <span className="text-slate-500">{` - ${lobLabel}`}</span> : null}
                          </div>
                          <div className="mt-1 text-[11px] text-slate-400">
                            {monthly?.value != null ? `Monthly: $${String(monthly.value)}` : null}
                            {annual?.value != null ? ` | Year 1: $${String(annual.value)}` : null}
                          </div>
                        </div>
                        <div className="flex items-center gap-2">
                          <Button
                            type="button"
                            size="sm"
                            variant="secondary"
                            disabled={modelSaving}
                            onClick={() => openProposalEditor(p)}
                          >
                            Edit
                          </Button>
                          <Button type="button" size="sm" disabled={modelSaving} onClick={() => void acceptProposal(p)}>
                            Accept
                          </Button>
                        </div>
                      </div>

                      {editingProposal?.proposalId === p.id ? (
                        <div className="mt-3 grid gap-2 md:grid-cols-3">
                          <Input
                            value={editingProposal.monthlyBudget}
                            onChange={(e) =>
                              setEditingProposal((prev) =>
                                prev ? { ...prev, monthlyBudget: e.target.value } : prev
                              )
                            }
                            placeholder="Monthly marketing budget (USD)"
                            disabled={modelSaving}
                          />
                          <Input
                            value={editingProposal.primaryChannels}
                            onChange={(e) =>
                              setEditingProposal((prev) =>
                                prev ? { ...prev, primaryChannels: e.target.value } : prev
                              )
                            }
                            placeholder="Primary channels"
                            disabled={modelSaving}
                          />
                          <div className="flex items-center justify-end gap-2">
                            <Button
                              type="button"
                              size="sm"
                              variant="secondary"
                              disabled={modelSaving}
                              onClick={cancelProposalEditor}
                            >
                              Cancel
                            </Button>
                            <Button type="button" size="sm" disabled={modelSaving} onClick={() => void submitProposalEdit()}>
                              Save & Accept
                            </Button>
                          </div>
                          <div className="md:col-span-3">
                            <Input
                              value={editingProposal.rationale}
                              onChange={(e) =>
                                setEditingProposal((prev) => (prev ? { ...prev, rationale: e.target.value } : prev))
                              }
                              placeholder="Rationale (optional)"
                              disabled={modelSaving}
                            />
                          </div>
                        </div>
                      ) : null}
                    </div>
                  );
                })}
              </div>
            ) : null}

            {modelCardEntries.map((entry) => {
              const modelKey = entry.modelKey;
              const lobKey = entry.lobKey;
              const label = entry.label;
              const drivers = entry.drivers || {};
              const derived = entry.derived || {};
              const driverKeys = Object.keys(drivers);
              const derivedKeys = Object.keys(derived);

              return (
                <div
                  key={entry.entryKey}
                  className="rounded-md border border-slate-800/70 bg-slate-950/40 px-3 py-2"
                  data-model-card={modelKey}
                  data-lob-key={lobKey}
                >
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="text-xs text-slate-200">{label}</div>
                    <div className="text-[11px] text-slate-500">
                      {driverKeys.length} driver{driverKeys.length === 1 ? "" : "s"}
                      {derivedKeys.length ? ` | ${derivedKeys.length} derived` : ""}
                    </div>
                  </div>

                  <div className="mt-2 space-y-2">
                    {driverKeys.map((driverKey) => {
                      const driver = drivers[driverKey] || {};
                      const displayValue = driver.value == null ? "" : String(driver.value);
                      const suffix = [driver.unit, driver.time_basis].filter(Boolean).join(" / ");
                      const isEditing =
                        Boolean(editingDriver) &&
                        editingDriver?.model === modelKey &&
                        editingDriver?.lobKey === lobKey &&
                        editingDriver?.key === driverKey;

                      return (
                        <div key={driverKey} className="rounded-md border border-slate-800/60 bg-slate-950/30 p-2">
                          <div className="flex items-start justify-between gap-2">
                            <div className="min-w-0">
                              <div className="truncate text-[11px] text-slate-400">{driverKey}</div>
                              <div className="truncate text-xs text-slate-200">
                                {displayValue || <span className="text-slate-500">(empty)</span>}
                                {suffix ? <span className="text-slate-500">{"  "}({suffix})</span> : null}
                              </div>
                              {driver.rationale ? (
                                <div className="mt-1 text-[11px] text-slate-400 line-clamp-2">
                                  {String(driver.rationale)}
                                </div>
                              ) : null}
                            </div>
                            <Button
                              type="button"
                              size="sm"
                              variant="secondary"
                              disabled={modelSaving}
                              onClick={() => openDriverEditor(modelKey, lobKey, driverKey, driver)}
                            >
                              Edit
                            </Button>
                          </div>

                          {isEditing ? (
                            <div className="mt-2 grid gap-2 md:grid-cols-4">
                              <Input
                                value={editingDriver?.value ?? ""}
                                onChange={(e) =>
                                  setEditingDriver((prev) => (prev ? { ...prev, value: e.target.value } : prev))
                                }
                                placeholder="Value"
                                disabled={modelSaving}
                              />
                              <Input
                                value={editingDriver?.unit ?? ""}
                                onChange={(e) =>
                                  setEditingDriver((prev) => (prev ? { ...prev, unit: e.target.value } : prev))
                                }
                                placeholder="Unit (optional)"
                                disabled={modelSaving}
                              />
                              <Input
                                value={editingDriver?.timeBasis ?? ""}
                                onChange={(e) =>
                                  setEditingDriver((prev) => (prev ? { ...prev, timeBasis: e.target.value } : prev))
                                }
                                placeholder="time_basis (optional)"
                                disabled={modelSaving}
                              />
                              <div className="flex items-center justify-end gap-2 md:col-span-1">
                                <Button type="button" size="sm" variant="secondary" disabled={modelSaving} onClick={cancelDriverEditor}>
                                  Cancel
                                </Button>
                                <Button type="button" size="sm" disabled={modelSaving} onClick={() => void submitDriverEdit()}>
                                  Save
                                </Button>
                              </div>
                              <div className="md:col-span-4">
                                <Input
                                  value={editingDriver?.rationale ?? ""}
                                  onChange={(e) =>
                                    setEditingDriver((prev) => (prev ? { ...prev, rationale: e.target.value } : prev))
                                  }
                                  placeholder="Rationale (optional)"
                                  disabled={modelSaving}
                                />
                              </div>
                            </div>
                          ) : null}
                        </div>
                      );
                    })}

                    {derivedKeys.length ? (
                      <div className="rounded-md border border-slate-800/60 bg-slate-950/30 p-2">
                        <div className="text-[11px] text-slate-400">Derived (read-only)</div>
                        <div className="mt-1 space-y-1">
                          {derivedKeys.map((k) => {
                            const d = derived[k] || {};
                            const v = d.value == null ? "" : String(d.value);
                            const suffix = [d.unit, d.time_basis].filter(Boolean).join(" / ");
                            return (
                              <div key={k} className="flex items-start justify-between gap-2 text-xs">
                                <div className="min-w-0 text-slate-400">{k}</div>
                                <div className="text-slate-200">
                                  {v || <span className="text-slate-500">(empty)</span>}
                                  {suffix ? <span className="text-slate-500">{"  "}({suffix})</span> : null}
                                </div>
                              </div>
                            );
                          })}
                        </div>
                      </div>
                    ) : null}
                  </div>
                </div>
              );
            })}
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}
