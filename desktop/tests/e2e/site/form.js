// Анкета: обязательные поля проверяются в браузере; email «проверяет сервер» — первая отправка
// получает ошибку (aria-invalid + текст), вторая принимается. Итог — в #result-json.
(() => {
  const form = document.getElementById("signup");
  const email = document.getElementById("email");
  const emailError = document.getElementById("email-error");
  const formError = document.getElementById("form-error");
  let serverChecks = 0;

  const values = () => ({
    name: form.elements.namedItem("name").value.trim(),
    email: email.value.trim(),
    city: form.elements.namedItem("city").value,
    contact: (form.querySelector("input[name=contact]:checked") || {}).value || "",
    agree: form.elements.namedItem("agree").checked,
    comment: form.elements.namedItem("comment").value.trim(),
  });

  function showError(box, text) {
    box.textContent = text;
    box.hidden = !text;
  }

  email.addEventListener("input", () => {
    email.removeAttribute("aria-invalid");
    showError(emailError, "");
  });

  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const v = values();
    const missing = [];
    if (!v.name) missing.push("имя");
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(v.email)) missing.push("электронная почта");
    if (!v.city) missing.push("город");
    if (!v.contact) missing.push("способ связи");
    if (!v.agree) missing.push("согласие");
    if (missing.length) {
      showError(formError, "Заполните: " + missing.join(", "));
      return;
    }
    showError(formError, "");
    const button = form.querySelector("button[type=submit]");
    button.disabled = true;
    button.textContent = "Проверяем…";
    setTimeout(() => {
      button.disabled = false;
      button.textContent = "Отправить";
      serverChecks += 1;
      if (serverChecks === 1) {
        email.setAttribute("aria-invalid", "true");
        showError(emailError, "Не удалось проверить адрес почты на сервере. Отправьте форму ещё раз.");
        return;
      }
      form.hidden = true;
      document.getElementById("result-json").textContent = JSON.stringify(Object.assign(v, { attempts: serverChecks }));
      document.getElementById("done").hidden = false;
      document.title = "Заявка отправлена";
    }, 400);
  });
})();
