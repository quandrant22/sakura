import { describe, expect, it } from "vitest";
import { blendFrames, coreFrame, DROP_R, ease, SATELLITES, VIEWBOX, type CoreVisualState, type Mobility } from "./coreFrame";

const STATES: CoreVisualState[] = ["idle", "listening", "thinking", "speaking", "offline"];
const MOBILITIES: Mobility[] = ["low", "normal", "high"];

function bbox(f: ReturnType<typeof coreFrame>) {
  const all = [f.drop, ...f.satellites];
  return {
    minX: Math.min(...all.map((c) => c.cx - c.r)), maxX: Math.max(...all.map((c) => c.cx + c.r)),
    minY: Math.min(...all.map((c) => c.cy - c.r)), maxY: Math.max(...all.map((c) => c.cy + c.r)),
  };
}

function maxWidth(state: CoreVisualState, mobility: Mobility, seconds = 60) {
  let w = 0;
  for (let t = 0; t < seconds; t += 0.05) {
    const b = bbox(coreFrame(t, state, 0, mobility));
    w = Math.max(w, b.maxX - b.minX);
  }
  return w;
}

/** Средняя скорость центров спутников, px/с. */
function meanSpeed(state: CoreVisualState, seconds = 60, dt = 1 / 60) {
  let dist = 0;
  let prev = coreFrame(0, state, 0).satellites;
  for (let t = dt; t <= seconds; t += dt) {
    const cur = coreFrame(t, state, 0).satellites;
    cur.forEach((s, i) => { dist += Math.hypot(s.cx - prev[i]!.cx, s.cy - prev[i]!.cy); });
    prev = cur;
  }
  return dist / seconds / SATELLITES.length;
}

describe("coreFrame", () => {
  it("нет NaN и всё внутри viewBox", () => {
    for (const s of STATES)
      for (const mob of MOBILITIES)
        for (const level of [0, 0.5, 1, NaN, -3, 7])
          for (let t = 0; t < 30; t += 0.37) {
            const f = coreFrame(t, s, level, mob);
            const nums = [f.drop, ...f.satellites].flatMap((c) => [c.cx, c.cy, c.r])
              .concat(f.rings.flatMap((r) => [r.r, r.opacity]), [f.opacity]);
            expect(nums.every(Number.isFinite)).toBe(true);
            const b = bbox(f);
            expect(b.minX).toBeGreaterThanOrEqual(VIEWBOX.x);
            expect(b.maxX).toBeLessThanOrEqual(VIEWBOX.x + VIEWBOX.w);
            expect(b.minY).toBeGreaterThanOrEqual(VIEWBOX.y);
            expect(b.maxY).toBeLessThanOrEqual(VIEWBOX.y + VIEWBOX.h);
            for (const r of f.rings) expect(r.r).toBeLessThanOrEqual(Math.min(-VIEWBOX.x, VIEWBOX.y + VIEWBOX.h));
          }
  });

  it("при полном раскрытии силуэт ≈155x149", () => {
    const all = [[0, 0, DROP_R] as const, ...SATELLITES];
    const w = Math.max(...all.map(([x, , r]) => x + r)) - Math.min(...all.map(([x, , r]) => x - r));
    const h = Math.max(...all.map(([, y, r]) => y + r)) - Math.min(...all.map(([, y, r]) => y - r));
    expect(w).toBeCloseTo(155, -1);
    expect(h).toBeCloseTo(149, -1);
    // В покое с высокой подвижностью силуэт доходит до полного раскрытия.
    expect(maxWidth("idle", "high")).toBeGreaterThan(150);
  });

  it("«думает» движется не медленнее покоя (орбита)", () => {
    expect(meanSpeed("thinking")).toBeGreaterThanOrEqual(meanSpeed("idle"));
  });

  it("подвижность: низкая в покое — ширина не больше ~115", () => {
    expect(maxWidth("idle", "low")).toBeLessThanOrEqual(115);
    expect(maxWidth("idle", "low")).toBeLessThan(maxWidth("idle", "normal"));
    expect(maxWidth("idle", "normal")).toBeLessThanOrEqual(maxWidth("idle", "high"));
  });

  it("кольца только при слушании и растут с уровнем", () => {
    expect(coreFrame(1, "idle", 1).rings).toHaveLength(0);
    const lo = coreFrame(0.6, "listening", 0).rings[0]!.r;
    const hi = coreFrame(0.6, "listening", 1).rings[0]!.r;
    expect(hi).toBeGreaterThan(lo);
  });

  it("офлайн — бледное и почти статичное", () => {
    const a = coreFrame(0, "offline", 0), b = coreFrame(5, "offline", 0);
    expect(a.opacity).toBeLessThan(0.6);
    a.satellites.forEach((s, i) => expect(Math.abs(s.cx - b.satellites[i]!.cx)).toBeLessThan(3));
  });
});

describe("переход между состояниями", () => {
  const a = coreFrame(2, "idle", 0);
  const b = coreFrame(2, "listening", 0.5);
  it("k=0 — исходный кадр, k=1 — целевой, кольца появляются из нуля", () => {
    expect(blendFrames(a, b, 0).satellites).toEqual(a.satellites);
    expect(blendFrames(a, b, 1)).toBe(b);
    const half = blendFrames(a, b, 0.5);
    expect(half.rings).toHaveLength(2);
    expect(half.rings[0]!.opacity).toBeCloseTo(b.rings[0]!.opacity / 2, 5);
    expect(half.rings[0]!.r).toBeCloseTo(b.rings[0]!.r, 5);
  });
  it("ease: 0 → 0, 1 → 1, монотонно, без выхода за границы", () => {
    let prev = -1;
    for (let p = -0.2; p <= 1.2; p += 0.05) {
      const v = ease(p);
      expect(v).toBeGreaterThanOrEqual(prev);
      expect(v).toBeGreaterThanOrEqual(0);
      expect(v).toBeLessThanOrEqual(1);
      prev = v;
    }
  });
});
