import * as React from "react";
import * as TooltipPrimitive from "@radix-ui/react-tooltip";
import { cn } from "../../lib/utils";

export const TOOLTIP_TEXT = {
  cogs:
    "Direct cost to make or deliver what you sell. Skip if unsure; we will use industry estimates.",
  expectedRevenueGrowth:
    "How fast you expect revenue to increase. Skip if unsure; we will estimate.",
  unitsSoldPerMonth:
    "Number of units, items, or customers sold each month. Skip if unsure; we will estimate.",
  taxRate:
    "Your estimated business tax rate. Skip if unsure; we will apply a standard rate.",

  marketingExpense:
    "Monthly advertising or promotion spend. Skip if unsure; we will estimate.",
  rAndDExpense:
    "Spending on improving products, services, or technology. Skip if unsure; we will estimate.",
  sgAndAExpense:
    "General admin costs like office supplies or software. Skip if unsure; we will estimate.",
  otherOpExpense:
    "Any other monthly cost not listed above. Can be used for startup costs. Skip if unsure.",
  rentLeaseExpense:
    "Monthly office or retail rent. Skip if unsure; we will estimate.",
  otherDebtPayments:
    "Monthly payments for smaller loans or credit lines. Skip if unsure; we will assume zero.",
  currentPayroll:
    "Total monthly payroll for employees or contractors. Skip if unsure; we will estimate.",
  currentEmployees:
    "Total current employees. Skip if unsure; we will estimate.",
  plannedEmployees5Years:
    "Expected number of employees in five years. Skip if unsure; we will estimate.",

  currentCapex:
    "Recent spending on long-term assets like equipment. Skip if unsure; we will estimate.",
  plannedCapex:
    "Expected major asset purchases over the next five years. Skip if unsure; we will estimate.",
  arBalance:
    "Money owed to you by customers. Skip if unsure; we will use industry defaults.",
  apBalance:
    "Money you owe to suppliers. Skip if unsure; we will use industry defaults.",
  inventoryBalance:
    "Value of products or materials on hand. Skip if unsure; we will use industry defaults.",

  totalDebtOutstanding:
    "Total business loans you owe. Skip if unsure; we will assume zero.",
  annualInterest:
    "Yearly interest paid on loans. Skip if unsure; we will estimate.",
  annualPrincipal:
    "Yearly repayment of loan principal. Skip if unsure; we will estimate.",
  ownerCompensation:
    "Amount you pay yourself. Skip if unsure; we will assume zero.",
  cashOnHand:
    "Cash the business has available. Skip if unsure; we will estimate.",

  businessDescription:
    "Describe your business in your own words. This helps us understand your tone and vision. If you’re unsure what to write, you can skip it — we will refine and enhance your description using the rest of your information.",
  businessAddress:
    "Start typing your address and choose your exact location from the popup. Make sure to select a full, complete address so your plan includes accurate local market and demographic data.",
  founderBackground:
    "Tell us about the founder or founders. Include names, their role in the business, relevant experience, and what makes them well-suited to run this business. For example: 'Larry J – Chief Marketing Officer, 10 years of marketing experience, MBA, led multiple successful campaigns.' The more detail you provide, the stronger the plan will be.",
  productKeywords:
    "List the key products or services you offer. This helps us personalize your plan with details specific to your business. If you’re not sure what to write, you can skip this — we’ll use your industry and business type to identify the most common offerings.",
  customerAdditionalDetails:
    "Add any helpful context about your target customers — behaviors, locations, niches, or specific groups you want to reach. This helps us personalize your plan’s positioning. If you’re not sure what to write, you can skip this.",
} as const;

const TooltipProvider = TooltipPrimitive.Provider;

const Tooltip = TooltipPrimitive.Root;

const TooltipTrigger = TooltipPrimitive.Trigger;

const TooltipContent = React.forwardRef<
  React.ElementRef<typeof TooltipPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof TooltipPrimitive.Content>
>(({ className, sideOffset = 4, ...props }, ref) => (
  <TooltipPrimitive.Content
    ref={ref}
    sideOffset={sideOffset}
    className={cn(
      "z-50 overflow-hidden rounded-md border border-slate-800/80 bg-slate-900/95 px-2 py-1 text-[11px] text-slate-100 shadow-soft",
      className
    )}
    {...props}
  />
));

TooltipContent.displayName = TooltipPrimitive.Content.displayName;

export { Tooltip, TooltipTrigger, TooltipContent, TooltipProvider };

