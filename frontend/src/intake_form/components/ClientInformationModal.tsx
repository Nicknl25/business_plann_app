import { useEffect, useRef } from "react";
import { useFormContext } from "react-hook-form";
import { Button } from "../../components/ui/Button";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/Card";
import {
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "../../components/ui/Form";
import { Input } from "../../components/ui/Input";
import { useIntakeFlow } from "../flow/IntakeFlowContext";
import type { IntakeValues } from "../schema";

export default function ClientInformationModal({
  open,
  submitting,
  onClose,
  onConfirm,
}: {
  open: boolean;
  submitting: boolean;
  onClose: () => void;
  onConfirm: () => void;
}) {
  const form = useFormContext<IntakeValues>();
  const {
    setSubmitError,
    setSubmitSuccess,
  } = useIntakeFlow();
  const firstInputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    if (!open) return;
    const t = window.setTimeout(() => {
      firstInputRef.current?.focus();
    }, 50);
    return () => window.clearTimeout(t);
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onClose, open]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/70 px-4 py-6 backdrop-blur-sm">
      <div
        className="absolute inset-0"
        onClick={() => {
          if (submitting) return;
          onClose();
        }}
      />
      <Card className="relative z-10 w-full max-w-xl border border-slate-800/80 bg-slate-950/95 shadow-soft">
        <CardHeader className="border-0 pb-3">
          <CardTitle className="text-sm">Client information</CardTitle>
          <p className="mt-1 text-xs text-slate-400">
            Add the contact details to deliver your plan and reference code.
          </p>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="rounded-md border border-slate-800/80 bg-slate-950/60 p-3 text-xs text-slate-300">
            Need to change something? Close this window and continue the chat — edits
            update the intake in place and don’t reset progress.
          </div>

          <div className="grid gap-4 md:grid-cols-2">
            <FormField name="firstName" control={form.control}>
              {(field) => (
                <FormItem>
                  <FormLabel>First Name</FormLabel>
                  <FormControl>
                    <Input
                      {...field}
                      ref={(el) => {
                        field.ref(el);
                        firstInputRef.current = el;
                      }}
                      type="text"
                      placeholder="Enter your first name"
                    />
                  </FormControl>
                  <FormMessage>{form.formState.errors.firstName?.message}</FormMessage>
                </FormItem>
              )}
            </FormField>

            <FormField name="lastName" control={form.control}>
              {(field) => (
                <FormItem>
                  <FormLabel>Last Name</FormLabel>
                  <FormControl>
                    <Input {...field} type="text" placeholder="Enter your last name" />
                  </FormControl>
                  <FormMessage>{form.formState.errors.lastName?.message}</FormMessage>
                </FormItem>
              )}
            </FormField>
          </div>

          <FormField name="emailAddress" control={form.control}>
            {(field) => (
              <FormItem>
                <FormLabel>Email Address</FormLabel>
                <FormControl>
                  <Input {...field} type="email" placeholder="you@example.com" />
                </FormControl>
                <FormMessage>{form.formState.errors.emailAddress?.message}</FormMessage>
              </FormItem>
            )}
          </FormField>

          <FormField name="phoneNumber" control={form.control}>
            {(field) => (
              <FormItem>
                <FormLabel>
                  Phone Number <span className="text-slate-400">(optional)</span>
                </FormLabel>
                <FormControl>
                  <Input {...field} type="text" placeholder="Optional" />
                </FormControl>
                <FormMessage>{form.formState.errors.phoneNumber?.message}</FormMessage>
              </FormItem>
            )}
          </FormField>

          <FormField name="howDidYouHear" control={form.control}>
            {(field) => (
              <FormItem>
                <FormLabel>How did you hear about us?</FormLabel>
                <FormControl>
                  <select
                    name={field.name}
                    value={(field.value as string) || ""}
                    onChange={(event) => field.onChange(event.target.value)}
                    onBlur={field.onBlur}
                    disabled={submitting}
                    className="mt-1 flex h-9 w-full rounded-md border border-slate-700/80 bg-slate-900/80 px-3 text-xs text-slate-50 shadow-sm transition-all placeholder:text-slate-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400/70 focus-visible:ring-offset-1 focus-visible:ring-offset-slate-950 disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    <option value="">Select an option</option>
                    <option value="Twitter">Twitter</option>
                    <option value="TikTok">TikTok</option>
                    <option value="YouTube">YouTube</option>
                    <option value="Other">Other</option>
                  </select>
                </FormControl>
                <FormMessage>{form.formState.errors.howDidYouHear?.message}</FormMessage>
              </FormItem>
            )}
          </FormField>

          <div className="flex flex-col-reverse gap-2 pt-2 sm:flex-row sm:justify-end">
            <Button
              type="button"
              variant="outline"
              disabled={submitting}
              onClick={onClose}
            >
              Cancel
            </Button>
            <Button type="button" disabled={submitting} onClick={onConfirm}>
              {submitting ? "Submitting..." : "Confirm and submit"}
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
