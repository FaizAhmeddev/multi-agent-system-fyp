import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig, type Plugin } from "vite";

// Uses the product logo from assets/brand/logo.png when it exists (otherwise the built-in mark).
const HERE = path.dirname(fileURLToPath(import.meta.url));

function brandLogo(): Plugin {
  return {
    name: "agentsmind-brand-logo",
    buildStart() {
      const src = path.resolve(HERE, "..", "assets", "brand", "logo.png");
      const dst = path.resolve(HERE, "public", "brand", "logo.png");
      if (fs.existsSync(src)) fs.copyFileSync(src, dst);
    },
  };
}

// Dev: `npm run dev` serves on http://127.0.0.1:5173 and proxies /api to the core API.
// Production: `npm run build` writes dist/, which the core API serves on its own port.
export default defineConfig({
  plugins: [brandLogo(), react(), tailwindcss()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    proxy: { "/api": "http://127.0.0.1:8000", "/health": "http://127.0.0.1:8000" },
  },
  build: { outDir: "dist", sourcemap: false, chunkSizeWarningLimit: 900 },
});
