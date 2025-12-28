import { useFormContext } from "react-hook-form";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/Card";
import {
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "../../components/ui/Form";
import { Input } from "../../components/ui/Input";
import type { IntakeValues } from "../schema";

export default function ClientInformationStep() {
  const form = useFormContext<IntakeValues>();

  return (
    <Card className="border border-slate-800/80 bg-slate-950/90">
      <CardHeader className="border-0 pb-3">
        <CardTitle className="text-sm">Client Information</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <FormField name="firstName" control={form.control}>
          {(field) => (
            <FormItem>
              <FormLabel>First Name</FormLabel>
              <FormControl>
                <Input {...field} type="text" placeholder="Enter your first name" />
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
                  className="mt-1 flex h-9 w-full rounded-md border border-slate-700/80 bg-slate-900/80 px-3 text-xs text-slate-50 shadow-sm transition-all placeholder:text-slate-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400/70 focus-visible:ring-offset-1 focus-visible:ring-offset-slate-950"
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
      </CardContent>
    </Card>
  );
}

