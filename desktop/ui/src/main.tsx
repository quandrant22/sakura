import "@fontsource/orbitron/500.css";
import "@fontsource/orbitron/700.css";
import "./index.css";

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import App, { WidgetWindowApp } from "./App";
import { CaptureMini } from "./capture/CaptureMini";
import { Stage } from "./stage/Stage";

const root = document.getElementById("root");
if (!root) throw new Error("нет #root");
// ?view=capture-mini&source=… — мини-окно показа окна приложения (отдельное окно Electron).
const params = new URLSearchParams(window.location.search);
// ?view=widget&type=…&id=… — виджет в отдельном окне.
// ?view=stage — сцена: прозрачный оверлей поверх «экрана Сакуры» (рисование, субтитры, игры).
const view = params.get("view") === "stage"
  ? <Stage />
  : params.get("view") === "capture-mini" && params.get("source")
  ? <CaptureMini sourceId={params.get("source")!} />
  : params.get("view") === "widget" && params.get("type")
    ? <WidgetWindowApp type={params.get("type")!} id={params.get("id") ?? ""} />
    : <App />;
createRoot(root).render(<StrictMode>{view}</StrictMode>);
