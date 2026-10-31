/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { resolve } from "path";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": resolve(__dirname, "src"),
      // The built-in themes have one copy, next to the server that also serves them.
      "@themes": resolve(__dirname, "../server/magbi/themes"),
    },
  },
  server: {
    // MAGBI_WEB_PORT and MAGBI_API_URL let a second copy run beside this one (the CI end-to-end run).
    port: Number(process.env.MAGBI_WEB_PORT ?? 3000),
    fs: { allow: [".", "../server/magbi/themes"] },
    proxy: {
      "/api": process.env.MAGBI_API_URL ?? "http://127.0.0.1:8000",
    },
  },
  test: {
    environment: "node",
  },
});
