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
