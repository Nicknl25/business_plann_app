import { ClipboardList } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useFormContext } from "react-hook-form";
import apiClient from "../../apiClient";
import GoogleAddressInput from "../../components/GoogleAddressInput";
import { Button } from "../../components/ui/Button";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/Card";
import {
  FormControl,
  FormField,
  FormItem,
  FormMessage,
} from "../../components/ui/Form";
import HelpTooltip from "../../components/ui/HelpTooltip";
import { Input } from "../../components/ui/Input";
import { TOOLTIP_TEXT } from "../../components/ui/tooltip";
import { consultStorage } from "../flow/consultStorage";
import { decideConfirmation } from "../flow/confirmationIntent";
import { useIntakeFlow } from "../flow/IntakeFlowContext";
import type { IntakeValues } from "../schema";

export default function BusinessOverviewStep() {
  const form = useFormContext<IntakeValues>();
  const businessName = form.watch("businessName");
  const address = form.watch("address");
  const addressStreet = form.watch("addressStreet");
  const addressCity = form.watch("addressCity");
  const addressState = form.watch("addressState");
  const addressZip = form.watch("addressZip");
  const addressCountry = form.watch("addressCountry");
  const businessStartDate = form.watch("businessStartDate");
  const {
    planStarted,
    opsConfirmed,
    setOpsConfirmed,
    setTargetMarketConfirmed,
    setPeopleConfirmed,
    setFinancialsConfirmed,
    editSection,
    setEditSection,
    clientId,
    setClientId,
    draftId,
    setDraftId,
    consultDone,
    setConsultDone,
    setConsultFinal,
    setTargetMarketDone,
    setTargetMarketSummary,
    setPeopleDone,
    setKeyPeopleSummary,
    setFinancialsDone,
    setSubmitError,
    setSubmitSuccess,
    bumpResetCounter,
  } = useIntakeFlow();

  const [consultMessages, setConsultMessages] = useState<
    { role: "user" | "assistant"; content: string }[]
  >([]);
  const [consultInput, setConsultInput] = useState("");
  const [consultLoading, setConsultLoading] = useState(false);
  const [consultError, setConsultError] = useState<string | null>(null);
  const [editConfirmPending, setEditConfirmPending] = useState(false);
  const [opsSetupStage, setOpsSetupStage] = useState<
    "need_business_name" | "need_address" | "need_business_start_date" | "ready"
  >("need_business_name");
  const [addressAccepted, setAddressAccepted] = useState(false);
  const [startDateAccepted, setStartDateAccepted] = useState(false);
  const didAutoStart = useRef(false);
  const cardRef = useRef<HTMLDivElement | null>(null);
  const chatInputRef = useRef<HTMLInputElement | null>(null);
  const addressInputRef = useRef<HTMLInputElement | null>(null);
  const startDateInputRef = useRef<HTMLInputElement | null>(null);
  const chatContainerRef = useRef<HTMLDivElement | null>(null);
  const lastFocusedStage = useRef<string | null>(null);
  const prevMessagesLen = useRef(0);
  const prevLoading = useRef(false);

  const roleLabel = (role: "user" | "assistant") =>
    role === "user" ? "client" : "consultant";

  const awaitingConfirmation = Boolean(consultDone && !opsConfirmed);
  const CONFIRM_PROMPT =
    "Does this look right before we move on to Customers & Positioning?";
  const CLARIFY_PROMPT =
    "Just to confirm - are we good to move on, or is there anything you want to change?";
  const editMode = editSection === "ops";

  function handleConfirmationReply(message: string) {
    const decision = decideConfirmation(message);
    if (decision === "proceed") {
      setOpsConfirmed(true);
      setConsultMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: "Great — let’s move on to Customers & Positioning.",
        },
      ]);
      return;
    }

    if (decision === "clarify") {
      setConsultMessages((prev) => [
        ...prev,
        { role: "assistant", content: CLARIFY_PROMPT },
      ]);
      return;
    }

    setConsultMessages((prev) =>
      prev.filter((m) => !(m.role === "assistant" && m.content === CONFIRM_PROMPT))
    );
    setConsultDone(false);
    setConsultFinal(null);
    void sendConsultMessage(message, { reopen: true, editFinalize: editConfirmPending });
  }

  const hasCompleteAddress =
    Boolean(address && address.trim()) &&
    [addressStreet, addressCity, addressState, addressZip, addressCountry].every(
      (v) => Boolean(v && v.trim())
    );
  const hasBusinessStartDate = Boolean(businessStartDate && businessStartDate.trim());

  useEffect(() => {
    if (!planStarted) return;
    (async () => {
      const storedDraftId = consultStorage.getDraftId();
      const storedClientId = consultStorage.getClientId();
      if (!storedDraftId || !storedClientId) return;

      const storedBusinessName = consultStorage.getBusinessName();
      if (storedBusinessName && !form.getValues("businessName")) {
        form.setValue("businessName", String(storedBusinessName), {
          shouldDirty: true,
          shouldValidate: false,
        });
      }

      const storedAddress = consultStorage.getAddress();
      if (storedAddress && !form.getValues("address")) {
        form.setValue("address", String(storedAddress), {
          shouldDirty: true,
          shouldValidate: false,
        });
      }

      const storedStreet = consultStorage.getAddressStreet();
      if (storedStreet && !form.getValues("addressStreet")) {
        form.setValue("addressStreet", String(storedStreet), {
          shouldDirty: true,
          shouldValidate: false,
        });
      }
      const storedCity = consultStorage.getAddressCity();
      if (storedCity && !form.getValues("addressCity")) {
        form.setValue("addressCity", String(storedCity), {
          shouldDirty: true,
          shouldValidate: false,
        });
      }
      const storedState = consultStorage.getAddressState();
      if (storedState && !form.getValues("addressState")) {
        form.setValue("addressState", String(storedState), {
          shouldDirty: true,
          shouldValidate: false,
        });
      }
      const storedZip = consultStorage.getAddressZip();
      if (storedZip && !form.getValues("addressZip")) {
        form.setValue("addressZip", String(storedZip), {
          shouldDirty: true,
          shouldValidate: false,
        });
      }
      const storedCountry = consultStorage.getAddressCountry();
      if (storedCountry && !form.getValues("addressCountry")) {
        form.setValue("addressCountry", String(storedCountry), {
          shouldDirty: true,
          shouldValidate: false,
        });
      }

      const storedStartDate = consultStorage.getBusinessStartDate();
      if (storedStartDate && !form.getValues("businessStartDate")) {
        form.setValue("businessStartDate", String(storedStartDate), {
          shouldDirty: true,
          shouldValidate: false,
        });
      }

      try {
        const res = await apiClient.get("/api/intake-consult/draft", {
          params: { draft_id: storedDraftId },
          validateStatus: () => true,
        });
        if (res.status < 200 || res.status >= 300) return;

        const body: any = res.data;
        setDraftId(String(body?.draft_id || storedDraftId));
        setClientId(String(body?.client_id || storedClientId));

        const draftStatus = String(body?.draft_status || "");
        if (draftStatus === "submitted") {
          consultStorage.clear();
          return;
        }
        const messagesJson = body?.messages_json;
        let hadServerMessages = false;
        if (messagesJson) {
          try {
            const parsed = JSON.parse(String(messagesJson));
            if (Array.isArray(parsed)) {
              hadServerMessages = parsed.length > 0;
              setConsultMessages(
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
          setConsultDone(true);
          const modelJson = body?.operating_model_json;
          if (modelJson) {
            try {
              setConsultFinal(JSON.parse(String(modelJson)));
            } catch {
              setConsultFinal(null);
            }
          }
          setOpsSetupStage("ready");
          setAddressAccepted(true);
          setStartDateAccepted(true);
          return;
        }

        if (hadServerMessages) {
          setOpsSetupStage("ready");
          setAddressAccepted(true);
          setStartDateAccepted(true);
          return;
        }

        const nameNow = form.getValues("businessName");
        const hasName = Boolean(nameNow && String(nameNow).trim());
        if (!hasName) {
          setOpsSetupStage("need_business_name");
          setAddressAccepted(false);
          setStartDateAccepted(false);
          setConsultMessages((prev) =>
            prev.length
              ? prev
              : [
                  {
                    role: "assistant",
                    content: "To start, what is the name of your business?",
                  },
                ]
          );
          return;
        }

        if (!hasCompleteAddress) {
          setOpsSetupStage("need_address");
          setAddressAccepted(false);
          setStartDateAccepted(false);
          setConsultMessages((prev) =>
            prev.length
              ? prev
              : [
                  {
                    role: "assistant",
                    content:
                      "Thanks. Now select your business address from the suggestions below.",
                  },
                ]
          );
          return;
        }

        const startNow = form.getValues("businessStartDate");
        const hasStart = Boolean(startNow && String(startNow).trim());
        if (!hasStart) {
          setOpsSetupStage("need_business_start_date");
          setAddressAccepted(true);
          setStartDateAccepted(false);
          setConsultMessages((prev) =>
            prev.length
              ? prev
              : [
                  {
                    role: "assistant",
                    content:
                      "Before we begin: when did your business start operating?",
                  },
                ]
          );
          return;
        }

        setOpsSetupStage("need_business_start_date");
        setAddressAccepted(true);
        setStartDateAccepted(true);
      } catch {
        // ignore resume errors
      }
    })();
  }, [
    form,
    hasCompleteAddress,
    planStarted,
    setClientId,
    setConsultDone,
    setConsultFinal,
    setDraftId,
  ]);

  useEffect(() => {
    if (!planStarted) return;
    if (didAutoStart.current) return;
    const storedDraftId = consultStorage.getDraftId();
    const storedClientId = consultStorage.getClientId();
    if (storedDraftId && storedClientId) return;
    if (clientId || draftId) return;
    didAutoStart.current = true;
    void createConsultSession();
  }, [clientId, draftId, planStarted]);

  useEffect(() => {
    if (!planStarted) return;
    if (!clientId) return;
    if (consultLoading) return;
    if (consultDone && opsConfirmed) return;
    if (lastFocusedStage.current === opsSetupStage) return;
    lastFocusedStage.current = opsSetupStage;

    cardRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    window.setTimeout(() => {
      if (opsSetupStage === "need_address") {
        addressInputRef.current?.focus();
        return;
      }
      if (opsSetupStage === "need_business_start_date") {
        startDateInputRef.current?.focus();
        return;
      }
      chatInputRef.current?.focus();
    }, 80);
  }, [clientId, consultDone, consultLoading, opsSetupStage, planStarted]);

  useEffect(() => {
    if (!planStarted) return;
    if (clientId) return;
    cardRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [clientId, planStarted]);

  useEffect(() => {
    if (!planStarted) return;
    if (!clientId) return;
    if (consultDone && opsConfirmed) return;
    if (consultLoading) return;

    const last = consultMessages[consultMessages.length - 1];
    if (!last || last.role !== "assistant") return;

    window.setTimeout(() => {
      if (opsSetupStage === "need_address") {
        addressInputRef.current?.focus();
        return;
      }
      if (opsSetupStage === "need_business_start_date") {
        startDateInputRef.current?.focus();
        return;
      }
      chatInputRef.current?.focus();
    }, 0);
  }, [
    addressInputRef,
    chatInputRef,
    clientId,
    consultDone,
    consultLoading,
    consultMessages,
    opsSetupStage,
    planStarted,
    startDateInputRef,
  ]);

  useEffect(() => {
    if (!planStarted) return;
    const container = chatContainerRef.current;
    if (!container) return;

    const wasLoading = prevLoading.current;
    const isLoading = consultLoading && !consultDone;
    const prevLen = prevMessagesLen.current;

    if (isLoading) {
      container.scrollTop = container.scrollHeight;
    }

    if (consultMessages.length > prevLen) {
      const last = consultMessages[consultMessages.length - 1];
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

    prevMessagesLen.current = consultMessages.length;
    prevLoading.current = isLoading;
  }, [consultDone, consultLoading, consultMessages, planStarted]);

  useEffect(() => {
    if (!planStarted) return;
    if (!awaitingConfirmation) return;
    setConsultMessages((prev) => {
      const already = prev.some(
        (m) => m.role === "assistant" && m.content === CONFIRM_PROMPT
      );
      if (already) return prev;
      return [...prev, { role: "assistant", content: CONFIRM_PROMPT }];
    });
  }, [awaitingConfirmation, planStarted]);

  useEffect(() => {
    if (!planStarted) return;
    if (!opsConfirmed) return;
    setConsultMessages((prev) =>
      prev.filter((m) => !(m.role === "assistant" && m.content === CONFIRM_PROMPT))
    );
    setEditConfirmPending(false);
  }, [opsConfirmed, planStarted]);

  function resetConsultSession() {
    consultStorage.clear();
    form.setValue("businessName", "", { shouldDirty: true, shouldValidate: false });
    form.setValue("address", "", { shouldDirty: true, shouldValidate: false });
    form.setValue("addressStreet", "", { shouldDirty: true, shouldValidate: false });
    form.setValue("addressCity", "", { shouldDirty: true, shouldValidate: false });
    form.setValue("addressState", "", { shouldDirty: true, shouldValidate: false });
    form.setValue("addressZip", "", { shouldDirty: true, shouldValidate: false });
    form.setValue("addressCountry", "", { shouldDirty: true, shouldValidate: false });
    form.setValue("businessStartDate", "", {
      shouldDirty: true,
      shouldValidate: false,
    });
    setClientId(null);
    setDraftId(null);
    setConsultMessages([]);
    setConsultInput("");
    setConsultDone(false);
    setOpsConfirmed(false);
    setConsultFinal(null);
    setConsultError(null);
    setEditConfirmPending(false);
    setEditSection(null);
    setOpsSetupStage("need_business_name");
    setAddressAccepted(false);
    setStartDateAccepted(false);

    setTargetMarketDone(false);
    setTargetMarketConfirmed(false);
    setTargetMarketSummary(null);

    setPeopleDone(false);
    setPeopleConfirmed(false);
    setKeyPeopleSummary(null);

    setFinancialsDone(false);
    setFinancialsConfirmed(false);

    bumpResetCounter();
  }

  async function startConsultConversation(
    nextDraftId: string,
    nextClientId: string
  ): Promise<boolean> {
    setConsultError(null);
    setConsultMessages([]);
    setConsultInput("");
    setConsultDone(false);
    setConsultFinal(null);
    setConsultLoading(true);

    try {
      const ok = await form.trigger([
        "businessName",
        "address",
        "addressStreet",
        "addressCity",
        "addressState",
        "addressZip",
        "addressCountry",
        "businessStartDate",
      ]);
      if (!ok) {
        throw new Error(
          "Please provide your business name, a complete business address (street, city, state, ZIP, country), and a business start date before starting the conversation."
        );
      }

      const {
        businessName,
        address,
        addressStreet,
        addressCity,
        addressState,
        addressZip,
        addressCountry,
      } = form.getValues();

      consultStorage.setBusinessName(String(businessName || "").trim());
      consultStorage.setAddress(String(address || "").trim());
      consultStorage.setAddressParts({
        street: String(addressStreet || "").trim(),
        city: String(addressCity || "").trim(),
        state: String(addressState || "").trim(),
        zip: String(addressZip || "").trim(),
        country: String(addressCountry || "").trim(),
      });
      consultStorage.setBusinessStartDate(
        String(form.getValues("businessStartDate") || "").trim()
      );

      const res = await apiClient.post(
        "/api/intake-consult",
        {
          draft_id: nextDraftId,
          client_id: nextClientId,
          business_name: businessName,
          address,
          address_street: addressStreet,
          address_city: addressCity,
          address_state: addressState,
          address_zip: addressZip,
          address_country: addressCountry,
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
            : `Consult error: ${res.status} ${res.statusText}`
        );
      }

      const body: any = res.data;
      setConsultDone(Boolean(body?.done));
      if (body?.done) {
        const rawModel = body?.operating_model_json;
        if (rawModel) {
          try {
            setConsultFinal(JSON.parse(String(rawModel)));
          } catch {
            setConsultFinal(null);
          }
        } else {
          setConsultFinal(null);
        }
      }
      setConsultMessages(() => {
        const next = [
          { role: "assistant" as const, content: String(body?.assistant_message || "") },
        ];
        if (body?.done) {
          next.push({ role: "assistant" as const, content: CONFIRM_PROMPT });
        }
        return next;
      });
      setOpsSetupStage("ready");
      return true;
    } catch (error) {
      setConsultError(error instanceof Error ? error.message : String(error));
      return false;
    } finally {
      setConsultLoading(false);
    }
  }

  async function createConsultSession() {
    setConsultError(null);
    setConsultLoading(true);
    setSubmitError(null);
    setSubmitSuccess(null);

    try {
      resetConsultSession();
      const res = await apiClient.post(
        "/api/intake-consult/session",
        {},
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
            : `Session error: ${res.status} ${res.statusText}`
        );
      }

      const body: any = res.data;
      const nextDraftId = String(body?.draft_id || "").trim();
      const nextClientId = String(body?.client_id || "").trim();
      if (!nextDraftId || !nextClientId) {
        throw new Error("Session did not return draft_id/client_id.");
      }

      consultStorage.set(nextDraftId, nextClientId);
      setDraftId(nextDraftId);
      setClientId(nextClientId);
      setOpsSetupStage("need_business_name");
      setAddressAccepted(false);
      setStartDateAccepted(false);
      setConsultMessages([
        { role: "assistant", content: "To start, what is the name of your business?" },
      ]);
    } catch (error) {
      setConsultError(error instanceof Error ? error.message : String(error));
    } finally {
      setConsultLoading(false);
    }
  }

  async function sendConsultMessage(
    message: string,
    options?: { reopen?: boolean; editFinalize?: boolean }
  ) {
    if (!draftId || !clientId) return;

    setConsultError(null);
    setConsultLoading(true);

    try {
      const {
        businessName,
        address,
        addressStreet,
        addressCity,
        addressState,
        addressZip,
        addressCountry,
      } = form.getValues();
      const res = await apiClient.post(
        "/api/intake-consult",
        {
          draft_id: draftId,
          client_id: clientId,
          message,
          reopen: Boolean(options?.reopen),
          edit_finalize: Boolean(options?.editFinalize),
          business_name: businessName,
          address,
          address_street: addressStreet,
          address_city: addressCity,
          address_state: addressState,
          address_zip: addressZip,
          address_country: addressCountry,
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
            : `Consult error: ${res.status} ${res.statusText}`
        );
      }

      const body: any = res.data;
      setConsultDone(Boolean(body?.done));
      if (body?.done) {
        const rawModel = body?.operating_model_json;
        if (rawModel) {
          try {
            setConsultFinal(JSON.parse(String(rawModel)));
          } catch {
            setConsultFinal(null);
          }
        } else {
          setConsultFinal(null);
        }
      }
      setConsultMessages((prev) => {
        const editFinalize = Boolean(options?.editFinalize) && Boolean(body?.done);
        const base = editFinalize
          ? prev.filter((m) => !(m.role === "assistant" && m.content === CONFIRM_PROMPT))
          : prev;
        const next = [
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
    } catch (error) {
      setConsultError(error instanceof Error ? error.message : String(error));
    } finally {
      setConsultLoading(false);
    }
  }

  async function handleConsultSubmit(rawMessage: string) {
    const msg = String(rawMessage || "").trim();
    if (!msg) return;
    if (consultLoading) return;
    if (consultDone && opsConfirmed) return;

    if (consultDone && !opsConfirmed) {
      setConsultMessages((prev) => [...prev, { role: "user", content: msg }]);
      handleConfirmationReply(msg);
      return;
    }

    if (opsSetupStage === "need_business_name") {
      setConsultMessages((prev) => [...prev, { role: "user", content: msg }]);
      form.setValue("businessName", msg, {
        shouldDirty: true,
        shouldValidate: true,
      });
      const ok = await form.trigger(["businessName"]);
      if (!ok) {
        form.setValue("businessName", "", {
          shouldDirty: true,
          shouldValidate: false,
        });
        setConsultMessages((prev) => [
          ...prev,
          {
            role: "assistant",
            content: "Please enter the full business name (at least 2 characters).",
          },
        ]);
        return;
      }
      consultStorage.setBusinessName(msg);
      setConsultMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: "Thanks. Now select your business address from the suggestions below.",
        },
      ]);
      setOpsSetupStage("need_address");
      return;
    }

    if (opsSetupStage === "ready") {
      setConsultMessages((prev) => [...prev, { role: "user", content: msg }]);
      if (editMode) {
        setEditSection(null);
        setEditConfirmPending(true);
        await sendConsultMessage(msg, { reopen: true, editFinalize: true });
        return;
      }
      await sendConsultMessage(msg);
    }
  }

  useEffect(() => {
    if (opsSetupStage !== "need_address") return;
    if (!draftId || !clientId) return;
    if (!businessName || !businessName.trim()) return;
    if (!hasCompleteAddress) return;
    if (addressAccepted) return;
    if (consultLoading || consultDone) return;

    setAddressAccepted(true);
    consultStorage.setAddress(String(address || "").trim());
    consultStorage.setAddressParts({
      street: String(addressStreet || "").trim(),
      city: String(addressCity || "").trim(),
      state: String(addressState || "").trim(),
      zip: String(addressZip || "").trim(),
      country: String(addressCountry || "").trim(),
    });

    setConsultMessages((prev) => [
      ...prev,
      {
        role: "assistant",
        content: "Thanks. When did your business start operating?",
      },
    ]);
    setOpsSetupStage("need_business_start_date");
  }, [
    address,
    addressAccepted,
    addressCity,
    addressCountry,
    addressState,
    addressStreet,
    addressZip,
    businessName,
    clientId,
    consultDone,
    consultLoading,
    draftId,
    hasCompleteAddress,
    opsSetupStage,
  ]);

  useEffect(() => {
    if (opsSetupStage !== "need_business_start_date") return;
    if (!draftId || !clientId) return;
    if (!businessName || !businessName.trim()) return;
    if (!hasCompleteAddress) return;
    if (!hasBusinessStartDate) return;
    if (startDateAccepted) return;
    if (consultLoading || consultDone) return;

    setStartDateAccepted(true);
    consultStorage.setBusinessStartDate(String(businessStartDate || "").trim());

    (async () => {
      const ok = await startConsultConversation(String(draftId), String(clientId));
      if (!ok) {
        setStartDateAccepted(false);
      }
    })();
  }, [
    businessName,
    businessStartDate,
    clientId,
    consultDone,
    consultLoading,
    draftId,
    hasBusinessStartDate,
    hasCompleteAddress,
    opsSetupStage,
    startDateAccepted,
  ]);

  useEffect(() => {
    if (opsSetupStage !== "need_address") return;
    if (!draftId || !clientId) return;
    if (address && address.trim()) {
      consultStorage.setAddress(String(address).trim());
    }
    if (
      [addressStreet, addressCity, addressState, addressZip, addressCountry].every(
        (v) => Boolean(v && v.trim())
      )
    ) {
      consultStorage.setAddressParts({
        street: String(addressStreet || "").trim(),
        city: String(addressCity || "").trim(),
        state: String(addressState || "").trim(),
        zip: String(addressZip || "").trim(),
        country: String(addressCountry || "").trim(),
      });
    }
  }, [
    address,
    addressCity,
    addressCountry,
    addressState,
    addressStreet,
    addressZip,
    clientId,
    draftId,
    opsSetupStage,
  ]);

  useEffect(() => {
    if (opsSetupStage !== "need_business_start_date") return;
    if (businessStartDate && businessStartDate.trim()) {
      consultStorage.setBusinessStartDate(String(businessStartDate).trim());
    }
  }, [businessStartDate, opsSetupStage]);

  if (!planStarted) {
    return (
      <Card
        id="intake-section-ops"
        ref={cardRef}
        className="border border-slate-800/80 bg-slate-950/90"
      >
        <CardHeader className="border-0 pb-3">
          <CardTitle className="flex items-center gap-2 text-sm">
            <span className="inline-flex h-7 w-7 items-center justify-center rounded-xl bg-sky-500/15 text-sky-300 ring-1 ring-sky-500/40">
              <ClipboardList className="h-3.5 w-3.5" />
            </span>
            Business overview
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3 text-xs text-slate-300">
          <div className="rounded-md border border-slate-800/80 bg-slate-950/60 p-3 text-slate-300">
            We&apos;ll start by capturing your business name, business address, and
            start date, then guide you through an operations consultation to
            understand how the business works.
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
      id="intake-section-ops"
      ref={cardRef}
      className="border border-slate-800/80 bg-slate-950/90"
    >
      <CardHeader className="border-0 pb-3">
        <CardTitle className="flex items-center gap-2 text-sm">
          <span className="inline-flex h-7 w-7 items-center justify-center rounded-xl bg-sky-500/15 text-sky-300 ring-1 ring-sky-500/40">
            <ClipboardList className="h-3.5 w-3.5" />
          </span>
          Business overview
        </CardTitle>
      </CardHeader>
      <CardContent className="grid gap-4 pt-1 md:grid-cols-2">
        <div className="col-span-2 space-y-3">
            {businessName || address ? (
              <div className="rounded-md border border-slate-800/80 bg-slate-950/60 p-3 text-xs text-slate-300">
                <div>
                  <span className="text-slate-400">Business name:</span>{" "}
                  {businessName || "\u2014"}
                </div>
                <div className="mt-1">
                  <span className="text-slate-400">Business address:</span>{" "}
                  {address || "\u2014"}
                </div>
                <div className="mt-1">
                  <span className="text-slate-400">Business start date:</span>{" "}
                  {businessStartDate || "\u2014"}
                </div>
              </div>
            ) : null}

            {!clientId ? (
              <div className="text-xs text-slate-400">
                {consultLoading ? "Starting your plan..." : "Preparing your plan..."}
                {consultError ? (
                  <div className="mt-2 rounded-md border border-rose-500/30 bg-rose-500/10 p-3 text-xs text-rose-200">
                    {consultError}
                  </div>
                ) : null}
              </div>
            ) : (
              <div className="space-y-2">
                {consultError ? (
                  <div className="rounded-md border border-rose-500/30 bg-rose-500/10 p-3 text-xs text-rose-200">
                    {consultError}
                  </div>
                ) : null}

                <div
                  ref={chatContainerRef}
                  className="max-h-64 space-y-2 overflow-auto rounded-md border border-slate-800/80 bg-slate-950/60 p-3 text-xs text-slate-200"
                >
                  {consultMessages.length === 0 ? (
                    <div className="text-slate-400">
                      {consultLoading
                        ? "Starting consultant conversation..."
                        : "Conversation will appear here."}
                    </div>
                  ) : (
                    <>
                      {consultMessages.map((m, idx) => (
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
                      {consultLoading && !consultDone ? (
                        <div
                          className="whitespace-pre-wrap rounded-md border border-slate-700/60 bg-slate-900/40 px-3 py-2 text-slate-400 italic animate-pulse"
                          data-msg-role="assistant"
                        >
                          <span className="text-slate-400">consultant:</span>{" "}
                          Consultant is generating a response...
                        </div>
                      ) : null}
                    </>
                  )}
                </div>

                {opsSetupStage === "need_address" ? (
                  <div className="space-y-2 rounded-md border border-slate-800/80 bg-slate-950/60 p-3">
                    <div className="text-xs text-slate-300">
                      Business address{" "}
                      <HelpTooltip
                        fieldName="address"
                        text={TOOLTIP_TEXT.businessAddress}
                      />
                    </div>
                    <FormField name="address" control={form.control}>
                      {({ ref, ...field }) => (
                        <FormItem>
                          <FormControl>
                            <GoogleAddressInput
                              {...field}
                              ref={(el) => {
                                addressInputRef.current = el;
                                ref(el);
                              }}
                              placeholder="Start typing and select your full address from suggestions"
                            />
                          </FormControl>
                          <FormMessage>
                            {form.formState.errors.address?.message}
                          </FormMessage>
                        </FormItem>
                      )}
                    </FormField>
                    <div className="text-[11px] text-slate-400">
                      Select a full address (street, city, state, ZIP, country) so the consultant can tailor questions to your location.
                    </div>
                    {consultError && addressAccepted && !consultLoading ? (
                      <div className="pt-1">
                        <Button
                          type="button"
                          size="sm"
                          variant="outline"
                          onClick={() => {
                            setConsultError(null);
                            setAddressAccepted(false);
                          }}
                        >
                          Retry starting consultation
                        </Button>
                      </div>
                    ) : null}
                  </div>
                ) : null}

                {opsSetupStage === "need_business_start_date" ? (
                  <div className="space-y-2 rounded-md border border-slate-800/80 bg-slate-950/60 p-3">
                    <div className="text-xs text-slate-300">Business start date</div>
                    <FormField name="businessStartDate" control={form.control}>
                      {(field) => (
                        <FormItem>
                          <FormControl>
                            <Input
                              ref={startDateInputRef}
                              type="date"
                              value={(field.value as string) || ""}
                              onChange={(event) => field.onChange(event.target.value)}
                            />
                          </FormControl>
                          <FormMessage>
                            {form.formState.errors.businessStartDate?.message}
                          </FormMessage>
                        </FormItem>
                      )}
                    </FormField>
                    <div className="text-[11px] text-slate-400">
                      Use the date the business began operating (or your best estimate).
                    </div>
                  </div>
                ) : null}

                {opsConfirmed ? (
                  <div className="rounded-md border border-emerald-500/30 bg-emerald-500/10 p-3 text-xs text-emerald-200">
                    Business overview confirmed.
                  </div>
                ) : consultDone ? (
                  <div className="text-xs text-slate-400">
                    Review the summary above and confirm when it looks right so we
                    can continue.
                  </div>
                ) : (
                  <div className="text-xs text-slate-400">
                    Complete this consultation to continue.
                  </div>
                )}

                <div className="flex gap-2">
                  <Input
                    ref={chatInputRef}
                    value={consultInput}
                    onChange={(e) => setConsultInput(e.target.value)}
                    onKeyDown={async (e) => {
                      if (e.key === "Enter") {
                        e.preventDefault();
                        if (consultLoading || (consultDone && opsConfirmed)) return;
                        if (
                          opsSetupStage === "need_address" ||
                          opsSetupStage === "need_business_start_date"
                        )
                          return;
                        const msg = consultInput.trim();
                        if (!msg) return;
                        setConsultInput("");
                        await handleConsultSubmit(msg);
                      }
                    }}
                    placeholder={
                      awaitingConfirmation
                        ? "Reply to continue..."
                        : consultDone
                        ? "Conversation completed."
                        : opsSetupStage === "need_business_name"
                          ? "Enter your business name..."
                          : "Reply to the consultant..."
                    }
                    disabled={
                      consultLoading ||
                      (consultDone && opsConfirmed) ||
                      opsSetupStage === "need_address" ||
                      opsSetupStage === "need_business_start_date"
                    }
                  />
                  <Button
                    type="button"
                    size="sm"
                    disabled={
                      consultLoading ||
                      (consultDone && opsConfirmed) ||
                      opsSetupStage === "need_address" ||
                      opsSetupStage === "need_business_start_date" ||
                      !consultInput.trim()
                    }
                    onClick={async () => {
                      const msg = consultInput.trim();
                      if (!msg) return;
                      setConsultInput("");
                      await handleConsultSubmit(msg);
                    }}
                  >
                    Send
                  </Button>
                </div>
              </div>
            )}
        </div>
      </CardContent>
    </Card>
  );
}
