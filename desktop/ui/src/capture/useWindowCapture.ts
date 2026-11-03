// Поток окна приложения: getDisplayMedia ровно того окна, которое выбрано (main проверяет выбор).
// Ничего не записывается: поток живёт только в <video>; при «Стоп», закрытии окна-источника,
// автостопе или размонтировании — остановлен.
import { useCallback, useEffect, useRef, useState } from "react";

import { bridge } from "../bridge";
import { adaptiveFps, CAPTURE_MAX, isBlackFrame } from "./captureLogic";

export type CaptureState = "idle" | "starting" | "live" | "ended" | "black" | "error";

/** Сколько минут показ идёт без остановки, прежде чем выключится сам (WINDOW_CAPTURE_AUTOSTOP_MIN). */
export const AUTOSTOP_MIN = 30;
const BLACK_CHECK_MS = 2000;

export function useWindowCapture(opts: { baseFps: number; width: number; hidden: boolean; interacting: boolean;
                                         viaMini?: boolean }) {
  const [stream, setStream] = useState<MediaStream | null>(null);
  const [state, setState] = useState<CaptureState>("idle");
  const [error, setError] = useState<string | null>(null);
  const [src, setSrc] = useState({ width: 0, height: 0 });
  const [since, setSince] = useState(0);
  const videoRef = useRef<HTMLVideoElement | null>(null);

  const stop = useCallback((next: CaptureState = "idle") => {
    setStream((s) => {
      s?.getTracks().forEach((t) => t.stop());
      return null;
    });
    setState(next);
  }, []);

  const start = useCallback(async (sourceId: string) => {
    stop("starting");
    setError(null);
    try {
      if (!opts.viaMini && !(await bridge().capture.select(sourceId))) throw new Error("окно не выбрано");
      const s = await navigator.mediaDevices.getDisplayMedia({
        audio: false,
        video: { frameRate: opts.baseFps, width: { max: CAPTURE_MAX.width }, height: { max: CAPTURE_MAX.height } },
      });
      const track = s.getVideoTracks()[0];
      track?.addEventListener("ended", () => stop("ended")); // окно-источник закрыто
      const st = track?.getSettings();
      setSrc({ width: st?.width ?? 0, height: st?.height ?? 0 });
      setStream(s);
      setSince(Date.now());
      setState("live");
    } catch (e) {
      setError((e as Error).message || "захват не удался");
      setState("error");
    }
  }, [opts.baseFps, opts.viaMini, stop]);

  // Пропорции — из фактического размера кадра; пересчитываются, когда окно-источник меняет размер.
  const onResize = useCallback((v: HTMLVideoElement) => {
    if (v.videoWidth > 0 && v.videoHeight > 0) setSrc({ width: v.videoWidth, height: v.videoHeight });
  }, []);

  // Адаптивная частота кадров.
  const fps = adaptiveFps(opts.baseFps, opts.width, opts.hidden, opts.interacting);
  useEffect(() => {
    const t = stream?.getVideoTracks()[0];
    void t?.applyConstraints({ frameRate: fps }).catch(() => {});
  }, [stream, fps]);

  // Свёрнутое или защищённое окно отдаёт чёрный кадр — показываем плашку вместо чёрного прямоугольника.
  useEffect(() => {
    if (!stream) return;
    const canvas = document.createElement("canvas");
    canvas.width = canvas.height = 16;
    const ctx = canvas.getContext("2d", { willReadFrequently: true });
    const id = setInterval(() => {
      const v = videoRef.current;
      if (!ctx || !v || v.readyState < 2) return;
      ctx.drawImage(v, 0, 0, 16, 16);
      setState((s) => (s === "live" || s === "black" ? (isBlackFrame(ctx.getImageData(0, 0, 16, 16).data) ? "black" : "live") : s));
    }, BLACK_CHECK_MS);
    return () => clearInterval(id);
  }, [stream]);

  // Автостоп.
  useEffect(() => {
    if (!stream) return;
    const t = setTimeout(() => stop("idle"), AUTOSTOP_MIN * 60_000);
    return () => clearTimeout(t);
  }, [stream, stop]);

  useEffect(() => () => stream?.getTracks().forEach((t) => t.stop()), [stream]);

  /** Один кадр JPEG (≤1280 px, q 0.7) — только по явному «Спросить про окно», на диск не пишется. */
  const grabFrame = useCallback((): string | null => {
    const v = videoRef.current;
    if (!v || !v.videoWidth) return null;
    const k = Math.min(1, 1280 / v.videoWidth);
    const c = document.createElement("canvas");
    c.width = Math.round(v.videoWidth * k);
    c.height = Math.round(v.videoHeight * k);
    c.getContext("2d")?.drawImage(v, 0, 0, c.width, c.height);
    return c.toDataURL("image/jpeg", 0.7).split(",")[1] ?? null;
  }, []);

  return { stream, state, error, src, since, fps, start, stop, videoRef, onResize, grabFrame };
}
