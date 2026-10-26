// Эталонные кадры ядра для CoreFrameTest: исполняет настольный coreFrame.ts как есть.
//
//   node mobile/android/tools/export-core-frames.mjs
//
// Источник — desktop/ui/src/core-gfx/coreFrame.ts из ветки origin/feat/desktop-integrated (только чтение,
// через `git show`). Node ≥ 22.18 исполняет .ts, убирая типы. Пишет app/src/test/resources/core_frames.json:
// t ∈ {0, 0.37, 1.5, 4.2} × 5 состояний × level {0, 0.5, 1} × mobility {low, normal, high}.
import { execFileSync } from "node:child_process";
import { mkdtempSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const REF = process.env.CORE_FRAME_REF ?? "origin/feat/desktop-integrated";
const SRC = "desktop/ui/src/core-gfx/coreFrame.ts";

const source = execFileSync("git", ["show", `${REF}:${SRC}`], { cwd: here, encoding: "utf8" });
const dir = mkdtempSync(join(tmpdir(), "core-frame-"));
const file = join(dir, "coreFrame.ts");
writeFileSync(file, source, "utf8");

try {
  const m = await import(pathToFileURL(file).href);
  const times = [0, 0.37, 1.5, 4.2];
  const states = ["idle", "listening", "thinking", "speaking", "offline"];
  const levels = [0, 0.5, 1];
  const mobility = ["low", "normal", "high"];
  const frames = [];
  for (const t of times)
    for (const state of states)
      for (const level of levels)
        for (const mob of mobility)
          frames.push({ t, state, level, mobility: mob, frame: m.coreFrame(t, state, level, mob) });
  const out = {
    source: `${REF}:${SRC}`,
    constants: {
      DROP_R: m.DROP_R, SATELLITES: m.SATELLITES, VIEWBOX: m.VIEWBOX, MAX_RING_R: m.MAX_RING_R,
      MERGE_PRESETS: m.MERGE_PRESETS, MOBILITY: m.MOBILITY,
    },
    frames,
  };
  const target = join(here, "..", "app", "src", "test", "resources", "core_frames.json");
  writeFileSync(target, JSON.stringify(out, null, 1) + "\n", "utf8");
  console.log(`записано ${frames.length} кадров → app/src/test/resources/core_frames.json`);
} finally {
  rmSync(dir, { recursive: true, force: true });
}
