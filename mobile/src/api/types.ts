/**
 * Sakura Protocol v2 TypeScript Types & Interfaces.
 * Based on desktop/docs/PROTOCOL.md and sakura_core/proto_v2.py.
 */

export type Role = 'user' | 'assistant' | 'system';
export type Channel = 'voice' | 'text' | 'telegram';
export type DeviceKind = 'pc' | 'phone' | 'tablet' | 'headphones' | 'other';
export type LinkState = 'disconnected' | 'connecting' | 'connected' | 'pairing_required' | 'error';
export type SakuraState = 'idle' | 'listening' | 'thinking' | 'speaking';

export interface LinkInfo {
  state: LinkState;
  secure: boolean;
  transport: 'noise' | 'ws' | null;
  reason: string | null;
  master: boolean | null;
}

export interface Message {
  id: string;
  ts: number;
  role: Role;
  text: string;
  channel?: Channel;
  device?: string;
  source?: 'mic' | 'ui' | 'e2e' | 'api' | 'server' | 'system';
  kind?: 'ack' | 'template' | 'error' | 'proactive' | 'command' | 'voice_only';
  turn_id?: string | null;
  pending?: boolean;
  streaming?: boolean;
  transcription?: string;
}

export interface DeviceStats {
  cpu?: number | null;
  ram?: number | null;
  gpu?: number | null;
  gpu_temp?: number | null;
  vram?: number | null;
  gpu_name?: string | null;
  battery?: number | null;
  charging?: boolean | null;
  wifi?: string | null;
  signal?: number | null;
}

export interface Device {
  id: string;
  name: string;
  kind: DeviceKind;
  online: boolean;
  last_seen: number;
  focus: boolean;
  stats?: DeviceStats;
}

export interface ScenarioCondition {
  type: 'phrase' | 'time' | 'device_connected' | 'device_disconnected' | 'app_started' | string;
  value: string;
}

export interface ScenarioAction {
  type: 'action' | 'pause' | 'telegram' | 'notify' | string;
  value: string;
}

export interface Scenario {
  id: string;
  name: string;
  enabled: boolean;
  builtin?: boolean;
  conditions: ScenarioCondition[];
  actions: ScenarioAction[];
}

export interface MemoryItem {
  id: string;
  category: 'preferences' | 'facts' | 'bookmarks' | string;
  text: string;
  ts: number;
}

export interface Profile {
  name: string;
  address_as: string;
  quiet_hours: string;
  voice: string;
  tone: string;
  notifications: {
    telegram?: boolean;
    sound?: boolean;
  };
}

export interface SakuraStatus {
  tone?: string;
  mode?: string;
  context?: string;
  quote?: string;
}

export interface SystemTelemetry {
  battery?: number | null;
  charging?: boolean | null;
  wifi?: string | null;
  os?: string;
}

export interface ScheduleLesson {
  date: string;
  start: string;
  end: string;
  subject: string;
  room?: string;
  teacher?: string;
  kind?: string;
}

export interface WidgetsData {
  schedule: {
    has_data: boolean;
    stale: boolean;
    today_label: string;
    tomorrow_label: string;
    today: ScheduleLesson[];
    tomorrow: ScheduleLesson[];
    current: ScheduleLesson | null;
    next: ScheduleLesson | null;
  };
  memory: {
    total: number;
    counts: Record<string, number>;
  };
  pc: Device | null;
  status: SakuraStatus;
}

export class SakuraApiError extends Error {
  code: string;
  requestId?: string;

  constructor(code: string, message: string, requestId?: string) {
    super(message);
    this.name = 'SakuraApiError';
    this.code = code;
    this.requestId = requestId;
  }
}
