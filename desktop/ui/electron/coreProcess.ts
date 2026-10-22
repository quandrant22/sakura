// Автозапуск ядра (SAKURA_CORE_AUTOSTART=1): main-процесс запускает `python -m desktop.core --headless`
// дочерним процессом, ждёт готовности (свежий ui.token), перезапускает при падении — не больше
// maxRestarts раз за windowMs — и закрывает ядро при выходе из приложения.
// Вывод консоли ядра — в logs/core-console.log; свой sakura.log ядро пишет само в ту же папку.
import { type ChildProcess, spawn as nodeSpawn, spawnSync } from "node:child_process";
import fs from "node:fs";
import net from "node:net";
import path from "node:path";

/** desktop/core/__main__.py: второй экземпляр ядра выходит с этим кодом — его не перезапускаем. */
export const EXIT_ALREADY_RUNNING = 3;

export type CoreState = "idle" | "starting" | "running" | "restarting" | "failed" | "external" | "stopped";

export interface CoreOptions {
  python: string;
  /** Корень репозитория: оттуда виден пакет desktop. */
  cwd: string;
  logDir: string;
  tokenFile: string;
  env?: NodeJS.ProcessEnv;
  maxRestarts?: number;
  windowMs?: number;
  restartDelayMs?: number;
  spawn?: typeof nodeSpawn;
  now?: () => number;
  log?: (line: string) => void;
  /** Смена состояния — окно и трей показывают «Ядро не запустилось». */
  onState?: (state: CoreState) => void;
  /** Закрыть ядро вместе с дочерними процессами (Windows: taskkill /T /F). */
  killTree?: (pid: number) => void;
  /** Живо ли уже ядро (блокировка core.lock + ответ локального API) — тогда не запускать второе. */
  probeExisting?: () => Promise<boolean>;
  /** pid владельца core.lock, если он жив (для ожидания прежнего ядра при перезапуске). */
  lockOwnerAlive?: () => boolean;
}

/** pid из core.lock (с позиции 1: байт 0 заблокирован ядром). */
export function readLockPid(lockFile: string): number | null {
  try {
    const fd = fs.openSync(lockFile, "r");
    try {
      const buf = Buffer.alloc(16);
      const n = fs.readSync(fd, buf, 0, 16, 1);
      const pid = Number.parseInt(buf.subarray(0, n).toString("utf8").trim(), 10);
      return Number.isFinite(pid) && pid > 0 ? pid : null;
    } finally {
      fs.closeSync(fd);
    }
  } catch {
    return null;
  }
}

export function pidAlive(pid: number | null): boolean {
  if (!pid) return false;
  try {
    process.kill(pid, 0);
    return true;
  } catch (e) {
    return (e as NodeJS.ErrnoException).code === "EPERM";
  }
}

/** Отвечает ли локальный API ядра на порту из ui.token (TCP-подключение к 127.0.0.1). */
export function apiAlive(tokenFile: string, timeoutMs = 800): Promise<boolean> {
  let port = 0;
  try {
    port = Number((JSON.parse(fs.readFileSync(tokenFile, "utf8")) as { port?: number }).port) || 0;
  } catch {
    return Promise.resolve(false);
  }
  if (!port) return Promise.resolve(false);
  return new Promise((resolve) => {
    const sock = net.connect({ host: "127.0.0.1", port });
    const done = (ok: boolean) => { sock.destroy(); resolve(ok); };
    sock.setTimeout(timeoutMs, () => done(false));
    sock.once("connect", () => done(true));
    sock.once("error", () => done(false));
  });
}

/** Ядро уже работает: владелец core.lock жив и API отвечает. */
export async function coreAlready(lockFile: string, tokenFile: string): Promise<boolean> {
  return pidAlive(readLockPid(lockFile)) && apiAlive(tokenFile);
}

/** Windows: дерево процессов ядра целиком — без осиротевших python. */
export function killTreeWin(pid: number): void {
  spawnSync("taskkill", ["/PID", String(pid), "/T", "/F"], { windowsHide: true, stdio: "ignore" });
}

export const coreAutostartEnabled = (env: NodeJS.ProcessEnv) => env.SAKURA_CORE_AUTOSTART === "1";

export class CoreSupervisor {
  private child: ChildProcess | null = null;
  private restarts: number[] = [];
  private timer: ReturnType<typeof setTimeout> | undefined;
  private startedAt = 0;
  private _state: CoreState = "idle";

  get state(): CoreState { return this._state; }
  set state(s: CoreState) {
    if (s === this._state) return;
    this._state = s;
    this.o.onState?.(s);
  }

  constructor(private o: CoreOptions) {}

  private get now() { return this.o.now ?? Date.now; }
  private note(line: string) {
    this.o.log?.(line);
    try {
      fs.mkdirSync(this.o.logDir, { recursive: true });
      fs.appendFileSync(path.join(this.o.logDir, "core-console.log"), `${new Date().toISOString()} [supervisor] ${line}\n`);
    } catch {
      // лог надзора необязателен
    }
  }

  /** Запуск с проверкой: живое ядро уже есть — подключаемся к нему, второе не запускаем. */
  async launch(): Promise<void> {
    if (this.state === "stopped") return;
    if (!this.o.python) {
      this.state = "failed";
      this.note("SAKURA_PYTHON не задан — ядро не запускаю (запускайте Сакуру ярлыком или Sakura.bat)");
      return;
    }
    if (this.o.probeExisting && await this.o.probeExisting()) {
      this.state = "external";
      this.note("ядро уже работает (core.lock и локальный API) — подключаюсь к нему");
      return;
    }
    this.start();
  }

  /** Перед перезапуском — дождаться, пока прежнее ядро отпустит core.lock (до 10 с). */
  private async restartAfterOldGone(): Promise<void> {
    const deadline = this.now() + 10_000;
    while (this.o.lockOwnerAlive?.() && this.now() < deadline) {
      await new Promise((r) => setTimeout(r, 250));
    }
    if (this.state !== "stopped") this.start();
  }

  start(): void {
    if (this.state === "stopped") return;
    fs.mkdirSync(this.o.logDir, { recursive: true });
    const out = fs.openSync(path.join(this.o.logDir, "core-console.log"), "a");
    this.startedAt = this.now();
    this.state = this.restarts.length ? "restarting" : "starting";
    const spawn = this.o.spawn ?? nodeSpawn;
    const child = spawn(this.o.python, ["-m", "desktop.core", "--headless"], {
      cwd: this.o.cwd,
      // SAKURA_PARENT_PID — ядро само завершится, если окно упало и не закрыло его.
      env: { ...process.env, ...this.o.env, PYTHONUNBUFFERED: "1", PYTHONIOENCODING: "utf-8",
             SAKURA_PARENT_PID: String(process.pid) },
      stdio: ["ignore", out, out],
      windowsHide: true,
    });
    fs.closeSync(out); // дочерний процесс держит свою копию дескриптора
    this.child = child;
    this.note(`старт ядра pid=${child.pid ?? "?"}`);
    child.on("error", (e) => { this.note(`не удалось запустить ядро: ${e.message}`); this.onExit(null); });
    child.on("exit", (code) => this.onExit(code));
  }

  private onExit(code: number | null) {
    this.child = null;
    if (this.state === "stopped") return;
    if (code === EXIT_ALREADY_RUNNING) {
      // Ядро уже работает отдельно (start_dev.ps1 или вручную) — окно подключится к нему.
      this.state = "external";
      this.note("ядро уже запущено другим процессом — не перезапускаю");
      return;
    }
    const now = this.now();
    const window = this.o.windowMs ?? 5 * 60_000;
    this.restarts = this.restarts.filter((t) => now - t < window);
    if (this.restarts.length >= (this.o.maxRestarts ?? 3)) {
      this.state = "failed";
      this.note(`ядро упало (код ${code}); лимит перезапусков исчерпан — смотрите logs\\sakura.log и crash.log`);
      return;
    }
    this.restarts.push(now);
    this.state = "restarting";
    this.note(`ядро завершилось (код ${code}); перезапуск ${this.restarts.length}`);
    this.timer = setTimeout(() => void this.restartAfterOldGone(), this.o.restartDelayMs ?? 2000);
  }

  /** Готово, когда ядро записало ui.token после своего старта (локальный API поднят). */
  async waitReady(timeoutMs = 60_000, pollMs = 250): Promise<boolean> {
    const deadline = this.now() + timeoutMs;
    while (this.now() < deadline) {
      if (this.state === "stopped" || this.state === "failed") return false;
      if (this.state === "external") return true;
      try {
        if (fs.statSync(this.o.tokenFile).mtimeMs >= this.startedAt - 1000) {
          this.state = "running";
          return true;
        }
      } catch {
        // файла ещё нет
      }
      await new Promise((r) => setTimeout(r, pollMs));
    }
    return false;
  }

  stop(): void {
    this.state = "stopped";
    clearTimeout(this.timer);
    if (this.child && this.child.exitCode === null) {
      this.note("закрываю ядро при выходе");
      const kill = this.o.killTree ?? (process.platform === "win32" ? killTreeWin : null);
      if (kill && this.child.pid) kill(this.child.pid);
      else this.child.kill();
    }
    this.child = null;
  }
}
