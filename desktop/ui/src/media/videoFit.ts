// Вписывание видео в тело виджета: явные width/height и смещение, без transform-масштаба.
export type VideoFit = "fit" | "fill";

export const ASPECT_16_9 = 16 / 9;

export interface FitRect { left: number; top: number; width: number; height: number }

/**
 * fit  — максимальный прямоугольник заданных пропорций внутри box, по центру (letterbox);
 * fill — прямоугольник пропорций, покрывающий box целиком (лишнее обрежет overflow: hidden).
 * Целые пиксели: width/height округляются вниз, чтобы не вылезать за box.
 */
export function fitRect(boxW: number, boxH: number, aspect = ASPECT_16_9, mode: VideoFit = "fit"): FitRect {
  if (!(boxW > 0) || !(boxH > 0) || !(aspect > 0)) return { left: 0, top: 0, width: 0, height: 0 };
  const byWidth = boxW / aspect;            // высота, если упереться в ширину
  const useWidth = mode === "fit" ? byWidth <= boxH : byWidth >= boxH;
  const width = Math.floor(useWidth ? boxW : boxH * aspect);
  const height = Math.floor(useWidth ? byWidth : boxH);
  return { left: Math.round((boxW - width) / 2), top: Math.round((boxH - height) / 2), width, height };
}
