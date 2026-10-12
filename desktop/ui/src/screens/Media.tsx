import { Film, Music2 } from "lucide-react";
import { useState } from "react";

import { MusicView } from "../components/media/MusicView";
import { VideoView } from "../components/media/VideoView";

export function Media({ initial = "music" }: { initial?: "music" | "video" }) {
  const [tab, setTab] = useState<"music" | "video">(initial);
  const tabBtn = (id: "music" | "video", label: string, Icon: typeof Music2) => (
    <button type="button" onClick={() => setTab(id)} aria-current={tab === id ? "page" : undefined}
            className={"flex items-center gap-2 rounded-card px-4 py-2 text-sm " +
              (tab === id ? "bg-accent text-white shadow-glow" : "text-ink-dim hover:bg-white/5 hover:text-ink")}>
      <Icon size={16} /> {label}
    </button>
  );
  return (
    <div className="flex min-h-0 flex-1 flex-col gap-4">
      <div className="flex gap-2">{tabBtn("music", "Музыка", Music2)}{tabBtn("video", "Видео", Film)}</div>
      {tab === "music" ? <MusicView /> : <VideoView />}
    </div>
  );
}
