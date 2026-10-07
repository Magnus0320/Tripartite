import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// The API listens on 127.0.0.1:8000 (ARCHITECTURE.md D8); the dev server proxies /api to it.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": "http://127.0.0.1:8000",
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["src/test/setup.ts"],
  },
});
