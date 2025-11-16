import { Sparkles } from "lucide-react";
import { NavLink, useLocation } from "react-router-dom";
import { Button } from "./ui/Button";
import { cn } from "../lib/utils";

const navItems = [
  { label: "Home", to: "/" },
  { label: "Pricing", to: "/pricing" },
  { label: "Business Plan Form", to: "/business-plan-form" },
];

function Header() {
  const location = useLocation();

  return (
    <header className="fixed inset-x-0 top-0 z-40 border-b border-white/5 bg-slate-950/70 backdrop-blur-xl">
      <div className="container flex h-[var(--header-height)] items-center justify-between gap-6">
        <NavLink
          to="/"
          className="group inline-flex items-center gap-2.5 text-sm font-medium tracking-tight text-slate-50"
        >
          <span className="relative flex h-9 w-9 items-center justify-center rounded-2xl bg-sky-500/15 text-sky-400 ring-1 ring-sky-500/40 shadow-glow">
            <Sparkles className="h-4 w-4 transition-transform duration-300 group-hover:rotate-12 group-hover:scale-110" />
            <span className="absolute inset-0 -z-10 rounded-2xl bg-sky-500/15 blur-xl" />
          </span>
          <div className="flex flex-col">
            <span className="text-xs uppercase tracking-[0.18em] text-slate-400">
              Tithe Studio
            </span>
            <span className="text-sm font-semibold">
              Business Plan Generator
            </span>
          </div>
        </NavLink>

        <nav className="hidden items-center gap-1 rounded-full border border-white/10 bg-slate-900/80 px-1 py-0.5 text-xs text-slate-200 shadow-soft backdrop-blur-xl md:flex">
          {navItems.map((item) => {
            const isActive = location.pathname === item.to;
            return (
              <NavLink
                key={item.to}
                to={item.to}
                className={({ isActive: navActive }) =>
                  cn(
                    "relative inline-flex items-center gap-2 rounded-full px-4 py-1.5 transition-all duration-200",
                    "hover:bg-slate-800/80 hover:text-slate-50",
                    (isActive || navActive) &&
                      "bg-slate-50 text-slate-900 shadow-[0_0_0_1px_rgba(148,163,184,0.35)]"
                  )
                }
              >
                <span className="w-1.5 h-1.5 rounded-full bg-gradient-to-r from-sky-400 to-cyan-300 shadow-[0_0_0_4px_rgba(56,189,248,0.45)] opacity-0 transition-opacity duration-200 data-[active=true]:opacity-100" />
                <span>{item.label}</span>
              </NavLink>
            );
          })}
        </nav>

        <div className="flex items-center gap-2">
          <Button
            asChild
            size="sm"
            className="hidden rounded-full bg-sky-500 px-4 text-xs font-semibold shadow-glow transition-transform duration-200 hover:scale-[1.03] hover:bg-sky-400 md:inline-flex"
          >
            <NavLink to="/business-plan-form">Start Your Plan</NavLink>
          </Button>
        </div>
      </div>
    </header>
  );
}

export default Header;

