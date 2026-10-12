// Настройки. Фаза 3Б: раздел «Медиа» (+ автозапуск). Остальные разделы — фаза 3.
import { FolderPlus, Power, Trash2, X } from "lucide-react";
import { type ReactNode, useEffect, useState } from "react";

import { bridge } from "../bridge";
import { Card } from "../components/ui";
import { useMediaClient, useMediaMeta, useMusic } from "../media/MediaContext";
import type { MediaSettings } from "../media/types";
import { errorText } from "../store";

function Row({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <div className="grid grid-cols-[220px_1fr] items-start gap-4 border-b border-line py-3 last:border-0">
      <div><div className="text-sm text-ink">{label}</div>{hint && <div className="mt-0.5 text-xs text-ink-dim">{hint}</div>}</div>
      <div className="min-w-0">{children}</div>
    </div>
  );
}

const input = "rounded-lg border border-line bg-panel2 px-2.5 py-1.5 text-sm text-ink outline-none focus:border-accent";

function Folders({ value, onChange, label }: { value: string[]; onChange(v: string[]): void; label: string }) {
  const [draft, setDraft] = useState("");
  const add = (p: string) => p.trim() && !value.includes(p.trim()) && onChange([...value, p.trim()]);
  return (
    <div className="space-y-2">
      {value.length === 0 && <div className="text-xs text-ink-dim">Папки не выбраны</div>}
      {value.map((p) => (
        <div key={p} className="flex items-center gap-2 text-sm text-ink">
          <span className="truncate">{p}</span>
          <button type="button" aria-label={`Убрать ${p}`} onClick={() => onChange(value.filter((x) => x !== p))} className="text-ink-dim hover:text-accent"><X size={14} /></button>
        </div>
      ))}
      <div className="flex gap-2">
        <input value={draft} onChange={(e) => setDraft(e.target.value)} placeholder="C:\Users\…" aria-label={label} className={input + " flex-1"} />
        <button type="button" onClick={async () => { const p = draft || (await bridge().media.chooseFolder()); if (p) add(p); setDraft(""); }}
                className="flex items-center gap-1 rounded-lg border border-line px-2.5 text-xs text-ink-dim hover:text-ink"><FolderPlus size={14} /> Добавить</button>
      </div>
    </div>
  );
}

function MediaSection() {
  const client = useMediaClient();
  const s = useMediaMeta((m) => m.settings);
  const scan = useMediaMeta((m) => m.scan);
  const sinkId = useMusic((m) => m.sinkId);
  const setSinkId = useMusic((m) => m.setSinkId);
  const [outputs, setOutputs] = useState<MediaDeviceInfo[]>([]);
  const [msg, setMsg] = useState<string | null>(null);

  useEffect(() => {
    void navigator.mediaDevices?.enumerateDevices?.().then((d) => setOutputs(d.filter((x) => x.kind === "audiooutput"))).catch(() => {});
  }, []);

  if (!s) return <div className="p-4 text-sm text-ink-dim">Нет связи с ядром Сакуры</div>;
  const set = async (key: keyof MediaSettings, value: unknown) => {
    try {
      await client.call("media_settings", { key, value });
      setMsg(null);
    } catch (e) {
      setMsg(errorText(e));
    }
  };

  return (
    <div className="px-4 pb-2">
      <Row label="Папки музыки"><Folders label="Папка музыки" value={s.music_folders} onChange={(v) => void set("music_folders", v)} /></Row>
      <Row label="Папки видео"><Folders label="Папка видео" value={s.video_folders} onChange={(v) => void set("video_folders", v)} /></Row>
      <Row label="Медиатека" hint={scan?.state === "running" ? `Сканирую: ${scan.done ?? 0} из ${scan.total ?? "?"}` :
                                   scan?.state === "done" ? `Готово: +${scan.added ?? 0}, −${scan.removed ?? 0}` : undefined}>
        <div className="flex gap-2">
          <button type="button" onClick={() => void client.call("media_scan")} className="rounded-lg bg-accent px-3 py-1.5 text-xs text-white">Пересканировать</button>
          <button type="button" onClick={() => void client.call("media_clear_covers")} className="flex items-center gap-1 rounded-lg border border-line px-3 py-1.5 text-xs text-ink-dim hover:text-ink">
            <Trash2 size={13} /> Очистить кэш обложек</button>
        </div>
      </Row>
      <Row label="Устройство вывода" hint="Для встроенного плеера">
        <select value={sinkId} onChange={(e) => void setSinkId(e.target.value)} aria-label="Устройство вывода" className={input}>
          <option value="default">По умолчанию</option>
          {outputs.filter((o) => o.deviceId !== "default").map((o) => <option key={o.deviceId} value={o.deviceId}>{o.label || o.deviceId}</option>)}
        </select>
      </Row>
      <Row label="Плавный переход" hint="CROSSFADE_S, 0 — выключено">
        <label className="flex items-center gap-3 text-sm text-ink">
          <input type="range" min={0} max={12} step={1} value={s.crossfade_s} aria-label="Плавный переход, секунды"
                 onChange={(e) => void set("crossfade_s", Number(e.target.value))} className="w-48 accent-[#ff4d94]" />
          {s.crossfade_s} с</label>
      </Row>
      <Row label="Приглушение при разговоре" hint="PLAYER_DUCK_PCT — громкость плееров, пока Сакура слушает или говорит">
        <label className="flex items-center gap-3 text-sm text-ink">
          <input type="range" min={0} max={100} step={5} value={s.player_duck_pct} aria-label="Приглушение, процентов"
                 onChange={(e) => void set("player_duck_pct", Number(e.target.value))} className="w-48 accent-[#ff4d94]" />
          {s.player_duck_pct}%</label>
      </Row>
      <Row label="YouTube" hint="embedded — встроенный плеер, remote — вкладка браузера">
        <select value={s.youtube_mode} onChange={(e) => void set("youtube_mode", e.target.value)} aria-label="Режим YouTube" className={input}>
          <option value="embedded">Встроенный плеер</option>
          <option value="remote">Вкладка браузера</option>
        </select>
      </Row>
      <Row label="Прокси для YouTube" hint="Только для плеера: http://host:port или socks5://host:port">
        <input defaultValue={s.youtube_proxy} onBlur={(e) => void set("youtube_proxy", e.target.value.trim())} placeholder="не задан"
               aria-label="Прокси для YouTube" className={input + " w-72"} />
      </Row>
      <Row label="Яндекс.Музыка" hint={`Во встроенном плеере, ${s.yandex_note ?? "неофициальный доступ"}; нужен YANDEX_MUSIC_TOKEN в .env`}>
        <label className="flex items-center gap-2 text-sm text-ink">
          <input type="checkbox" checked={s.music_yandex} onChange={(e) => void set("music_yandex", e.target.checked)} className="accent-[#ff4d94]" />
          Включить</label>
      </Row>
      {msg && <div role="alert" className="py-2 text-sm text-accent">{msg}</div>}
    </div>
  );
}

function AutostartRow() {
  const [on, setOn] = useState(false);
  useEffect(() => { void bridge().autostart.get().then(setOn); }, []);
  return (
    <div className="px-4 pb-2">
      <Row label="Автозапуск" hint="Запуск Sakura при входе в Windows (реестр Run текущего пользователя)">
        <label className="flex items-center gap-2 text-sm text-ink">
          <input type="checkbox" checked={on} onChange={(e) => void bridge().autostart.set(e.target.checked).then(setOn)} className="accent-[#ff4d94]" />
          <Power size={14} /> Запускать вместе с Windows</label>
      </Row>
    </div>
  );
}

export function Settings() {
  return (
    <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto pr-1">
      <Card title="Медиа"><MediaSection /></Card>
      <Card title="Система"><AutostartRow /></Card>
    </div>
  );
}
