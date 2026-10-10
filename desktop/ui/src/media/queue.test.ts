import { describe, expect, test } from "vitest";

import * as Q from "./queue";
import type { Track } from "./types";

const t = (id: number): Track => ({ id, source: "local", title: `T${id}`, artist: "", album: "", duration: 100 });
const five = [1, 2, 3, 4, 5].map(t);
const ids = (q: Q.Queue) => q.items.map((x) => x.id);

describe("очередь", () => {
  test("линейный порядок, конец очереди, повтор всего и одного", () => {
    let q = Q.setItems(Q.emptyQueue(), five, 3);
    expect(Q.nextIndex(q)).toBe(4);
    q = { ...q, index: 4 };
    expect(Q.nextIndex(q)).toBe(-1);
    expect(Q.nextIndex({ ...q, repeat: "all" })).toBe(0);
    expect(Q.nextIndex({ ...q, repeat: "one" }, true)).toBe(4);
    expect(Q.nextIndex({ ...q, repeat: "one" }, false)).toBe(-1);  // «следующий» вручную при repeat one
    expect(Q.prevIndex({ ...q, index: 0 })).toBe(0);
    expect(Q.prevIndex({ ...q, index: 0, repeat: "all" })).toBe(4);
    expect(Q.cycleRepeat("off")).toBe("all");
    expect(Q.cycleRepeat("all")).toBe("one");
    expect(Q.cycleRepeat("one")).toBe("off");
  });

  test("перемешивание: текущий первым, все треки по разу", () => {
    let seed = 0.3;
    const rnd = () => (seed = (seed * 9301 + 49297) % 233280 / 233280);
    let q = Q.setItems(Q.emptyQueue(), five, 2);
    q = Q.setShuffle(q, true, rnd);
    expect(q.order[0]).toBe(2);
    expect([...q.order].sort()).toEqual([0, 1, 2, 3, 4]);
    const seen = [q.index];
    let cur = q;
    for (let i = 0; i < 4; i++) {
      const n = Q.nextIndex(cur);
      seen.push(n);
      cur = { ...cur, index: n };
    }
    expect([...seen].sort()).toEqual([0, 1, 2, 3, 4]);
    expect(Q.nextIndex(cur)).toBe(-1);
    expect(Q.setShuffle(cur, false).order).toEqual([0, 1, 2, 3, 4]);
  });

  test("перетаскивание сохраняет текущий трек", () => {
    let q = Q.setItems(Q.emptyQueue(), five, 1); // текущий — T2
    q = Q.move(q, 4, 0);
    expect(ids(q)).toEqual([5, 1, 2, 3, 4]);
    expect(q.items[q.index]!.id).toBe(2);
    q = Q.move(q, q.index, 4);
    expect(ids(q)).toEqual([5, 1, 3, 4, 2]);
    expect(q.items[q.index]!.id).toBe(2);
    expect(Q.move(q, 0, 99)).toBe(q);
  });

  test("играть следующим и удаление", () => {
    let q = Q.setItems(Q.emptyQueue(), five, 1);
    q = Q.playNext(q, t(9));
    expect(ids(q)).toEqual([1, 2, 9, 3, 4, 5]);
    expect(q.items[Q.nextIndex(q)]!.id).toBe(9);
    q = Q.removeAt(q, 0);
    expect(q.items[q.index]!.id).toBe(2);
    q = Q.removeAt(q, q.index);
    expect(q.items[q.index]!.id).toBe(9);
    expect(Q.removeAt(Q.setItems(Q.emptyQueue(), [t(1)]), 0).index).toBe(-1);
  });

  test("играть следующим при перемешивании", () => {
    let q = Q.setShuffle(Q.setItems(Q.emptyQueue(), five, 0), true, () => 0.5);
    q = Q.playNext(q, t(9));
    expect(q.items[Q.nextIndex(q)]!.id).toBe(9);
    expect([...q.order].sort((a, b) => a - b)).toEqual([0, 1, 2, 3, 4, 5]);
  });
});
