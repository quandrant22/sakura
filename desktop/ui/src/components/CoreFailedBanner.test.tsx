import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import type { CoreProcessState, SakuraBridge } from "../bridge";
import { CoreFailedBanner } from "./CoreFailedBanner";

afterEach(() => { cleanup(); delete window.sakura; });

function fakeBridge(initial: CoreProcessState | null) {
  let listener: ((s: CoreProcessState) => void) | null = null;
  const openLog = vi.fn(async () => {});
  window.sakura = { core: { connection: async () => null, state: async () => initial,
    onState: (cb: (s: CoreProcessState) => void) => { listener = cb; return () => { listener = null; }; }, openLog } } as unknown as SakuraBridge;
  return { push: (s: CoreProcessState) => listener?.(s), openLog };
}

test("ядро работает — плашки нет; упало — «Ядро не запустилось» и «Открыть журнал»", async () => {
  const b = fakeBridge("running");
  render(<CoreFailedBanner />);
  await act(async () => {});
  expect(screen.queryByRole("alert")).toBeNull();
  act(() => b.push("failed"));
  expect(screen.getByRole("alert").textContent).toContain("Ядро не запустилось");
  fireEvent.click(screen.getByText("Открыть журнал"));
  expect(b.openLog).toHaveBeenCalled();
});

test("ядро запущено отдельно (null) — плашки нет", async () => {
  fakeBridge(null);
  render(<CoreFailedBanner />);
  await act(async () => {});
  expect(screen.queryByRole("alert")).toBeNull();
});
