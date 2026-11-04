// Сакура: расписание — букмарклет (docs/SCHEDULE.md).
// Запускается кликом Мастера на странице расписания МУИВ. Делает тот же
// запрос, что и сама страница при выборе группы (браузер Мастера уже прошёл
// проверку сайта), и отправляет на VPS только поле ttable. Куки сайта не
// читает и не пересылает. Плейсхолдеры __ENDPOINT__/__TOKEN__/__FORM__
// подставляет build.py; готовая строка содержит токен — в git её не класть.
(async () => {
  const ENDPOINT = __ENDPOINT__;
  const TOKEN = __TOKEN__;
  const FORM = __FORM__;
  const say = (m) => alert('Сакура: ' + m);
  if (location.hostname !== 'www.muiv.ru') {
    say('открой страницу расписания на www.muiv.ru и нажми ещё раз');
    return;
  }
  try {
    const r = await fetch('/services/timetable/ajax.php?' + Date.now(), {
      method: 'POST',
      credentials: 'same-origin',
      headers: {
        'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
        'X-Requested-With': 'XMLHttpRequest',
      },
      body: new URLSearchParams(FORM),
    });
    if (!(r.headers.get('content-type') || '').includes('json')) {
      say('сайт не отдал расписание — обнови страницу и нажми ещё раз');
      return;
    }
    const data = await r.json();
    if (typeof data.ttable !== 'string') {
      say('в ответе сайта нет расписания');
      return;
    }
    const p = await fetch(ENDPOINT, {
      method: 'POST',
      headers: { 'Authorization': 'Bearer ' + TOKEN, 'Content-Type': 'application/json' },
      body: JSON.stringify({ group: FORM.groupname, ttable: data.ttable }),
    });
    const res = await p.json().catch(() => ({ message: 'ошибка сервера ' + p.status }));
    say(res.message);
  } catch (e) {
    say('не получилось — ' + e.message);
  }
})();
