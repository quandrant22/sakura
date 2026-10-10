import { useState } from "react";

import { type Tab, TitleBar } from "./components/TitleBar";

// Фаза 0: пустое окно со своим заголовком. Экраны появляются в Фазе 2+.
export default function App() {
  const [tab, setTab] = useState<Tab>("Главная");
  return (
    <div className="flex h-full flex-col overflow-hidden rounded-win border border-line bg-bg shadow-soft">
      <TitleBar tab={tab} onTab={setTab} />
      <main className="grid flex-1 place-items-center text-ink-dim">{tab}</main>
    </div>
  );
}
