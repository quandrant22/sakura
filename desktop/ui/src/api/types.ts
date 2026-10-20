// Типы протокола (desktop/docs/PROTOCOL.md).
export type Role = "user" | "assistant" | "system";
export type Channel = "voice" | "text" | "telegram";
export type CoreState = "idle" | "listening" | "thinking" | "speaking";

export interface Message {
  id: string;
  ts: number;
  role: Role;
  text: string;
  channel: Channel;
  device: string;
  /** только локально: сообщение отправлено и ждёт эха от сервера */
  pending?: boolean;
  /** Откуда сообщение: mic — голос, ui — окно чата, e2e — автоматическая проверка, api — другой клиент, server — ответ. */
  source?: "mic" | "ui" | "e2e" | "api" | "server" | "system";
  /** Вид реплики Сакуры: llm — ответ модели, ack/template — быстрый, error, proactive,
   *  command — результат команды (строка «действие»), voice_only — звук без текста. */
  kind?: "llm" | "ack" | "template" | "error" | "proactive" | "command" | "voice_only";
  /** Ход: реплика пользователя и все ответы на неё. */
  turn_id?: string | null;
}

export interface DeviceStats {
  cpu?: number | null;
  ram?: number | null;
  gpu?: number | null;
  battery?: number | null;
  charging?: boolean | null;
  wifi?: string | null;
  signal?: number | null;
}

export interface Device {
  id: string;
  name: string;
  kind: "pc" | "phone" | "tablet" | "headphones" | "other";
  online: boolean;
  last_seen: number;
  focus: boolean;
  stats: DeviceStats;
}

export interface Status {
  tone: string;
  mode: string;
  context: string;
  quote: string;
}

export interface ScenarioStep {
  type: string;
  value: string;
}

export interface Scenario {
  id: string | null;
  name: string;
  enabled: boolean;
  builtin?: boolean;
  conditions: ScenarioStep[];
  actions: ScenarioStep[];
}

export interface Settings {
  quick_prompts: string[];
  language: string;
  theme: string;
  device_id?: string;
  extension_id?: string;
  mic_enabled?: boolean;
  core_ready?: boolean;
  [key: string]: unknown;
}

export interface ApiError {
  code: string;
  message: string;
}

export type CoreEvent =
  | { type: "connection"; server: "online" | "offline"; proto: number | null }
  | { type: "state"; value: CoreState; level?: number }
  | { type: "transcript"; text: string; final: boolean }
  | { type: "chat_message"; message: Message }
  | { type: "devices"; devices: Device[] }
  | { type: "device_update"; device: Device }
  | ({ type: "status" } & Status)
  | { type: "settings"; settings: Settings }
  | { type: "notify"; text: string; level: "info" | "warn" | "error" }
  | { type: "game_mode"; on: boolean }
  | { type: "scenario_event"; run_id: string; step: number; status: string; detail: string }
  | { type: "audio_level"; bars: number[] }
  /** Сакура перешла между ПК (сервер §10.4): arrival — на этот, departure — с этого. */
  | { type: "presence"; event: "arrival" | "departure"; from: string | null; to: string }
  /** Уровень звука ядра 0..1 (озвучка или микрофон), не чаще 30 раз в секунду. */
  | { type: "level"; value: number }
  | { type: string; [key: string]: unknown };

/** Ошибка команды ядра (reply.ok === false). */
export class CoreError extends Error {
  constructor(
    public code: string,
    message: string,
  ) {
    super(message);
  }
}
