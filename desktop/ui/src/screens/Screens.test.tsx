import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test } from "vitest";

import type { CoreClient } from "../api/client";
import { DemoClient } from "../api/demo";
import { CoreError } from "../api/types";
import { translate } from "../i18n";
import { MediaProvider } from "../media/MediaContext";
import { Memory } from "./Memory";
import { Profile } from "./Profile";

afterEach(cleanup);

class ServerClient extends DemoClient {
  unsupported = false;
  memory = [{ id: "k1", category: "preferences", text: "Любит лоу-фай", ts: 1 },
            { id: "k2", category: "facts", text: "Работает из дома", ts: 2 }];
  profile = { name: "Хозяин", address_as: "ты", quiet_hours: "23:00-07:00", voice: "Leda", tone: "calm",
              notifications: { telegram: true, sound: true } };
  sent: Record<string, unknown>[] = [];
  override async server<T>(m: Record<string, unknown> & { type: string }): Promise<T> {
    this.sent.push(m);
    if (this.unsupported) throw new CoreError("unsupported", "Сервер не поддерживает");
    const reply = (items = this.memory) => ({ items, total: items.length,
      counts: Object.fromEntries(["preferences", "facts"].map((c) => [c, this.memory.filter((x) => x.category === c).length])) });
    switch (m.type) {
      case "memory_list": return reply(m.category ? this.memory.filter((x) => x.category === m.category) : this.memory) as T;
      case "memory_search": return reply(this.memory.filter((x) => x.text.toLowerCase().includes(String(m.q).toLowerCase()))) as T;
      case "memory_update": this.memory = this.memory.map((x) => (x.id === m.id ? { ...x, text: String(m.text) } : x)); return reply() as T;
      case "memory_delete": this.memory = this.memory.filter((x) => x.id !== m.id); return reply([]) as T;
      case "profile_get": return { profile: this.profile } as T;
      case "profile_set": this.profile = { ...this.profile, ...(m as object) }; return { profile: this.profile } as T;
    }
    return super.server<T>(m);
  }
}

function mount(node: React.ReactNode, c = new ServerClient("normal")) {
  render(<MediaProvider client={c as CoreClient}>{node}</MediaProvider>);
  return c;
}

test("Память: список, категория, поиск, правка и удаление с подтверждением", async () => {
  const c = mount(<Memory />);
  await waitFor(() => expect(screen.getByText("Любит лоу-фай")).toBeTruthy());
  fireEvent.click(screen.getByRole("button", { name: /Факты/ }));
  await waitFor(() => expect(screen.queryByText("Любит лоу-фай")).toBeNull());
  fireEvent.click(screen.getByRole("button", { name: "Все" }));
  fireEvent.change(screen.getByLabelText("Поиск по памяти"), { target: { value: "дома" } });
  await waitFor(() => expect(screen.queryByText("Любит лоу-фай")).toBeNull());
  fireEvent.click(screen.getByLabelText("Изменить: Работает из дома"));
  fireEvent.change(screen.getByLabelText("Текст записи"), { target: { value: "Работает из офиса" } });
  fireEvent.keyDown(screen.getByLabelText("Текст записи"), { key: "Enter" });
  await waitFor(() => expect(c.sent.some((m) => m.type === "memory_update")).toBe(true));
  fireEvent.change(screen.getByLabelText("Поиск по памяти"), { target: { value: "" } });
  await waitFor(() => expect(screen.getByText("Работает из офиса")).toBeTruthy());
  fireEvent.click(screen.getByLabelText("Удалить: Работает из офиса"));
  expect(c.sent.some((m) => m.type === "memory_delete")).toBe(false); // сначала подтверждение
  fireEvent.click(screen.getByText("Да"));
  await waitFor(() => expect(screen.queryByText("Работает из офиса")).toBeNull());
});

test("Память и Профиль: сервер без поддержки — «Сервер ещё не поддерживает»", async () => {
  const c = new ServerClient("normal");
  c.unsupported = true;
  mount(<Memory />, c);
  await waitFor(() => expect(screen.getByRole("alert").textContent).toContain("Сервер ещё не поддерживает"));
  cleanup();
  mount(<Profile />, c);
  await waitFor(() => expect(screen.getByRole("alert").textContent).toContain("Сервер ещё не поддерживает"));
});

test("Профиль: правка и сохранение", async () => {
  const c = mount(<Profile />);
  await waitFor(() => expect((screen.getByLabelText("Как вас зовут") as HTMLInputElement).value).toBe("Хозяин"));
  fireEvent.change(screen.getByLabelText("Тихие часы"), { target: { value: "22:00-08:00" } });
  fireEvent.click(screen.getByText("Сохранить"));
  await act(async () => {});
  expect(c.profile.quiet_hours).toBe("22:00-08:00");
  expect(screen.getByRole("status").textContent).toBe("Сохранено");
});

test("i18n: английский — меню и баннеры, неизвестное — как есть", () => {
  expect(translate("Настройки", "en")).toBe("Settings");
  expect(translate("Настройки", "ru")).toBe("Настройки");
  expect(translate("Нечто новое", "en")).toBe("Нечто новое");
});

test("ошибки сервера различаются: не поддерживает, нужен защищённый канал, не отвечает", async () => {
  const { errorKind, errorText } = await import("../store");
  expect(errorText(new CoreError("unknown_type", "x"))).toBe("Сервер ещё не поддерживает");
  expect(errorKind(new CoreError("secure_channel_required", "x"))).toBe("secure");
  expect(errorText(new CoreError("secure_channel_required", "x"))).toContain("Настройки → Безопасность");
  expect(errorText(new CoreError("timeout", "x"))).toBe("Сервер не отвечает");
  expect(errorKind(new CoreError("not_found", "запись не найдена"))).toBe("error");
});

test("Память: сервер требует защищённый канал — подсказка про VPN и «Безопасность»", async () => {
  class Secure extends ServerClient {
    override async server<T>(): Promise<T> { throw new CoreError("secure_channel_required", "подключитесь через защищённый канал"); }
  }
  mount(<Memory />, new Secure("normal"));
  await waitFor(() => expect(screen.getByRole("alert").textContent).toContain("включи VPN или подключи устройство"));
});
