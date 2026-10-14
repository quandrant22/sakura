// Экран «Профиль»: как Сакура обращается, тихие часы, голос и тон, уведомления (profile_get/profile_set).
import { UserRound } from "lucide-react";
import { useEffect, useState } from "react";

import { CoreError } from "../api/types";
import { Card } from "../components/ui";
import { useMediaClient } from "../media/MediaContext";
import { errorText } from "../store";

export interface ProfileData {
  name: string; address_as: string; quiet_hours: string; voice: string; tone: string;
  notifications: { telegram?: boolean; sound?: boolean };
}

const input = "rounded-lg border border-line bg-panel2 px-2.5 py-1.5 text-sm text-ink outline-none focus:border-accent";

export function Profile() {
  const client = useMediaClient();
  const [p, setP] = useState<ProfileData | null>(null);
  const [state, setState] = useState<"loading" | "ready" | "error" | "unsupported">("loading");
  const [msg, setMsg] = useState("");

  useEffect(() => {
    let alive = true;
    client.server<{ profile: ProfileData }>({ type: "profile_get" }).then(
      (r) => { if (alive) { setP(r.profile); setState("ready"); } },
      (e: unknown) => {
        if (!alive) return;
        const un = e instanceof CoreError && (e.code === "unsupported" || e.code === "unknown_type");
        setState(un ? "unsupported" : "error");
        setMsg(un ? "Сервер не поддерживает «Профиль»" : errorText(e));
      },
    );
    return () => { alive = false; };
  }, [client]);

  const save = async () => {
    if (!p) return;
    try {
      const r = await client.server<{ profile: ProfileData }>({ type: "profile_set", ...p });
      setP(r.profile);
      setMsg("Сохранено");
    } catch (e) {
      setMsg(errorText(e));
    }
  };
  const field = (key: keyof ProfileData, label: string, hint: string) => (
    <label className="grid grid-cols-[200px_1fr] items-center gap-4 border-b border-line py-3">
      <span><span className="block text-sm text-ink">{label}</span><span className="text-xs text-ink-dim">{hint}</span></span>
      <input value={String(p?.[key] ?? "")} onChange={(e) => setP((x) => (x ? { ...x, [key]: e.target.value } : x))}
             aria-label={label} className={input} />
    </label>
  );

  return (
    <Card title="Профиль" icon={<UserRound size={18} />} className="h-full min-h-0">
      <div className="min-h-0 flex-1 overflow-y-auto px-4 pb-4">
        {state === "loading" && <div className="text-sm text-ink-dim">Загрузка…</div>}
        {state !== "ready" && state !== "loading" && <div role="alert" className="text-sm text-warn">{msg}</div>}
        {state === "ready" && p && (
          <form onSubmit={(e) => { e.preventDefault(); void save(); }}>
            {field("name", "Как вас зовут", "Сакура обращается по имени")}
            {field("address_as", "Обращение", "«ты» или «вы»")}
            {field("quiet_hours", "Тихие часы", "Например 23:00-07:00: без голосовых уведомлений")}
            {field("voice", "Голос", "Голос озвучки на сервере")}
            {field("tone", "Тон", "calm, playful, formal")}
            <div className="grid grid-cols-[200px_1fr] items-center gap-4 py-3 text-sm text-ink">
              <span>Уведомления</span>
              <span className="flex gap-4">
                {(["telegram", "sound"] as const).map((k) => (
                  <label key={k} className="flex items-center gap-2">
                    <input type="checkbox" checked={Boolean(p.notifications?.[k])} className="accent-accent"
                           onChange={(e) => setP({ ...p, notifications: { ...p.notifications, [k]: e.target.checked } })} />
                    {k === "telegram" ? "Telegram" : "Звук"}
                  </label>
                ))}
              </span>
            </div>
            <div className="flex items-center gap-3">
              <button type="submit" className="rounded-full bg-accent-grad px-4 py-1.5 text-sm text-white">Сохранить</button>
              {msg && <span role="status" className="text-xs text-ink-dim">{msg}</span>}
            </div>
          </form>
        )}
      </div>
    </Card>
  );
}
