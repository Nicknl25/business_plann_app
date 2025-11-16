import type { ReactNode } from "react";
import { motion } from "framer-motion";

interface PageShellProps {
  children: ReactNode;
}

function PageShell({ children }: PageShellProps) {
  return (
    <motion.main
      className="flex-1"
      initial={{ opacity: 0, y: 28 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -24 }}
      transition={{ duration: 0.35, ease: "easeOut" }}
    >
      <div className="container max-w-6xl py-8 md:py-12 lg:py-16">
        {children}
      </div>
    </motion.main>
  );
}

export default PageShell;

