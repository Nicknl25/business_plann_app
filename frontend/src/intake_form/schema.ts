import { z } from "zod";

export function parseNumberFromString(
  value: string | undefined | null
): number | null {
  if (!value) return null;
  const normalized = value.replace(/,/g, "").trim();
  if (!normalized) return null;
  const parsed = Number(normalized);
  if (!Number.isFinite(parsed)) return null;
  return parsed;
}

export const intakeSchema = z
  .object({
    businessName: z.string().min(2, "Please enter your business name."),
    address: z.string().min(1, "Please select a full address from suggestions."),
    addressStreet: z.string().min(1, "Street address is required."),
    addressCity: z.string().min(1, "City is required."),
    addressState: z.string().min(1, "State is required."),
    addressZip: z.string().min(1, "ZIP code is required."),
    addressCountry: z.string().min(1, "Country is required."),
    productKeywords: z.string().optional(),
    firstName: z.string().min(1, "First Name is required."),
    lastName: z.string().min(1, "Last Name is required."),
    emailAddress: z.string().email("Please enter a valid email address."),
    phoneNumber: z.string().optional(),
    howDidYouHear: z.string().optional(),
    // Financials section
    businessStartDate: z.string().min(1, "Business Start Date is required."),
    currentRevenue: z.string().min(1, "Current Revenue is required."),
    currentCogs: z.string().optional(),
    otherOperatingExpense: z.string().optional(),
    monthlyRentExpense: z.string().optional(),
    otherMonthlyDebtPayments: z.string().optional(),
    currentPayroll: z.string().optional(),
    currentNumEmployees: z.string().optional(),
    currentCapex: z.string().optional(),
    arBalance: z.string().optional(),
    apBalance: z.string().optional(),
    inventoryBalance: z.string().optional(),
    totalDebtOutstanding: z.string().optional(),
    annualInterestPayment: z.string().optional(),
    annualPrincipalPayment: z.string().optional(),
    ownerCompensation: z.string().optional(),
    cashOnHand: z.string().optional(),
  })
  .superRefine((values, ctx) => {
    const addressParts = [
      values.addressStreet,
      values.addressCity,
      values.addressState,
      values.addressZip,
      values.addressCountry,
    ];
    const hasAllAddressParts = addressParts.every((v) => Boolean(v && v.trim()));
    if (values.address && values.address.trim() && !hasAllAddressParts) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["address"],
        message:
          "Please select a full address from suggestions (street, city, state, ZIP, country).",
      });
    }

    const nonNegativeNumericFields = [
      "currentRevenue",
      "currentCogs",
      "otherOperatingExpense",
      "currentPayroll",
      "currentNumEmployees",
      "currentCapex",
      "arBalance",
      "apBalance",
      "inventoryBalance",
      "totalDebtOutstanding",
      "annualInterestPayment",
      "annualPrincipalPayment",
      "ownerCompensation",
      "cashOnHand",
    ] as const;

    nonNegativeNumericFields.forEach((fieldName) => {
      const raw = (values as any)[fieldName];
      if (!raw) return;
      const parsed = parseNumberFromString(raw);
      if (parsed === null) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: [fieldName],
          message: "Enter a valid number.",
        });
        return;
      }
      if (parsed < 0) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: [fieldName],
          message: "Value must be zero or greater.",
        });
      }
    });

    const revenue = parseNumberFromString(values.currentRevenue);
    if (revenue !== null && revenue > 0) {
      if (!values.currentCogs) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: ["currentCogs"],
          message:
            "Cost of Goods Sold is required when revenue is greater than zero.",
        });
      }
    }
  });

export type IntakeValues = z.infer<typeof intakeSchema>;

export const serverFieldToFormField: Record<string, keyof IntakeValues> = {
  business_name: "businessName",
  address: "address",
  first_name: "firstName",
  last_name: "lastName",
  email_address: "emailAddress",
  phone_number: "phoneNumber",
  how_did_you_hear: "howDidYouHear",
  business_start_date: "businessStartDate",
  current_revenue: "currentRevenue",
  current_cogs: "currentCogs",
  other_operating_expense: "otherOperatingExpense",
  monthly_rent_expense: "monthlyRentExpense",
  other_monthly_debt_payments: "otherMonthlyDebtPayments",
  current_payroll: "currentPayroll",
  current_num_employees: "currentNumEmployees",
  current_capex: "currentCapex",
  ar_balance: "arBalance",
  ap_balance: "apBalance",
  inventory_balance: "inventoryBalance",
  total_debt_outstanding: "totalDebtOutstanding",
  annual_interest_payment: "annualInterestPayment",
  annual_principal_payment: "annualPrincipalPayment",
  owner_compensation: "ownerCompensation",
  cash_on_hand: "cashOnHand",
};

export const defaultValues: IntakeValues = {
  businessName: "",
  address: "",
  addressStreet: "",
  addressCity: "",
  addressState: "",
  addressZip: "",
  addressCountry: "",
  productKeywords: "",
  firstName: "",
  lastName: "",
  emailAddress: "",
  phoneNumber: "",
  howDidYouHear: "",
  businessStartDate: "",
  currentRevenue: "",
  currentCogs: "",
  otherOperatingExpense: "",
  monthlyRentExpense: "",
  otherMonthlyDebtPayments: "",
  currentPayroll: "",
  currentNumEmployees: "",
  currentCapex: "",
  arBalance: "",
  apBalance: "",
  inventoryBalance: "",
  totalDebtOutstanding: "",
  annualInterestPayment: "",
  annualPrincipalPayment: "",
  ownerCompensation: "",
  cashOnHand: "",
};
