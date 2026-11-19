// Тексты и шаблоны сценариев: подписи условий и действий, дни недели, заготовки.
import type { CatalogAction, Device, Scenario, ScenarioStep } from "../api/types";

export const CONDITION_TYPES = [
  { id: "phrase", label: "Скажу фразу", hint: "Голосом или в чате, например: «доброе утро»" },
  { id: "time", label: "Наступит время", hint: "В выбранные дни в указанное время" },
  { id: "device_connected", label: "Устройство подключится", hint: "После того как его не было больше минуты" },
  { id: "device_disconnected", label: "Устройство отключится", hint: "Если не вернётся в течение минуты" },
  { id: "app_started", label: "Открою приложение или игру", hint: "Часть названия окна или игры, например: Steam" },
] as const;

export const ACTION_TYPES = [
  { id: "action", label: "Команда Сакуры" },
  { id: "pause", label: "Пауза" },
  { id: "telegram", label: "Сообщение в Telegram" },
  { id: "notify", label: "Сказать и показать" },
] as const;

export const DAYS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"];
export const WEEKDAYS = [0, 1, 2, 3, 4];
export const WEEKEND = [5, 6];

const same = (a: number[], b: number[]) => a.length === b.length && a.every((x, i) => x === b[i]);

export function daysText(days?: number[]): string {
  const d = [...new Set(days ?? [])].sort((a, b) => a - b);
  if (!d.length || d.length === 7) return "каждый день";
  if (same(d, WEEKDAYS)) return "по будням";
  if (same(d, WEEKEND)) return "по выходным";
  return d.map((x) => (DAYS[x] ?? "").toLowerCase()).join(", ");
}

export function deviceName(id: string, devices: Device[]): string {
  if (!id) return "любое устройство";
  return devices.find((d) => d.id === id)?.name ?? id;
}

export function conditionText(c: ScenarioStep, devices: Device[] = []): string {
  switch (c.type) {
    case "phrase": return `фраза «${c.value}»`;
    case "time": return `${c.value.split("-")[0]}, ${daysText(c.days)}`;
    case "device_connected": return `подключится: ${deviceName(c.value, devices)}`;
    case "device_disconnected": return `отключится: ${deviceName(c.value, devices)}`;
    case "app_started": return `открыто: ${c.value}`;
    default: return c.value;
  }
}

export function actionText(a: ScenarioStep, catalog: CatalogAction[] = []): string {
  switch (a.type) {
    case "action": {
      const cut = a.value.includes(":") && !catalog.some((x) => x.id === a.value) ? a.value.indexOf(":") : -1;
      const id = cut >= 0 ? a.value.slice(0, cut) : a.value;
      const legacyArg = cut >= 0 ? a.value.slice(cut + 1) : "";
      const title = catalog.find((x) => x.id === id)?.title ?? id;
      const arg = a.arg ?? legacyArg;
      return arg ? `${title}: ${arg}` : title;
    }
    case "pause": return `пауза ${a.value} с`;
    case "telegram": return `Telegram: ${a.value}`;
    case "notify": return `сказать: ${a.value}`;
    default: return a.value;
  }
}

export const emptyScenario = (): Scenario => ({
  id: null, name: "", enabled: true, conditions: [], actions: [{ type: "action", value: "" }],
});

/** Заготовки: открываются в конструкторе, сохраняет Мастер. Команды — из реестра сервера. */
export const TEMPLATES: { title: string; scenario: Scenario }[] = [
  { title: "Доброе утро", scenario: {
    id: null, name: "Доброе утро", enabled: true,
    conditions: [{ type: "phrase", value: "доброе утро" }, { type: "time", value: "08:00", days: WEEKDAYS }],
    actions: [{ type: "action", value: "weather.now" }, { type: "action", value: "briefing.now" },
              { type: "action", value: "music.wave" }] } },
  { title: "Режим фокуса", scenario: {
    id: null, name: "Фокус", enabled: true, conditions: [{ type: "phrase", value: "режим фокуса" }],
    actions: [{ type: "action", value: "music.wave" }, { type: "notify", value: "Режим фокуса: не отвлекаю" }] } },
  { title: "Игровой вечер", scenario: {
    id: null, name: "Игровой вечер", enabled: true, conditions: [{ type: "app_started", value: "Steam" }],
    actions: [{ type: "action", value: "app.launch", arg: "Discord" }, { type: "notify", value: "Удачной игры!" }] } },
  { title: "Чай после прихода", scenario: {
    id: null, name: "Я дома", enabled: true, conditions: [{ type: "device_connected", value: "" }],
    actions: [{ type: "action", value: "kettle.boil" }, { type: "notify", value: "С возвращением! Чайник уже греется" }] } },
  { title: "Отбой", scenario: {
    id: null, name: "Отбой", enabled: true, conditions: [{ type: "time", value: "23:30" }],
    actions: [{ type: "action", value: "display.night_light" }, { type: "telegram", value: "Пора спать 🌙" }] } },
];
