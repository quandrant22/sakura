import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import { WsCoreClient } from "./client";
import { CoreError } from "./types";

class FakeWs {
  static last: FakeWs | null = null;
  readyState = 0;
  sent: Record<string, unknown>[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((e: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  constructor(public url: string) {
    FakeWs.last = this;
  }
  send(data: string) {
    this.sent.push(JSON.parse(data));
  }
  close() {
    this.readyState = 3;
    this.onclose?.();
  }
  open() {
    this.readyState = 1;
    this.onopen?.();
  }
  push(obj: unknown) {
    this.onmessage?.({ data: JSON.stringify(obj) });
  }
}

const conn = async () => ({ port: 8790, token: "tok" });

async function started(timeoutMs = 10_000) {
  const c = new WsCoreClient(conn, FakeWs as unknown as new (u: string) => WebSocket, 50, timeoutMs);
  c.start();
  await vi.waitFor(() => expect(FakeWs.last).not.toBeNull());
  const ws = FakeWs.last!;
  ws.open();
  return { c, ws };
}

describe("WsCoreClient", () => {
  beforeEach(() => {
    FakeWs.last = null;
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  test("hello с токеном и адрес 127.0.0.1", async () => {
    const { ws } = await started();
    expect(ws.url).toBe("ws://127.0.0.1:8790");
    expect(ws.sent[0]).toEqual({ type: "hello", token: "tok", client: "ui" });
  });

  test("ответы сопоставляются по request_id", async () => {
    const { c, ws } = await started();
    const a = c.call("list_apps");
    const b = c.server({ type: "devices_request" });
    const [ra, rb] = ws.sent.slice(1) as { request_id: string; type: string; message?: unknown }[];
    expect(rb!.type).toBe("server");
    expect(rb!.message).toEqual({ type: "devices_request" });
    ws.push({ type: "reply", request_id: rb!.request_id, ok: true, result: { devices: [] } });
    ws.push({ type: "reply", request_id: ra!.request_id, ok: true, result: { apps: [] } });
    await expect(a).resolves.toEqual({ apps: [] });
    await expect(b).resolves.toEqual({ devices: [] });
  });

  test("ok=false превращается в CoreError с кодом", async () => {
    const { c, ws } = await started();
    const p = c.call("server", { message: { type: "status_request" } });
    const req = ws.sent[1] as { request_id: string };
    ws.push({ type: "reply", request_id: req.request_id, ok: false, error: { code: "unsupported", message: "нет" } });
    await expect(p).rejects.toMatchObject({ code: "unsupported" });
  });

  test("таймаут ответа", async () => {
    const { c } = await started(30);
    await expect(c.call("list_apps")).rejects.toMatchObject({ code: "timeout" });
  });

  test("без соединения — core_offline; обрыв отменяет ожидающие", async () => {
    const c = new WsCoreClient(async () => null, FakeWs as unknown as new (u: string) => WebSocket, 10_000);
    await expect(c.call("x")).rejects.toBeInstanceOf(CoreError);
    const { c: c2, ws } = await started();
    const p = c2.call("list_apps");
    ws.close();
    await expect(p).rejects.toMatchObject({ code: "core_offline" });
    c2.stop();
  });

  test("события приходят подписчикам, reply — нет", async () => {
    const { c, ws } = await started();
    const got: string[] = [];
    c.onEvent((e) => got.push(e.type));
    ws.push({ type: "state", value: "listening" });
    ws.push({ type: "reply", request_id: "zzz", ok: true });
    expect(got).toEqual(["state"]);
  });

  test("переподключение после обрыва", async () => {
    const { c, ws } = await started();
    ws.close();
    await vi.waitFor(() => expect(FakeWs.last).not.toBe(ws), { timeout: 1000 });
    c.stop();
  });
});
