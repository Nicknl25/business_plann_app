import path from "node:path";
import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react-swc";

// THE SPA FALLBACK MUST NOT ANSWER FOR THE API (Nick 2026-09-13).
//
// The dev server has no /api proxy, so every /api/* path fell through to
// index.html and came back 200 text/html. That made a missing endpoint and a
// working one indistinguishable: Cowork read the artifact routes from this
// origin and saw `help` "absent", a cell read with none of its fields, and an
// unknown parameter returning 200 instead of 400 - three symptoms of one
// wrong origin, and an hour spent looking for the wrong thing.
//
// Same permissive class as the unknown query parameter: a wrong call that
// returns 200 hides the mistake. This answers 404 with the right address in
// the body, so the next caller is told rather than left to infer.
const apiIsNotServedHere = () => ({
  name: "api-is-not-served-here",
  configureServer(server: { middlewares: { use: (fn: unknown) => void } }) {
    server.middlewares.use((req: any, res: any, next: () => void) => {
      const url = String(req.url || "");
      if (!url.startsWith("/api/")) return next();
      res.statusCode = 404;
      res.setHeader("Content-Type", "application/json");
      res.end(
        JSON.stringify({
          error: "not_found",
          detail:
            "the API is not served on the dev server - this origin only serves the app",
          call_instead: `http://127.0.0.1:5050${url}`,
          discovery: "http://127.0.0.1:5050/api/artifacts/help",
        }),
      );
    });
  },
});

export default defineConfig(({ mode }) => {
  const rootDir = path.resolve(__dirname, "..");
  const rootEnv = loadEnv(mode, rootDir, "");
  const appEnv = loadEnv(mode, __dirname, "");

  const googlePlacesKey =
    appEnv.GOOGLE_PLACES_API_KEY || rootEnv.GOOGLE_PLACES_API_KEY || "";

  return {
    plugins: [react(), apiIsNotServedHere()],
    // CW-018: listen on all interfaces so the dev server is reachable on
    // BOTH loopbacks. A default bind came up IPv6-only (::1) on this
    // machine, so Chrome probes of 127.0.0.1:5173 got
    // ERR_CONNECTION_REFUSED while the terminal said the server was up.
    server: {
      host: true,
      port: 5173,
      strictPort: true,
    },
    resolve: {
      alias: {
        "@": path.resolve(__dirname, "./src"),
      },
    },
    envPrefix: ["VITE_", "GOOGLE_"],
    define: {
      "import.meta.env.GOOGLE_PLACES_API_KEY": JSON.stringify(googlePlacesKey),
    },
  };
});
