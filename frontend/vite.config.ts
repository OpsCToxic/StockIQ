import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// The dev server proxies /api to the FastAPI backend, so the browser sees one origin and the
// backend needs no CORS (STOCKIQ_API overrides the target). Start the backend with:
//   uvicorn stockiq.api.app:app --host 127.0.0.1 --port 8000
export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    proxy: {
      "/api": {
        target: process.env.STOCKIQ_API ?? "http://127.0.0.1:8000",
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
  test: { environment: "node" },
});
