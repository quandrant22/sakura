import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, test } from "vitest";

import App from "./App";

afterEach(cleanup);

test("заголовок: логотип, вкладки, кнопки окна", () => {
  render(<App />);
  expect(screen.getByText("SAKURA")).toBeTruthy();
  expect(screen.getByText("Система активна")).toBeTruthy();
  for (const label of ["Свернуть", "Развернуть", "Закрыть"]) {
    expect(screen.getByLabelText(label)).toBeTruthy();
  }
});

test("переключение вкладок подсвечивает активную", () => {
  render(<App />);
  fireEvent.click(screen.getByRole("button", { name: "Сценарии" }));
  expect(screen.getByRole("button", { name: "Сценарии" }).getAttribute("aria-current")).toBe("page");
  expect(screen.getByRole("button", { name: "Главная" }).getAttribute("aria-current")).toBeNull();
});
