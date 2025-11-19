import * as React from "react";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
  TooltipProvider,
} from "@/components/ui/tooltip";
import { Info } from "lucide-react";
import { cn } from "../../lib/utils";

interface HelpTooltipProps {
  text: string;
}

export function HelpTooltip({ text }: HelpTooltipProps) {
  return (
    <TooltipProvider delayDuration={150}>
      <Tooltip>
        <TooltipTrigger asChild>
          <button
            type="button"
            className={cn(
              "ml-1 inline-flex h-4 w-4 items-center justify-center rounded-full border border-slate-600/70 text-slate-400 transition-colors hover:border-slate-400 hover:text-slate-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400/70 focus-visible:ring-offset-1 focus-visible:ring-offset-slate-950"
            )}
          >
            <Info className="h-3 w-3" aria-hidden="true" />
            <span className="sr-only">More info</span>
          </button>
        </TooltipTrigger>

        <TooltipContent
          side="top"
          align="start"
          className={cn(
            "z-50 max-w-xs rounded-md border border-slate-700/80 bg-slate-900/95 px-2 py-1 text-[11px] text-slate-100 shadow-soft"
          )}
        >
          {text}
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}

export default HelpTooltip;
