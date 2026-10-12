import "./index.css";

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import App from "./App";
import { CaptureMini } from "./capture/CaptureMini";

const root = document.getElementById("root");
if (!root) throw new Error("нет #root");
// ?view=capture-mini&source=… — мини-окно показа окна приложения (отдельное окно Electron).
const params = new URLSearchParams(window.location.search);
const view = params.get("view") === "capture-mini" && params.get("source")
  ? <CaptureMini sourceId={params.get("source")!} />
  : <App />;
createRoot(root).render(<StrictMode>{view}</StrictMode>);
