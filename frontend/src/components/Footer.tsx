import { Facebook, Twitter, Youtube, Music2 } from "lucide-react";
import { Link } from "react-router-dom";

const socials = [
  { label: "Facebook", icon: Facebook },
  { label: "Twitter", icon: Twitter },
  { label: "TikTok", icon: Music2 },
  { label: "YouTube", icon: Youtube },
];

function Footer() {
  return (
    <footer className="border-t border-slate-800/80 bg-slate-950/90">
      <div className="container flex flex-col gap-6 py-8 text-xs text-slate-400 md:flex-row md:items-center md:justify-between">
        <div className="flex flex-col gap-2">
          <p className="font-medium text-slate-300">
            Business Plan Studio by Tithe
          </p>
          <p className="max-w-md text-[11px] leading-relaxed text-slate-500">
            Strategy-ready business plans, crafted with clarity and built for
            investors, lenders, and real-world execution.
          </p>
          <p className="text-[11px] text-slate-500">
            © {new Date().getFullYear()} Tithe Financial Wealth Management. All
            rights reserved.
          </p>
        </div>

        <div className="flex flex-col gap-4 md:items-end">
          <nav className="flex flex-wrap gap-x-6 gap-y-2 text-[11px]">
            <Link to="#" className="transition-colors hover:text-slate-200">
              Privacy Policy
            </Link>
            <Link to="#" className="transition-colors hover:text-slate-200">
              Terms of Service
            </Link>
            <Link to="#" className="transition-colors hover:text-slate-200">
              Contact
            </Link>
          </nav>

          <div className="flex items-center gap-3">
            {socials.map(({ label, icon: Icon }) => (
              <button
                key={label}
                aria-label={label}
                className="inline-flex h-8 w-8 items-center justify-center rounded-full border border-slate-700/80 bg-slate-900/80 text-slate-300 shadow-sm transition-all duration-200 hover:-translate-y-0.5 hover:scale-[1.07] hover:border-sky-400/80 hover:bg-slate-900 hover:text-sky-300 hover:shadow-glow"
              >
                <Icon className="h-3.5 w-3.5" />
              </button>
            ))}
          </div>
        </div>
      </div>
    </footer>
  );
}

export default Footer;
