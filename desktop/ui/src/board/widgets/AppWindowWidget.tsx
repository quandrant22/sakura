// Виджет «Окно приложения»: показ окна внутри Сакуры (desktopCapturer) — фаза 4.
// Захват только по явному действию, без записи на диск и без отправки кадров на сервер.
import { AppWindow } from "lucide-react";

export function AppWindowWidget() {
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-2 px-6 pb-6 text-center text-sm text-ink-dim">
      <AppWindow size={28} className="text-accent" />
      <span>Здесь будет окно выбранного приложения</span>
      <span className="text-xs">Показ включается только вами и ничего не записывает на диск</span>
    </div>
  );
}
