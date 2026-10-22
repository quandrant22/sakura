// Мини-окно показа окна приложения: поверх всех окон, красная рамка — «идёт показ».
// Поток запрашивается заново в этом окне (main разрешает только источник из адреса страницы).
import { useEffect } from "react";

import { bridge } from "../bridge";
import { useWindowCapture } from "./useWindowCapture";

export function CaptureMini({ sourceId }: { sourceId: string }) {
  const cap = useWindowCapture({ baseFps: 10, width: window.innerWidth, hidden: false, interacting: false, viaMini: true });
  const { start, videoRef, stream } = cap;

  useEffect(() => {
    void bridge().capture.miniSelect().then(() => start(sourceId));
  }, [sourceId, start]);
  useEffect(() => {
    if (videoRef.current) videoRef.current.srcObject = stream;
  }, [stream, videoRef]);
  useEffect(() => {
    if (cap.state === "ended") window.close();
  }, [cap.state]);

  return (
    <div className="drag h-full w-full overflow-hidden border-2 border-accent bg-black" aria-label="Показ окна поверх всех">
      <video ref={videoRef} autoPlay muted playsInline className="h-full w-full object-contain" />
      {cap.state === "black" && (
        <div className="absolute inset-0 grid place-items-center text-sm text-ink-dim">Окно свёрнуто или защищено</div>
      )}
    </div>
  );
}
