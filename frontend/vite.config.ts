import react from "@vitejs/plugin-react";
import { defineConfig, loadEnv } from "vite";

// API_URL points the dev server at another back (default: the one on port 8000)
export default defineConfig(({ mode }) => ({
  plugins: [react()],
  server: { proxy: { "/api": loadEnv(mode, ".", "").API_URL || "http://localhost:8000" } },
}));
