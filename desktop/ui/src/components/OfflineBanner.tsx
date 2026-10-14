// Офлайн-баннер: нет связи с ядром (окно переподключается) или с сервером (ядро работает локально).
import { WifiOff } from "lucide-react";

import { useT } from "../i18n";
import { useApp } from "../store";

export function OfflineBanner() {
  const t = useT();
  const link = useApp((s) => s.link);
  const online = useApp((s) => s.server.online);
  const offlineMode = useApp((s) => Boolean(s.settings?.offline));
  let text: string | null = null;
  if (link !== "open") text = t("Нет связи с ядром Сакуры — переподключаюсь…");
  else if (!online && !offlineMode) text = t("Нет связи с сервером: голосовые ответы недоступны, управление компьютером работает.");
  if (!text) return null;
  return (
    <div aria-live="polite" aria-label="Связь" className="flex items-center gap-2 border-b border-warn/40 bg-warn/10 px-4 py-1.5 text-xs text-warn">
      <WifiOff size={14} className="shrink-0" /> {text}
    </div>
  );
}
