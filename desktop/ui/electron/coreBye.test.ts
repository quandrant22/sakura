import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { BYE_TIMEOUT_MS, sayBye, type WsLike } from "./coreBye";

let dir: string;
let tokenFile: string;
beforeEach(() => {
  dir = fs.mkdtempSync(path.join(os.tmpdir(), "sakura-bye-"));
  tokenFile = path.join(dir, "ui.token");
  fs.writeFileSync(tokenFile, JSON.stringify({ port: 5555, token: "t" }));
});
afterEach(() => { vi.useRealTimers(); fs.rmSync(dir, { recursive: true, force: true }); });

class FakeWs implements WsLike {
  onopen: (() => void) | null = null;
  onmessage: ((ev: { data: unknown }) => void) | null = null;
  onerror: (() => void) | null = null;
  onclose: (() => void) | null = null;
  sent: Record<string, unknown>[] = [];
  closed = false;
  constructor(public url: string, private replyOk: boolean | null) {
    setTimeout(() => this.onopen?.(), 5);
  }
  send(data: string) {
    const m = JSON.parse(data) as Record<string, unknown>;
    this.sent.push(m);
    if (m.type === "bye" && this.replyOk !== null) {
      setTimeout(() => {
        this.onmessage?.({ data: JSON.stringify({ type: "state", value: "idle" }) });
        this.onmessage?.({ data: JSON.stringify({ type: "reply", request_id: "bye", ok: true, result: { sent: this.replyOk } }) });
      }, 5);
    }
  }
  close() { this.closed = true; }
}

test("выход: hello с токеном и bye exit в ядро, ответ — сразу", async () => {
  let ws: FakeWs | null = null;
  const ok = await sayBye(tokenFile, "exit", BYE_TIMEOUT_MS, (url) => (ws = new FakeWs(url, true)));
  expect(ok).toBe(true);
  expect(ws!.url).toBe("ws://127.0.0.1:5555");
  expect(ws!.sent).toEqual([{ type: "hello", token: "t", client: "electron" }, { type: "bye", request_id: "bye", reason: "exit" }]);
  expect(ws!.closed).toBe(true);
});

test("ядро молчит — выход не задерживается дольше 1 с", async () => {
  vi.useFakeTimers();
  let resolved: boolean | null = null;
  const p = sayBye(tokenFile, "exit", BYE_TIMEOUT_MS, (url) => new FakeWs(url, null)).then((v) => { resolved = v; });
  await vi.advanceTimersByTimeAsync(999);
  expect(resolved).toBeNull();
  await vi.advanceTimersByTimeAsync(2);
  await p;
  expect(resolved).toBe(false);
});

test("ядро не запущено (нет ui.token) — сразу false", async () => {
  fs.rmSync(tokenFile);
  const make = vi.fn();
  expect(await sayBye(tokenFile, "exit", BYE_TIMEOUT_MS, make)).toBe(false);
  expect(make).not.toHaveBeenCalled();
});
