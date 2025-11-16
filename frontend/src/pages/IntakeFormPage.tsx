import { zodResolver } from "@hookform/resolvers/zod";
import { motion } from "framer-motion";
import { ClipboardList, Sparkles } from "lucide-react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import PageShell from "../components/PageShell";
import { Button } from "../components/ui/Button";
import { Card, CardContent, CardHeader, CardTitle } from "../components/ui/Card";
import { Input } from "../components/ui/Input";
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "../components/ui/Form";
import { Textarea } from "../components/ui/Textarea";
import GoogleAddressInput from "../components/GoogleAddressInput";
import GoogleBusinessTypeInput from "../components/GoogleBusinessTypeInput";
import IndustryInput from "../components/IndustryInput";

const intakeSchema = z.object({
  businessName: z.string().min(2, "Please enter your business name."),
  industry: z.string().min(2, "Please describe your industry."),
  businessType: z
    .string()
    .min(2, "Please describe the type of business."),
  description: z
    .string()
    .min(20, "Give us a bit more detail about what you do."),
  address: z.string().optional(),
  productKeywords: z
    .string()
    .min(6, "List a few keywords that describe what you sell."),
  sellingMethod: z
    .string()
    .min(4, "Describe how you expect to sell your product or service."),
  targetCustomer: z
    .string()
    .min(10, "Describe your ideal customer or audience."),
  estimatedRevenue: z
    .string()
    .min(2, "Share a rough revenue estimate or range."),
  startupCosts: z
    .string()
    .min(2, "Share your estimated one-time startup costs."),
  monthlyCosts: z
    .string()
    .min(2, "Share your estimated ongoing monthly costs."),
  pricingModel: z
    .string()
    .min(4, "Describe your pricing model or structure."),
  founderBackground: z
    .string()
    .min(10, "Share your background and why you're starting this business."),
});

type IntakeValues = z.infer<typeof intakeSchema>;

const defaultValues: IntakeValues = {
  businessName: "",
  industry: "",
  businessType: "",
  description: "",
  address: "",
  productKeywords: "",
  sellingMethod: "",
  targetCustomer: "",
  estimatedRevenue: "",
  startupCosts: "",
  monthlyCosts: "",
  pricingModel: "",
  founderBackground: "",
};

function IntakeFormPage() {
  const form = useForm<IntakeValues>({
    resolver: zodResolver(intakeSchema),
    defaultValues,
    mode: "onBlur",
  });

  function handleSubmit(values: IntakeValues) {
    // Visual-only form: placeholder handling.
    console.log("Intake submission", values);
  }

  return (
    <PageShell>
      <div className="space-y-8 md:space-y-10">
        <section className="space-y-3">
          <motion.div
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.4 }}
          >
            <div className="inline-flex items-center gap-2 rounded-full border border-sky-400/20 bg-slate-950/80 px-3 py-1 text-[11px] text-sky-200/90 shadow-soft backdrop-blur-xl">
              <Sparkles className="h-3 w-3" />
              <span className="section-label text-[10px] text-sky-100/90">
                Business Plan Intake
              </span>
            </div>
            <h1 className="mt-3 text-2xl font-semibold tracking-tight text-slate-50 md:text-3xl">
              Tell us about your business.
            </h1>
            <p className="mt-2 max-w-2xl text-sm leading-relaxed text-slate-300">
              This intake form gives us the context we need to craft a
              lender-ready business plan tailored to your goals, industry, and
              numbers. Expect ~15–20 minutes to complete.
            </p>
          </motion.div>
        </section>

        <Form form={form} onSubmit={handleSubmit} className="space-y-8">
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

                <FormField name="industry" control={form.control}>
                  {(field) => (
                    <FormItem>
                      <FormLabel>Industry</FormLabel>
                      <FormControl>
                        <IndustryInput
                          {...field}
                          placeholder="Select your industry"
                        />
                      </FormControl>
                      <FormMessage>
                        {form.formState.errors.industry?.message}
                      </FormMessage>
                    </FormItem>
                  )}
                </FormField>

                  <FormField name="businessType" control={form.control}>
                    {(field) => (
                      <FormItem>
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
                      <FormLabel>Business address</FormLabel>
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

                <FormField name="description" control={form.control}>
                  {(field) => (
                    <FormItem className="col-span-2">
                      <FormLabel>Business description</FormLabel>
                      <FormControl>
                        <Textarea
                          {...field}
                          rows={4}
                          placeholder="In 3–5 sentences, describe what your business does and how it creates value."
                        />
                      </FormControl>
                      <FormMessage>
                        {form.formState.errors.description?.message}
                      </FormMessage>
                    </FormItem>
                  )}
                </FormField>
              </CardContent>
            </Card>

            {/* Snapshot card */}
            <Card className="border border-slate-800/80 bg-slate-950/90">
              <CardHeader className="border-0 pb-2">
                <CardTitle className="text-sm">What to expect next</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3 text-[11px] text-slate-300">
                <p>
                  After you submit this form, we'll review your details and
                  confirm fit, scope, and timing. No payment is required to
                  complete the intake.
                </p>
                <ul className="space-y-1.5">
                  <li>• Review and alignment on goals and audience.</li>
                  <li>• Clarifying questions where needed.</li>
                  <li>• Confirmation of timeline and next steps.</li>
                </ul>
                <p className="text-slate-400">
                  The more specific you are, the more precise and compelling
                  your finished plan can be.
                </p>
              </CardContent>
            </Card>
          </div>

          {/* Offering & customers */}
          <div className="grid gap-5 md:grid-cols-2">
            <Card className="border border-slate-800/80 bg-slate-950/90">
              <CardHeader className="border-0 pb-3">
                <CardTitle className="text-sm">What you offer</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <FormField name="productKeywords" control={form.control}>
                  {(field) => (
                    <FormItem>
                      <FormLabel>Product / service keywords</FormLabel>
                      <FormControl>
                        <Textarea
                          {...field}
                          rows={3}
                          placeholder="List key products or services, separated by commas."
                        />
                      </FormControl>
                      <FormMessage>
                        {form.formState.errors.productKeywords?.message}
                      </FormMessage>
                    </FormItem>
                  )}
                </FormField>

                <FormField name="sellingMethod" control={form.control}>
                  {(field) => (
                    <FormItem>
                      <FormLabel>Preferred selling method</FormLabel>
                      <FormControl>
                        <Textarea
                          {...field}
                          rows={3}
                          placeholder="Describe how you plan to sell: in-person, online, recurring, project-based, etc."
                        />
                      </FormControl>
                      <FormMessage>
                        {form.formState.errors.sellingMethod?.message}
                      </FormMessage>
                    </FormItem>
                  )}
                </FormField>
              </CardContent>
            </Card>

            <Card className="border border-slate-800/80 bg-slate-950/90">
              <CardHeader className="border-0 pb-3">
                <CardTitle className="text-sm">
                  Customers &amp; positioning
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <FormField name="targetCustomer" control={form.control}>
                  {(field) => (
                    <FormItem>
                      <FormLabel>Target customer</FormLabel>
                      <FormControl>
                        <Textarea
                          {...field}
                          rows={3}
                          placeholder="Who is your ideal customer? Include demographics, behaviors, and context."
                        />
                      </FormControl>
                      <FormMessage>
                        {form.formState.errors.targetCustomer?.message}
                      </FormMessage>
                    </FormItem>
                  )}
                </FormField>

                <FormField name="pricingModel" control={form.control}>
                  {(field) => (
                    <FormItem>
                      <FormLabel>Pricing model</FormLabel>
                      <FormControl>
                        <Textarea
                          {...field}
                          rows={3}
                          placeholder="Describe your pricing (e.g., flat-fee, tiered, hourly, subscription, retainers)."
                        />
                      </FormControl>
                      <FormMessage>
                        {form.formState.errors.pricingModel?.message}
                      </FormMessage>
                    </FormItem>
                  )}
                </FormField>
              </CardContent>
            </Card>
          </div>

          {/* Financial snapshot & founder background */}
          <div className="grid gap-5 md:grid-cols-2">
            <Card className="border border-slate-800/80 bg-slate-950/90">
              <CardHeader className="border-0 pb-3">
                <CardTitle className="text-sm">
                  Financial snapshot (high level)
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <FormField name="estimatedRevenue" control={form.control}>
                  {(field) => (
                    <FormItem>
                      <FormLabel>Estimated annual revenue</FormLabel>
                      <FormControl>
                        <Textarea
                          {...field}
                          rows={2}
                          placeholder="Share your expected first-year or steady-state annual revenue (ranges are okay)."
                        />
                      </FormControl>
                      <FormMessage>
                        {form.formState.errors.estimatedRevenue?.message}
                      </FormMessage>
                    </FormItem>
                  )}
                </FormField>

                <FormField name="startupCosts" control={form.control}>
                  {(field) => (
                    <FormItem>
                      <FormLabel>Startup costs</FormLabel>
                      <FormControl>
                        <Textarea
                          {...field}
                          rows={2}
                          placeholder="List your one-time startup costs (build-out, equipment, launch, etc.)."
                        />
                      </FormControl>
                      <FormMessage>
                        {form.formState.errors.startupCosts?.message}
                      </FormMessage>
                    </FormItem>
                  )}
                </FormField>

                <FormField name="monthlyCosts" control={form.control}>
                  {(field) => (
                    <FormItem>
                      <FormLabel>Ongoing monthly costs</FormLabel>
                      <FormControl>
                        <Textarea
                          {...field}
                          rows={2}
                          placeholder="List key monthly costs (rent, payroll, software, marketing, etc.)."
                        />
                      </FormControl>
                      <FormMessage>
                        {form.formState.errors.monthlyCosts?.message}
                      </FormMessage>
                    </FormItem>
                  )}
                </FormField>
              </CardContent>
            </Card>

            <Card className="border border-slate-800/80 bg-slate-950/90">
              <CardHeader className="border-0 pb-3">
                <CardTitle className="text-sm">
                  Founder background &amp; story
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <FormField name="founderBackground" control={form.control}>
                  {(field) => (
                    <FormItem>
                      <FormLabel>Founder background</FormLabel>
                      <FormControl>
                        <Textarea
                          {...field}
                          rows={5}
                          placeholder="Share your experience, expertise, and why you are the right person or team to build this business."
                        />
                      </FormControl>
                      <FormMessage>
                        {form.formState.errors.founderBackground?.message}
                      </FormMessage>
                    </FormItem>
                  )}
                </FormField>
              </CardContent>
            </Card>
          </div>

          <motion.div
            className="flex flex-col items-start justify-between gap-4 border-t border-slate-800/80 pt-4 text-[11px] text-slate-400 md:flex-row md:items-center"
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.35 }}
          >
            <div>
              <p className="font-medium text-slate-100">
                Ready? Submit your intake for review.
              </p>
              <p className="mt-1 max-w-xl">
                We'll review your information, follow up with any clarifying
                questions, and outline next steps. No automatic billing or
                commitments from this form alone.
              </p>
            </div>
            <Button
              type="submit"
              size="lg"
              className="group rounded-full px-6 text-xs sm:text-sm"
            >
              Submit intake
            </Button>
          </motion.div>
        </Form>
      </div>
    </PageShell>
  );
}

export default IntakeFormPage;
