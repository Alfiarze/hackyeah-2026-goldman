import { defineConfig } from "astro/config";

// LANDING_BASE: "/" when hosted on its own (Docker image), "/landing" when served next to the gateway.
export default defineConfig({
  site: process.env.LANDING_SITE || "https://aegis.local",
  base: process.env.LANDING_BASE || "/",
});
