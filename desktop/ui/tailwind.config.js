/** Тема «Сакура-ночь». Токены описаны в desktop/docs/UI.md — меняй оба места вместе. */
/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: "#0a0610",
        panel: "#120c1a",
        panel2: "#160f20",
        line: "rgba(255,255,255,0.06)",
        accent: { DEFAULT: "#ff4d94", soft: "rgba(255,77,148,0.14)" },
        ink: { DEFAULT: "#f1e9f5", dim: "#9b8fa8" },
        online: "#3ddc97",
      },
      borderRadius: { win: "14px", card: "16px", panel: "18px" },
      fontFamily: { sans: ["Inter", "Segoe UI", "system-ui", "sans-serif"] },
      letterSpacing: { logo: "0.32em" },
      boxShadow: {
        soft: "0 8px 30px rgba(0,0,0,0.35)",
        glow: "0 0 18px rgba(255,77,148,0.35)",
      },
      transitionDuration: { DEFAULT: "200ms" },
    },
  },
  plugins: [],
};
