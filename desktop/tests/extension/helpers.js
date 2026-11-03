// Общие помощники тестов расширения: загрузка content.js / lib/*.js в jsdom, фикстуры, прямоугольники.
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

// Пути строками: в окружении jsdom глобальный URL — jsdom-овский, readFileSync его не принимает.
const HERE = dirname(fileURLToPath(import.meta.url));
const EXT = join(HERE, "..", "..", "extension");
const FIXTURES = join(HERE, "..", "fixtures", "extension");

const read = (base, name) => readFileSync(join(base, name), "utf-8");

// Скрипт расширения — как classic script в глобальной области (так его выполняет браузер).
function runScript(src) {
  (0, eval)(src);  // eslint-disable-line no-eval
}

export function loadContent() {
  delete globalThis.__sakuraAgent;
  runScript(read(EXT, "content.js"));
  return globalThis.__sakuraAgent;
}

export function loadLib(name) {
  runScript(read(EXT, name));
}

export function fixture(name) {
  document.body.innerHTML = read(FIXTURES, name);
}

// jsdom не считает раскладку: прямоугольник берётся из data-rect="x,y,w,h", иначе 100x20 у верха окна.
export function stubRects() {
  Element.prototype.getBoundingClientRect = function () {
    const r = this.getAttribute && this.getAttribute("data-rect");
    const [x, y, w, h] = r ? r.split(",").map(Number) : [10, 10, 100, 20];
    return { x, y, left: x, top: y, width: w, height: h, right: x + w, bottom: y + h, toJSON() {} };
  };
  Element.prototype.scrollIntoView = function () {};
}

export const byName = (obs, name) => obs.elements.find((e) => e.name === name);
