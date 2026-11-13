// Цвет и подпись состояния Сакуры — из её оригинального HUD (agent/ui/overlay.py: «Япония × будущее»):
// слушает — голубой, думает — золото, говорит — розовый, катакана под именем. Покой — фирменный акцент.
// Используют ядро-капля (SakuraCore), левая колонка и сцена (оверлей).
import type { CoreVisualState } from "./coreFrame";

export interface StateStyle {
  /** Основной цвет состояния (капля, кольца, точка статуса). */
  color: string;
  /** Тёмный конец градиента капли. */
  deep: string;
  /** Свечение вокруг (rgba). */
  glow: string;
  /** Катакана состояния — как в оригинальном HUD. */
  kana: string;
  label: string;
}

export const STATE_STYLE: Record<CoreVisualState, StateStyle> = {
  idle: { color: "#FF6AE3", deep: "#3E0074", glow: "rgba(255,106,227,.35)", kana: "待機中", label: "Онлайн" },
  listening: { color: "#4FD8FF", deep: "#1B2A8F", glow: "rgba(79,216,255,.45)", kana: "聴取中", label: "Слушаю" },
  thinking: { color: "#FFCF6B", deep: "#6B1F7A", glow: "rgba(255,207,107,.40)", kana: "思考中", label: "Думаю" },
  speaking: { color: "#FF7EB9", deep: "#5A0F8C", glow: "rgba(255,126,185,.50)", kana: "発話中", label: "Говорю" },
  offline: { color: "#6B6475", deep: "#1D1628", glow: "rgba(107,100,117,.20)", kana: "切断", label: "Нет связи" },
};
