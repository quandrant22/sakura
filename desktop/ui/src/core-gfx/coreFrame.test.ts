import { describe, expect, it } from "vitest";
import { coreFrame, VIEWBOX, type CoreVisualState } from "./coreFrame";

const STATES: CoreVisualState[] = ["idle", "listening", "thinking", "speaking", "offline"];

function bbox(f: ReturnType<typeof coreFrame>) {
  const all = [f.drop, ...f.satellites];
  return {
    minX: Math.min(...all.map((c) => c.cx - c.r)), maxX: Math.max(...all.map((c) => c.cx + c.r)),
    minY: Math.min(...all.map((c) => c.cy - c.r)), maxY: Math.max(...all.map((c) => c.cy + c.r)),
  };
}

describe("coreFrame", () => {
  it("нет NaN и всё внутри viewBox", () => {
    for (const s of STATES)
      for (const level of [0, 0.5, 1, NaN, -3, 7])
        for (let t = 0; t < 30; t += 0.37) {
          const f = coreFrame(t, s, level);
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

  it("при максимальном раскрытии силуэт ≈155x149", () => {
    let w = 0, h = 0;
    for (let t = 0; t < 60; t += 0.05) {
      const b = bbox(coreFrame(t, "thinking", 0));
      w = Math.max(w, b.maxX - b.minX); h = Math.max(h, b.maxY - b.minY);
    }
    expect(w).toBeGreaterThan(150); expect(w).toBeLessThan(160);
    expect(h).toBeGreaterThan(144); expect(h).toBeLessThan(154);
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
