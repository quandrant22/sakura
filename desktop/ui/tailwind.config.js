/** Цвета — только токены; значения тем в src/index.css (:root — «Сакура-ночь», [data-theme="sketch"] — «Как в наброске»).
 *  Токены описаны в desktop/docs/UI.md — меняй оба места вместе. */
const c = (v) => `rgb(var(--${v}) / <alpha-value>)`;

/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./preview-core.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: c("bg"),
        bar: c("bar"),
        panel: c("panel"),
        panel2: c("panel2"),
        line: "var(--line)",
        accent: { DEFAULT: c("accent"), deep: c("accent-deep"), soft: "var(--accent-soft)" },
        ink: { DEFAULT: c("ink"), dim: c("ink-dim") },
        online: c("online"),
        warn: c("warn"),
        ym: { yellow: c("ym-yellow"), on: c("ym-on-yellow"), bar: c("ym-bar") },
      },
      backgroundImage: {
        "accent-grad": "linear-gradient(135deg, rgb(var(--accent)), rgb(var(--accent-deep)))",
      },
      // card — карточки по наброску (rx 20); win — окно; btn — кнопки и пункты меню.
      borderRadius: { win: "14px", card: "20px", panel: "20px", btn: "12px" },
      spacing: { gap: "20px", edge: "30px" },
      fontFamily: { sans: ["Inter", "Segoe UI", "system-ui", "sans-serif"] },
      letterSpacing: { logo: "0.32em" },
      boxShadow: {
        soft: "0 8px 30px rgba(0,0,0,0.35)",
        glow: "0 0 18px var(--accent-soft)",
      },
      transitionDuration: { DEFAULT: "200ms" },
    },
  },
  plugins: [],
};
