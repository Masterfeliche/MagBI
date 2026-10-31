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
    port: 3000,
    fs: { allow: [".", "../server/magbi/themes"] },
    proxy: {
      "/api": "http://127.0.0.1:8000",
    },
  },
  test: {
    environment: "node",
  },
});
