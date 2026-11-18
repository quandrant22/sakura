// Экран Яндекс.Музыки поверх приложения: открывается по команде Сакуры
// («открой плейлисты», «найди…», «покажи текст песни») и закрывается крестиком или Esc.
import { X } from "lucide-react";
import { useEffect } from "react";

import { useMusic } from "../../media/MediaContext";
import { MusicView } from "./MusicView";

export function YandexOverlay() {
  const show = useMusic((s) => s.yandexShow);
  const close = useMusic((s) => s.setYandexShow);

  useEffect(() => {
    if (!show) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") close(null); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [show, close]);

  if (!show) return null;
  const lyrics = show.view === "lyrics";
  return (
    <div role="dialog" aria-modal="true" aria-label={lyrics ? "Текст песни" : "Яндекс Музыка"}
         className="fixed inset-6 z-50 flex min-h-0 flex-col rounded-panel border border-line bg-panel p-4 shadow-soft">
      <header className="mb-3 flex items-center gap-2">
        <h2 className="min-w-0 flex-1 truncate text-sm font-semibold text-ink">{lyrics ? show.title : "Яндекс Музыка"}</h2>
        <button type="button" aria-label="Закрыть" onClick={() => close(null)} className="text-ink-dim hover:text-ink"><X size={18} /></button>
      </header>
      {lyrics ? (
        <pre className="min-h-0 flex-1 overflow-y-auto whitespace-pre-wrap font-sans text-sm leading-relaxed text-ink">{show.text}</pre>
      ) : (
        // key: новая команда открывает экран заново с новым запросом
        <div className="flex min-h-0 flex-1"><MusicView key={`${show.view}|${show.q ?? ""}`} initialView="yandex" initialQuery={show.q ?? ""} initialYandex={show.view === "playlists" ? "playlists" : undefined} /></div>
      )}
    </div>
  );
}
