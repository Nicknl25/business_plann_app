import path from "node:path";
import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react-swc";

export default defineConfig(({ mode }) => {
  const rootDir = path.resolve(__dirname, "..");
  const rootEnv = loadEnv(mode, rootDir, "");
  const appEnv = loadEnv(mode, __dirname, "");

  const googlePlacesKey =
    appEnv.GOOGLE_PLACES_API_KEY || rootEnv.GOOGLE_PLACES_API_KEY || "";

  return {
    plugins: [react()],
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
