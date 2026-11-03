// Сверка ответов теста (sessionStorage) с эталоном answers.json; итог — таблица и #result-json.
(async () => {
  const answers = (() => { try { return JSON.parse(sessionStorage.getItem("stand.quiz.answers")) || {}; } catch (_) { return {}; } })();
  const ref = (await (await fetch("answers.json", { cache: "no-store" })).json()).quiz.questions;

  const same = (x, y) => JSON.stringify(x) === JSON.stringify(y);
  function verdict(id, want) {
    const got = answers[id];
    if (got === undefined || got === "" || (Array.isArray(got) && !got.length)) return "нет ответа";
    if (want.kind === "text") return want.answer.includes(String(got).trim().toLowerCase()) ? "верно" : "неверно";
    if (want.kind === "multi") return same([...got].sort(), [...want.answer].sort()) ? "верно" : "неверно";
    if (want.kind === "match" || (want.kind === "order" && !want.drag)) {
      const keys = Object.keys(want.answer);
      if (keys.every((k) => !got[k])) return "нет ответа";
      return keys.every((k) => got[k] === want.answer[k]) ? "верно" : "неверно";
    }
    return same(got, want.answer) ? "верно" : "неверно";
  }

  const result = {};
  const body = document.getElementById("rows");
  for (const [id, want] of Object.entries(ref)) {
    result[id] = { verdict: verdict(id, want), answer: answers[id] === undefined ? null : answers[id] };
    const tr = document.createElement("tr");
    tr.className = result[id].verdict === "верно" ? "ok" : "bad";
    for (const text of [id.toUpperCase(), JSON.stringify(result[id].answer), result[id].verdict]) {
      const td = document.createElement("td");
      td.textContent = text;
      tr.appendChild(td);
    }
    body.appendChild(tr);
  }
  const right = Object.values(result).filter((r) => r.verdict === "верно").length;
  document.getElementById("score").textContent = `Верно ${right} из ${Object.keys(result).length}`;
  document.getElementById("result-json").textContent = JSON.stringify({ right, total: Object.keys(result).length, questions: result });
  document.getElementById("again").addEventListener("click", () => sessionStorage.clear());
})();
