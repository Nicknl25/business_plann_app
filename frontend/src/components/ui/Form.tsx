import * as React from "react";
import {
  Controller,
  FormProvider,
  type FieldValues,
  type UseFormReturn,
  type ControllerRenderProps,
  type Path
} from "react-hook-form";
import { cn } from "../../lib/utils";

/* ---------------------------------------
   Form Wrapper — CLEAN, CORRECT VERSION
----------------------------------------*/

interface FormProps<TFieldValues extends FieldValues> {
  form: UseFormReturn<TFieldValues>;
  onSubmit: (values: TFieldValues) => void;
  className?: string;
  children: React.ReactNode;
}

export function Form<TFieldValues extends FieldValues>({
  form,
  onSubmit,
  className,
  children,
}: FormProps<TFieldValues>) {
  return (
    <FormProvider {...form}>
      <form
        onSubmit={form.handleSubmit(onSubmit)}
        className={cn("space-y-6", className)}
      >
        {children}
      </form>
    </FormProvider>
  );
}

/* ---------------------------------------
   FormField
----------------------------------------*/

interface FormFieldProps<TFieldValues extends FieldValues> {
  name: Path<TFieldValues>;
  control: UseFormReturn<TFieldValues>["control"];
  children: (
    field: ControllerRenderProps<TFieldValues, Path<TFieldValues>>
  ) => React.ReactNode;
}

export function FormField<TFieldValues extends FieldValues>({
  name,
  control,
  children,
}: FormFieldProps<TFieldValues>) {
  return (
    <Controller
      name={name}
      control={control}
      render={({ field }) => <>{children(field)}</>}
    />
  );
}

/* ---------------------------------------
   UI Helpers
----------------------------------------*/

export function FormItem({
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn("flex flex-col gap-1.5 text-xs text-slate-300", className)}
      {...props}
    />
  );
}

export function FormLabel({
  className,
  ...props
}: React.LabelHTMLAttributes<HTMLLabelElement>) {
  return (
    <label
      className={cn(
        "text-[11px] font-medium tracking-tight text-slate-300",
        className
      )}
      {...props}
    />
  );
}

export function FormControl({
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("mt-1", className)} {...props} />;
}

export function FormMessage({
  className,
  children,
  ...props
}: React.HTMLAttributes<HTMLParagraphElement>) {
  if (!children) return null;
  return (
    <p
      className={cn("text-[11px] text-red-400/90", className)}
      {...props}
    >
      {children}
    </p>
  );
}
