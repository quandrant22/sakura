// Верхняя панель 84 px по наброску: логотип 300x45 слева, три кнопки 45x45 справа, в центре — перетаскивание окна.
import { Copy, Minus, Square, X } from "lucide-react";
import { type ReactNode, useEffect, useState } from "react";

import { bridge } from "../bridge";
import { SakuraLogo } from "./SakuraLogo";

/** center — содержимое центра (страницы доски на главной); пустое место остаётся перетаскиванием окна. */
export function TitleBar({ center }: { center?: ReactNode }) {
  const [maximized, setMaximized] = useState(false);

  useEffect(() => {
    void bridge().window.isMaximized().then(setMaximized);
    return bridge().window.onMaximized(setMaximized);
  }, []);

  return (
    <header className="drag flex h-[84px] shrink-0 items-center gap-gap bg-bar px-edge">
      <div className="flex h-[45px] w-[300px] shrink-0 items-center gap-3 rounded-btn bg-panel px-4">
        <SakuraLogo size={30} />
        <span className="text-sm font-semibold tracking-logo text-ink">SAKURA</span>
      </div>

      {/* Центр: страницы доски (кнопки — no-drag); всё пустое — перетаскивание окна. */}
      {center ?? <div className="h-full flex-1" />}

      <div className="no-drag flex items-center gap-gap">
        <WinButton label="Свернуть" onClick={() => void bridge().window.minimize()}>
          <Minus size={18} />
        </WinButton>
        <WinButton label={maximized ? "Восстановить" : "Развернуть"}
                   onClick={() => void bridge().window.toggleMaximize().then(setMaximized)}>
          {maximized ? <Copy size={16} /> : <Square size={16} />}
        </WinButton>
        <WinButton label="Закрыть" danger onClick={() => void bridge().window.close()}>
          <X size={18} />
        </WinButton>
      </div>
    </header>
  );
}

function WinButton(props: { label: string; danger?: boolean; onClick(): void; children: ReactNode }) {
  return (
    <button type="button" aria-label={props.label} title={props.label} onClick={props.onClick}
            className={"grid h-[45px] w-[45px] place-items-center rounded-btn bg-panel text-ink-dim transition-colors " +
              (props.danger ? "hover:bg-accent-grad hover:text-white" : "hover:bg-panel2 hover:text-ink")}>
      {props.children}
    </button>
  );
}
