// Чистая логика панели музыки: экстраполяция позиции, что показывать при какой ширине,
// доминирующий цвет обложки, поведение кнопки «Предыдущий». Отрисовка — YandexBar.tsx.

export interface RemoteState {
  status: "ok" | "idle" | "not_running" | "no_smtc" | "starting";
  /** Номер события наблюдателя SMTC (music_state) — для подтверждения окном. */
  seq?: number;
  title?: string;
  artist?: string;
  album?: string;
  playing?: boolean;
  position_s?: number | null;
  duration_s?: number | null;
  updated_age_s?: number | null;
  shuffle?: boolean | null;
  repeat?: "none" | "track" | "list" | null;
  cover?: string | null;
  volume?: number | null;
  can_like?: boolean;
  like_hint?: string | null;
  can_lyrics?: boolean;
  /** Стоит ли лайк у текущего трека (API, нужен токен); null — неизвестно. */
  liked?: boolean | null;
}

/** Ответ пульта на действие. */
export interface ControlResult {
  ok: boolean;
  status?: "done" | "noop" | "failed" | "unsupported";
  detail: string;
  /** «token» — показать кнопку «Как это сделать» (инструкция про YANDEX_MUSIC_TOKEN). */
  help?: string;
  /** Повторить действие через столько мс (звук приложения ещё не появился). */
  retry_ms?: number;
  lyrics?: string;
  liked?: boolean;
  volume?: number;
}

export interface Hint {
  text: string;
  /** Ошибка или отказ — цвет предупреждения; успех — обычный. */
  warn: boolean;
  help?: string;
}

/** Подсказка по ответу действия: успехи не показываются, отказ и ошибка — полностью, с действием. */
export function hintFor(r: ControlResult | null | undefined): Hint | null {
  if (!r || r.ok) return null;
  return { text: r.detail, warn: true, help: r.help };
}

/** Позиция сейчас: снимок SMTC + время с его обновления (+ сколько прошло с получения снимка). */
export function extrapolate(st: RemoteState | null, sinceFetchS: number): number {
  if (!st || st.position_s == null) return 0;
  let pos = st.position_s;
  if (st.playing) pos += (st.updated_age_s ?? 0) + Math.max(0, sinceFetchS);
  const dur = st.duration_s ?? 0;
  return dur > 0 ? Math.min(pos, dur) : pos;
}

/** Что помещается в панель заданной ширины — элементы скрываются по приоритету. */
export function visibleControls(width: number) {
  return {
    modes: width >= 560,       // перемешать, повтор
    rating: width >= 640,      // лайк, дизлайк
    volume: width >= 720,      // ползунок громкости (ниже — только кнопка звука)
    extras: width >= 840,      // «Текст», настройки
  };
}

/** Средний цвет непрозрачных пикселей (RGBA) — фон панели по обложке, затемнённый для читаемости. */
export function dominantColor(px: Uint8ClampedArray, darken = 0.45): [number, number, number] | null {
  let r = 0, g = 0, b = 0, n = 0;
  for (let i = 0; i + 3 < px.length; i += 4) {
    if ((px[i + 3] ?? 0) < 128) continue;
    r += px[i] ?? 0; g += px[i + 1] ?? 0; b += px[i + 2] ?? 0; n++;
  }
  if (!n) return null;
  const k = 1 - darken;
  return [Math.round((r / n) * k), Math.round((g / n) * k), Math.round((b / n) * k)];
}

export const PREV_RESTART_THRESHOLD_S = 3;

/** Кнопка «Предыдущий»: одинарный клик — в начало, если играет дольше 3 с, иначе предыдущий;
 *  второй клик двойного — предыдущий трек (после перемотки в начало это ровно один шаг назад). */
export function prevAction(clickCount: number, position: number): "restart" | "prev" {
  if (clickCount >= 2) return "prev";
  return position > PREV_RESTART_THRESHOLD_S ? "restart" : "prev";
}

export function fmt(s: number | null | undefined): string {
  const v = Math.max(0, Math.floor(s ?? 0));
  return `${Math.floor(v / 60)}:${String(v % 60).padStart(2, "0")}`;
}

/** Как подключить Яндекс.Музыку — панель («Как это сделать») и Настройки → Музыка. Значение токена не показывается. */
export const TOKEN_STEPS = [
  "Откройте файл C:\\sakura-git\\agent\\.env в Блокноте.",
  "Добавьте строку YANDEX_MUSIC_TOKEN=ваш_токен (токен — в настройках аккаунта Яндекс.Музыки или через инструкцию библиотеки yandex-music).",
  "Сохраните файл и перезапустите Сакуру (трей → «Выход», затем снова ярлык Sakura).",
  "Значение токена Сакура нигде не показывает и не отправляет на сервер.",
];
