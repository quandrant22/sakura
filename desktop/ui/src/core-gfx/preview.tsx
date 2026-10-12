// Страница проверки ядра-графики владельцем: 5 состояний, ползунок уровня, 3 пресета слияния.
import { useLayoutEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { MERGE_PRESETS, MOBILITY, type CoreVisualState, type MergePreset, type Mobility } from "./coreFrame";
import { SakuraCore } from "./SakuraCore";

const ALL_STATES: [CoreVisualState, string][] = [
  ["idle", "Покой"], ["listening", "Слушаю"], ["thinking", "Думаю"], ["speaking", "Говорю"], ["offline", "Нет связи"],
];
// ?only=idle — одна карточка (для замера CPU, scripts/core-cpu.cjs).
const only = new URLSearchParams(location.search).get("only");
const STATES = only ? ALL_STATES.filter(([s]) => s === only) : ALL_STATES;

function Preview() {
  const [level, setLevel] = useState(0.4);
  const [preset, setPreset] = useState<MergePreset>("soft");
  const [mobility, setMobility] = useState<Mobility>("normal");
  const ref = useRef(level);
  useLayoutEffect(() => { ref.current = level; }, [level]);
  return (
    <div style={{ padding: 30 }}>
      <div style={{ display: "flex", gap: 24, alignItems: "center", marginBottom: 24 }}>
        <label>Уровень {level.toFixed(2)}{" "}
          <input type="range" min={0} max={1} step={0.01} value={level} onChange={(e) => setLevel(+e.target.value)} />
        </label>
        {(Object.keys(MERGE_PRESETS) as MergePreset[]).map((p) => (
          <label key={p}><input type="radio" checked={preset === p} onChange={() => setPreset(p)} /> {p}</label>
        ))}
        <label>Подвижность{" "}
          <select value={mobility} onChange={(e) => setMobility(e.target.value as Mobility)}>
            {(Object.keys(MOBILITY) as Mobility[]).map((k) => <option key={k} value={k}>{k}</option>)}
          </select>
        </label>
      </div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 20 }}>
        {STATES.map(([s, name]) => (
          <div key={s} style={{ width: 300, height: 287, background: "#14101c", borderRadius: 20, textAlign: "center" }}>
            <SakuraCore state={s} level={() => ref.current} preset={preset} mobility={mobility} size={260} />
            <div>{name}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

createRoot(document.getElementById("root")!).render(<Preview />);
