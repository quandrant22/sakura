import { Copy, Minus, Square, X } from "lucide-react";
import { type ReactNode, useEffect, useState } from "react";

import { bridge } from "../bridge";
import { SakuraLogo } from "./SakuraLogo";

const TABS = ["Главная", "Устройства", "Сценарии", "Настройки"] as const;
export type Tab = (typeof TABS)[number];

interface Props {
  tab: Tab;
  onTab(tab: Tab): void;
}

export function TitleBar({ tab, onTab }: Props) {
  const [maximized, setMaximized] = useState(false);

  useEffect(() => {
    void bridge().window.isMaximized().then(setMaximized);
    return bridge().window.onMaximized(setMaximized);
  }, []);

  return (
    <header className="drag flex h-16 items-center gap-6 border-b border-line px-5">
      <div className="flex items-center gap-3">
        <SakuraLogo size={30} />
        <div className="leading-tight">
          <div className="text-sm font-semibold tracking-logo text-ink">SAKURA</div>
          <div className="text-[11px] text-ink-dim">Your AI companion</div>
        </div>
      </div>

      <nav className="no-drag ml-8 flex gap-1" aria-label="Разделы">
        {TABS.map((t) => (
          <button
            key={t}
            type="button"
            onClick={() => onTab(t)}
            aria-current={t === tab ? "page" : undefined}
            className={
              "rounded-card px-4 py-2 text-sm transition-colors " +
              (t === tab ? "bg-accent-soft text-accent shadow-glow" : "text-ink-dim hover:text-ink")
            }
          >
            {t}
          </button>
        ))}
      </nav>

      <div className="ml-auto flex items-center gap-2 text-xs text-ink-dim">
        <span className="h-2 w-2 rounded-full bg-online shadow-[0_0_8px_#3ddc97]" />
        Система активна
      </div>

      <div className="no-drag flex items-center gap-1">
        <WinButton label="Свернуть" onClick={() => void bridge().window.minimize()}>
          <Minus size={16} />
        </WinButton>
        <WinButton
          label={maximized ? "Восстановить" : "Развернуть"}
          onClick={() => void bridge().window.toggleMaximize().then(setMaximized)}
        >
          {maximized ? <Copy size={14} /> : <Square size={14} />}
        </WinButton>
        <WinButton label="Закрыть" danger onClick={() => void bridge().window.close()}>
          <X size={16} />
        </WinButton>
      </div>
    </header>
  );
}

function WinButton(props: { label: string; danger?: boolean; onClick(): void; children: ReactNode }) {
  return (
    <button
      type="button"
      aria-label={props.label}
      title={props.label}
      onClick={props.onClick}
      className={
        "grid h-8 w-10 place-items-center rounded-lg text-ink-dim transition-colors " +
        (props.danger ? "hover:bg-accent hover:text-white" : "hover:bg-white/5 hover:text-ink")
      }
    >
      {props.children}
    </button>
  );
}
