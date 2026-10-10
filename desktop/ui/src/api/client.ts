// Клиент локального API ядра: hello с токеном, команды с request_id и таймаутом,
// события, переподключение. Интерфейс не знает ничего, кроме этого протокола.
import { CoreError, type CoreEvent } from "./types";

export type Listener = (ev: CoreEvent) => void;
export type LinkState = "connecting" | "open" | "closed";

export interface CoreClient {
  /** Команда ядру; reject(CoreError) при ok=false, таймауте или обрыве. */
  call<T = unknown>(type: string, payload?: Record<string, unknown>): Promise<T>;
  /** Запрос серверу (протокол v2) через ядро. */
  server<T = unknown>(message: Record<string, unknown> & { type: string }): Promise<T>;
  onEvent(cb: Listener): () => void;
  onLink(cb: (s: LinkState) => void): () => void;
  start(): void;
  stop(): void;
}

export const REQUEST_TIMEOUT_MS = 10_000;

interface Pending {
  resolve(v: unknown): void;
  reject(e: unknown): void;
  timer: ReturnType<typeof setTimeout>;
}

export interface Connection {
  port: number;
  token: string;
}

type WsCtor = new (url: string) => WebSocket;

export class WsCoreClient implements CoreClient {
  private ws: WebSocket | null = null;
  private seq = 0;
  private pending = new Map<string, Pending>();
  private listeners = new Set<Listener>();
  private linkListeners = new Set<(s: LinkState) => void>();
  private stopped = true;
  private retryTimer: ReturnType<typeof setTimeout> | null = null;

  constructor(
    private getConnection: () => Promise<Connection | null>,
    private Ws: WsCtor = WebSocket,
    private retryMs = 2000,
    private timeoutMs = REQUEST_TIMEOUT_MS,
  ) {}

  start(): void {
    this.stopped = false;
    void this.connect();
  }

  stop(): void {
    this.stopped = true;
    if (this.retryTimer) clearTimeout(this.retryTimer);
    this.ws?.close();
    this.ws = null;
  }

  onEvent(cb: Listener): () => void {
    this.listeners.add(cb);
    return () => this.listeners.delete(cb);
  }

  onLink(cb: (s: LinkState) => void): () => void {
    this.linkListeners.add(cb);
    return () => this.linkListeners.delete(cb);
  }

  call<T = unknown>(type: string, payload: Record<string, unknown> = {}): Promise<T> {
    const ws = this.ws;
    if (!ws || ws.readyState !== 1) {
      return Promise.reject(new CoreError("core_offline", "нет связи с ядром"));
    }
    const request_id = `u${++this.seq}`;
    return new Promise<T>((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(request_id);
        reject(new CoreError("timeout", `${type}: нет ответа за ${this.timeoutMs / 1000} с`));
      }, this.timeoutMs);
      this.pending.set(request_id, { resolve: resolve as (v: unknown) => void, reject, timer });
      ws.send(JSON.stringify({ ...payload, type, request_id }));
    });
  }

  server<T = unknown>(message: Record<string, unknown> & { type: string }): Promise<T> {
    return this.call<T>("server", { message });
  }

  private emitLink(s: LinkState) {
    for (const cb of this.linkListeners) cb(s);
  }

  private async connect(): Promise<void> {
    if (this.stopped) return;
    this.emitLink("connecting");
    const conn = await this.getConnection().catch(() => null);
    if (!conn) return this.scheduleRetry();
    const ws = new this.Ws(`ws://127.0.0.1:${conn.port}`);
    this.ws = ws;
    ws.onopen = () => {
      ws.send(JSON.stringify({ type: "hello", token: conn.token, client: "ui" }));
      this.emitLink("open");
    };
    ws.onmessage = (e: MessageEvent) => this.handle(String(e.data));
    ws.onclose = () => {
      if (this.ws === ws) this.ws = null;
      for (const [id, p] of this.pending) {
        clearTimeout(p.timer);
        p.reject(new CoreError("core_offline", "нет связи с ядром"));
        this.pending.delete(id);
      }
      this.emitLink("closed");
      this.scheduleRetry();
    };
    ws.onerror = () => ws.close();
  }

  private scheduleRetry() {
    if (this.stopped) return;
    this.emitLink("closed");
    this.retryTimer = setTimeout(() => void this.connect(), this.retryMs);
  }

  private handle(raw: string) {
    let msg: CoreEvent & { request_id?: string; ok?: boolean; result?: unknown; error?: { code: string; message: string } };
    try {
      msg = JSON.parse(raw);
    } catch {
      return;
    }
    if (msg.type === "reply" && msg.request_id) {
      const p = this.pending.get(msg.request_id);
      if (!p) return;
      this.pending.delete(msg.request_id);
      clearTimeout(p.timer);
      if (msg.ok) p.resolve(msg.result);
      else p.reject(new CoreError(msg.error?.code ?? "error", msg.error?.message ?? ""));
      return;
    }
    for (const cb of this.listeners) cb(msg);
  }
}
