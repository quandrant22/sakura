// Стенд сквозного прогона (desktop/tests/e2e/site) глазами content.js: вопросы распознаются по видам,
// пары match/order и перетаскивание проходят через настоящие обработчики quiz.js и form.js.
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { afterEach, beforeEach, describe, expect, test } from "vitest";

import { byName, loadContent, stubRects } from "./helpers.js";

const SITE = join(dirname(fileURLToPath(import.meta.url)), "..", "e2e", "site");
const read = (name) => readFileSync(join(SITE, name), "utf-8");
const ANSWERS = JSON.parse(read("answers.json"));

let A;

// Страница стенда: разметка body без <script>, затем её скрипт — как classic script.
function open(page, search = "") {
  window.history.replaceState(null, "", "/" + page + search);
  const html = read(page);
  document.body.innerHTML = html.slice(html.indexOf("<body>") + 6, html.indexOf("</body>"))
    .replace(/<script[^>]*><\/script>/g, "");
  (0, eval)(read(page.replace(".html", ".js")));  // eslint-disable-line no-eval
  A.observe({ snapshot_id: "s1" });
}

beforeEach(() => {
  sessionStorage.clear();
  stubRects();
  A = loadContent();
});
afterEach(() => { document.body.innerHTML = ""; });

describe("стенд: тест", () => {
  test("страница 1: single, multi, text, single только с картинкой", () => {
    open("quiz.html", "?page=1");
    const qs = A.questions({ snapshot_id: "s1" }).questions;
    expect(qs.map((q) => [q.index, q.kind])).toEqual([[1, "single"], [2, "multi"], [3, "text"], [4, "single"]]);
    expect(qs[3].has_media).toBe(true);
    expect(qs[3].options.map((o) => o.text)).toEqual(["a. 36", "b. 42", "c. 48"]);
  });

  test("страница 2: match и два order — rows и общий options", () => {
    open("quiz.html", "?page=2");
    const [q5, q6, q7] = A.questions({ snapshot_id: "s1" }).questions;
    expect([q5.kind, q6.kind, q7.kind]).toEqual(["match", "order", "order"]);
    expect(q5.rows.map((r) => r.text)).toEqual(["Италия", "Испания", "Германия"]);
    expect(q5.options.map((o) => o.text)).toEqual(["Берлин", "Рим", "Мадрид"]);
    expect(q6.rows.map((r) => r.text)).toEqual(["Завтрак", "Обед", "Пробуждение"]);
    expect(q7.rows.map((r) => r.text)).toEqual(["Марс", "Земля", "Меркурий", "Венера"]);
  });

  test("пары по эталону: select в строках и перетаскивание обработчиками стенда", async () => {
    open("quiz.html", "?page=2");
    const [q5, q6, q7] = A.questions({ snapshot_id: "s1" }).questions;
    const want = ANSWERS.quiz.questions;
    const country = { Италия: "it", Испания: "es", Германия: "de" };
    const event = { Завтрак: "breakfast", Обед: "lunch", Пробуждение: "wake" };
    const planet = { Меркурий: "mercury", Венера: "venus", Земля: "earth", Марс: "mars" };
    const r = await A.fill({ snapshot_id: "s1", settle_ms: 0, values: {
      [q5.q_ref]: { kind: "match", pairs: q5.rows.map((x) => ({ row_ref: x.row_ref, option_text: want.q5.answer[country[x.text]] })) },
      [q6.q_ref]: { kind: "order", pairs: q6.rows.map((x) => ({ row_ref: x.row_ref, option_text: want.q6.answer[event[x.text]] })) },
      [q7.q_ref]: { kind: "order", pairs: q7.rows.map((x) => ({
        row_ref: x.row_ref, option_text: String(want.q7.answer.indexOf(planet[x.text]) + 1) })) },
    } });
    expect(r.fields.map((f) => f.status)).toEqual(["done", "done", "done"]);
    expect(document.getElementById("q7-order").value).toBe(want.q7.answer.join(","));
    expect(document.querySelector("select[name=q6-wake]").value).toBe("1");
    expect(document.querySelector("select[name=q5-de]").value).toBe("Берлин");
  });

  test("капча: .g-recaptcha появляется на 2-й странице и уходит после «Я не робот»", async () => {
    open("quiz.html", "?page=2&captcha=1");
    await new Promise((res) => setTimeout(res, 1600));
    expect(A.observe({ snapshot_id: "s2" }).captcha_detected).toBe(true);
    document.getElementById("captcha-check").click();
    await new Promise((res) => setTimeout(res, 700));
    expect(document.querySelector(".g-recaptcha")).toBeNull();
    expect(A.observe({ snapshot_id: "s3" }).captcha_detected).toBe(false);
  });
});

describe("стенд: анкета", () => {
  test("первая отправка — ошибка email (aria-invalid и текст), вторая принимается", async () => {
    open("form.html");
    const o = A.observe({ snapshot_id: "s1" });
    const exp = ANSWERS.form.expected;
    const r = await A.fill({ snapshot_id: "s1", settle_ms: 0, values: {
      [byName(o, "Имя и фамилия").ref]: exp.name, [byName(o, "Электронная почта").ref]: exp.email,
      [byName(o, "Город").ref]: "Казань", [byName(o, "По почте").ref]: true,
      [byName(o, "Согласен на обработку персональных данных").ref]: true, [byName(o, "Комментарий").ref]: exp.comment,
    } });
    expect(r.status).toBe("done");
    const submit = () => document.getElementById("signup").requestSubmit();
    submit();
    await new Promise((res) => setTimeout(res, 450));
    const after = A.observe({ snapshot_id: "s2" });
    expect(byName(after, "Электронная почта")).toMatchObject({ invalid: true, error: expect.stringContaining("ещё раз") });
    submit();
    await new Promise((res) => setTimeout(res, 450));
    const done = JSON.parse(document.getElementById("result-json").textContent);
    expect(done).toEqual({ ...exp, attempts: 2 });
  });
});
