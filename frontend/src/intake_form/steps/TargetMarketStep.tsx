import { useEffect, useRef, useState } from "react";
import { useFormContext } from "react-hook-form";
import apiClient from "../../apiClient";
import { Button } from "../../components/ui/Button";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/Card";
import { Input } from "../../components/ui/Input";
import { useIntakeFlow } from "../flow/IntakeFlowContext";
import type { IntakeValues } from "../schema";

export default function TargetMarketStep() {
  const form = useFormContext<IntakeValues>();
  const {
    planStarted,
    draftId,
    opsConfirmed,
    editSection,
    setEditSection,
    targetMarketDone,
    setTargetMarketDone,
    setTargetMarketSummary,
    targetMarketConfirmed,
    setTargetMarketConfirmed,
    resetCounter,
  } = useIntakeFlow();

  const [targetMarketMessages, setTargetMarketMessages] = useState<
    { role: "user" | "assistant"; content: string }[]
  >([]);
  const [targetMarketInput, setTargetMarketInput] = useState("");
  const [targetMarketLoading, setTargetMarketLoading] = useState(false);
  const [targetMarketError, setTargetMarketError] = useState<string | null>(null);
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

  useEffect(() => {
    setTargetMarketMessages([]);
    setTargetMarketInput("");
    setTargetMarketLoading(false);
    setTargetMarketError(null);
    didAutoStart.current = false;
    setResumeChecked(false);
  }, [resetCounter]);

  const editMode = editSection === "targetMarket";
  const awaitingConfirmation = Boolean(targetMarketDone && !targetMarketConfirmed);
  const isActive = Boolean(editMode || (opsConfirmed && !targetMarketConfirmed));
  const isUnlocked = Boolean(opsConfirmed);

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
    if (targetMarketLoading) return;
    if (!chatInputRef.current) return;
    const last = targetMarketMessages[targetMarketMessages.length - 1];
    if (!last || last.role !== "assistant") return;
    chatInputRef.current.focus();
  }, [isActive, planStarted, targetMarketLoading, targetMarketMessages]);

  useEffect(() => {
    if (!planStarted) return;
    const container = chatContainerRef.current;
    if (!container) return;

    const wasLoading = prevLoading.current;
    const isLoading = targetMarketLoading;
    const prevLen = prevMessagesLen.current;

    if (isLoading) {
      container.scrollTop = container.scrollHeight;
    }

    if (targetMarketMessages.length > prevLen) {
      const last = targetMarketMessages[targetMarketMessages.length - 1];
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

    prevMessagesLen.current = targetMarketMessages.length;
    prevLoading.current = isLoading;
  }, [planStarted, targetMarketDone, targetMarketLoading, targetMarketMessages]);

  useEffect(() => {
    if (!planStarted) return;
    if (!resumeChecked) return;
    if (!isActive) return;
    if (targetMarketDone) return;
    if (targetMarketLoading) return;
    if (targetMarketMessages.length > 0) return;
    if (didAutoStart.current) return;
    if (!draftId) return;
    didAutoStart.current = true;
    void startTargetMarketConversation();
  }, [
    draftId,
    isActive,
    planStarted,
    resumeChecked,
    targetMarketDone,
    targetMarketLoading,
    targetMarketMessages.length,
  ]);

  useEffect(() => {
    if (!planStarted) return;
    if (!draftId) return;
    (async () => {
      try {
        const res = await apiClient.get("/api/target-market/draft", {
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
                setTargetMarketMessages(
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
            setTargetMarketDone(true);
            const tmJson = body?.target_market_json;
            if (tmJson) {
              try {
                const parsed = JSON.parse(String(tmJson));
                if (parsed && typeof parsed === "object") {
                  setTargetMarketSummary(
                    String((parsed as any).target_market_summary || "").trim() ||
                      null
                  );
                }
              } catch {
                setTargetMarketSummary(null);
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
  }, [draftId, planStarted, setTargetMarketDone, setTargetMarketSummary]);

  async function startTargetMarketConversation(preface?: string) {
    if (!draftId) {
      setTargetMarketError("Missing draft id. Reload and start Ops first.");
      return;
    }
    setTargetMarketError(null);
    setTargetMarketLoading(true);
    setTargetMarketMessages(preface ? [{ role: "assistant", content: preface }] : []);
    setTargetMarketInput("");
    setTargetMarketDone(false);
    setTargetMarketSummary(null);

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

      const sessionRes = await apiClient.post(
        "/api/target-market/session",
        { draft_id: draftId },
        { validateStatus: () => true, headers: { "Content-Type": "application/json" } }
      );
      if (sessionRes.status < 200 || sessionRes.status >= 300) {
        const body = sessionRes.data;
        throw new Error(
          body && typeof body === "object" && body.detail
            ? String(body.detail)
            : `Target market session error: ${sessionRes.status} ${sessionRes.statusText}`
        );
      }

      const res = await apiClient.post(
        "/api/target-market",
        {
          draft_id: draftId,
          business_name: businessName,
          address,
          address_street: addressStreet,
          address_city: addressCity,
          address_state: addressState,
          address_zip: addressZip,
          address_country: addressCountry,
        },
        { validateStatus: () => true, headers: { "Content-Type": "application/json" } }
      );

      if (res.status < 200 || res.status >= 300) {
        const body = res.data;
        throw new Error(
          body && typeof body === "object" && body.detail
            ? String(body.detail)
            : `Target market error: ${res.status} ${res.statusText}`
        );
      }

      const body: any = res.data;
      const action = String(body?.action || "");
      if (action === "confirm_proceed") {
        setTargetMarketConfirmed(true);
      }
      setTargetMarketDone(Boolean(body?.done));
      setTargetMarketMessages((prev) => [
        ...prev,
        { role: "assistant" as const, content: String(body?.assistant_message || "") },
      ]);
      const tmJson = body?.target_market_json;
      if (tmJson) {
        try {
          const parsed = JSON.parse(String(tmJson));
          setTargetMarketSummary(
            parsed && typeof parsed === "object"
              ? String((parsed as any).target_market_summary || "").trim() || null
              : null
          );
        } catch {
          setTargetMarketSummary(null);
        }
      }
    } catch (error) {
      setTargetMarketError(error instanceof Error ? error.message : String(error));
    } finally {
      setTargetMarketLoading(false);
    }
  }

  async function sendTargetMarketMessage(message: string) {
    if (!draftId) {
      setTargetMarketError("Missing draft id. Reload and start Ops first.");
      return;
    }
    setTargetMarketError(null);
    setTargetMarketLoading(true);

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
        "/api/target-market",
        {
          draft_id: draftId,
          message,
          business_name: businessName,
          address,
          address_street: addressStreet,
          address_city: addressCity,
          address_state: addressState,
          address_zip: addressZip,
          address_country: addressCountry,
        },
        { validateStatus: () => true, headers: { "Content-Type": "application/json" } }
      );

      if (res.status < 200 || res.status >= 300) {
        const body = res.data;
        throw new Error(
          body && typeof body === "object" && body.detail
            ? String(body.detail)
            : `Target market error: ${res.status} ${res.statusText}`
        );
      }

      const body: any = res.data;
      const action = String(body?.action || "");
      if (action === "confirm_proceed") {
        setTargetMarketConfirmed(true);
      }
      setTargetMarketDone(Boolean(body?.done));
      setTargetMarketMessages((prev) => [
        ...prev,
        { role: "assistant" as const, content: String(body?.assistant_message || "") },
      ]);
      const tmJson = body?.target_market_json;
      if (tmJson) {
        try {
          const parsed = JSON.parse(String(tmJson));
          setTargetMarketSummary(
            parsed && typeof parsed === "object"
              ? String((parsed as any).target_market_summary || "").trim() || null
              : null
          );
        } catch {
          setTargetMarketSummary(null);
        }
      }
    } catch (error) {
      setTargetMarketError(error instanceof Error ? error.message : String(error));
    } finally {
      setTargetMarketLoading(false);
    }
  }

  if (!planStarted) {
    return (
      <Card
        id="intake-section-target-market"
        ref={cardRef}
        className="border border-slate-800/80 bg-slate-950/90"
      >
        <CardHeader className="border-0 pb-3">
          <CardTitle className="text-sm">Customers &amp; positioning</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3 text-xs text-slate-300">
          <div className="rounded-md border border-slate-800/80 bg-slate-950/60 p-3">
            You&apos;ll work with the assistant to define your target market and
            positioning in a guided, step-by-step consultation.
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
      id="intake-section-target-market"
      ref={cardRef}
      className="border border-slate-800/80 bg-slate-950/90"
    >
      <CardHeader className="border-0 pb-3">
        <CardTitle className="text-sm">Customers &amp; positioning</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="mt-2 space-y-3 rounded-md border border-slate-800/80 bg-slate-950/60 p-3">
          <div className="text-xs text-slate-300">
            Target market consultation: GPT will help you define who you serve
            (age, income, household, etc.) and will summarize before finalizing.
          </div>

          {!opsConfirmed ? (
            <div className="text-xs text-slate-400">
              Complete and confirm the Business overview consultation first.
            </div>
          ) : targetMarketMessages.length === 0 && !awaitingConfirmation ? (
            <div className="text-xs text-slate-400">
              {targetMarketLoading
                ? "Starting target market consultation..."
                : "Preparing target market consultation..."}
            </div>
          ) : null}

            {targetMarketLoading && targetMarketMessages.length === 0 ? (
              <div className="text-xs text-slate-400 italic animate-pulse">
                Consultant is generating a response...
              </div>
            ) : null}

            {targetMarketError ? (
              <div className="rounded-md border border-rose-500/30 bg-rose-500/10 p-3 text-xs text-rose-200">
                {targetMarketError}
              </div>
            ) : null}

          {targetMarketMessages.length ? (
              <div
                ref={chatContainerRef}
                className="max-h-64 space-y-2 overflow-auto rounded-md border border-slate-800/80 bg-slate-950/60 p-3 text-xs text-slate-200"
              >
                {targetMarketMessages.map((m, idx) => (
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
                {targetMarketLoading ? (
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

            {targetMarketConfirmed ? (
              <div className="flex items-center justify-between gap-3 rounded-md border border-emerald-500/30 bg-emerald-500/10 p-3 text-xs text-emerald-200">
                <span>Customers &amp; positioning confirmed.</span>
                <Button
                  type="button"
                  size="sm"
                  variant="secondary"
                  onClick={() => setEditSection("targetMarket")}
                >
                  Edit
                </Button>
              </div>
            ) : null}

            {isUnlocked ? (
              <div className="flex gap-2">
                <Input
                  ref={chatInputRef}
                  value={targetMarketInput}
                  onChange={(e) => setTargetMarketInput(e.target.value)}
                  onKeyDown={async (e) => {
                    if (e.key === "Enter") {
                      e.preventDefault();
                      if (targetMarketLoading) return;
                      if (!isActive) return;
                      if (!awaitingConfirmation && !editMode && !targetMarketConfirmed && targetMarketMessages.length === 0) return;
                      const msg = targetMarketInput.trim();
                      if (!msg) return;
                      setTargetMarketInput("");
                      setTargetMarketMessages((prev) => [
                        ...prev,
                        { role: "user", content: msg },
                      ]);
                      if (editMode) {
                        setEditSection(null);
                      }
                      await sendTargetMarketMessage(msg);
                    }
                  }}
                  placeholder={
                    !isActive
                      ? targetMarketConfirmed
                        ? "Click Edit to update this section..."
                        : "Complete the previous step to continue..."
                      : awaitingConfirmation
                        ? "Reply to continue..."
                        : "Reply about your target market..."
                  }
                  disabled={
                    targetMarketLoading ||
                    !isActive ||
                    (!awaitingConfirmation && !editMode && !targetMarketConfirmed && targetMarketMessages.length === 0)
                  }
                />
                <Button
                  type="button"
                  size="sm"
                  disabled={
                    targetMarketLoading ||
                    !isActive ||
                    (!awaitingConfirmation && !editMode && !targetMarketConfirmed && targetMarketMessages.length === 0) ||
                    !targetMarketInput.trim()
                  }
                  onClick={async () => {
                    const msg = targetMarketInput.trim();
                    setTargetMarketInput("");
                    setTargetMarketMessages((prev) => [
                      ...prev,
                      { role: "user", content: msg },
                    ]);
                    if (editMode) {
                      setEditSection(null);
                    }
                    await sendTargetMarketMessage(msg);
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
