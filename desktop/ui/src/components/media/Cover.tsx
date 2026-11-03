import { Music2 } from "lucide-react";

/** Обложка трека или заглушка в цветах акцента. */
export function Cover({ src, className = "h-12 w-12" }: { src?: string | null; className?: string }) {
  return src ? (
    <img src={src} alt="" className={"shrink-0 rounded-btn object-cover " + className} />
  ) : (
    <div className={"grid shrink-0 place-items-center rounded-btn bg-accent-grad text-white/80 " + className}>
      <Music2 size={22} />
    </div>
  );
}
