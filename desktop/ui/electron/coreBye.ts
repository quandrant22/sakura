// «Выход» и закрытие приложения: перед тем как закрыть ядро, просим его отправить серверу bye
// (команда bye локального API ядра). Ждём не дольше timeoutMs — дальше закрываемся как обычно.
import fs from "node:fs";

export type ByeReason = "exit" | "shutdown" | "sleep";

/** Минимум WebSocket, который нужен здесь (глобальный WebSocket Node; в тестах — подставной). */
export interface WsLike {
  onopen: (() => void) | null;
  onmessage: ((ev: { data: unknown }) => void) | null;
  onerror: (() => void) | null;
  onclose: (() => void) | null;
  send(data: string): void;
  close(): void;
}

export const BYE_TIMEOUT_MS = 1000;

export function sayBye(tokenFile: string, reason: ByeReason = "exit", timeoutMs = BYE_TIMEOUT_MS,
                       makeWs: (url: string) => WsLike = (url) => new WebSocket(url) as unknown as WsLike): Promise<boolean> {
  let port: number, token: string;
  try {
    const data = JSON.parse(fs.readFileSync(tokenFile, "utf-8")) as { port?: unknown; token?: unknown };
    if (typeof data.port !== "number" || typeof data.token !== "string") return Promise.resolve(false);
    port = data.port;
    token = data.token;
  } catch {
    return Promise.resolve(false); // ядро не запущено
  }
  return new Promise((resolve) => {
    let ws: WsLike | null = null;
    let done = false;
    const finish = (ok: boolean) => {
      if (done) return;
      done = true;
      clearTimeout(timer);
      try { ws?.close(); } catch { /* уже закрыт */ }
      resolve(ok);
    };
    const timer = setTimeout(() => finish(false), timeoutMs);
    try {
      ws = makeWs(`ws://127.0.0.1:${port}`);
    } catch {
      finish(false);
      return;
    }
    ws.onopen = () => {
      ws?.send(JSON.stringify({ type: "hello", token, client: "electron" }));
      ws?.send(JSON.stringify({ type: "bye", request_id: "bye", reason }));
    };
    ws.onmessage = (ev) => {
      try {
        const m = JSON.parse(String(ev.data)) as { type?: string; request_id?: string; ok?: boolean; result?: { sent?: boolean } };
        if (m.type === "reply" && m.request_id === "bye") finish(m.ok === true && m.result?.sent !== false);
      } catch {
        // события ядра (снимок состояния) — пропускаем
      }
    };
    ws.onerror = () => finish(false);
    ws.onclose = () => finish(false);
  });
}
