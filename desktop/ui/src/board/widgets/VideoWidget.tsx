// Виджет «Видео»: встроенный проигрыватель (файлы, HLS, YouTube) в компактном виде.
import { VideoView } from "../../components/media/VideoView";

export function VideoWidget() {
  return (
    <div className="flex min-h-0 flex-1 px-3 pb-3">
      <VideoView compact />
    </div>
  );
}
