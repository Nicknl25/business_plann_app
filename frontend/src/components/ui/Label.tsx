import * as React from "react";
import { cn } from "../../lib/utils";

export interface LabelProps
  extends React.LabelHTMLAttributes<HTMLLabelElement> {}

const Label = React.forwardRef<HTMLLabelElement, LabelProps>(
  ({ className, ...props }, ref) => (
    <label
      ref={ref}
      className={cn(
        "block text-[11px] font-medium tracking-tight text-slate-300",
        className
      )}
      {...props}
    />
  )
);

Label.displayName = "Label";

export { Label };

