// Очередь воспроизведения — чистые функции (без React), покрыты тестами.
import type { RepeatMode, Track } from "./types";

export interface Queue {
  items: Track[];
  index: number;        // текущий трек в items, -1 — пусто
  order: number[];      // порядок проигрывания (индексы items); при shuffle — перемешан
  shuffle: boolean;
  repeat: RepeatMode;
}

export const emptyQueue = (): Queue => ({ items: [], index: -1, order: [], shuffle: false, repeat: "off" });

/** Перемешивание Фишера–Йетса; текущий трек остаётся первым. rnd — для тестов. */
export function shuffled(n: number, first: number, rnd: () => number = Math.random): number[] {
  const rest = [...Array(n).keys()].filter((i) => i !== first);
  for (let i = rest.length - 1; i > 0; i--) {
    const j = Math.floor(rnd() * (i + 1));
    [rest[i], rest[j]] = [rest[j]!, rest[i]!];
  }
  return first >= 0 && first < n ? [first, ...rest] : rest;
}

const linear = (n: number) => [...Array(n).keys()];

export function setItems(q: Queue, items: Track[], start = 0, rnd?: () => number): Queue {
  const index = items.length ? Math.min(Math.max(start, 0), items.length - 1) : -1;
  return { ...q, items, index, order: q.shuffle ? shuffled(items.length, index, rnd) : linear(items.length) };
}

export function setShuffle(q: Queue, on: boolean, rnd?: () => number): Queue {
  return { ...q, shuffle: on, order: on ? shuffled(q.items.length, q.index, rnd) : linear(q.items.length) };
}

export function cycleRepeat(r: RepeatMode): RepeatMode {
  return r === "off" ? "all" : r === "all" ? "one" : "off";
}

/** Индекс следующего трека или -1 (конец очереди). auto — переход по окончанию трека. */
export function nextIndex(q: Queue, auto = false): number {
  if (q.index < 0 || !q.items.length) return -1;
  if (auto && q.repeat === "one") return q.index;
  const pos = q.order.indexOf(q.index);
  if (pos + 1 < q.order.length) return q.order[pos + 1]!;
  return q.repeat === "all" ? q.order[0]! : -1;
}

export function prevIndex(q: Queue): number {
  if (q.index < 0) return -1;
  const pos = q.order.indexOf(q.index);
  if (pos > 0) return q.order[pos - 1]!;
  return q.repeat === "all" ? q.order[q.order.length - 1]! : q.index;
}

/** Перетаскивание в очереди: переносим from → to, текущий трек остаётся текущим. */
export function move(q: Queue, from: number, to: number): Queue {
  if (from === to || from < 0 || to < 0 || from >= q.items.length || to >= q.items.length) return q;
  const items = [...q.items];
  const [it] = items.splice(from, 1);
  items.splice(to, 0, it!);
  const remap = (i: number) => {
    if (i === from) return to;
    if (from < to && i > from && i <= to) return i - 1;
    if (from > to && i >= to && i < from) return i + 1;
    return i;
  };
  return { ...q, items, index: remap(q.index), order: q.shuffle ? q.order.map(remap) : linear(items.length) };
}

/** «Играть следующим»: вставить сразу после текущего. */
export function playNext(q: Queue, t: Track): Queue {
  const at = q.index + 1;
  const items = [...q.items.slice(0, at), t, ...q.items.slice(at)];
  const shift = (i: number) => (i >= at ? i + 1 : i);
  if (!q.shuffle) return { ...q, items, index: q.index < 0 ? 0 : q.index, order: linear(items.length) };
  const order = q.order.map(shift);
  order.splice(order.indexOf(q.index) + 1, 0, at);
  return { ...q, items, order };
}

export function removeAt(q: Queue, i: number): Queue {
  if (i < 0 || i >= q.items.length) return q;
  const items = q.items.filter((_, k) => k !== i);
  const fix = (k: number) => (k > i ? k - 1 : k);
  const index = items.length === 0 ? -1 : i === q.index ? Math.min(i, items.length - 1) : fix(q.index);
  return { ...q, items, index, order: q.shuffle ? q.order.filter((k) => k !== i).map(fix) : linear(items.length) };
}
