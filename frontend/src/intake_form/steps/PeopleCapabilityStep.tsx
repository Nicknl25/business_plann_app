import { useEffect, useState } from "react";
import { useFormContext } from "react-hook-form";
import apiClient from "../../apiClient";
import { Button } from "../../components/ui/Button";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/Card";
import { Input } from "../../components/ui/Input";
import { useIntakeFlow } from "../flow/IntakeFlowContext";
import type { IntakeValues } from "../schema";

export default function PeopleCapabilityStep() {
  const form = useFormContext<IntakeValues>();
  const {
    draftId,
    clientId,
    consultDone,
    peopleDone,
    setPeopleDone,
    setKeyPeopleSummary,
    resetCounter,
  } = useIntakeFlow();

  const [peopleMessages, setPeopleMessages] = useState<
    { role: "user" | "assistant"; content: string }[]
  >([]);
  const [peopleInput, setPeopleInput] = useState("");
  const [peopleLoading, setPeopleLoading] = useState(false);
  const [peopleError, setPeopleError] = useState<string | null>(null);

  useEffect(() => {
    setPeopleMessages([]);
    setPeopleInput("");
    setPeopleLoading(false);
    setPeopleError(null);
  }, [resetCounter]);

  useEffect(() => {
    if (!draftId) return;
    (async () => {
      try {
        const res = await apiClient.get("/api/people-capability/draft", {
          params: { draft_id: draftId },
          validateStatus: () => true,
        });
        if (res.status < 200 || res.status >= 300) return;
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
      } catch {
        // ignore resume errors
      }
    })();
  }, [draftId, setKeyPeopleSummary, setPeopleDone]);

  async function startPeopleCapabilityConversation() {
    if (!draftId || !clientId) return;
    setPeopleError(null);
    setPeopleMessages([]);
    setPeopleInput("");
    setPeopleDone(false);
    setKeyPeopleSummary(null);
    setPeopleLoading(true);

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
      setPeopleMessages([{ role: "assistant", content: String(body?.assistant_message || "") }]);
      if (body?.done) {
        setKeyPeopleSummary(String(body?.assistant_message || "").trim() || null);
      }
    } catch (error) {
      setPeopleError(error instanceof Error ? error.message : String(error));
    } finally {
      setPeopleLoading(false);
    }
  }

  async function sendPeopleCapabilityMessage(message: string) {
    if (!draftId || !clientId) return;
    setPeopleError(null);
    setPeopleLoading(true);

    try {
      const { businessName } = form.getValues();
      const res = await apiClient.post(
        "/api/people-capability",
        { draft_id: draftId, message, business_name: businessName },
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
      setPeopleMessages((prev) => [
        ...prev,
        { role: "assistant", content: String(body?.assistant_message || "") },
      ]);
      if (body?.done) {
        setKeyPeopleSummary(String(body?.assistant_message || "").trim() || null);
      }
    } catch (error) {
      setPeopleError(error instanceof Error ? error.message : String(error));
    } finally {
      setPeopleLoading(false);
    }
  }

  return (
    <Card className="border border-slate-800/80 bg-slate-950/90">
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

          {!consultDone ? (
            <div className="text-xs text-slate-400">
              Complete the operational consultant conversation first.
            </div>
          ) : peopleMessages.length === 0 && !peopleDone ? (
            <Button
              type="button"
              size="sm"
              disabled={peopleLoading}
              onClick={startPeopleCapabilityConversation}
            >
              {peopleLoading ? "Starting..." : "Start people & capability conversation"}
            </Button>
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
            <div className="max-h-64 space-y-2 overflow-auto rounded-md border border-slate-800/80 bg-slate-950/60 p-3 text-xs text-slate-200">
              {peopleMessages.map((m, idx) => (
                <div key={idx} className="whitespace-pre-wrap">
                  <span className="text-slate-400">{m.role}:</span> {m.content}
                </div>
              ))}
              {peopleLoading && !peopleDone ? (
                <div className="whitespace-pre-wrap text-slate-400 italic animate-pulse">
                  <span className="text-slate-400">assistant:</span> Consultant is
                  generating a response...
                </div>
              ) : null}
            </div>
          ) : null}

          {peopleDone ? (
            <div className="rounded-md border border-emerald-500/30 bg-emerald-500/10 p-3 text-xs text-emerald-200">
              People &amp; capability intake complete. Continue filling out the rest
              of the form and click Submit intake.
            </div>
          ) : null}

          {consultDone && !peopleDone ? (
            <div className="flex gap-2">
              <Input
                value={peopleInput}
                onChange={(e) => setPeopleInput(e.target.value)}
                onKeyDown={async (e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    if (peopleLoading || peopleDone) return;
                    const msg = peopleInput.trim();
                    if (!msg) return;
                    setPeopleInput("");
                    setPeopleMessages((prev) => [
                      ...prev,
                      { role: "user", content: msg },
                    ]);
                    await sendPeopleCapabilityMessage(msg);
                  }
                }}
                placeholder={
                  peopleDone ? "Conversation completed." : "Reply to the consultant..."
                }
                disabled={peopleLoading || peopleDone}
              />
              <Button
                type="button"
                size="sm"
                disabled={peopleLoading || peopleDone || !peopleInput.trim()}
                onClick={async () => {
                  const msg = peopleInput.trim();
                  if (!msg) return;
                  setPeopleInput("");
                  setPeopleMessages((prev) => [...prev, { role: "user", content: msg }]);
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
