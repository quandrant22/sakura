import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, test } from "vitest";

import type { CoreClient, Listener } from "../../api/client";
import { DemoClient } from "../../api/demo";
import type { CoreEvent } from "../../api/types";
import { MediaProvider, useMediaMeta, useMusicStore } from "../../media/MediaContext";
import type { Track } from "../../media/types";
import { PlayerBar } from "./PlayerBar";

afterEach(cleanup);

const tracks: Track[] = [1, 2].map((id) => ({ id, source: "local", title: `Песня ${id}`, artist: "Артист", album: "", duration: 120 }));

function Harness() {
  const m = useMusicStore();
  return <button type="button" onClick={() => void m.getState().playTracks(tracks)}>старт</button>;
}

test("мини-плеер скрыт без очереди и управляет воспроизведением", async () => {
  render(<MediaProvider client={new DemoClient("normal")}><Harness /><PlayerBar /></MediaProvider>);
  expect(screen.queryByLabelText("Мини-плеер")).toBeNull();
  await act(async () => { fireEvent.click(screen.getByText("старт")); });
  expect(screen.getByText("Песня 1")).toBeTruthy();
  expect(screen.getByLabelText("Пауза")).toBeTruthy();
  await act(async () => { fireEvent.click(screen.getByLabelText("Пауза")); });
  expect(screen.getByLabelText("Играть")).toBeTruthy();
  await act(async () => { fireEvent.click(screen.getByLabelText("Следующий")); });
  expect(screen.getByText("Песня 2")).toBeTruthy();
  fireEvent.click(screen.getByLabelText("Перемешать"));
  expect(screen.getByLabelText("Перемешать").getAttribute("aria-pressed")).toBe("true");
});

class EventClient extends DemoClient {
  hooks: Listener[] = [];
  override onEvent(cb: Listener) {
    this.hooks.push(cb);
    return super.onEvent(cb);
  }
  push(ev: CoreEvent) {
    this.hooks.forEach((l) => l(ev));
  }
}

function Duck() {
  const d = useMediaMeta((s) => s.duck.music);
  return <span>duck {d}</span>;
}

test("команды ядра media_command и приглушение audio_duck", async () => {
  const c = new EventClient("normal");
  render(<MediaProvider client={c as CoreClient}><Harness /><PlayerBar /><Duck /></MediaProvider>);
  await act(async () => { fireEvent.click(screen.getByText("старт")); });
  await act(async () => { c.push({ type: "media_command", player: "music", cmd: "next" }); });
  expect(screen.getByText("Песня 2")).toBeTruthy();
  await act(async () => { c.push({ type: "media_command", player: "all", cmd: "pause" }); });
  expect(screen.getByLabelText("Играть")).toBeTruthy();
  act(() => { c.push({ type: "audio_duck", gains: { music: 0.3, video: 0.3 }, ramp_ms: 150 }); });
  expect(screen.getByText("duck 0.3")).toBeTruthy();
});
