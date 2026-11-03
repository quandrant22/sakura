import { fileURLToPath } from "node:url";

import { defineConfig } from "vitest/config";

// Тесты расширения браузера (desktop/extension) лежат в desktop/tests/extension — вне папки ui.
// Кэш — в node_modules интерфейса, а не рядом с тестами (иначе он попадает в репозиторий).
export default defineConfig({
  root: fileURLToPath(new URL("../tests/extension", import.meta.url)),
  cacheDir: fileURLToPath(new URL("./node_modules/.vite-extension", import.meta.url)),
  test: { environment: "jsdom", include: ["**/*.test.js"] },
});
