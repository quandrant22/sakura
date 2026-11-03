// Тест на двух страницах: quiz.html?page=1 → «Далее» → ?page=2 → «Завершить» → result.html.
// Ответы — в sessionStorage вкладки (переживают перезагрузку и перезапуск ядра).
// ?captcha=1 — на второй странице через 1,5 с появляется .g-recaptcha; «Я не робот» убирает её,
// пока она есть — «Завершить» не принимается.
(() => {
  const KEY = "stand.quiz.answers";
  const params = new URLSearchParams(location.search);
  const page = params.get("page") === "2" ? 2 : 1;
  const form = document.getElementById("responseform");
  const error = document.getElementById("quiz-error");

  const load = () => { try { return JSON.parse(sessionStorage.getItem(KEY)) || {}; } catch (_) { return {}; } };
  const save = (a) => sessionStorage.setItem(KEY, JSON.stringify(a));

  form.appendChild(document.getElementById("page-" + page).content.cloneNode(true));
  document.getElementById("page-no").textContent = String(page);

  const radio = (name) => (form.querySelector(`input[name=${name}]:checked`) || {}).value || "";
  const checks = (name) => Array.from(form.querySelectorAll(`input[name=${name}]:checked`)).map((x) => x.value);
  const selectText = (sel) => (sel.value ? sel.options[sel.selectedIndex].text : "");
  const rows = (prefix) => Object.fromEntries(Array.from(form.querySelectorAll(`select[name^=${prefix}-]`))
    .map((s) => [s.name.slice(prefix.length + 1), selectText(s)]));

  // ── перетаскивание (HTML5 DnD, как у простых sortable-библиотек) ──
  const list = document.getElementById("q7-list");
  const q7Order = () => Array.from(list ? list.children : []).map((li) => li.dataset.id);
  if (list) {
    let dragged = null;
    const sync = () => { document.getElementById("q7-order").value = q7Order().join(","); };
    list.addEventListener("dragstart", (e) => {
      dragged = e.target.closest("li");
      if (e.dataTransfer) { e.dataTransfer.effectAllowed = "move"; e.dataTransfer.setData("text/plain", dragged.dataset.id); }
      dragged.classList.add("dragging");
    });
    list.addEventListener("dragover", (e) => { e.preventDefault(); });
    list.addEventListener("drop", (e) => {
      e.preventDefault();
      const target = e.target.closest("li");
      if (!dragged || !target || target === dragged) return;
      const r = target.getBoundingClientRect();
      list.insertBefore(dragged, e.clientY < r.top + r.height / 2 ? target : target.nextSibling);
      sync();
    });
    list.addEventListener("dragend", () => { if (dragged) dragged.classList.remove("dragging"); dragged = null; });
    const saved = load().q7;
    if (Array.isArray(saved)) for (const id of saved) { const li = list.querySelector(`[data-id=${id}]`); if (li) list.appendChild(li); }
    sync();
  }

  // ── восстановление ответов страницы ──
  const a = load();
  for (const [name, v] of Object.entries(a)) {
    if (typeof v === "string") {
      for (const el of form.querySelectorAll(`[name=${name}]`)) {
        if (el.type === "radio") el.checked = el.value === v; else if (el.type !== "hidden") el.value = v;
      }
    } else if (Array.isArray(v) && name !== "q7") {
      for (const el of form.querySelectorAll(`input[name=${name}]`)) el.checked = v.includes(el.value);
    } else if (v && typeof v === "object") {
      for (const [row, text] of Object.entries(v)) {
        const sel = form.querySelector(`select[name=${name}-${row}]`);
        if (sel) for (const o of sel.options) if (o.text === text && text) o.selected = true;
      }
    }
  }

  // ── капча на второй странице ──
  let captcha = null;
  if (page === 2 && params.get("captcha") === "1" && !sessionStorage.getItem("stand.captcha.ok")) {
    setTimeout(() => {
      captcha = document.getElementById("captcha").content.firstElementChild.cloneNode(true);
      form.parentElement.insertBefore(captcha, form);
      captcha.querySelector("#captcha-check").addEventListener("change", () => {
        setTimeout(() => {
          sessionStorage.setItem("stand.captcha.ok", "1");
          captcha.remove();
          captcha = null;
        }, 600);
      });
    }, 1500);
  }

  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const answers = load();
    if (page === 1) {
      Object.assign(answers, { q1: radio("q1"), q2: checks("q2"), q3: form.elements.namedItem("q3").value.trim(), q4: radio("q4") });
      save(answers);
      params.set("page", "2");
      location.href = "quiz.html?" + params.toString();
      return;
    }
    if (captcha) {
      error.textContent = "Подтвердите, что вы не робот.";
      error.hidden = false;
      return;
    }
    Object.assign(answers, { q5: rows("q5"), q6: rows("q6"), q7: q7Order() });
    save(answers);
    location.href = "result.html";
  });
})();
