// content.js: снимок с ref, stale, дифф changed, формы, вопросы, заполнение, загрузка файла.
import { beforeEach, describe, expect, test, vi } from "vitest";

import { byName, fixture, loadContent, stubRects } from "./helpers.js";

let A;

beforeEach(() => {
  document.body.innerHTML = "";
  stubRects();
  A = loadContent();
});

describe("page.observe — ref-разметка", () => {
  test("интерактивные элементы, роли, имена, скрытые не попадают", () => {
    fixture("observe.html");
    const o = A.observe({ snapshot_id: "s1" });
    const names = o.elements.map((e) => e.name);
    expect(names).toContain("Главная");
    expect(names).toContain("Корзина");              // aria-label
    expect(names).toContain("Поиск");                // label[for]
    expect(names).toContain("Кликабельный текст");   // [onclick]
    expect(names).toContain("Комментарий");          // contenteditable
    expect(names).not.toContain("Спрятана");          // display:none
    expect(names).not.toContain("Тоже спрятана");     // [hidden] у предка
    for (const e of o.elements) expect(e.ref).toMatch(/^e\d+$/);
    expect(new Set(o.elements.map((e) => e.ref)).size).toBe(o.elements.length);

    expect(byName(o, "Поиск")).toMatchObject({ role: "searchbox", value: "кофе", enabled: true, in_viewport: true });
    expect(byName(o, "Недоступно").enabled).toBe(false);
    expect(byName(o, "Доставка").role).toBe("tab");
    expect(byName(o, "Подарочная упаковка")).toMatchObject({ role: "checkbox", checked: false });
    expect(byName(o, "Пароль").value).toBe("••••");  // значение пароля не уходит
    expect(byName(o, "Купить").bbox).toEqual([10, 10, 100, 20]);
    expect(o.captcha_detected).toBe(true);
    expect(o.has_canvas).toBe(true);
    expect(o.has_video).toBe(false);
    expect(o.iframes).toEqual([{ src: "https://pay.example/frame", bbox: [200, 300, 400, 200] }]);
    expect(o.text).toContain("Оформление заказа");
    expect(o.changed).toBeUndefined();  // первый снимок кадра — без диффа
  });

  test("лимиты max_elements и text_limit; видимые в окне — первыми", () => {
    document.body.innerHTML = Array.from({ length: 10 }, (_, i) =>
      `<button data-rect="0,${i < 5 ? 2000 : 10},50,20">b${i}</button>`).join("") + "<p>" + "x".repeat(500) + "</p>";
    const o = A.observe({ snapshot_id: "s1", max_elements: 4, text_limit: 100 });
    expect(o.elements.map((e) => e.name)).toEqual(["b5", "b6", "b7", "b8"]);
    expect(o.total).toBe(10);
    expect(o.text.length).toBe(100);
  });

  test("таймер Moodle: текст и секунды", () => {
    fixture("moodle_quiz.html");
    const o = A.observe({ snapshot_id: "s1" });
    expect(o.timer).toEqual({ text: "Оставшееся время 0:14:32", seconds_left: 872 });
  });

  test("невидимая reCAPTCHA v3 (badge) — не капча", () => {
    document.body.innerHTML = '<div class="grecaptcha-badge g-recaptcha" data-rect="0,0,256,60"></div><button>Ок</button>';
    expect(A.observe({ snapshot_id: "s1" }).captcha_detected).toBe(false);
  });
});

describe("stale: действие не выполняется", () => {
  test("устаревший snapshot_id", async () => {
    fixture("observe.html");
    const click = vi.fn();
    document.getElementById("buy").addEventListener("click", click);
    const o1 = A.observe({ snapshot_id: "s1" });
    const ref = byName(o1, "Купить").ref;
    A.observe({ snapshot_id: "s2" });
    expect(await A.act({ snapshot_id: "s1", ref, op: "click" })).toMatchObject({ status: "stale" });
    expect(click).not.toHaveBeenCalled();
    expect(await A.act({ snapshot_id: "s2", ref, op: "click" })).toMatchObject({ status: "done" });
    expect(click).toHaveBeenCalledTimes(1);
  });

  test("отсутствующий ref и удалённый из DOM элемент", async () => {
    fixture("observe.html");
    const o = A.observe({ snapshot_id: "s1" });
    expect((await A.act({ snapshot_id: "s1", ref: "e999", op: "click" })).status).toBe("stale");
    const buy = document.getElementById("buy");
    const ref = byName(o, "Купить").ref;
    buy.remove();
    expect((await A.act({ snapshot_id: "s1", ref, op: "click" })).status).toBe("stale");
  });

  test("новая страница (content.js загружен заново) — любой старый ref stale", async () => {
    fixture("observe.html");
    const o = A.observe({ snapshot_id: "s1" });
    A = loadContent();
    expect((await A.act({ snapshot_id: "s1", ref: o.elements[0].ref, op: "click" })).status).toBe("stale");
    await expect(A.fill({ snapshot_id: "s1", values: {} })).resolves.toMatchObject({ status: "stale" });
  });

  test("неизвестная операция — unsupported", async () => {
    fixture("observe.html");
    const o = A.observe({ snapshot_id: "s1" });
    expect((await A.act({ snapshot_id: "s1", ref: o.elements[0].ref, op: "explode" })).status).toBe("unsupported");
  });
});

describe("changed — дифф относительно прошлого снимка", () => {
  test("добавленные, изменённые, удалённые; ref стабильны", () => {
    document.body.innerHTML = '<a href="#a">Ссылка</a><input id="i" aria-label="Поле" value="1"><button id="b">Кнопка</button>';
    const o1 = A.observe({ snapshot_id: "s1" });
    const refs1 = Object.fromEntries(o1.elements.map((e) => [e.name, e.ref]));

    document.querySelector("a").remove();
    document.getElementById("i").value = "2";
    document.body.insertAdjacentHTML("beforeend", "<button>Новая</button>");
    const o2 = A.observe({ snapshot_id: "s2" });
    const refs2 = Object.fromEntries(o2.elements.map((e) => [e.name, e.ref]));

    expect(refs2["Кнопка"]).toBe(refs1["Кнопка"]);
    expect(refs2["Поле"]).toBe(refs1["Поле"]);
    const by = Object.fromEntries(o2.changed.map((c) => [c.change, c]));
    expect(o2.changed).toHaveLength(3);
    expect(by.removed).toMatchObject({ ref: refs1["Ссылка"], name: "Ссылка" });
    expect(by.changed).toMatchObject({ ref: refs1["Поле"], value: "2" });
    expect(by.added).toMatchObject({ ref: refs2["Новая"], name: "Новая" });
  });

  test("не больше 80 записей", () => {
    document.body.innerHTML = "<button>0</button>";
    A.observe({ snapshot_id: "s1" });
    document.body.insertAdjacentHTML("beforeend", Array.from({ length: 120 }, (_, i) => `<button>n${i}</button>`).join(""));
    expect(A.observe({ snapshot_id: "s2" }).changed).toHaveLength(80);
  });

  test("act → новый снимок показывает изменение checked", async () => {
    document.body.innerHTML = '<label><input type="checkbox" id="c"> Подписка</label>';
    const o1 = A.observe({ snapshot_id: "s1" });
    const ref = byName(o1, "Подписка").ref;
    expect((await A.act({ snapshot_id: "s1", ref, op: "check" })).status).toBe("done");
    const o2 = A.observe({ snapshot_id: "s2" });
    expect(o2.changed).toEqual([{ ref, change: "changed", role: "checkbox", name: "Подписка", checked: true }]);
  });
});

describe("page.forms", () => {
  test("обычная форма: поля, подписи, группы, submit", () => {
    fixture("forms.html");
    A.observe({ snapshot_id: "s1" });
    const { forms } = A.forms({ snapshot_id: "s1" });
    expect(forms).toHaveLength(2);
    const f = forms[0];
    expect(f.action_host).toBe("accounts.example.com");
    expect(f.form_ref).toMatch(/^e\d+$/);
    const by = Object.fromEntries(f.fields.map((x) => [x.name, x]));
    expect(Object.keys(by)).toEqual(["fullname", "email", "phone", "city", "sex", "agree", "pwd", "about"]);
    expect(by.fullname).toMatchObject({ label: "Имя и фамилия", type: "text", required: true, autocomplete: "name", value: "" });
    expect(by.email.label).toBe("Электронная почта");
    expect(by.city.options.map((o) => o.text)).toEqual(["— выберите —", "Москва", "Санкт-Петербург"]);
    expect(by.sex).toMatchObject({ type: "radio", label: "Пол" });
    expect(by.sex.options.map((o) => o.text)).toEqual(["Мужской", "Женский"]);
    expect(by.agree).toMatchObject({ type: "checkbox", checked: false, required: true });
    expect(by.pwd.value).toBe("••••");
    expect(f.submit_refs).toHaveLength(1);
  });

  test("ошибки валидации: aria-invalid + describedby, соседний .error", () => {
    fixture("forms.html");
    A.observe({ snapshot_id: "s1" });
    const by = Object.fromEntries(A.forms({ snapshot_id: "s1" }).forms[0].fields.map((x) => [x.name, x]));
    expect(by.email.error).toBe("Введите корректный адрес почты");
    expect(by.phone.error).toBe("Телефон обязателен");
    expect(by.fullname.error).toBeUndefined();  // не тронуто — :invalid не показываем
  });

  test(":invalid + validationMessage после заполнения агентом", async () => {
    document.body.innerHTML = '<form><input id="age" name="age" type="number" min="18" aria-label="Возраст"></form>';
    const o = A.observe({ snapshot_id: "s1" });
    const r = await A.fill({ snapshot_id: "s1", values: { [byName(o, "Возраст").ref]: "12" }, settle_ms: 0 });
    expect(r.fields[0].error).toBeTruthy();
    const f = A.forms({ snapshot_id: "s1" }).forms[0].fields[0];
    expect(f.error).toBeTruthy();
  });

  test("поля вне <form> — псевдоформа с кнопкой «Отправить»", () => {
    fixture("forms.html");
    const o = A.observe({ snapshot_id: "s1" });
    const pseudo = A.forms({ snapshot_id: "s1" }).forms[1];
    expect(pseudo).toMatchObject({ form_ref: null, pseudo: true });
    expect(pseudo.fields.map((x) => x.label)).toEqual(["Почта для рассылки"]);
    expect(pseudo.submit_refs).toEqual([byName(o, "Отправить").ref]);
  });

  test("устаревший снимок — stale", () => {
    fixture("forms.html");
    A.observe({ snapshot_id: "s1" });
    expect(A.forms({ snapshot_id: "old" })).toEqual({ stale: true });
  });
});

describe("page.questions", () => {
  test("Moodle-подобная разметка: single с картинкой, multi, text, match", () => {
    fixture("moodle_quiz.html");
    A.observe({ snapshot_id: "s1" });
    const { questions } = A.questions({ snapshot_id: "s1" });
    expect(questions.map((q) => [q.index, q.kind])).toEqual([[1, "single"], [2, "multi"], [3, "text"], [4, "match"]]);
    const [q1, q2, q3, q4] = questions;
    expect(q1.text).toBe("Какая фигура изображена на рисунке?");
    expect(q1.options.map((o) => o.text)).toEqual(["a. Круг", "b. Треугольник", "c. Квадрат"]);
    expect(q1.has_media).toBe(true);
    expect(q1.q_ref).toMatch(/^e\d+$/);
    expect(q1.bbox).toHaveLength(4);
    expect(q2.options.map((o) => o.text)).toEqual(["a. 2", "b. 4", "c. 7"]);
    expect(q2.has_media).toBe(false);
    expect(q3.text).toBe("Столица Франции?");
    expect(q3.input_ref).toMatch(/^e\d+$/);
    expect(q4.options.map((o) => o.text)).toEqual(["Италия", "Испания"]);
    expect(q4.choices).toEqual(["Рим", "Мадрид"]);
  });

  test("radio (fieldset), role=radiogroup, checkbox по name, текст по нумерации, вопрос с картинкой", () => {
    fixture("questions_generic.html");
    A.observe({ snapshot_id: "s1" });
    const qs = A.questions({ snapshot_id: "s1" }).questions;
    const by = (t) => qs.find((q) => q.text.includes(t));
    expect(by("Какая планета")).toMatchObject({ kind: "single", has_media: false });
    expect(by("Какая планета").options.map((o) => o.text)).toEqual(["Меркурий", "Венера"]);
    expect(by("Тёплые цвета")).toMatchObject({ kind: "single" });
    expect(by("Тёплые цвета").options.map((o) => o.text)).toEqual(["Красный", "Синий"]);
    expect(by("животные")).toMatchObject({ kind: "multi" });
    expect(by("животные").options.map((o) => o.text)).toEqual(["Кошка", "Собака"]);
    expect(by("фотосинтез")).toMatchObject({ kind: "text", index: 5 });
    expect(by("схеме")).toMatchObject({ kind: "single", index: 6, has_media: true });
    expect(qs).toHaveLength(5);
  });

  test("ответ на вопрос через fill_form по q_ref и тексту варианта", async () => {
    fixture("moodle_quiz.html");
    A.observe({ snapshot_id: "s1" });
    const [q1, q2, q3, q4] = A.questions({ snapshot_id: "s1" }).questions;
    const r = await A.fill({
      snapshot_id: "s1", settle_ms: 0,
      values: { [q1.q_ref]: "Треугольник", [q2.q_ref]: ["2", "7"], [q3.input_ref]: "Париж", [q4.options[0].ref]: "Рим" },
    });
    expect(r.status).toBe("done");
    expect(document.getElementById("q5:1_answer1").checked).toBe(true);
    expect(document.getElementById("q5:2_choice0").checked).toBe(true);
    expect(document.getElementById("q5:2_choice1").checked).toBe(false);
    expect(document.getElementById("q5:2_choice2").checked).toBe(true);
    expect(document.getElementById("q5:3_answer").value).toBe("Париж");
    expect(document.getElementById("menuq5:4_sub0").value).toBe("1");
    const multi = r.fields.find((f) => f.ref === q2.q_ref);
    expect(multi.options.map((o) => o.checked)).toEqual([true, false, true]);
  });
});

describe("page.fill_form", () => {
  // Как React отслеживает value: свой сеттер на экземпляре; onChange — только если DOM-значение отличается от отслеженного.
  function reactControlled(input) {
    const desc = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value");
    let tracked = desc.get.call(input);
    const onChange = vi.fn();
    Object.defineProperty(input, "value", {
      configurable: true,
      get() { return desc.get.call(this); },
      set(v) { tracked = String(v); desc.set.call(this, v); },
    });
    input.addEventListener("input", () => {
      const cur = desc.get.call(input);
      if (cur !== tracked) { tracked = cur; onChange(cur); }
    });
    return onChange;
  }

  test("React controlled input: onChange срабатывает, события input/change/blur", async () => {
    document.body.innerHTML = '<input id="n" aria-label="Имя">';
    const input = document.getElementById("n");
    const onChange = reactControlled(input);
    const events = [];
    for (const t of ["input", "change", "blur"]) input.addEventListener(t, () => events.push(t));

    // Контроль: прямое присваивание React не замечает (поэтому нужен нативный сеттер).
    input.value = "x";
    input.dispatchEvent(new Event("input", { bubbles: true }));
    expect(onChange).not.toHaveBeenCalled();
    events.length = 0;

    const o = A.observe({ snapshot_id: "s1" });
    const r = await A.fill({ snapshot_id: "s1", values: { [byName(o, "Имя").ref]: "Анна" }, settle_ms: 0 });
    expect(r).toMatchObject({ status: "done", detail: "заполнено 1 из 1" });
    expect(onChange).toHaveBeenCalledWith("Анна");
    expect(events).toEqual(["input", "change", "blur"]);
  });

  test("кастомный выпадающий список: открыть → найти вариант → клик", async () => {
    document.body.innerHTML = `
      <div id="cb" role="combobox" aria-label="Страна" aria-controls="lb" aria-expanded="false" tabindex="0">Выберите</div>
      <ul id="lb" role="listbox" style="display:none">
        <li role="option" data-v="ru">Россия</li><li role="option" data-v="kz">Казахстан</li>
      </ul>
      <input type="hidden" id="country">`;
    const cb = document.getElementById("cb");
    const lb = document.getElementById("lb");
    cb.addEventListener("click", () => { lb.style.display = "block"; cb.setAttribute("aria-expanded", "true"); });
    for (const li of lb.children) {
      li.addEventListener("click", () => {
        cb.textContent = li.textContent;
        document.getElementById("country").value = li.dataset.v;
        lb.style.display = "none";
      });
    }
    const o = A.observe({ snapshot_id: "s1" });
    const r = await A.fill({ snapshot_id: "s1", values: { [byName(o, "Страна").ref]: "казах" }, settle_ms: 0 });
    expect(r.status).toBe("done");
    expect(document.getElementById("country").value).toBe("kz");
    expect(cb.textContent).toBe("Казахстан");

    const miss = await A.fill({ snapshot_id: "s1", values: { [byName(o, "Страна").ref]: "Атлантида" }, settle_ms: 0 });
    expect(miss.fields[0].status).toBe("not_found");
  });

  test("select / radio / checkbox по тексту варианта; checked в ответе", async () => {
    fixture("forms.html");
    A.observe({ snapshot_id: "s1" });
    const f = A.forms({ snapshot_id: "s1" }).forms[0];
    const by = Object.fromEntries(f.fields.map((x) => [x.name, x]));
    const r = await A.fill({
      snapshot_id: "s1", settle_ms: 0,
      values: { [by.city.ref]: "санкт", [by.sex.ref]: "Женский", [by.agree.ref]: true },
    });
    expect(r.status).toBe("done");
    expect(document.getElementById("city").value).toBe("spb");
    expect(document.querySelector('input[value="f"]').checked).toBe(true);
    const out = Object.fromEntries(r.fields.map((x) => [x.ref, x]));
    expect(out[by.agree.ref].checked).toBe(true);
    expect(out[by.sex.ref].options.map((o) => o.checked)).toEqual([false, true]);
    expect(out[by.city.ref].value).toBe("Санкт-Петербург");
  });

  test("значения с переводом строки, кавычками и обратным слэшем — без искажений", async () => {
    document.body.innerHTML = '<textarea aria-label="Текст"></textarea><input aria-label="Строка"><div contenteditable="true" aria-label="Редактор"></div>';
    const tricky = "строка 1\nстрока 2 \"двойные\" 'одинарные' \\ слэш \\n ${x} `бэктик` </script>";
    const line = "C:\\Users\\Анна \"цитата\" 'и' `x` ${y}";
    const o = A.observe({ snapshot_id: "s1" });
    const r = await A.fill({
      snapshot_id: "s1", settle_ms: 0,
      values: { [byName(o, "Текст").ref]: tricky, [byName(o, "Строка").ref]: line, [byName(o, "Редактор").ref]: tricky },
    });
    expect(r.status).toBe("done");
    expect(document.querySelector("textarea").value).toBe(tricky);
    expect(document.querySelector("input").value).toBe(line);
    expect(document.querySelector("[contenteditable]").textContent).toBe(tricky);
    // То же через page.act fill.
    document.querySelector("input").value = "";
    expect((await A.act({ snapshot_id: "s1", ref: byName(o, "Строка").ref, op: "fill", value: line })).status).toBe("done");
    expect(document.querySelector("input").value).toBe(line);
  });

  test("устаревший ref — ничего не заполняется", async () => {
    document.body.innerHTML = '<input aria-label="А"><input aria-label="Б">';
    const o = A.observe({ snapshot_id: "s1" });
    const r = await A.fill({ snapshot_id: "s1", values: { [byName(o, "А").ref]: "1", e999: "2" }, settle_ms: 0 });
    expect(r).toMatchObject({ status: "stale", stale_refs: ["e999"] });
    expect(document.querySelector("input").value).toBe("");
  });

  test("платёжные поля не заполняются", async () => {
    document.body.innerHTML = '<input autocomplete="cc-number" aria-label="Номер карты">';
    const o = A.observe({ snapshot_id: "s1" });
    const r = await A.fill({ snapshot_id: "s1", values: { [o.elements[0].ref]: "4111" }, settle_ms: 0 });
    expect(r.fields[0].status).toBe("unsupported");
    expect(document.querySelector("input").value).toBe("");
  });
});

describe("page.upload через DataTransfer", () => {
  class FakeDataTransfer {
    constructor() { this.list = []; this.items = { add: (f) => this.list.push(f) }; }
    get files() { return this.list.slice(); }
  }

  test("input[type=file]: файл с именем и содержимым, событие change", async () => {
    globalThis.DataTransfer = FakeDataTransfer;
    document.body.innerHTML = '<label>Резюме <input type="file" id="cv"></label>';
    const input = document.getElementById("cv");
    let stored = [];
    Object.defineProperty(input, "files", { configurable: true, get: () => stored, set: (v) => { stored = v; } });
    const change = vi.fn();
    input.addEventListener("change", change);
    const o = A.observe({ snapshot_id: "s1" });
    const data = Buffer.from("привет, мир").toString("base64");
    const r = A.upload({ snapshot_id: "s1", ref: byName(o, "Резюме").ref, name: "cv.txt", mime: "text/plain", data_b64: data });
    expect(r.status).toBe("done");
    expect(change).toHaveBeenCalledTimes(1);
    expect(stored).toHaveLength(1);
    expect(stored[0].name).toBe("cv.txt");
    expect(stored[0].type).toBe("text/plain");
    expect(await stored[0].text()).toBe("привет, мир");
    delete globalThis.DataTransfer;
  });

  test("зона перетаскивания получает drop с файлом; stale без действия", () => {
    globalThis.DataTransfer = FakeDataTransfer;
    document.body.innerHTML = '<div id="drop" role="button" aria-label="Перетащите файл">Сюда</div>';
    const seen = [];
    document.getElementById("drop").addEventListener("drop", (e) => seen.push(e.dataTransfer.files[0].name));
    const o = A.observe({ snapshot_id: "s1" });
    expect(A.upload({ snapshot_id: "s0", ref: o.elements[0].ref, name: "a.pdf", data_b64: "" }).status).toBe("stale");
    expect(seen).toEqual([]);
    expect(A.upload({ snapshot_id: "s1", ref: o.elements[0].ref, name: "a.pdf", data_b64: "" }).status).toBe("done");
    expect(seen).toEqual(["a.pdf"]);
    delete globalThis.DataTransfer;
  });
});

describe("разметка кадра (annotated)", () => {
  test("номера ref поверх элементов и снятие слоя", () => {
    document.body.innerHTML = "<button>Один</button><button>Два</button>";
    const o = A.observe({ snapshot_id: "s1" });
    expect(A.annotate({ on: true, prefix: "f0:" }).count).toBe(2);
    const labels = Array.from(document.querySelectorAll("#__sakura_annot__ span")).map((s) => s.textContent);
    expect(labels).toEqual(o.elements.map((e) => "f0:" + e.ref));
    A.annotate({ on: false });
    expect(document.getElementById("__sakura_annot__")).toBeNull();
  });
});

describe("describe(): type, invalid, error (для решений сервера)", () => {
  test("type у input/textarea/select; ошибка из aria-describedby и соседнего .error", () => {
    fixture("forms.html");
    const o = A.observe({ snapshot_id: "s1" });
    const by = (n) => byName(o, n);
    expect(by("Пароль").type).toBe("password");
    expect(by("Имя и фамилия").type).toBe("text");
    expect(by("О себе").type).toBe("textarea");
    expect(by("Город").type).toBe("select");
    expect(by("Зарегистрироваться").type).toBeUndefined();   // кнопка — не поле ввода
    expect(by("Электронная почта")).toMatchObject({ type: "email", invalid: true, error: "Введите корректный адрес почты" });
    expect(by("Телефон")).toMatchObject({ invalid: true, error: "Телефон обязателен" });
    expect(by("Имя и фамилия").invalid).toBeUndefined();     // пустое обязательное, не тронуто
  });

  test("aria-invalid без текста — invalid с общим текстом; длинная ошибка ≤ 200", () => {
    document.body.innerHTML = '<div><input aria-label="Код" aria-invalid="true"></div>' +
      `<div><input aria-label="Логин"><span class="error">${"о".repeat(400)}</span></div>`;
    const o = A.observe({ snapshot_id: "s1" });
    expect(byName(o, "Код")).toMatchObject({ invalid: true, error: "поле помечено как неверное" });
    expect(byName(o, "Логин").invalid).toBe(true);
    expect(byName(o, "Логин").error.length).toBeLessThanOrEqual(200);
  });

  test("ошибка после заполнения агентом попадает в changed", async () => {
    document.body.innerHTML = '<form><input name="age" type="number" min="18" aria-label="Возраст"></form>';
    const o = A.observe({ snapshot_id: "s1" });
    await A.fill({ snapshot_id: "s1", values: { [byName(o, "Возраст").ref]: "12" }, settle_ms: 0 });
    const o2 = A.observe({ snapshot_id: "s2" });
    expect(byName(o2, "Возраст").invalid).toBe(true);
    expect(o2.changed[0]).toMatchObject({ ref: byName(o, "Возраст").ref, change: "changed" });
  });
});

describe("page.scroll: знак dy", () => {
  test("dy −1 — экран вверх, +1 и без dy — экран вниз, иначе пиксели", () => {
    const calls = [];
    window.scrollBy = (x, y) => calls.push(y);
    A.scroll({ dy: -1 });
    A.scroll({ dy: 1 });
    A.scroll({});
    A.scroll({ dy: -250 });
    const screen = Math.round(window.innerHeight * 0.8);
    expect(calls).toEqual([-screen, screen, screen, -250]);
  });
});

describe("ref из page.questions действуют в следующем снимке", () => {
  test("crop по q_ref после нового observe — не stale; удалённый блок — stale", () => {
    fixture("moodle_quiz.html");
    A.observe({ snapshot_id: "s1" });
    const [q1, q2] = A.questions({ snapshot_id: "s1" }).questions;
    A.observe({ snapshot_id: "s2" });
    expect(A.rect({ snapshot_id: "s2", ref: q1.q_ref })).not.toBeNull();
    document.getElementById("question-5-2").remove();
    A.observe({ snapshot_id: "s3" });
    expect(A.rect({ snapshot_id: "s3", ref: q2.q_ref })).toBeNull();
    expect(A.rect({ snapshot_id: "s3", ref: q1.q_ref })).not.toBeNull();
  });
});
