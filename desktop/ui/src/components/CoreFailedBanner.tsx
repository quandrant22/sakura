// Плашка «Ядро не запустилось»: ядро, запущенное окном (SAKURA_CORE_AUTOSTART), упало и исчерпало перезапуски.
import { AlertTriangle } from "lucide-react";
import { useEffect, useState } from "react";

import { bridge, type CoreProcessState } from "../bridge";

export function CoreFailedBanner() {
  const [state, setState] = useState<CoreProcessState | null>(null);
  useEffect(() => {
    let alive = true;
    void bridge().core.state().then((s) => { if (alive) setState(s); });
    const off = bridge().core.onState(setState);
    return () => { alive = false; off(); };
  }, []);
  if (state !== "failed") return null;
  return (
    <div role="alert" className="flex items-center gap-3 border-b border-warn/40 bg-warn/10 px-4 py-2 text-sm text-warn">
      <AlertTriangle size={16} className="shrink-0" />
      <span className="flex-1">Ядро не запустилось. Сакура не слышит и не выполняет команды.</span>
      <button type="button" onClick={() => void bridge().core.openLog()}
              className="rounded-full border border-warn/50 px-3 py-1 text-xs hover:bg-warn/10">Открыть журнал</button>
    </div>
  );
}
