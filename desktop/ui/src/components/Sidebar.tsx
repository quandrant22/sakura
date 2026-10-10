import { Brain, Cpu, MessageCircle, User, Workflow } from "lucide-react";
import { useEffect, useState } from "react";

import { bridge } from "../bridge";
import { useApp } from "../store";
import { CharacterArt } from "./CharacterArt";
import { SakuraLogo } from "./SakuraLogo";

export type Section = "chat" | "devices" | "scenarios" | "memory" | "profile";

const MENU: { id: Section; label: string; icon: typeof MessageCircle }[] = [
  { id: "chat", label: "Чат", icon: MessageCircle },
  { id: "devices", label: "Устройства", icon: Cpu },
  { id: "scenarios", label: "Сценарии", icon: Workflow },
  { id: "memory", label: "Память", icon: Brain },
  { id: "profile", label: "Профиль", icon: User },
];

export function Sidebar({ section, onSection }: { section: Section; onSection(s: Section): void }) {
  const [version, setVersion] = useState(__APP_VERSION__);
  const online = useApp((s) => s.link === "open" && s.server.online);
  useEffect(() => {
    void bridge().version().then((v) => v !== "dev" && setVersion(v));
  }, []);

  return (
    <aside className="flex w-[246px] shrink-0 flex-col gap-4">
      <div className="overflow-hidden rounded-panel border border-line bg-panel shadow-soft">
        <CharacterArt className="h-52" />
        <div className="relative z-10 -mt-10 px-4 pb-4">
          <div className="text-lg font-semibold text-accent">Sakura</div>
          <div className="flex items-center gap-2 text-xs text-ink-dim">
            <span className={"h-2 w-2 rounded-full " + (online ? "bg-online" : "bg-ink-dim")} />
            {online ? "Онлайн" : "Нет связи"}
          </div>
          <p className="mt-2 text-sm text-ink">Я рядом. Чем могу помочь?</p>
        </div>
      </div>

      <nav className="flex flex-col gap-1 rounded-panel border border-line bg-panel p-2" aria-label="Меню">
        {MENU.map(({ id, label, icon: Icon }) => (
          <button key={id} type="button" onClick={() => onSection(id)}
                  aria-current={section === id ? "page" : undefined}
                  className={"flex items-center gap-3 rounded-card px-3 py-2.5 text-sm transition-colors " +
                    (section === id ? "bg-accent text-white shadow-glow" : "text-ink-dim hover:bg-white/5 hover:text-ink")}>
            <Icon size={18} /> {label}
          </button>
        ))}
      </nav>

      <div className="mt-auto flex items-center gap-2 px-2 pb-1 text-xs text-ink-dim">
        <SakuraLogo size={18} /> Sakura v{version}
      </div>
    </aside>
  );
}
