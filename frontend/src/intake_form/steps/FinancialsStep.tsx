import type React from "react";
import { useFormContext } from "react-hook-form";
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
import type { IntakeValues } from "../schema";

export default function FinancialsStep() {
  const form = useFormContext<IntakeValues>();

  function formatNumericForDisplay(raw: string): string {
    const withoutCommas = raw.replace(/,/g, "");
    if (!withoutCommas.trim()) return "";

    const parts = withoutCommas.split(".");
    const integerPart = parts[0].replace(/[^\d]/g, "");
    const fractionalPart = parts[1]?.replace(/[^\d]/g, "") ?? "";

    if (!integerPart) {
      return fractionalPart ? `0.${fractionalPart}` : "";
    }

    const parsedInteger = Number(integerPart);
    if (!Number.isFinite(parsedInteger)) return "";

    const formattedInteger = parsedInteger.toLocaleString("en-US", {
      maximumFractionDigits: 0,
    });

    if (!fractionalPart) return formattedInteger;

    return `${formattedInteger}.${fractionalPart}`;
  }

  function handleNumericChange(
    event: React.ChangeEvent<HTMLInputElement>,
    onChange: (value: unknown) => void
  ) {
    const rawValue = event.target.value ?? "";
    const sanitized = rawValue.replace(/-/g, "");
    onChange(sanitized);
  }

  function handleNumericBlur(
    event: React.FocusEvent<HTMLInputElement>,
    fieldName: keyof IntakeValues
  ) {
    const rawValue = event.target.value ?? "";
    const withoutCommas = rawValue.replace(/,/g, "").trim();

    if (!withoutCommas) {
      form.setValue(fieldName, "", {
        shouldValidate: true,
        shouldDirty: true,
      });
      return;
    }

    const parsed = Number(withoutCommas);
    if (!Number.isFinite(parsed)) {
      form.setValue(fieldName, rawValue, {
        shouldValidate: true,
        shouldDirty: true,
      });
      return;
    }

    const nonNegative = parsed < 0 ? 0 : parsed;
    const formatted = formatNumericForDisplay(String(nonNegative));

    form.setValue(fieldName, formatted, {
      shouldValidate: true,
      shouldDirty: true,
    });
  }

  return (
    <Card className="border border-slate-800/80 bg-slate-950/90">
      <CardHeader className="border-0 pb-3">
        <CardTitle className="text-sm">Financials</CardTitle>
      </CardHeader>
      <CardContent className="space-y-6">
        <FormField name="businessStartDate" control={form.control}>
          {(field) => (
            <FormItem>
              <FormLabel>Business Start Date</FormLabel>
              <FormControl>
                <Input
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

        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          <div className="space-y-3 rounded-lg border border-slate-800/80 bg-slate-950/80 p-4">
            <div className="text-[11px] font-semibold tracking-tight text-slate-200">
              Revenue Model
            </div>
            <div className="grid gap-3">
              <FormField name="currentRevenue" control={form.control}>
                {(field) => (
                  <FormItem>
                    <FormLabel>
                      Current Revenue{" "}
                      <HelpTooltip
                        fieldName="currentRevenue"
                        text="Enter your current annual revenue. Use 0 if you are pre-revenue."
                      />
                    </FormLabel>
                    <FormControl>
                      <Input
                        {...field}
                        type="text"
                        inputMode="decimal"
                        min={0}
                        placeholder="Enter current revenue"
                        onChange={(event) =>
                          handleNumericChange(event, field.onChange)
                        }
                        onBlur={(event) => {
                          field.onBlur();
                          handleNumericBlur(event, "currentRevenue");
                        }}
                      />
                    </FormControl>
                    <FormMessage>
                      {form.formState.errors.currentRevenue?.message}
                    </FormMessage>
                  </FormItem>
                )}
              </FormField>

              <FormField name="currentCogs" control={form.control}>
                {(field) => (
                  <FormItem>
                    <FormLabel>
                      Cost of Goods Sold (COGS){" "}
                      <HelpTooltip fieldName="currentCogs" text={TOOLTIP_TEXT.cogs} />
                    </FormLabel>
                    <FormControl>
                      <Input
                        {...field}
                        type="text"
                        inputMode="decimal"
                        min={0}
                        placeholder="Required if revenue is greater than 0"
                        onChange={(event) =>
                          handleNumericChange(event, field.onChange)
                        }
                        onBlur={(event) => {
                          field.onBlur();
                          handleNumericBlur(event, "currentCogs");
                        }}
                      />
                    </FormControl>
                    <FormMessage>
                      {form.formState.errors.currentCogs?.message}
                    </FormMessage>
                  </FormItem>
                )}
              </FormField>

              <FormField
                name="expectedRevenueGrowthPctNextYear"
                control={form.control}
              >
                {(field) => (
                  <FormItem>
                    <FormLabel>
                      Expected Revenue Growth (%){" "}
                      <HelpTooltip
                        fieldName="expectedRevenueGrowthPctNextYear"
                        text={TOOLTIP_TEXT.expectedRevenueGrowth}
                      />
                    </FormLabel>
                    <FormControl>
                      <Input
                        {...field}
                        type="text"
                        inputMode="decimal"
                        min={0}
                        max={100}
                        step={1}
                        placeholder="Required if revenue is greater than 0"
                        onChange={(event) =>
                          handleNumericChange(event, field.onChange)
                        }
                      />
                    </FormControl>
                    <FormMessage>
                      {
                        form.formState.errors.expectedRevenueGrowthPctNextYear
                          ?.message
                      }
                    </FormMessage>
                  </FormItem>
                )}
              </FormField>

              <FormField name="taxRate" control={form.control}>
                {(field) => (
                  <FormItem>
                    <FormLabel>
                      Tax Rate{" "}
                      <HelpTooltip fieldName="taxRate" text={TOOLTIP_TEXT.taxRate} />
                    </FormLabel>
                    <FormControl>
                      <Input
                        {...field}
                        type="text"
                        inputMode="decimal"
                        min={0}
                        onChange={(event) =>
                          handleNumericChange(event, field.onChange)
                        }
                        onBlur={(event) => {
                          field.onBlur();
                          handleNumericBlur(event, "taxRate");
                        }}
                      />
                    </FormControl>
                    <FormMessage>{form.formState.errors.taxRate?.message}</FormMessage>
                  </FormItem>
                )}
              </FormField>
            </div>
          </div>

          <div className="space-y-3 rounded-lg border border-slate-800/80 bg-slate-950/80 p-4">
            <div className="text-[11px] font-semibold tracking-tight text-slate-200">
              Operating Expenses
            </div>
            <div className="grid gap-3">
              <FormField name="marketingExpense" control={form.control}>
                {(field) => (
                  <FormItem>
                    <FormLabel>
                      Marketing Expense{" "}
                      <HelpTooltip
                        fieldName="marketingExpense"
                        text={TOOLTIP_TEXT.marketingExpense}
                      />
                    </FormLabel>
                    <FormControl>
                      <Input
                        {...field}
                        type="text"
                        inputMode="decimal"
                        min={0}
                        onChange={(event) =>
                          handleNumericChange(event, field.onChange)
                        }
                        onBlur={(event) => {
                          field.onBlur();
                          handleNumericBlur(event, "marketingExpense");
                        }}
                      />
                    </FormControl>
                    <FormMessage>
                      {form.formState.errors.marketingExpense?.message}
                    </FormMessage>
                  </FormItem>
                )}
              </FormField>

              <FormField name="rAndDExpense" control={form.control}>
                {(field) => (
                  <FormItem>
                    <FormLabel>
                      Research &amp; Development (R&amp;D){" "}
                      <HelpTooltip fieldName="rAndDExpense" text={TOOLTIP_TEXT.rAndDExpense} />
                    </FormLabel>
                    <FormControl>
                      <Input
                        {...field}
                        type="text"
                        inputMode="decimal"
                        min={0}
                        onChange={(event) =>
                          handleNumericChange(event, field.onChange)
                        }
                        onBlur={(event) => {
                          field.onBlur();
                          handleNumericBlur(event, "rAndDExpense");
                        }}
                      />
                    </FormControl>
                    <FormMessage>{form.formState.errors.rAndDExpense?.message}</FormMessage>
                  </FormItem>
                )}
              </FormField>

              <FormField name="sgaExpense" control={form.control}>
                {(field) => (
                  <FormItem>
                    <FormLabel>
                      SG&amp;A Expense{" "}
                      <HelpTooltip
                        fieldName="sgaExpense"
                        text={(TOOLTIP_TEXT as any).sgaExpense}
                      />
                    </FormLabel>
                    <FormControl>
                      <Input
                        {...field}
                        type="text"
                        inputMode="decimal"
                        min={0}
                        onChange={(event) =>
                          handleNumericChange(event, field.onChange)
                        }
                        onBlur={(event) => {
                          field.onBlur();
                          handleNumericBlur(event, "sgaExpense");
                        }}
                      />
                    </FormControl>
                    <FormMessage>{form.formState.errors.sgaExpense?.message}</FormMessage>
                  </FormItem>
                )}
              </FormField>

              <FormField name="otherOperatingExpense" control={form.control}>
                {(field) => (
                  <FormItem>
                    <FormLabel>
                      Other Operating Expense{" "}
                      <HelpTooltip
                        fieldName="otherOperatingExpense"
                        text={(TOOLTIP_TEXT as any).otherOperatingExpense}
                      />
                    </FormLabel>
                    <FormControl>
                      <Input
                        {...field}
                        type="text"
                        inputMode="decimal"
                        min={0}
                        onChange={(event) =>
                          handleNumericChange(event, field.onChange)
                        }
                        onBlur={(event) => {
                          field.onBlur();
                          handleNumericBlur(event, "otherOperatingExpense");
                        }}
                      />
                    </FormControl>
                    <FormMessage>
                      {form.formState.errors.otherOperatingExpense?.message}
                    </FormMessage>
                  </FormItem>
                )}
              </FormField>

              <FormField name="monthlyRentExpense" control={form.control}>
                {(field) => (
                  <FormItem>
                    <FormLabel>
                      Monthly Rent / Lease Expense{" "}
                      <HelpTooltip
                        fieldName="monthlyRentExpense"
                        text={TOOLTIP_TEXT.rentLeaseExpense}
                      />
                    </FormLabel>
                    <FormControl>
                      <Input
                        {...field}
                        type="text"
                        inputMode="decimal"
                        min={0}
                        onChange={(event) =>
                          handleNumericChange(event, field.onChange)
                        }
                        onBlur={(event) => {
                          field.onBlur();
                          handleNumericBlur(event, "monthlyRentExpense");
                        }}
                      />
                    </FormControl>
                    <FormMessage>
                      {form.formState.errors.monthlyRentExpense?.message}
                    </FormMessage>
                  </FormItem>
                )}
              </FormField>

              <FormField name="otherMonthlyDebtPayments" control={form.control}>
                {(field) => (
                  <FormItem>
                    <FormLabel>
                      Other Monthly Debt Payments{" "}
                      <HelpTooltip
                        fieldName="otherMonthlyDebtPayments"
                        text={TOOLTIP_TEXT.otherDebtPayments}
                      />
                    </FormLabel>
                    <FormControl>
                      <Input
                        {...field}
                        type="text"
                        inputMode="decimal"
                        min={0}
                        onChange={(event) =>
                          handleNumericChange(event, field.onChange)
                        }
                        onBlur={(event) => {
                          field.onBlur();
                          handleNumericBlur(event, "otherMonthlyDebtPayments");
                        }}
                      />
                    </FormControl>
                    <FormMessage>
                      {form.formState.errors.otherMonthlyDebtPayments?.message}
                    </FormMessage>
                  </FormItem>
                )}
              </FormField>

              <FormField name="currentPayroll" control={form.control}>
                {(field) => (
                  <FormItem>
                    <FormLabel>
                      Current Payroll{" "}
                      <HelpTooltip
                        fieldName="currentPayroll"
                        text={TOOLTIP_TEXT.currentPayroll}
                      />
                    </FormLabel>
                    <FormControl>
                      <Input
                        {...field}
                        type="text"
                        inputMode="decimal"
                        min={0}
                        onChange={(event) =>
                          handleNumericChange(event, field.onChange)
                        }
                        onBlur={(event) => {
                          field.onBlur();
                          handleNumericBlur(event, "currentPayroll");
                        }}
                      />
                    </FormControl>
                    <FormMessage>
                      {form.formState.errors.currentPayroll?.message}
                    </FormMessage>
                  </FormItem>
                )}
              </FormField>

              <FormField name="currentNumEmployees" control={form.control}>
                {(field) => (
                  <FormItem>
                    <FormLabel>
                      Current Number of Employees{" "}
                      <HelpTooltip
                        fieldName="currentNumEmployees"
                        text={TOOLTIP_TEXT.currentEmployees}
                      />
                    </FormLabel>
                    <FormControl>
                      <Input
                        {...field}
                        type="text"
                        inputMode="decimal"
                        min={0}
                        onChange={(event) =>
                          handleNumericChange(event, field.onChange)
                        }
                        onBlur={(event) => {
                          field.onBlur();
                          handleNumericBlur(event, "currentNumEmployees");
                        }}
                      />
                    </FormControl>
                    <FormMessage>
                      {form.formState.errors.currentNumEmployees?.message}
                    </FormMessage>
                  </FormItem>
                )}
              </FormField>

              <FormField name="plannedNumEmployees5yrs" control={form.control}>
                {(field) => (
                  <FormItem>
                    <FormLabel>
                      Planned Number of Employees in 5 Years{" "}
                      <HelpTooltip
                        fieldName="plannedNumEmployees5yrs"
                        text={TOOLTIP_TEXT.plannedEmployees5Years}
                      />
                    </FormLabel>
                    <FormControl>
                      <Input
                        {...field}
                        type="text"
                        inputMode="decimal"
                        min={0}
                        onChange={(event) =>
                          handleNumericChange(event, field.onChange)
                        }
                        onBlur={(event) => {
                          field.onBlur();
                          handleNumericBlur(event, "plannedNumEmployees5yrs");
                        }}
                      />
                    </FormControl>
                    <FormMessage>
                      {form.formState.errors.plannedNumEmployees5yrs?.message}
                    </FormMessage>
                  </FormItem>
                )}
              </FormField>
            </div>
          </div>

          <div className="space-y-3 rounded-lg border border-slate-800/80 bg-slate-950/80 p-4">
            <div className="text-[11px] font-semibold tracking-tight text-slate-200">
              Capital Expenditures &amp; Working Capital
            </div>
            <div className="grid gap-3">
              <FormField name="currentCapex" control={form.control}>
                {(field) => (
                  <FormItem>
                    <FormLabel>
                      Current Capex{" "}
                      <HelpTooltip fieldName="currentCapex" text={TOOLTIP_TEXT.currentCapex} />
                    </FormLabel>
                    <FormControl>
                      <Input
                        {...field}
                        type="text"
                        inputMode="decimal"
                        min={0}
                        onChange={(event) =>
                          handleNumericChange(event, field.onChange)
                        }
                        onBlur={(event) => {
                          field.onBlur();
                          handleNumericBlur(event, "currentCapex");
                        }}
                      />
                    </FormControl>
                    <FormMessage>{form.formState.errors.currentCapex?.message}</FormMessage>
                  </FormItem>
                )}
              </FormField>

              <FormField name="plannedCapex5yr" control={form.control}>
                {(field) => (
                  <FormItem>
                    <FormLabel>
                      Planned Capex (5 Years){" "}
                      <HelpTooltip
                        fieldName="plannedCapex5yr"
                        text={TOOLTIP_TEXT.plannedCapex}
                      />
                    </FormLabel>
                    <FormControl>
                      <Input
                        {...field}
                        type="text"
                        inputMode="decimal"
                        min={0}
                        onChange={(event) =>
                          handleNumericChange(event, field.onChange)
                        }
                        onBlur={(event) => {
                          field.onBlur();
                          handleNumericBlur(event, "plannedCapex5yr");
                        }}
                      />
                    </FormControl>
                    <FormMessage>{form.formState.errors.plannedCapex5yr?.message}</FormMessage>
                  </FormItem>
                )}
              </FormField>

              <FormField name="arBalance" control={form.control}>
                {(field) => (
                  <FormItem>
                    <FormLabel>
                      Accounts Receivable Balance{" "}
                      <HelpTooltip fieldName="arBalance" text={TOOLTIP_TEXT.arBalance} />
                    </FormLabel>
                    <FormControl>
                      <Input
                        {...field}
                        type="text"
                        inputMode="decimal"
                        min={0}
                        onChange={(event) =>
                          handleNumericChange(event, field.onChange)
                        }
                        onBlur={(event) => {
                          field.onBlur();
                          handleNumericBlur(event, "arBalance");
                        }}
                      />
                    </FormControl>
                    <FormMessage>{form.formState.errors.arBalance?.message}</FormMessage>
                  </FormItem>
                )}
              </FormField>

              <FormField name="apBalance" control={form.control}>
                {(field) => (
                  <FormItem>
                    <FormLabel>
                      Accounts Payable Balance{" "}
                      <HelpTooltip fieldName="apBalance" text={TOOLTIP_TEXT.apBalance} />
                    </FormLabel>
                    <FormControl>
                      <Input
                        {...field}
                        type="text"
                        inputMode="decimal"
                        min={0}
                        onChange={(event) =>
                          handleNumericChange(event, field.onChange)
                        }
                        onBlur={(event) => {
                          field.onBlur();
                          handleNumericBlur(event, "apBalance");
                        }}
                      />
                    </FormControl>
                    <FormMessage>{form.formState.errors.apBalance?.message}</FormMessage>
                  </FormItem>
                )}
              </FormField>

              <FormField name="inventoryBalance" control={form.control}>
                {(field) => (
                  <FormItem>
                    <FormLabel>
                      Inventory Balance{" "}
                      <HelpTooltip fieldName="inventoryBalance" text={TOOLTIP_TEXT.inventoryBalance} />
                    </FormLabel>
                    <FormControl>
                      <Input
                        {...field}
                        type="text"
                        inputMode="decimal"
                        min={0}
                        onChange={(event) =>
                          handleNumericChange(event, field.onChange)
                        }
                        onBlur={(event) => {
                          field.onBlur();
                          handleNumericBlur(event, "inventoryBalance");
                        }}
                      />
                    </FormControl>
                    <FormMessage>{form.formState.errors.inventoryBalance?.message}</FormMessage>
                  </FormItem>
                )}
              </FormField>
            </div>
          </div>

          <div className="space-y-3 rounded-lg border border-slate-800/80 bg-slate-950/80 p-4">
            <div className="text-[11px] font-semibold tracking-tight text-slate-200">
              Debt &amp; Liquidity
            </div>
            <div className="grid gap-3">
              <FormField name="totalDebtOutstanding" control={form.control}>
                {(field) => (
                  <FormItem>
                    <FormLabel>
                      Total Debt Outstanding{" "}
                      <HelpTooltip
                        fieldName="totalDebtOutstanding"
                        text={TOOLTIP_TEXT.totalDebtOutstanding}
                      />
                    </FormLabel>
                    <FormControl>
                      <Input
                        {...field}
                        type="text"
                        inputMode="decimal"
                        min={0}
                        onChange={(event) =>
                          handleNumericChange(event, field.onChange)
                        }
                        onBlur={(event) => {
                          field.onBlur();
                          handleNumericBlur(event, "totalDebtOutstanding");
                        }}
                      />
                    </FormControl>
                    <FormMessage>
                      {form.formState.errors.totalDebtOutstanding?.message}
                    </FormMessage>
                  </FormItem>
                )}
              </FormField>

              <FormField name="annualInterestPayment" control={form.control}>
                {(field) => (
                  <FormItem>
                    <FormLabel>
                      Annual Interest Payment{" "}
                      <HelpTooltip
                        fieldName="annualInterestPayment"
                        text={(TOOLTIP_TEXT as any).annualInterestPayment}
                      />
                    </FormLabel>
                    <FormControl>
                      <Input
                        {...field}
                        type="text"
                        inputMode="decimal"
                        min={0}
                        onChange={(event) =>
                          handleNumericChange(event, field.onChange)
                        }
                        onBlur={(event) => {
                          field.onBlur();
                          handleNumericBlur(event, "annualInterestPayment");
                        }}
                      />
                    </FormControl>
                    <FormMessage>
                      {form.formState.errors.annualInterestPayment?.message}
                    </FormMessage>
                  </FormItem>
                )}
              </FormField>

              <FormField name="annualPrincipalPayment" control={form.control}>
                {(field) => (
                  <FormItem>
                    <FormLabel>
                      Annual Principal Payment{" "}
                      <HelpTooltip
                        fieldName="annualPrincipalPayment"
                        text={(TOOLTIP_TEXT as any).annualPrincipalPayment}
                      />
                    </FormLabel>
                    <FormControl>
                      <Input
                        {...field}
                        type="text"
                        inputMode="decimal"
                        min={0}
                        onChange={(event) =>
                          handleNumericChange(event, field.onChange)
                        }
                        onBlur={(event) => {
                          field.onBlur();
                          handleNumericBlur(event, "annualPrincipalPayment");
                        }}
                      />
                    </FormControl>
                    <FormMessage>
                      {form.formState.errors.annualPrincipalPayment?.message}
                    </FormMessage>
                  </FormItem>
                )}
              </FormField>

              <FormField name="ownerCompensation" control={form.control}>
                {(field) => (
                  <FormItem>
                    <FormLabel>
                      Owner Compensation (if applicable){" "}
                      <HelpTooltip
                        fieldName="ownerCompensation"
                        text={TOOLTIP_TEXT.ownerCompensation}
                      />
                    </FormLabel>
                    <FormControl>
                      <Input
                        {...field}
                        type="text"
                        inputMode="decimal"
                        min={0}
                        onChange={(event) =>
                          handleNumericChange(event, field.onChange)
                        }
                        onBlur={(event) => {
                          field.onBlur();
                          handleNumericBlur(event, "ownerCompensation");
                        }}
                      />
                    </FormControl>
                    <FormMessage>
                      {form.formState.errors.ownerCompensation?.message}
                    </FormMessage>
                  </FormItem>
                )}
              </FormField>

              <FormField name="cashOnHand" control={form.control}>
                {(field) => (
                  <FormItem>
                    <FormLabel>
                      Cash on Hand{" "}
                      <HelpTooltip fieldName="cashOnHand" text={TOOLTIP_TEXT.cashOnHand} />
                    </FormLabel>
                    <FormControl>
                      <Input
                        {...field}
                        type="text"
                        inputMode="decimal"
                        min={0}
                        onChange={(event) =>
                          handleNumericChange(event, field.onChange)
                        }
                        onBlur={(event) => {
                          field.onBlur();
                          handleNumericBlur(event, "cashOnHand");
                        }}
                      />
                    </FormControl>
                    <FormMessage>{form.formState.errors.cashOnHand?.message}</FormMessage>
                  </FormItem>
                )}
              </FormField>
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
