import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test } from "vitest";

import { DemoClient } from "./api/demo";
import App from "./App";

afterEach(cleanup);

test("заголовок: логотип, вкладки, кнопки окна", () => {
  render(<App client={new DemoClient("normal")} />);
  expect(screen.getByText("SAKURA")).toBeTruthy();
  for (const label of ["Свернуть", "Развернуть", "Закрыть"]) {
    expect(screen.getByLabelText(label)).toBeTruthy();
  }
});

test("главная на демо-данных: чат, устройства, статус, подсказки", async () => {
  render(<App client={new DemoClient("normal")} />);
  await waitFor(() => expect(screen.getByText("Включаю «Мою волну».")).toBeTruthy());
  expect(screen.getByText("Система активна")).toBeTruthy();
  expect(screen.getByText("Ноутбук")).toBeTruthy();
  expect(screen.getByText(/Последняя активность/)).toBeTruthy();
  await waitFor(() => expect(screen.getByText("Спокойное")).toBeTruthy());
  expect(screen.getByRole("button", { name: "Погода" })).toBeTruthy();
});

test("отправка сообщения из поля ввода", async () => {
  render(<App client={new DemoClient("normal")} />);
  fireEvent.change(screen.getByLabelText("Сообщение"), { target: { value: "Привет" } });
  fireEvent.click(screen.getByLabelText("Отправить"));
  await waitFor(() => expect(screen.getByText("Демо: «Привет»")).toBeTruthy());
});

test("офлайн-баннер", () => {
  render(<App client={new DemoClient("offline")} />);
  expect(screen.getByText("Нет связи с сервером")).toBeTruthy();
});

test("меню и вкладки синхронизированы", () => {
  render(<App client={new DemoClient("normal")} />);
  fireEvent.click(screen.getAllByRole("button", { name: /Сценарии/ })[0]!);
  expect(screen.getByText(/Сценарии: экран появится/)).toBeTruthy();
});
