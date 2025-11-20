import React, { useEffect, useMemo, useState } from "react";
import { Input } from "./ui/Input";

type IndustryInputProps = React.InputHTMLAttributes<HTMLInputElement> & {
  error?: string;
};

type IndustryOption = {
  id: number;
  naics_code: string;
  display_name: string;
};

const IndustryInput = React.forwardRef<HTMLInputElement, IndustryInputProps>(
  (props, forwardedRef) => {
    const { name, id, value, onChange, onBlur, ...rest } = props;
    const [options, setOptions] = useState<IndustryOption[]>([]);
    const [selected, setSelected] = useState<IndustryOption | null>(null);
    const [loading, setLoading] = useState(false);
    const [open, setOpen] = useState(false);
    const [query, setQuery] = useState<string>((value as string) || "");
    const [activeIndex, setActiveIndex] = useState<number>(-1);

    const apiBase =
      ((import.meta as any).env &&
        (import.meta as any).env.VITE_API_BASE_URL) ||
      (((import.meta as any).env && (import.meta as any).env.DEV)
        ? "http://localhost:5000"
        : "");

    useEffect(() => {
      setQuery((value as string) || "");
    }, [value]);

    useEffect(() => {
      let cancelled = false;
      setLoading(true);

      const base =
        typeof apiBase === "string" && apiBase.length
          ? apiBase.replace(/\/$/, "")
          : "";
      const url = base ? `${base}/api/industry-types` : "/api/industry-types";

      fetch(url)
        .then(async (res) => {
          const contentType = res.headers.get("content-type") || "";
          if (!res.ok || !contentType.includes("application/json")) {
            const text = await res.text();
            throw new Error(
              `Failed to load industry types: ${res.status} ${res.statusText} (${contentType ||
                "no content-type"}) ${text.slice(0, 120)}`
            );
          }
          return (res.json() as Promise<IndustryOption[]>);
        })
        .then((data) => {
          if (!cancelled && Array.isArray(data)) {
            setOptions(data);
          }
        })
        .catch((err) => {
          console.error("Error loading industry types:", err);
        })
        .finally(() => {
          if (!cancelled) {
            setLoading(false);
          }
        });

      return () => {
        cancelled = true;
      };
    }, [apiBase]);

    const filteredOptions = useMemo(() => {
      const q = query.trim().toLowerCase();
      if (!q) return options;
      return options.filter((opt) =>
        opt.display_name.toLowerCase().includes(q)
      );
    }, [options, query]);

    useEffect(() => {
      if (!open || !filteredOptions.length) {
        setActiveIndex(-1);
      } else {
        setActiveIndex(0);
      }
    }, [open, filteredOptions]);

    const handleSelect = (opt: IndustryOption) => {
      const nextValue = opt.display_name;
      setSelected(opt);
      setQuery(nextValue);

      if (onChange) {
        onChange({
          target: {
            name,
            id,
            value: nextValue,
          },
        } as any);
      }

      setOpen(false);
    };

    const handleInputChange = (
      event: React.ChangeEvent<HTMLInputElement>
    ) => {
      setQuery(event.target.value);
      setOpen(true);
    };

    const handleKeyDown = (
      event: React.KeyboardEvent<HTMLInputElement>
    ) => {
      if (!open && (event.key === "ArrowDown" || event.key === "ArrowUp")) {
        setOpen(true);
        return;
      }

      if (!filteredOptions.length) {
        return;
      }

      if (event.key === "ArrowDown") {
        event.preventDefault();
        setActiveIndex((prev) => {
          if (prev === -1) return 0;
          return (prev + 1) % filteredOptions.length;
        });
      } else if (event.key === "ArrowUp") {
        event.preventDefault();
        setActiveIndex((prev) => {
          if (prev === -1) return filteredOptions.length - 1;
          return (prev - 1 + filteredOptions.length) % filteredOptions.length;
        });
      } else if (event.key === "Enter") {
        if (open && activeIndex >= 0 && activeIndex < filteredOptions.length) {
          event.preventDefault();
          handleSelect(filteredOptions[activeIndex]);
        }
      } else if (event.key === "Escape") {
        setOpen(false);
      }
    };

    const handleBlur = (event: React.FocusEvent<HTMLInputElement>) => {
      setTimeout(() => {
        setOpen(false);
        setQuery((value as string) || "");
      }, 120);
      if (onBlur) {
        onBlur(event);
      }
    };

    return (
      <div className="relative">
        <Input
          ref={forwardedRef}
          id={id}
          name={name}
          value={query}
          onChange={handleInputChange}
          onKeyDown={handleKeyDown}
          onBlur={handleBlur}
          onFocus={() => setOpen(true)}
          onClick={() => setOpen(true)}
          autoComplete="off"
          {...rest}
        />
        {open && (
          <div className="absolute z-50 mt-1 max-h-52 w-full overflow-y-auto rounded-md border border-slate-700/80 bg-slate-950/95 text-xs text-slate-100 shadow-soft">
            {loading ? (
              <div className="px-3 py-2 text-slate-400">Loading…</div>
            ) : filteredOptions.length ? (
              filteredOptions.map((opt, index) => (
                <button
                  key={opt.id}
                  type="button"
                  className={`flex w-full items-center px-3 py-1.5 text-left transition-colors ${
                    index === activeIndex
                      ? "bg-sky-500/20 text-sky-100"
                      : "hover:bg-slate-800/80"
                  }`}
                  onMouseDown={(event) => {
                    event.preventDefault();
                    handleSelect(opt);
                  }}
                >
                  {opt.display_name}
                </button>
              ))
            ) : (
              <div className="px-3 py-2 text-slate-500">
                No industry options available.
              </div>
            )}
          </div>
        )}
      </div>
    );
  }
);

IndustryInput.displayName = "IndustryInput";

export default IndustryInput;
