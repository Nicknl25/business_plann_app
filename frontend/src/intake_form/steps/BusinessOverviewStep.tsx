import { ClipboardList, Sparkles } from "lucide-react";
import { useEffect, useState } from "react";
import { useFormContext } from "react-hook-form";
import apiClient from "../../apiClient";
import GoogleAddressInput from "../../components/GoogleAddressInput";
import GoogleBusinessTypeInput from "../../components/GoogleBusinessTypeInput";
import { Button } from "../../components/ui/Button";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/Card";
import {
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "../../components/ui/Form";
import HelpTooltip from "../../components/ui/HelpTooltip";
import { Input } from "../../components/ui/Input";
import { TOOLTIP_TEXT } from "../../components/ui/tooltip";
import { consultStorage } from "../flow/consultStorage";
import { useIntakeFlow } from "../flow/IntakeFlowContext";
import type { IntakeValues } from "../schema";

export default function BusinessOverviewStep() {
  const form = useFormContext<IntakeValues>();
  const {
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
    submitLoading,
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

  useEffect(() => {
    (async () => {
      const storedDraftId = consultStorage.getDraftId();
      const storedClientId = consultStorage.getClientId();
      if (!storedDraftId || !storedClientId) return;

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
        if (messagesJson) {
          try {
            const parsed = JSON.parse(String(messagesJson));
            if (Array.isArray(parsed)) {
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
        }
      } catch {
        // ignore resume errors
      }
    })();
  }, [setClientId, setConsultDone, setConsultFinal, setDraftId]);

  function resetConsultSession() {
    consultStorage.clear();
    setClientId(null);
    setDraftId(null);
    setConsultMessages([]);
    setConsultInput("");
    setConsultDone(false);
    setConsultFinal(null);
    setConsultError(null);

    setTargetMarketDone(false);
    setTargetMarketSummary(null);

    setPeopleDone(false);
    setKeyPeopleSummary(null);

    bumpResetCounter();
  }

  async function startConsultConversation(
    nextDraftId: string,
    nextClientId: string
  ) {
    setConsultError(null);
    setConsultMessages([]);
    setConsultInput("");
    setConsultDone(false);
    setConsultFinal(null);
    setConsultLoading(true);

    try {
      const { businessName, businessType } = form.getValues();
      const res = await apiClient.post(
        "/api/intake-consult",
        {
          draft_id: nextDraftId,
          client_id: nextClientId,
          business_name: businessName,
          business_type: businessType,
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
      setConsultMessages([
        { role: "assistant", content: String(body?.assistant_message || "") },
      ]);
    } catch (error) {
      setConsultError(error instanceof Error ? error.message : String(error));
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
      await startConsultConversation(nextDraftId, nextClientId);
    } catch (error) {
      setConsultError(error instanceof Error ? error.message : String(error));
    } finally {
      setConsultLoading(false);
    }
  }

  async function sendConsultMessage(message: string) {
    if (!draftId || !clientId) return;

    setConsultError(null);
    setConsultLoading(true);

    try {
      const { businessName, businessType } = form.getValues();
      const res = await apiClient.post(
        "/api/intake-consult",
        {
          draft_id: draftId,
          client_id: clientId,
          message,
          business_name: businessName,
          business_type: businessType,
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
      setConsultMessages((prev) => [
        ...prev,
        { role: "assistant", content: String(body?.assistant_message || "") },
      ]);
    } catch (error) {
      setConsultError(error instanceof Error ? error.message : String(error));
    } finally {
      setConsultLoading(false);
    }
  }

  return (
    <div className="grid gap-5 md:grid-cols-[1.3fr_1fr]">
      {/* Business basics */}
      <Card className="border border-slate-800/80 bg-slate-950/90">
        <CardHeader className="border-0 pb-3">
          <CardTitle className="flex items-center gap-2 text-sm">
            <span className="inline-flex h-7 w-7 items-center justify-center rounded-xl bg-sky-500/15 text-sky-300 ring-1 ring-sky-500/40">
              <ClipboardList className="h-3.5 w-3.5" />
            </span>
            Business overview
          </CardTitle>
        </CardHeader>
        <CardContent className="grid gap-4 pt-1 md:grid-cols-2">
          <FormField name="businessName" control={form.control}>
            {(field) => (
              <FormItem className="col-span-2 md:col-span-2">
                <FormLabel>Business name</FormLabel>
                <FormControl>
                  <Input
                    {...field}
                    placeholder="Working or legal name of your business"
                  />
                </FormControl>
                <FormMessage>
                  {form.formState.errors.businessName?.message}
                </FormMessage>
              </FormItem>
            )}
          </FormField>

          <FormField name="businessType" control={form.control}>
            {(field) => (
              <FormItem className="col-span-2 md:col-span-2">
                <FormLabel>Type of Business</FormLabel>
                <FormControl>
                  <GoogleBusinessTypeInput
                    {...field}
                    placeholder="E.g., coffee shop, trucking company, HVAC repair, childcare, bookkeeping"
                  />
                </FormControl>
                <FormMessage>
                  {form.formState.errors.businessType?.message}
                </FormMessage>
              </FormItem>
            )}
          </FormField>

          <FormField name="address" control={form.control}>
            {(field) => (
              <FormItem>
                <FormLabel>
                  Business address{" "}
                  <HelpTooltip
                    fieldName="address"
                    text={TOOLTIP_TEXT.businessAddress}
                  />
                </FormLabel>
                <FormControl>
                  <GoogleAddressInput
                    {...field}
                    placeholder="If applicable, list your physical location"
                  />
                </FormControl>
                <FormMessage>
                  {form.formState.errors.address?.message}
                </FormMessage>
              </FormItem>
            )}
          </FormField>

          <div className="col-span-2 space-y-3">
            {!clientId ? (
              <div className="flex flex-col gap-2">
                <div className="text-xs text-slate-300">
                  Start the consultant conversation before submitting the
                  intake. GPT will ask operational questions and will tell you
                  when it's complete.
                </div>
                <Button
                  type="button"
                  size="sm"
                  disabled={consultLoading}
                  onClick={createConsultSession}
                >
                  {consultLoading ? "Starting..." : "Start conversation"}
                </Button>
                {consultError ? (
                  <div className="rounded-md border border-rose-500/30 bg-rose-500/10 p-3 text-xs text-rose-200">
                    {consultError}
                  </div>
                ) : null}
              </div>
            ) : (
              <div className="space-y-2">
                <div className="text-xs text-slate-300">
                  Reference code:{" "}
                  <span className="font-mono">{clientId}</span>
                </div>

                <div className="flex flex-wrap gap-2">
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    disabled={consultLoading || submitLoading}
                    onClick={createConsultSession}
                  >
                    Start new conversation
                  </Button>
                </div>

                {consultError ? (
                  <div className="rounded-md border border-rose-500/30 bg-rose-500/10 p-3 text-xs text-rose-200">
                    {consultError}
                  </div>
                ) : null}

                <div className="max-h-64 space-y-2 overflow-auto rounded-md border border-slate-800/80 bg-slate-950/60 p-3 text-xs text-slate-200">
                  {consultMessages.length === 0 ? (
                    <div className="text-slate-400">
                      {consultLoading
                        ? "Starting consultant conversation..."
                        : "Conversation will appear here."}
                    </div>
                  ) : (
                    <>
                      {consultMessages.map((m, idx) => (
                        <div key={idx} className="whitespace-pre-wrap">
                          <span className="text-slate-400">{m.role}:</span>{" "}
                          {m.content}
                        </div>
                      ))}
                      {consultLoading && !consultDone ? (
                        <div className="whitespace-pre-wrap text-slate-400 italic animate-pulse">
                          <span className="text-slate-400">assistant:</span>{" "}
                          Consultant is generating a response...
                        </div>
                      ) : null}
                    </>
                  )}
                </div>

                {consultDone ? (
                  <div className="rounded-md border border-emerald-500/30 bg-emerald-500/10 p-3 text-xs text-emerald-200">
                    Operational intake complete. Continue filling out the rest
                    of the form and click Submit intake.
                  </div>
                ) : (
                  <div className="text-xs text-slate-400">
                    Complete this conversation to unlock submission.
                  </div>
                )}

                <div className="flex gap-2">
                  <Input
                    value={consultInput}
                    onChange={(e) => setConsultInput(e.target.value)}
                    onKeyDown={async (e) => {
                      if (e.key === "Enter") {
                        e.preventDefault();
                        if (consultLoading || consultDone) return;
                        const msg = consultInput.trim();
                        if (!msg) return;
                        setConsultInput("");
                        setConsultMessages((prev) => [
                          ...prev,
                          { role: "user", content: msg },
                        ]);
                        await sendConsultMessage(msg);
                      }
                    }}
                    placeholder={
                      consultDone
                        ? "Conversation completed."
                        : "Reply to the consultant..."
                    }
                    disabled={consultLoading || consultDone}
                  />
                  <Button
                    type="button"
                    size="sm"
                    disabled={consultLoading || consultDone || !consultInput.trim()}
                    onClick={async () => {
                      const msg = consultInput.trim();
                      setConsultInput("");
                      setConsultMessages((prev) => [
                        ...prev,
                        { role: "user", content: msg },
                      ]);
                      await sendConsultMessage(msg);
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

      {/* Snapshot card */}
      <Card className="relative border border-slate-800/80 bg-slate-950/90">
        <CardHeader className="border-0 pb-2">
          <CardTitle className="text-sm">What to expect next</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3 text-[11px] text-slate-300">
          <p>
            After you submit this form, we'll review your details and confirm
            fit, scope, and timing. No payment is required to complete the
            intake.
          </p>
          <ul className="space-y-1.5">
            <li>â€¢ Review and alignment on goals and audience.</li>
            <li>â€¢ Clarifying questions where needed.</li>
            <li>â€¢ Confirmation of timeline and next steps.</li>
          </ul>
          <p className="text-slate-400">
            The more specific you are, the more precise and compelling your
            finished plan can be.
          </p>
          <div className="absolute top-4 right-4 animate-glow">
            <span className="relative flex h-8 w-8 items-center justify-center rounded-2xl bg-sky-500/15 text-sky-400 ring-1 ring-sky-500/40 shadow-glow animate-slowspin">
              <Sparkles className="h-4 w-4" />
              <span className="absolute inset-0 -z-10 rounded-2xl bg-sky-500/15 blur-xl" />
            </span>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

