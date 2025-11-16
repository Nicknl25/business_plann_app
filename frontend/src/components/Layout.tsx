import type { ReactNode } from "react";
import Footer from "./Footer";
import Header from "./Header";

function Layout({ children }: { children: ReactNode }) {
  return (
    <div className="relative flex min-h-screen flex-col bg-slate-950 text-slate-50">
      <div className="pointer-events-none fixed inset-0 -z-10 bg-[radial-gradient(circle_at_top,_rgba(56,189,248,0.22),transparent_60%),radial-gradient(circle_at_bottom,_rgba(129,140,248,0.22),transparent_60%)]" />
      <Header />
      <div className="flex flex-1 flex-col pt-[var(--header-height)]">
        {children}
      </div>
      <Footer />
    </div>
  );
}

export default Layout;

