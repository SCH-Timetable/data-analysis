import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // NOTE: no proxy — api.js calls the backend via absolute BACKEND_URL
    // (http://localhost:8000). A "/api" proxy prefix would also swallow
    // the static /api.js module file and break the page, so keep it off.
  },
});
