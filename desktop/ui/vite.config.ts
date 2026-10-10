import react from "@vitejs/plugin-react";
import type { Plugin } from "vite";
import { defineConfig } from "vitest/config";

// React Refresh в dev вставляет inline-скрипт и ходит на ws dev-сервера.
// Ослабляем CSP только для `vite serve`; сборка остаётся со строгой политикой.
const devCsp = (): Plugin => ({
  name: "sakura-dev-csp",
  apply: "serve",
  transformIndexHtml: (html) =>
    html
      .replace("script-src 'self'", "script-src 'self' 'unsafe-inline'")
      .replace("connect-src 'self'", "connect-src 'self' ws://localhost:5173"),
});

export default defineConfig({
  plugins: [react(), devCsp()],
  // Electron грузит dist/index.html через file:// — пути должны быть относительными.
  base: "./",
  server: { port: 5173, strictPort: true },
  build: { outDir: "dist", emptyOutDir: true },
  test: { environment: "jsdom", pool: "threads" },
});
