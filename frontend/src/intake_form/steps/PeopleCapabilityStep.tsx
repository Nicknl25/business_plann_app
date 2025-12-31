import { useEffect, useRef, useState } from "react";
import { useFormContext } from "react-hook-form";
import apiClient from "../../apiClient";
import { Button } from "../../components/ui/Button";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/Card";
import { Input } from "../../components/ui/Input";
import { useIntakeFlow } from "../flow/IntakeFlowContext";
import { decideConfirmation } from "../flow/confirmationIntent";
import type { IntakeValues } from "../schema";

export default function PeopleCapabilityStep() {
  const form = useFormContext<IntakeValues>();
  const {
    planStarted,
    draftId,
    clientId,
    targetMarketConfirmed,
    editSection,
    setEditSection,
    peopleDone,
    setPeopleDone,
    setKeyPeopleSummary,
    peopleConfirmed,
    setPeopleConfirmed,
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

  const [peopleMessages, setPeopleMessages] = useState<
    { role: "user" | "assistant"; content: string }[]
  >([]);
  const [peopleInput, setPeopleInput] = useState("");
  const [peopleLoading, setPeopleLoading] = useState(false);
  const [peopleError, setPeopleError] = useState<string | null>(null);
  const [editConfirmPending, setEditConfirmPending] = useState(false);

  useEffect(() => {
    setPeopleMessages([]);
    setPeopleInput("");
    setPeopleLoading(false);
    setPeopleError(null);
    setEditConfirmPending(false);
    didAutoStart.current = false;
    setResumeChecked(false);
  }, [resetCounter]);

  const awaitingConfirmation = Boolean(peopleDone && !peopleConfirmed);
  const isActive = Boolean(targetMarketConfirmed && !peopleConfirmed);

  const CONFIRM_PROMPT = "Does this look right before we move on to Financials?";
  const CLARIFY_PROMPT =
    "Just to confirm - are we good to move on, or is there anything you want to change?";
  const editMode = editSection === "people";

  function handleConfirmationReply(message: string) {
    const decision = decideConfirmation(message);
    if (decision === "proceed") {
      setPeopleConfirmed(true);
      setPeopleMessages((prev) => [
        ...prev,
        { role: "assistant", content: "Great — let’s move on to Financials." },
      ]);
      return;
    }

    if (decision === "clarify") {
      setPeopleMessages((prev) => [
        ...prev,
        { role: "assistant", content: CLARIFY_PROMPT },
      ]);
      return;
    }

    setPeopleMessages((prev) =>
      prev.filter((m) => !(m.role === "assistant" && m.content === CONFIRM_PROMPT))
    );
    setPeopleDone(false);
    setKeyPeopleSummary(null);
    void sendPeopleCapabilityMessage(message, {
      reopen: true,
      editFinalize: editConfirmPending,
    });
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
    if (peopleLoading) return;
    if (!chatInputRef.current) return;
    const last = peopleMessages[peopleMessages.length - 1];
    if (!last || last.role !== "assistant") return;
    chatInputRef.current.focus();
  }, [isActive, peopleLoading, peopleMessages, planStarted]);

  useEffect(() => {
    if (!planStarted) return;
    if (!isActive) return;
    if (peopleLoading) return;
    if (!chatInputRef.current) return;

    const last = peopleMessages[peopleMessages.length - 1];
    if (!last || last.role !== "assistant") return;
    chatInputRef.current.focus();
  }, [isActive, peopleDone, peopleLoading, peopleMessages, planStarted]);

  useEffect(() => {
    if (!planStarted) return;
    const container = chatContainerRef.current;
    if (!container) return;

    const wasLoading = prevLoading.current;
    const isLoading = peopleLoading && !peopleDone;
    const prevLen = prevMessagesLen.current;

    if (isLoading) {
      container.scrollTop = container.scrollHeight;
    }

    if (peopleMessages.length > prevLen) {
      const last = peopleMessages[peopleMessages.length - 1];
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

    prevMessagesLen.current = peopleMessages.length;
    prevLoading.current = isLoading;
  }, [peopleDone, peopleLoading, peopleMessages, planStarted]);

  useEffect(() => {
    if (!planStarted) return;
    if (!awaitingConfirmation) return;
    setPeopleMessages((prev) => {
      const already = prev.some(
        (m) => m.role === "assistant" && m.content === CONFIRM_PROMPT
      );
      if (already) return prev;
      return [...prev, { role: "assistant", content: CONFIRM_PROMPT }];
    });
  }, [awaitingConfirmation, planStarted]);

  useEffect(() => {
    if (!planStarted) return;
    if (!peopleConfirmed) return;
    setPeopleMessages((prev) =>
      prev.filter((m) => !(m.role === "assistant" && m.content === CONFIRM_PROMPT))
    );
    setEditConfirmPending(false);
  }, [peopleConfirmed, planStarted]);

  useEffect(() => {
    if (!draftId || !clientId) return;
    if (!planStarted) return;
    if (!resumeChecked) return;
    if (!isActive) return;
    if (peopleDone) return;
    if (peopleLoading) return;
    if (peopleMessages.length > 0) return;
    if (didAutoStart.current) return;
    didAutoStart.current = true;
    void startPeopleCapabilityConversation();
  }, [
    clientId,
    draftId,
    isActive,
    peopleDone,
    peopleLoading,
    peopleMessages.length,
    planStarted,
    resumeChecked,
  ]);

  useEffect(() => {
    if (!planStarted) return;
    if (!draftId) return;
    (async () => {
      try {
        const res = await apiClient.get("/api/people-capability/draft", {
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
                setPeopleMessages(
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
            setPeopleDone(true);
            const peopleJson = body?.people_json;
            if (peopleJson) {
              try {
                const parsed = JSON.parse(String(peopleJson));
                if (parsed && typeof parsed === "object") {
                  setKeyPeopleSummary(
                    String((parsed as any).key_people_summary || "").trim() || null
                  );
                }
              } catch {
                setKeyPeopleSummary(null);
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
  }, [draftId, planStarted, setKeyPeopleSummary, setPeopleDone]);

  async function startPeopleCapabilityConversation(preface?: string) {
    if (!draftId || !clientId) return;
    setPeopleError(null);
    setPeopleLoading(true);
    setPeopleMessages(preface ? [{ role: "assistant", content: preface }] : []);
    setPeopleInput("");
    setPeopleDone(false);
    setKeyPeopleSummary(null);

    try {
      const sessionRes = await apiClient.post(
        "/api/people-capability/session",
        { draft_id: draftId },
        { validateStatus: () => true, headers: { "Content-Type": "application/json" } }
      );
      if (sessionRes.status < 200 || sessionRes.status >= 300) {
        const body = sessionRes.data;
        throw new Error(
          body && typeof body === "object" && body.detail
            ? String(body.detail)
            : `People session error: ${sessionRes.status} ${sessionRes.statusText}`
        );
      }

      const { businessName } = form.getValues();
      const res = await apiClient.post(
        "/api/people-capability",
        { draft_id: draftId, business_name: businessName },
        { validateStatus: () => true, headers: { "Content-Type": "application/json" } }
      );

      if (res.status < 200 || res.status >= 300) {
        const body = res.data;
        throw new Error(
          body && typeof body === "object" && body.detail
            ? String(body.detail)
            : `People consult error: ${res.status} ${res.statusText}`
        );
      }

      const body: any = res.data;
      setPeopleDone(Boolean(body?.done));
      setPeopleMessages((prev) => {
        const next: { role: "user" | "assistant"; content: string }[] = [
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
        setKeyPeopleSummary(String(body?.assistant_message || "").trim() || null);
      }
    } catch (error) {
      setPeopleError(error instanceof Error ? error.message : String(error));
    } finally {
      setPeopleLoading(false);
    }
  }

  async function sendPeopleCapabilityMessage(
    message: string,
    options?: { reopen?: boolean; editFinalize?: boolean }
  ) {
    if (!draftId || !clientId) return;
    setPeopleError(null);
    setPeopleLoading(true);

    try {
      const { businessName } = form.getValues();
      const res = await apiClient.post(
        "/api/people-capability",
        {
          draft_id: draftId,
          message,
          reopen: Boolean(options?.reopen),
          edit_finalize: Boolean(options?.editFinalize),
          business_name: businessName,
        },
        { validateStatus: () => true, headers: { "Content-Type": "application/json" } }
      );

      if (res.status < 200 || res.status >= 300) {
        const body = res.data;
        throw new Error(
          body && typeof body === "object" && body.detail
            ? String(body.detail)
            : `People consult error: ${res.status} ${res.statusText}`
        );
      }

      const body: any = res.data;
      setPeopleDone(Boolean(body?.done));
      setPeopleMessages((prev) => {
        const next: { role: "user" | "assistant"; content: string }[] = [
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
        setKeyPeopleSummary(String(body?.assistant_message || "").trim() || null);
      }
    } catch (error) {
      setPeopleError(error instanceof Error ? error.message : String(error));
    } finally {
      setPeopleLoading(false);
    }
  }

  if (!planStarted) {
    return (
      <Card
        id="intake-section-people"
        ref={cardRef}
        className="border border-slate-800/80 bg-slate-950/90"
      >
        <CardHeader className="border-0 pb-3">
          <CardTitle className="text-sm">People &amp; capability</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3 text-xs text-slate-300">
          <div className="rounded-md border border-slate-800/80 bg-slate-950/60 p-3">
            You&apos;ll work with the assistant to capture the key people behind the
            business and produce polished, credibility-building summaries.
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
      id="intake-section-people"
      ref={cardRef}
      className="border border-slate-800/80 bg-slate-950/90"
    >
      <CardHeader className="border-0 pb-3">
        <CardTitle className="text-sm">People &amp; capability</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="mt-2 space-y-3 rounded-md border border-slate-800/80 bg-slate-950/60 p-3">
          <div className="text-xs text-slate-300">
            People &amp; capability consultation: GPT will help you capture the key
            people behind the business and produce polished, credibility-building
            paragraphs.
          </div>

          {!targetMarketConfirmed ? (
            <div className="text-xs text-slate-400">
              Complete and confirm Customers &amp; positioning first.
            </div>
          ) : peopleMessages.length === 0 && !awaitingConfirmation ? (
            <div className="text-xs text-slate-400">
              {peopleLoading
                ? "Starting people & capability consultation..."
                : "Preparing people & capability consultation..."}
            </div>
          ) : null}

          {peopleLoading && peopleMessages.length === 0 ? (
            <div className="text-xs text-slate-400 italic animate-pulse">
              Consultant is generating a response...
            </div>
          ) : null}

          {peopleError ? (
            <div className="rounded-md border border-rose-500/30 bg-rose-500/10 p-3 text-xs text-rose-200">
              {peopleError}
            </div>
          ) : null}

          {peopleMessages.length ? (
            <div
              ref={chatContainerRef}
              className="max-h-64 space-y-2 overflow-auto rounded-md border border-slate-800/80 bg-slate-950/60 p-3 text-xs text-slate-200"
            >
              {peopleMessages.map((m, idx) => (
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
              {peopleLoading && !peopleDone ? (
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

          {peopleConfirmed ? (
            <div className="rounded-md border border-emerald-500/30 bg-emerald-500/10 p-3 text-xs text-emerald-200">
              People &amp; capability confirmed.
            </div>
          ) : null}

          {isActive ? (
            <div className="flex gap-2">
              <Input
                ref={chatInputRef}
                value={peopleInput}
                onChange={(e) => setPeopleInput(e.target.value)}
                onKeyDown={async (e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    if (peopleLoading) return;
                    if (!awaitingConfirmation && peopleMessages.length === 0) return;
                    const msg = peopleInput.trim();
                    if (!msg) return;
                    setPeopleInput("");
                    setPeopleMessages((prev) => [
                      ...prev,
                      { role: "user", content: msg },
                    ]);
                    if (awaitingConfirmation) {
                      handleConfirmationReply(msg);
                      return;
                    }
                    if (editMode) {
                      setEditSection(null);
                      setEditConfirmPending(true);
                      await sendPeopleCapabilityMessage(msg, {
                        reopen: true,
                        editFinalize: true,
                      });
                      return;
                    }
                    await sendPeopleCapabilityMessage(msg);
                  }
                }}
                placeholder={
                  awaitingConfirmation
                    ? "Reply to continue..."
                    : "Reply to the consultant..."
                }
                disabled={
                  peopleLoading || (!awaitingConfirmation && peopleMessages.length === 0)
                }
              />
              <Button
                type="button"
                size="sm"
                disabled={
                  peopleLoading ||
                  (!awaitingConfirmation && peopleMessages.length === 0) ||
                  !peopleInput.trim()
                }
                onClick={async () => {
                  const msg = peopleInput.trim();
                  if (!msg) return;
                  setPeopleInput("");
                  setPeopleMessages((prev) => [...prev, { role: "user", content: msg }]);
                  if (awaitingConfirmation) {
                    handleConfirmationReply(msg);
                    return;
                  }
                  if (editMode) {
                    setEditSection(null);
                    setEditConfirmPending(true);
                    await sendPeopleCapabilityMessage(msg, {
                      reopen: true,
                      editFinalize: true,
                    });
                    return;
                  }
                  await sendPeopleCapabilityMessage(msg);
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
