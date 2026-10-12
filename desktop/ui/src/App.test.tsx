import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { DemoClient } from "./api/demo";
import App from "./App";
import { LONG_PRESS_MS } from "./components/LeftColumn";
import { prefsStore } from "./layout/prefs";

const initialPrefs = prefsStore.getState();
beforeEach(() => prefsStore.setState(initialPrefs, true));
afterEach(() => { cleanup(); vi.useRealTimers(); });

test("верхняя панель: логотип и три кнопки окна", () => {
  render(<App client={new DemoClient("normal")} />);
  expect(screen.getByText("SAKURA")).toBeTruthy();
  for (const label of ["Свернуть", "Развернуть", "Закрыть"]) expect(screen.getByLabelText(label)).toBeTruthy();
});

test("левая колонка: ядро со статусом и пять пунктов меню", async () => {
  render(<App client={new DemoClient("normal")} />);
  expect(screen.getByLabelText("Ядро Сакуры")).toBeTruthy();
  await waitFor(() => expect(screen.getByRole("status").textContent).toContain("Онлайн"));
  const menu = screen.getByRole("navigation", { name: "Меню" });
  const items = ["Главная", "Устройства", "Сценарии", "Память", "Настройки"];
  for (const name of items) expect(menu.textContent).toContain(name);
  expect(screen.getByRole("button", { name: /Главная/ }).getAttribute("aria-current")).toBe("page");
});

test("главная — доска с виджетами по умолчанию, чат справа с подсказками", async () => {
  render(<App client={new DemoClient("normal")} />);
  await waitFor(() => expect(screen.getByLabelText("Доска виджетов")).toBeTruthy());
  for (const name of ["Система", "Видео", "Окно приложения", "Музыка"]) expect(screen.getByRole("region", { name })).toBeTruthy();
  await waitFor(() => expect(screen.getByText("Включаю «Мою волну».")).toBeTruthy());
  for (const p of ["Что у меня сегодня?", "Погода", "Включи музыку"]) expect(screen.getByRole("button", { name: p })).toBeTruthy();
});

test("отправка сообщения из поля ввода", async () => {
  render(<App client={new DemoClient("normal")} />);
  await waitFor(() => expect(screen.getByLabelText("Сообщение")).toBeTruthy());
  fireEvent.change(screen.getByLabelText("Сообщение"), { target: { value: "Привет" } });
  fireEvent.click(screen.getByLabelText("Отправить"));
  await waitFor(() => expect(screen.getByText("Демо: «Привет»")).toBeTruthy());
});

test("офлайн: ядро «Нет связи» с пояснением, «Повторить» вместо скелетонов", async () => {
  render(<App client={new DemoClient("offline")} />);
  await waitFor(() => expect(screen.getByLabelText("Доска виджетов")).toBeTruthy());
  expect(screen.getByRole("status").textContent).toContain("Нет связи");
  expect(screen.getByLabelText("Ядро Сакуры").textContent).toContain("нет связи с сервером");
  expect(screen.getAllByRole("button", { name: /Повторить/ }).length).toBeGreaterThanOrEqual(2);
});

test("меню переключает экраны; инструменты доски только на главной", async () => {
  render(<App client={new DemoClient("normal")} />);
  await waitFor(() => expect(screen.getByRole("button", { name: /Правка доски/ })).toBeTruthy());
  fireEvent.click(screen.getByRole("button", { name: /Сценарии/ }));
  expect(screen.getByRole("region", { name: "Создание сценария" })).toBeTruthy();
  expect(screen.queryByRole("button", { name: /Правка доски/ })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: /Устройства/ }));
  await waitFor(() => expect(screen.getByText(/Последняя активность/)).toBeTruthy());
  fireEvent.click(screen.getByRole("button", { name: /Память/ }));
  expect(screen.getByText(/Память: экран появится/)).toBeTruthy();
});

test("режим правки: убрать виджет, вернуть, сбросить; замок выключает правку", async () => {
  render(<App client={new DemoClient("normal")} />);
  await waitFor(() => expect(screen.getByRole("button", { name: /Правка доски/ })).toBeTruthy());
  fireEvent.click(screen.getByRole("button", { name: /Правка доски/ }));
  fireEvent.click(screen.getByLabelText("Убрать виджет «Видео»"));
  expect(screen.queryByRole("region", { name: "Видео" })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Видео" }));
  expect(screen.getByRole("region", { name: "Видео" })).toBeTruthy();
  fireEvent.click(screen.getByLabelText("Убрать виджет «Музыка»"));
  fireEvent.click(screen.getByRole("button", { name: /Сбросить раскладку/ }));
  expect(screen.getByRole("region", { name: "Музыка" })).toBeTruthy();

  fireEvent.click(screen.getByLabelText("Закрепить доску"));
  expect(screen.queryByLabelText(/Убрать виджет/)).toBeNull();
  expect((screen.getByRole("button", { name: /Правка доски/ }) as HTMLButtonElement).disabled).toBe(true);
});

test("клик по ядру — «говорить сейчас», долгое нажатие — микрофон", async () => {
  const client = new DemoClient("normal");
  const call = vi.spyOn(client, "call");
  render(<App client={client} />);
  const core = screen.getByLabelText(/Говорить сейчас/);
  fireEvent.pointerDown(core);
  fireEvent.pointerUp(core);
  await waitFor(() => expect(call).toHaveBeenCalledWith("listen_now"));

  vi.useFakeTimers();
  fireEvent.pointerDown(core);
  act(() => { vi.advanceTimersByTime(LONG_PRESS_MS + 10); });
  fireEvent.pointerUp(core);
  expect(call).toHaveBeenCalledWith("mic_toggle");
  expect(call.mock.calls.filter(([t]) => t === "listen_now")).toHaveLength(1);
});

test("сворачивание чата в полосу и обратно", async () => {
  render(<App client={new DemoClient("normal")} />);
  await waitFor(() => expect(screen.getByLabelText("Свернуть чат")).toBeTruthy());
  act(() => prefsStore.getState().set("chatCollapsed", true));
  expect(screen.getByLabelText("Развернуть чат")).toBeTruthy();
  expect(screen.queryByLabelText("Сообщение")).toBeNull();
});
