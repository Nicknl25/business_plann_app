import axios from "axios";

const resolveApiBaseUrl = (): string => {
  const processUrl =
    typeof process !== "undefined" ? process.env?.REACT_APP_API_URL : undefined;

  if (processUrl) {
    return processUrl;
  }

  const viteEnv =
    typeof import.meta !== "undefined" ? import.meta.env : undefined;
  const viteEnvRecord =
    typeof viteEnv === "object"
      ? (viteEnv as Record<string, string | boolean | undefined>)
      : undefined;

  const viteBaseUrl =
    viteEnvRecord?.VITE_API_BASE_URL &&
    typeof viteEnvRecord.VITE_API_BASE_URL === "string"
      ? viteEnvRecord.VITE_API_BASE_URL
      : undefined;

  if (viteBaseUrl) {
    return viteBaseUrl;
  }

  if (viteEnvRecord?.DEV) {
    return "http://localhost:5000";
  }

  return "";
};

const resolvedBase = resolveApiBaseUrl();
const baseURL = resolvedBase
  ? resolvedBase.replace(/\/$/, "")
  : "http://localhost:5000";

const apiClient = axios.create({
  baseURL,
});

export default apiClient;
