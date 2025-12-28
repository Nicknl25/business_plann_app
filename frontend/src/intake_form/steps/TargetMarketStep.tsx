import { useEffect, useState } from "react";
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
    draftId,
    clientId,
    consultDone,
    targetMarketDone,
    setTargetMarketDone,
    setTargetMarketSummary,
    resetCounter,
  } = useIntakeFlow();

  const [targetMarketMessages, setTargetMarketMessages] = useState<
    { role: "user" | "assistant"; content: string }[]
  >([]);
  const [targetMarketInput, setTargetMarketInput] = useState("");
  const [targetMarketLoading, setTargetMarketLoading] = useState(false);
  const [targetMarketError, setTargetMarketError] = useState<string | null>(null);

  useEffect(() => {
    setTargetMarketMessages([]);
    setTargetMarketInput("");
    setTargetMarketLoading(false);
    setTargetMarketError(null);
  }, [resetCounter]);

  useEffect(() => {
    if (!draftId) return;
    (async () => {
      try {
        const res = await apiClient.get("/api/target-market/draft", {
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
                  String((parsed as any).target_market_summary || "").trim() || null
                );
              }
            } catch {
              setTargetMarketSummary(null);
            }
          }
        }
      } catch {
        // ignore resume errors
      }
    })();
  }, [draftId, setTargetMarketDone, setTargetMarketSummary]);

  async function startTargetMarketConversation() {
    if (!draftId || !clientId) return;
    setTargetMarketError(null);
    setTargetMarketMessages([]);
    setTargetMarketInput("");
    setTargetMarketDone(false);
    setTargetMarketSummary(null);
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
      setTargetMarketDone(Boolean(body?.done));
      setTargetMarketMessages([
        { role: "assistant", content: String(body?.assistant_message || "") },
      ]);
      if (body?.done) {
        setTargetMarketSummary(String(body?.assistant_message || "").trim() || null);
      }
    } catch (error) {
      setTargetMarketError(error instanceof Error ? error.message : String(error));
    } finally {
      setTargetMarketLoading(false);
    }
  }

  async function sendTargetMarketMessage(message: string) {
    if (!draftId || !clientId) return;
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
      setTargetMarketDone(Boolean(body?.done));
      setTargetMarketMessages((prev) => [
        ...prev,
        { role: "assistant", content: String(body?.assistant_message || "") },
      ]);
      if (body?.done) {
        setTargetMarketSummary(String(body?.assistant_message || "").trim() || null);
      }
    } catch (error) {
      setTargetMarketError(error instanceof Error ? error.message : String(error));
    } finally {
      setTargetMarketLoading(false);
    }
  }

  return (
    <div className="grid gap-5 md:grid-cols-2">
      <Card className="border border-slate-800/80 bg-slate-950/90">
        <CardHeader className="border-0 pb-3">
          <CardTitle className="text-sm">Customers &amp; positioning</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="mt-2 space-y-3 rounded-md border border-slate-800/80 bg-slate-950/60 p-3">
            <div className="text-xs text-slate-300">
              Target market consultation: GPT will help you define who you serve
              (age, income, household, etc.) and will summarize before finalizing.
            </div>

            {!consultDone ? (
              <div className="text-xs text-slate-400">
                Complete the operational consultant conversation first.
              </div>
            ) : targetMarketMessages.length === 0 && !targetMarketDone ? (
              <Button
                type="button"
                size="sm"
                disabled={targetMarketLoading}
                onClick={startTargetMarketConversation}
              >
                {targetMarketLoading ? "Starting..." : "Start target market conversation"}
              </Button>
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
              <div className="max-h-64 space-y-2 overflow-auto rounded-md border border-slate-800/80 bg-slate-950/60 p-3 text-xs text-slate-200">
                {targetMarketMessages.map((m, idx) => (
                  <div key={idx} className="whitespace-pre-wrap">
                    <span className="text-slate-400">{m.role}:</span> {m.content}
                  </div>
                ))}
                {targetMarketLoading && !targetMarketDone ? (
                  <div className="whitespace-pre-wrap text-slate-400 italic animate-pulse">
                    <span className="text-slate-400">assistant:</span> Consultant is
                    generating a response...
                  </div>
                ) : null}
              </div>
            ) : null}

            {targetMarketDone ? (
              <div className="rounded-md border border-emerald-500/30 bg-emerald-500/10 p-3 text-xs text-emerald-200">
                Target market intake complete. Continue filling out the rest of the
                form and click Submit intake.
              </div>
            ) : null}

            {consultDone && !targetMarketDone ? (
              <div className="flex gap-2">
                <Input
                  value={targetMarketInput}
                  onChange={(e) => setTargetMarketInput(e.target.value)}
                  onKeyDown={async (e) => {
                    if (e.key === "Enter") {
                      e.preventDefault();
                      if (targetMarketLoading || targetMarketDone) return;
                      const msg = targetMarketInput.trim();
                      if (!msg) return;
                      setTargetMarketInput("");
                      setTargetMarketMessages((prev) => [
                        ...prev,
                        { role: "user", content: msg },
                      ]);
                      await sendTargetMarketMessage(msg);
                    }
                  }}
                  placeholder="Reply about your target market..."
                  disabled={targetMarketLoading || targetMarketDone}
                />
                <Button
                  type="button"
                  size="sm"
                  disabled={
                    targetMarketLoading ||
                    targetMarketDone ||
                    !targetMarketInput.trim()
                  }
                  onClick={async () => {
                    const msg = targetMarketInput.trim();
                    setTargetMarketInput("");
                    setTargetMarketMessages((prev) => [
                      ...prev,
                      { role: "user", content: msg },
                    ]);
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
    </div>
  );
}
