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
    businessStartDate: z.string().min(1, "Business Start Date is required."),
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
};
