// background.js: перебор портов 8766–8769. Живая проверка 26.10: VS Code держал 8767, принимал TCP
// и не отвечал на рукопожатие — сокет навсегда оставался CONNECTING, и до Сакуры перебор не доходил.
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { loadLib } from "./helpers.js";

const EXT = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "extension");

class FakeWebSocket {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSING = 2;
  static CLOSED = 3;
  static all = [];

  constructor(url) {
    this.url = url;
    this.readyState = FakeWebSocket.CONNECTING;
    this.sent = [];
    this.listeners = [];
    FakeWebSocket.all.push(this);
  }

  addEventListener(type, fn) { if (type === "message") this.listeners.push(fn); }
  removeEventListener(type, fn) { this.listeners = this.listeners.filter((f) => f !== fn); }
  send(data) { this.sent.push(JSON.parse(data)); }

  // Как в браузере: close() — onclose позже, асинхронно.
  close() {
    if (this.readyState === FakeWebSocket.CLOSED) return;
    this.readyState = FakeWebSocket.CLOSED;
    setTimeout(() => this.onclose && this.onclose({}), 0);
  }

  // Действия «сервера».
  accept() { this.readyState = FakeWebSocket.OPEN; this.onopen && this.onopen({}); }
  message(obj) {
    const ev = { data: JSON.stringify(obj) };
    this.listeners.forEach((f) => f(ev));
    if (this.onmessage) this.onmessage(ev);
  }
  drop() { this.readyState = FakeWebSocket.CLOSED; this.onclose && this.onclose({}); }
}

const ports = () => FakeWebSocket.all.map((s) => Number(s.url.split(":")[2]));

beforeEach(() => {
  vi.useFakeTimers();
  FakeWebSocket.all = [];
  const noop = () => {};
  const listener = { addListener: noop };
  globalThis.WebSocket = FakeWebSocket;
  globalThis.importScripts = (...names) => names.forEach((n) => loadLib(n));
  globalThis.chrome = {
    alarms: { create: noop, onAlarm: listener },
    runtime: { onStartup: listener, onInstalled: listener, onMessage: listener, getManifest: () => ({ version: "3.2.0" }) },
    tabs: { captureVisibleTab: noop },
  };
  vi.spyOn(console, "log").mockImplementation(noop);
  (0, eval)(readFileSync(join(EXT, "background.js"), "utf-8"));  // eslint-disable-line no-eval
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
  delete globalThis.WebSocket;
  delete globalThis.chrome;
});

test("порт принял TCP и молчит: через 2 с — следующий порт, без двойного перебора", async () => {
  expect(ports()).toEqual([8766]);
  await vi.advanceTimersByTimeAsync(1999);
  expect(ports()).toEqual([8766]);
  await vi.advanceTimersByTimeAsync(1);
  expect(ports()).toEqual([8766, 8767]);
  expect(FakeWebSocket.all[0].readyState).toBe(FakeWebSocket.CLOSED);
  // Поздний onclose брошенного сокета не запускает второй перебор.
  await vi.advanceTimersByTimeAsync(10);
  expect(ports()).toEqual([8766, 8767]);

  const sakura = FakeWebSocket.all[1];
  sakura.accept();
  sakura.message({ type: "sakura_hello", version: "3.1.0" });
  expect(sakura.sent).toEqual([{ type: "extension_ready", version: "3.2.0" }]);
  await vi.advanceTimersByTimeAsync(10_000);
  expect(ports()).toEqual([8766, 8767]);   // подключено — больше никуда не ходит
});

test("ядро закрыло соединение до hello (уже подключено другое): таймер hello не плодит сокеты", async () => {
  const busy = FakeWebSocket.all[0];
  busy.accept();
  busy.drop();
  expect(ports()).toEqual([8766, 8767]);
  await vi.advanceTimersByTimeAsync(1500);  // таймер hello 8766 был бы здесь
  expect(ports()).toEqual([8766, 8767]);
});

test("чужой сокет без sakura_hello — через 1 с следующий порт; Сакура на 8768 подключается", async () => {
  FakeWebSocket.all[0].drop();                 // 8766 закрыт
  const foreign = FakeWebSocket.all[1];         // 8767 — открылся, но не Сакура
  foreign.accept();
  foreign.message({ type: "something" });
  await vi.advanceTimersByTimeAsync(1000);
  expect(ports()).toEqual([8766, 8767, 8768]);
  await vi.advanceTimersByTimeAsync(10);
  expect(ports()).toEqual([8766, 8767, 8768]);
  const sakura = FakeWebSocket.all[2];
  sakura.accept();
  sakura.message({ type: "sakura_hello" });
  expect(sakura.sent[0]).toEqual({ type: "extension_ready", version: "3.2.0" });
});

test("обрыв после подключения — реконнект с 8766 через 3 с", async () => {
  const s = FakeWebSocket.all[0];
  s.accept();
  s.message({ type: "sakura_hello" });
  s.drop();
  await vi.advanceTimersByTimeAsync(2999);
  expect(ports()).toEqual([8766]);
  await vi.advanceTimersByTimeAsync(1);
  expect(ports()).toEqual([8766, 8766]);
});
