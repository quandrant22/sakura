// Звуковой движок музыкального плеера: два <audio> (текущий + предзагрузка следующего),
// Web Audio: громкость × приглушение (GainNode), плавный переход, AnalyserNode → полосы.
export interface AudioEngine {
  load(src: string, startAt?: number): Promise<void>;
  preload(src: string | null): void;
  /** Плавно перейти на src за seconds (0 — сразу, без паузы, если src предзагружен). */
  switchTo(src: string, seconds: number): Promise<void>;
  play(): Promise<void>;
  pause(): void;
  seek(time: number): void;
  setVolume(v: number): void;
  setMuted(m: boolean): void;
  setDuck(gain: number, rampMs: number): void;
  setSinkId(id: string): Promise<void>;
  onTime(cb: (position: number, duration: number) => void): void;
  onEnded(cb: () => void): void;
  onError(cb: (message: string) => void): void;
  onLevel(cb: (bars: number[]) => void): void;
}

const BARS = 8;

type SinkCtx = AudioContext & { setSinkId?: (id: string) => Promise<void> };

export class HtmlAudioEngine implements AudioEngine {
  private els: [HTMLAudioElement, HTMLAudioElement];
  private gains: GainNode[] = [];
  private active = 0;
  private ctx: SinkCtx | null = null;
  private master: GainNode | null = null;
  private duck: GainNode | null = null;
  private analyser: AnalyserNode | null = null;
  private volume = 1;
  private muted = false;
  private timeCb: (p: number, d: number) => void = () => {};
  private endedCb: () => void = () => {};
  private errorCb: (m: string) => void = () => {};
  private levelCb: (b: number[]) => void = () => {};
  private raf = 0;
  private lastLevel = 0;

  constructor() {
    const mk = () => {
      const a = new Audio();
      a.crossOrigin = "anonymous"; // иначе Web Audio отдаст тишину для http://127.0.0.1
      a.preload = "auto";
      return a;
    };
    this.els = [mk(), mk()];
    this.els.forEach((el, i) => {
      el.addEventListener("timeupdate", () => i === this.active && this.timeCb(el.currentTime, el.duration || 0));
      el.addEventListener("ended", () => i === this.active && this.endedCb());
      el.addEventListener("error", () => i === this.active && el.src && this.errorCb(this.describe(el)));
    });
  }

  private describe(el: HTMLAudioElement): string {
    const c = el.error?.code;
    return c === 4 ? "Формат не поддерживается" : c === 2 ? "Ошибка сети" : "Не удалось воспроизвести";
  }

  /** Граф Web Audio создаётся лениво — AudioContext требует жеста пользователя. */
  private graph() {
    if (this.ctx) return;
    const ctx: SinkCtx = new AudioContext();
    this.ctx = ctx;
    this.duck = ctx.createGain();
    this.master = ctx.createGain();
    this.analyser = ctx.createAnalyser();
    this.analyser.fftSize = 256;
    this.els.forEach((el) => {
      const g = ctx.createGain();
      ctx.createMediaElementSource(el).connect(g);
      g.connect(this.master!);
      this.gains.push(g);
    });
    this.gains[1 - this.active]!.gain.value = 0; // второй плеер молчит до перехода
    this.master.connect(this.duck);
    this.duck.connect(this.analyser);
    this.analyser.connect(ctx.destination);
    this.applyVolume();
    this.loopLevel();
  }

  private loopLevel = () => {
    this.raf = requestAnimationFrame(this.loopLevel);
    const now = performance.now();
    if (!this.analyser || now - this.lastLevel < 100) return; // 10 раз в секунду
    this.lastLevel = now;
    const data = new Uint8Array(this.analyser.frequencyBinCount);
    this.analyser.getByteFrequencyData(data);
    const per = Math.floor(data.length / BARS);
    const bars = Array.from({ length: BARS }, (_, b) => {
      let s = 0;
      for (let i = b * per; i < (b + 1) * per; i++) s += data[i]!;
      return Math.round((s / per / 255) * 1000) / 1000;
    });
    this.levelCb(bars);
  };

  private applyVolume() {
    if (this.master) this.master.gain.value = this.muted ? 0 : this.volume;
    else this.els.forEach((el) => { el.volume = this.volume; el.muted = this.muted; });
  }

  private elAt(i: number): HTMLAudioElement {
    return i === 0 ? this.els[0] : this.els[1];
  }

  private get el(): HTMLAudioElement {
    return this.elAt(this.active);
  }

  async load(src: string, startAt = 0) {
    this.graph();
    await this.ctx?.resume();
    const el = this.el;
    el.src = src;
    el.currentTime = startAt;
    await el.play();
  }

  preload(src: string | null) {
    const other = this.elAt(1 - this.active);
    if (!src) return;
    if (other.src !== src) {
      other.src = src;
      other.load();
    }
  }

  async switchTo(src: string, seconds: number) {
    this.graph();
    const from = this.active;
    const to = 1 - from;
    const next = this.elAt(to);
    if (next.src !== src) next.src = src;
    next.currentTime = 0;
    this.active = to;
    const ctx = this.ctx!;
    const t = ctx.currentTime;
    const gFrom = this.gains[from]!.gain;
    const gTo = this.gains[to]!.gain;
    gTo.cancelScheduledValues(t);
    gFrom.cancelScheduledValues(t);
    if (seconds > 0) {
      gTo.setValueAtTime(0, t);
      gTo.linearRampToValueAtTime(1, t + seconds);
      gFrom.setValueAtTime(gFrom.value, t);
      gFrom.linearRampToValueAtTime(0, t + seconds);
      setTimeout(() => this.elAt(from).pause(), seconds * 1000 + 50);
    } else {
      gTo.setValueAtTime(1, t);
      gFrom.setValueAtTime(0, t);
      this.elAt(from).pause();
    }
    await next.play();
  }

  async play() {
    this.graph();
    await this.ctx?.resume();
    await this.el.play();
  }

  pause() {
    this.el.pause();
  }

  seek(time: number) {
    const el = this.el;
    el.currentTime = Math.max(0, Math.min(time, el.duration || time));
  }

  setVolume(v: number) {
    this.volume = Math.max(0, Math.min(1, v));
    this.applyVolume();
  }

  setMuted(m: boolean) {
    this.muted = m;
    this.applyVolume();
  }

  setDuck(gain: number, rampMs: number) {
    if (!this.ctx || !this.duck) return;
    const t = this.ctx.currentTime;
    this.duck.gain.cancelScheduledValues(t);
    this.duck.gain.setValueAtTime(this.duck.gain.value, t);
    this.duck.gain.linearRampToValueAtTime(gain, t + rampMs / 1000);
  }

  async setSinkId(id: string) {
    this.graph();
    // Звук идёт через Web Audio — устройство выбирается у AudioContext (Chromium 110+).
    if (this.ctx?.setSinkId) await this.ctx.setSinkId(id === "default" ? "" : id);
  }

  onTime(cb: (p: number, d: number) => void) { this.timeCb = cb; }
  onEnded(cb: () => void) { this.endedCb = cb; }
  onError(cb: (m: string) => void) { this.errorCb = cb; }
  onLevel(cb: (b: number[]) => void) { this.levelCb = cb; }

  dispose() {
    cancelAnimationFrame(this.raf);
    this.els.forEach((el) => { el.pause(); el.removeAttribute("src"); });
    void this.ctx?.close();
  }
}
