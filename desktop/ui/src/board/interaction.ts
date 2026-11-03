// «Идёт взаимодействие с доской» (перетаскивание или изменение размера виджета).
// Пока оно идёт: на <body> класс is-interacting (pointer-events: none для iframe/video/canvas,
// user-select: none — index.css), превью окна снижает частоту до 1 кадра, видео не перехватывает мышь.
import { createStore, useStore } from "zustand";

export const interactionStore = createStore<{ active: boolean; set(on: boolean): void }>()((set) => ({
  active: false,
  set(on) {
    if (typeof document !== "undefined") document.body.classList.toggle("is-interacting", on);
    set({ active: on });
  },
}));

export const useInteracting = () => useStore(interactionStore, (s) => s.active);
