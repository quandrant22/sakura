import { EventEmitter } from "node:events";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { CoreSupervisor, coreAutostartEnabled, EXIT_ALREADY_RUNNING } from "./coreProcess";

class FakeChild extends EventEmitter {
  pid = 4242;
  exitCode: number | null = null;
  killed = false;
  kill() { this.killed = true; this.exitCode = 0; return true; }
  exit(code: number) { this.exitCode = code; this.emit("exit", code); }
}

let dir = "";
let children: FakeChild[] = [];
let clock = 0;
const spawn = vi.fn(() => { const c = new FakeChild(); children.push(c); return c; });

function make(extra: Partial<ConstructorParameters<typeof CoreSupervisor>[0]> = {}) {
  return new CoreSupervisor({
    python: "python", cwd: dir, logDir: path.join(dir, "logs"), tokenFile: path.join(dir, "ui.token"),
    spawn: spawn as never, now: () => clock, restartDelayMs: 10, ...extra,
  });
}

beforeEach(() => {
  dir = fs.mkdtempSync(path.join(os.tmpdir(), "sakura-core-"));
  children = []; clock = 1_000_000; spawn.mockClear();
  vi.useFakeTimers();
});
afterEach(() => { vi.useRealTimers(); fs.rmSync(dir, { recursive: true, force: true }); });

test("включается только при SAKURA_CORE_AUTOSTART=1", () => {
  expect(coreAutostartEnabled({})).toBe(false);
  expect(coreAutostartEnabled({ SAKURA_CORE_AUTOSTART: "0" })).toBe(false);
  expect(coreAutostartEnabled({ SAKURA_CORE_AUTOSTART: "1" })).toBe(true);
});

test("запуск: python -m desktop.core --headless, вывод в logs/core-console.log", () => {
  make().start();
  expect(spawn).toHaveBeenCalledTimes(1);
  const [cmd, args, opts] = spawn.mock.calls[0] as unknown as [string, string[], { cwd: string; windowsHide: boolean }];
  expect(cmd).toBe("python");
  expect(args).toEqual(["-m", "desktop.core", "--headless"]);
  expect(opts.cwd).toBe(dir);
  expect(opts.windowsHide).toBe(true);
  expect(fs.existsSync(path.join(dir, "logs", "core-console.log"))).toBe(true);
});

test("перезапуск при падении — не больше 3 раз за 5 минут, потом failed", () => {
  const s = make();
  s.start();
  for (let i = 0; i < 3; i++) {
    children.at(-1)!.exit(1);
    expect(s.state).toBe("restarting");
    vi.advanceTimersByTime(20);
    clock += 1000;
  }
  expect(spawn).toHaveBeenCalledTimes(4);
  children.at(-1)!.exit(1);
  expect(s.state).toBe("failed");
  vi.advanceTimersByTime(100);
  expect(spawn).toHaveBeenCalledTimes(4);
});

test("старые падения за пределами 5 минут не считаются", () => {
  const s = make();
  s.start();
  for (let i = 0; i < 6; i++) {
    children.at(-1)!.exit(1);
    vi.advanceTimersByTime(20);
    clock += 2 * 60_000; // по падению раз в 2 минуты — в окне не больше трёх
  }
  expect(s.state).not.toBe("failed");
  expect(spawn).toHaveBeenCalledTimes(7);
});

test("ядро уже запущено отдельно — не перезапускаем, окно подключится к нему", async () => {
  const s = make();
  s.start();
  children[0]!.exit(EXIT_ALREADY_RUNNING);
  expect(s.state).toBe("external");
  vi.advanceTimersByTime(100);
  expect(spawn).toHaveBeenCalledTimes(1);
  await expect(s.waitReady(1000)).resolves.toBe(true);
});

test("готовность — свежий ui.token; старый файл не считается", async () => {
  const token = path.join(dir, "ui.token");
  fs.writeFileSync(token, "{}");
  const old = new Date(clock - 60_000);
  fs.utimesSync(token, old, old);
  const s = make();
  s.start();
  const ready = s.waitReady(500, 50);
  await vi.advanceTimersByTimeAsync(100);
  const now = new Date(clock);
  fs.utimesSync(token, now, now);
  await vi.advanceTimersByTimeAsync(100);
  await expect(ready).resolves.toBe(true);
  expect(s.state).toBe("running");
});

test("выход из приложения закрывает ядро и не перезапускает", () => {
  const s = make();
  s.start();
  s.stop();
  expect(children[0]!.killed).toBe(true);
  children[0]!.emit("exit", 1);
  vi.advanceTimersByTime(100);
  expect(spawn).toHaveBeenCalledTimes(1);
  expect(s.state).toBe("stopped");
});
