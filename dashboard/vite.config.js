import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Served by the gateway at /dashboard; `npm run dev` proxies the API to localhost:8000.
export default defineConfig({
  plugins: [react()],
  base: "/dashboard/",
  build: { outDir: "dist", emptyOutDir: true },
  server: { proxy: { "/admin": "http://localhost:8000", "/health": "http://localhost:8000" } },
});
