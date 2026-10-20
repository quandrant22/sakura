// ПК Мастера: игровой (pc), ноутбук (laptop), рабочий ноутбук (mostech). Список с сервера (devices_request)
// дополняется ими, даже если сервер их ещё не видел; активное устройство — focus (сервер §10.1).
import type { Device } from "./api/types";

export const PCS = ["pc", "laptop", "mostech"] as const;
export const PC_LABELS: Record<string, string> = { pc: "Игровой компьютер", laptop: "Ноутбук", mostech: "Рабочий ноутбук" };

/** Имя ПК для фраз: сервер, иначе своё; «Сакура перешла на игровой компьютер». */
export function pcName(id: string, list: Device[] = []): string {
  const fromServer = list.find((d) => d.id === id)?.name;
  return fromServer || PC_LABELS[id]?.toLowerCase() || id;
}

/** Все три ПК (первыми, по порядку) и остальные устройства сервера. */
export function withAllPcs(list: Device[]): Device[] {
  const byId = new Map(list.map((d) => [d.id, d]));
  const pcs: Device[] = PCS.map((id) => byId.get(id) ?? {
    id, name: PC_LABELS[id] ?? id, kind: "pc", online: false, last_seen: 0, focus: false, stats: {},
  });
  return [...pcs, ...list.filter((d) => !(PCS as readonly string[]).includes(d.id))];
}

/** Варианты DEVICE_ID для мастера: три ПК, ПК с сервера и текущее значение (чтобы его не потерять). */
export function pcChoices(list: Device[], current?: string): { id: string; name: string }[] {
  const out = withAllPcs(list).filter((d) => d.kind === "pc").map((d) => ({ id: d.id, name: d.name || PC_LABELS[d.id] || d.id }));
  if (current && !out.some((c) => c.id === current)) out.push({ id: current, name: current });
  return out;
}
