import { expect, test } from "vitest";

import type { Message } from "../api/types";
import * as chipModule from "./Chat";
import { sourceLabel } from "./Chat";

const msg = (p: Partial<Message>): Message => ({ id: "1", ts: 0, role: "user", text: "x", channel: "text", device: "pc", ...p });

test("метка источника сообщения", () => {
  expect(sourceLabel(msg({ source: "mic", channel: "voice" }))).toBe("микрофон");
  expect(sourceLabel(msg({ source: "ui" }))).toBe("окно");
  expect(sourceLabel(msg({ source: "e2e" }))).toBe("проверка");
  expect(sourceLabel(msg({ role: "system" }))).toBe("система");
  expect(sourceLabel(msg({ role: "assistant", source: "server" }))).toBe("");
  // сервер v2 без source: голосовое сообщение всё равно помечается
  expect(sourceLabel(msg({ channel: "voice" }))).toBe("микрофон");
});

test("цветные метки вида ответа", () => {
  const { kindChip } = chipModule;
  expect(kindChip(msg({ role: "assistant", kind: "ack" }))?.text).toBe("быстрый ответ");
  expect(kindChip(msg({ role: "assistant", kind: "template" }))?.text).toBe("быстрый ответ");
  expect(kindChip(msg({ role: "assistant", kind: "error" }))?.tone).toBe("error");
  expect(kindChip(msg({ role: "assistant", kind: "proactive" }))?.text).toBe("проактивно");
  expect(kindChip(msg({ role: "system", kind: "command" }))?.text).toBe("команда");
  expect(kindChip(msg({ role: "assistant", kind: "llm" }))).toBeNull();
  expect(sourceLabel(msg({ channel: "telegram" }))).toBe("Telegram");
});
