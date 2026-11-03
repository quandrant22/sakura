/**
 * background.js — Service Worker (Manifest V3)
 *
 * Полное управление браузером для Сакуры:
 *   Вкладки, навигация, закладки, история, YouTube, формы, скриншоты,
 *   управление окнами, mute/pin, reader mode, и т.д.
 *
 * Агент браузера (3.2.0): действия tabs.* / agent_window.* / page.* — lib/agent.js,
 * захват кадра — lib/capture.js. Код в страницу — только функции
 * (chrome.scripting.executeScript({func, args})), сборка кода строкой запрещена.
 * В console.log — только действие и статус, без данных страниц.
 */

importScripts("lib/capture.js", "lib/agent.js");

// Произвольный JS на странице (js_exec / js_exec_url) выключен. Включается только
// правкой этой строки; из реестра команд desktop core действия убраны.
const ALLOW_JS_EXEC = false;

// Агент занимает первый свободный порт из списка (agent/config.py:
// EXTENSION_PORTS, .env override). Перебираем те же порты по порядку и
// проверяем, что на том конце Сакура: агент после подключения первым
// шлёт sakura_hello. Без проверки расширение подключалось бы к чужому
// сокету (VS Code держал 8766) и слало бы ему команды в никуда.
const PORTS = [8766, 8767, 8768, 8769];
const HELLO_TIMEOUT_MS = 1000;
const CONNECT_TIMEOUT_MS = 2000;

// Реконнект с экспоненциальным бэкоффом: если агент не запущен,
// не стучимся в порт каждые 3 секунды бесконечно
let reconnectDelay = 3000;
const RECONNECT_MAX = 30000;

let ws        = null;
let connected = false;

// ── WebSocket ──────────────────────────────────────────────────────

function connect(portIdx = 0) {
  if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) {
    return;
  }
  if (portIdx >= PORTS.length) {
    // Ни один порт не ответил как Сакура — ждём и начинаем с начала.
    console.log("[Sakura] Агент не найден ни на одном порту из", PORTS,
                "— повтор через", reconnectDelay, "мс");
    setTimeout(() => connect(0), reconnectDelay);
    reconnectDelay = Math.min(reconnectDelay * 2, RECONNECT_MAX);
    return;
  }
  const url = `ws://127.0.0.1:${PORTS[portIdx]}`;
  let sock;
  try {
    sock = ws = new WebSocket(url);
  } catch (e) {
    console.log("[Sakura] Не удалось открыть", url, e && e.message);
    setTimeout(() => connect(portIdx + 1), 50);
    return;
  }

  // Бросить этот сокет и перейти к следующему порту. Обработчики снимаются до close():
  // иначе поздний onclose старого сокета затёр бы ws нового и запустил второй перебор.
  let helloTimer = null;
  const abandon = (why) => {
    console.log("[Sakura]", url, why);
    clearTimeout(connectTimer);
    clearTimeout(helloTimer);
    sock.onopen = sock.onclose = sock.onerror = null;
    try { sock.close(); } catch (_) {}
    if (ws === sock) ws = null;
    connect(portIdx + 1);
  };

  // Чужая программа может принять TCP и не ответить на рукопожатие (VS Code на 8767):
  // без срока сокет навсегда остаётся CONNECTING, и до Сакуры перебор не доходит.
  const connectTimer = setTimeout(() => {
    if (sock.readyState === WebSocket.CONNECTING) abandon("— нет рукопожатия, пробую следующий порт");
  }, CONNECT_TIMEOUT_MS);

  sock.onopen = () => {
    clearTimeout(connectTimer);
    // Ждём sakura_hello не дольше секунды: не пришло или пришло другое —
    // на этом порту не Сакура, закрываем и пробуем следующий порт.
    helloTimer = setTimeout(() => abandon("— нет sakura_hello, пробую следующий порт"), HELLO_TIMEOUT_MS);
    sock.addEventListener("message", function onHello(event) {
      let msg = null;
      try { msg = JSON.parse(event.data); } catch (_) { return; }
      if (!msg || msg.type !== "sakura_hello") {
        return; // не приветствие — игнорируем, ждём дальше
      }
      clearTimeout(helloTimer);
      sock.removeEventListener("message", onHello);
      sock.onmessage = handleMessages;
      connected = true;
      reconnectDelay = 3000;
      console.log("[Sakura] Подключено к агенту:", url,
                  "версия", msg.version || "?");
      send({ type: "extension_ready", version: chrome.runtime.getManifest().version });
    });
  };

  sock.onclose = () => {
    // Сюда попадаем и при отказе порта (чужой сокет закрыл соединение).
    // Если hello уже принят, onclose — обычный обрыв: реконнект с начала.
    clearTimeout(connectTimer);
    clearTimeout(helloTimer);
    if (ws !== sock) return;  // событие брошенного сокета
    const wasConnected = connected;
    connected = false;
    ws = null;
    if (wasConnected) {
      console.log("[Sakura] Обрыв — реконнект через", reconnectDelay, "мс");
      setTimeout(() => connect(0), reconnectDelay);
      reconnectDelay = Math.min(reconnectDelay * 2, RECONNECT_MAX);
    } else {
      connect(portIdx + 1);
    }
  };

  sock.onerror = (e) => {
    console.log("[Sakura] Ошибка WS:", url, e && e.message);
    try { sock.close(); } catch (_) {}
  };
}

function handleMessages(event) {
  let msg;
  try { msg = JSON.parse(event.data); } catch { return; }
  if (msg && msg.type === "upload_data") {
    const waiter = uploadWaiters.get(msg.id);
    if (waiter) { uploadWaiters.delete(msg.id); waiter(msg); }
    return;
  }
  (async () => {
    const result = await handleCommand(msg);
    if (result !== undefined) {
      send({ type: "extension_result", id: msg.id, action: msg.action, result });
    }
  })();
}

function send(data) {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify(data));
  }
}

// ── Агент браузера ────────────────────────────────────────────────

// Файл для page.upload приходит из desktop core по одноразовому токену.
const uploadWaiters = new Map();
let uploadSeq = 0;

function fetchUpload(token) {
  return new Promise((resolve) => {
    if (!connected) { resolve({ ok: false, error: "нет связи с ядром" }); return; }
    const id = "u" + (++uploadSeq) + "-" + Date.now().toString(36);
    const timer = setTimeout(() => {
      uploadWaiters.delete(id);
      resolve({ ok: false, error: "ядро не прислало файл" });
    }, 20000);
    uploadWaiters.set(id, (m) => { clearTimeout(timer); resolve(m); });
    send({ type: "upload_fetch", id, file_token: token });
  });
}

const captureQueue = SakuraCapture.createQueue({
  capture: (windowId, opts) => chrome.tabs.captureVisibleTab(windowId, opts),
});

const agent = SakuraAgent.create({ chrome, capture: captureQueue, fetchUpload });

// ── Утилиты ───────────────────────────────────────────────────────

async function getActiveTab() {
  const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
  return tabs[0] || null;
}

async function findTab(query) {
  if (!query) return await getActiveTab();
  const tabs = await chrome.tabs.query({});
  const q = query.toLowerCase();
  return tabs.find(t =>
    (t.url && t.url.toLowerCase().includes(q)) ||
    (t.title && t.title.toLowerCase().includes(q))
  ) || null;
}

// Функция в страницу с аргументами — без сборки кода строкой.
async function runInTab(tabId, func, args = []) {
  try {
    const results = await chrome.scripting.executeScript({ target: { tabId }, func, args });
    return results[0]?.result;
  } catch (e) {
    return { error: e.message };
  }
}

// Только для js_exec при ALLOW_JS_EXEC = true: произвольный код по определению.
async function execInTab(tabId, code) {
  try {
    const results = await chrome.scripting.executeScript({
      target: { tabId },
      func: (codeStr) => { try { return eval(codeStr); } catch(e) { return { error: e.message }; } },
      args: [code],
    });
    return results[0]?.result;
  } catch (e) {
    return { error: e.message };
  }
}

// ── Обработчик команд ──────────────────────────────────────────────

async function handleCommand(msg) {
  const action = msg.action || "";
  const arg    = msg.arg    || "";

  if (SakuraAgent.handles(action)) {
    const res = await agent.handle(action, msg.args || {});
    console.log("[Sakura]", action, "→", res.status);
    return res;
  }

  // ══════════════════════════════════════════════════════════════════
  // ВКЛАДКИ
  // ══════════════════════════════════════════════════════════════════

  if (action === "tabs_list") {
    const tabs = await chrome.tabs.query({});
    return tabs.map(t => ({
      id: t.id, title: t.title, url: t.url,
      active: t.active, pinned: t.pinned, muted: t.mutedInfo?.muted,
      groupId: t.groupId,
    }));
  }

  if (action === "tab_switch") {
    const tab = await findTab(arg);
    if (tab) {
      await chrome.tabs.update(tab.id, { active: true });
      await chrome.windows.update(tab.windowId, { focused: true });
      return { ok: true, title: tab.title, url: tab.url };
    }
    return { ok: false, error: "Вкладка не найдена: " + arg };
  }

  if (action === "tab_new") {
    const tab = await chrome.tabs.create({ url: arg || "about:blank" });
    return { ok: true, id: tab.id, title: tab.title };
  }

  if (action === "tab_new_bg") {
    const tab = await chrome.tabs.create({ url: arg, active: false });
    return { ok: true, id: tab.id };
  }

  if (action === "tab_close") {
    if (arg === "all") {
      const tabs = await chrome.tabs.query({});
      const ids = tabs.filter(t => !t.active).map(t => t.id);
      if (ids.length) await chrome.tabs.remove(ids);
      return { ok: true, closed: ids.length };
    }
    const tab = arg ? await findTab(arg) : await getActiveTab();
    if (tab) { await chrome.tabs.remove(tab.id); return { ok: true }; }
    return { ok: false };
  }

  if (action === "tab_close_others") {
    const tabs = await chrome.tabs.query({ currentWindow: true });
    const active = tabs.find(t => t.active);
    const ids = tabs.filter(t => t.id !== active?.id).map(t => t.id);
    if (ids.length) await chrome.tabs.remove(ids);
    return { ok: true, closed: ids.length };
  }

  if (action === "tab_dup") {
    const tab = await getActiveTab();
    if (tab) { await chrome.tabs.duplicate(tab.id); return { ok: true }; }
    return { ok: false };
  }

  if (action === "tab_reload") {
    const tab = arg ? await findTab(arg) : await getActiveTab();
    if (tab) { await chrome.tabs.reload(tab.id); return { ok: true }; }
    return { ok: false };
  }

  if (action === "tab_next") {
    const tabs = await chrome.tabs.query({ currentWindow: true });
    const active = tabs.find(t => t.active);
    const idx = tabs.indexOf(active);
    const next = tabs[(idx + 1) % tabs.length];
    await chrome.tabs.update(next.id, { active: true });
    return { ok: true, title: next.title };
  }

  if (action === "tab_prev") {
    const tabs = await chrome.tabs.query({ currentWindow: true });
    const active = tabs.find(t => t.active);
    const idx = tabs.indexOf(active);
    const prev = tabs[(idx - 1 + tabs.length) % tabs.length];
    await chrome.tabs.update(prev.id, { active: true });
    return { ok: true, title: prev.title };
  }

  if (action === "tab_pin") {
    const tab = arg ? await findTab(arg) : await getActiveTab();
    if (tab) { await chrome.tabs.update(tab.id, { pinned: !tab.pinned }); return { ok: true, pinned: !tab.pinned }; }
    return { ok: false };
  }

  if (action === "tab_mute") {
    const tab = arg ? await findTab(arg) : await getActiveTab();
    if (tab) {
      const muted = !tab.mutedInfo?.muted;
      await chrome.tabs.update(tab.id, { muted });
      return { ok: true, muted };
    }
    return { ok: false };
  }

  if (action === "tab_info") {
    const tab = await getActiveTab();
    if (tab) return { id: tab.id, title: tab.title, url: tab.url, pinned: tab.pinned, muted: tab.mutedInfo?.muted };
    return { ok: false };
  }

  if (action === "tab_move") {
    const tab = await getActiveTab();
    if (!tab) return { ok: false };
    // arg = "left" / "right" / windowId
    if (arg === "left" || arg === "right") {
      const tabs = await chrome.tabs.query({ currentWindow: true });
      const idx = tabs.findIndex(t => t.id === tab.id);
      const newIdx = arg === "left" ? Math.max(0, idx - 1) : Math.min(tabs.length - 1, idx + 1);
      await chrome.tabs.move(tab.id, { index: newIdx });
      return { ok: true };
    }
    const winId = parseInt(arg);
    if (winId) {
      await chrome.tabs.move(tab.id, { windowId: winId, index: -1 });
      return { ok: true };
    }
    return { ok: false, error: "Укажи 'left', 'right' или windowId" };
  }

  // ══════════════════════════════════════════════════════════════════
  // НАВИГАЦИЯ
  // ══════════════════════════════════════════════════════════════════

  if (action === "navigate") {
    const tab = await getActiveTab();
    if (tab) {
      const url = arg.startsWith("http") ? arg : "https://" + arg;
      await chrome.tabs.update(tab.id, { url });
      return { ok: true };
    }
    return { ok: false };
  }

  if (action === "go_back") {
    const tab = await getActiveTab();
    if (tab) { await chrome.tabs.goBack(tab.id); return { ok: true }; }
    return { ok: false };
  }

  if (action === "go_forward") {
    const tab = await getActiveTab();
    if (tab) { await chrome.tabs.goForward(tab.id); return { ok: true }; }
    return { ok: false };
  }

  // ══════════════════════════════════════════════════════════════════
  // МАСШТАБ
  // ══════════════════════════════════════════════════════════════════

  if (action === "zoom_in") {
    const tab = await getActiveTab();
    if (tab) { const z = await chrome.tabs.getZoom(tab.id); await chrome.tabs.setZoom(tab.id, Math.min(z + 0.25, 5)); return { ok: true }; }
    return { ok: false };
  }

  if (action === "zoom_out") {
    const tab = await getActiveTab();
    if (tab) { const z = await chrome.tabs.getZoom(tab.id); await chrome.tabs.setZoom(tab.id, Math.max(z - 0.25, 0.25)); return { ok: true }; }
    return { ok: false };
  }

  if (action === "zoom_reset") {
    const tab = await getActiveTab();
    if (tab) { await chrome.tabs.setZoom(tab.id, 1); return { ok: true }; }
    return { ok: false };
  }

  // ══════════════════════════════════════════════════════════════════
  // СТРАНИЦА — чтение
  // ══════════════════════════════════════════════════════════════════

  if (action === "page_content") {
    const tab = await getActiveTab();
    if (!tab) return { ok: false };
    const content = await runInTab(tab.id, () => {
      try {
        const body = document.body.cloneNode(true);
        body.querySelectorAll("script,style,noscript,svg,nav,header,footer,aside,iframe").forEach(e => e.remove());
        return (body.innerText || body.textContent || "").replace(/\s+/g, " ").trim().slice(0, 12000);
      } catch (e) { return { error: e.message }; }
    });
    return { ok: true, content: content || "", url: tab.url, title: tab.title };
  }

  if (action === "page_article") {
    // Reader mode — извлекает чистую статью
    const tab = await getActiveTab();
    if (!tab) return { ok: false };
    const content = await runInTab(tab.id, () => {
      try {
        // Ищем основной контент
        let article = document.querySelector("article") ||
                      document.querySelector('[role="main"]') ||
                      document.querySelector(".post-content") ||
                      document.querySelector(".article-content") ||
                      document.querySelector(".entry-content") ||
                      document.querySelector(".content") ||
                      document.querySelector("main");
        if (!article) {
          const body = document.body.cloneNode(true);
          body.querySelectorAll("script,style,noscript,svg,nav,header,footer,aside,iframe,form").forEach(e => e.remove());
          article = body;
        }
        const text = (article.innerText || article.textContent || "").replace(/\s+/g, " ").trim();
        // Извлекаем заголовок
        const h1 = document.querySelector("h1");
        const title = h1 ? h1.textContent.trim() : document.title;
        return { title: title, content: text.slice(0, 12000), url: location.href };
      } catch (e) { return { error: e.message }; }
    });
    return { ok: true, ...(content || {}) };
  }

  if (action === "page_links") {
    const tab = await getActiveTab();
    if (!tab) return { ok: false };
    const links = await runInTab(tab.id, () =>
      Array.from(document.querySelectorAll("a[href]")).slice(0, 50).map(a => ({
        text: a.textContent.trim().slice(0, 80),
        href: a.href,
      })));
    return { ok: true, links: links || [] };
  }

  if (action === "page_images") {
    const tab = await getActiveTab();
    if (!tab) return { ok: false };
    const images = await runInTab(tab.id, () =>
      Array.from(document.querySelectorAll("img[src]")).slice(0, 20).map(img => ({
        src: img.src,
        alt: img.alt?.slice(0, 80) || "",
        width: img.naturalWidth,
        height: img.naturalHeight,
      })));
    return { ok: true, images: images || [] };
  }

  if (action === "page_meta") {
    const tab = await getActiveTab();
    if (!tab) return { ok: false };
    const meta = await runInTab(tab.id, () => {
      const get = (n) => document.querySelector('meta[name="' + n + '"]')?.content ||
                         document.querySelector('meta[property="' + n + '"]')?.content || "";
      return {
        title: document.title,
        description: get("description") || get("og:description"),
        image: get("og:image"),
        url: location.href,
        author: get("author"),
        keywords: get("keywords"),
      };
    });
    return { ok: true, ...(meta || {}) };
  }

  if (action === "page_content_youtube") {
    // «Что за видео»: ищем вкладку YouTube — сначала звучащую, затем активную, затем первую
    const ytTabs = await chrome.tabs.query({ url: [
      "*://www.youtube.com/watch*",
      "*://m.youtube.com/watch*",
      "*://music.youtube.com/watch*",
    ] });
    const tab = ytTabs.find(t => t.audible) || ytTabs.find(t => t.active) || ytTabs[0];
    if (!tab) return { ok: false, error: "нет открытого видео YouTube" };
    try {
      const results = await chrome.scripting.executeScript({
        target: { tabId: tab.id },
        func: () => {
          const q = (s) => document.querySelector(s);
          const title = (document.title || "").replace(/^\(\d+\)\s*/, "").replace(/ - YouTube( Music)?$/, "");
          const channel = (q("ytd-channel-name a")?.textContent ||
                           q('meta[itemprop="author"]')?.content ||
                           q('link[itemprop="name"]')?.getAttribute("content") || "").trim();
          const description = (q('meta[name="description"]')?.content || "").slice(0, 1500);
          const v = q("video");
          return {
            title, channel, description,
            video_id: new URL(location.href).searchParams.get("v") || "",
            duration: v && isFinite(v.duration) ? v.duration : null,
            currentTime: v ? v.currentTime : null,
            paused: v ? v.paused : null,
            url: location.href,
          };
        },
      });
      const result = results[0]?.result;
      if (!result) return { ok: false, error: "не удалось прочитать страницу" };
      return { ok: true, result };
    } catch (e) {
      return { ok: false, error: e.message };
    }
  }

  // ══════════════════════════════════════════════════════════════════
  // СТРАНИЦА — взаимодействие
  // ══════════════════════════════════════════════════════════════════

  if (action === "page_scroll") {
    const tab = await getActiveTab();
    if (!tab) return { ok: false };
    const dir = arg === "up" ? -500 : arg === "down" ? 500 : parseInt(arg) || 500;
    await runInTab(tab.id, (dy) => window.scrollBy(0, dy), [dir]);
    return { ok: true };
  }

  if (action === "page_scroll_to") {
    const tab = await getActiveTab();
    if (!tab) return { ok: false };
    const pct = Math.max(0, Math.min(100, parseInt(arg) || 0));
    await runInTab(tab.id, (p) => window.scrollTo(0, document.body.scrollHeight * p / 100), [pct]);
    return { ok: true };
  }

  if (action === "page_click") {
    const tab = await getActiveTab();
    if (!tab) return { ok: false };
    const result = await runInTab(tab.id, (text) => {
      const all = document.querySelectorAll('a,button,[role="button"],input[type="submit"]');
      for (let i = 0; i < all.length; i++) {
        if (all[i].textContent.toLowerCase().includes(text.toLowerCase())) {
          all[i].scrollIntoView({ block: "center" });
          all[i].click();
          return "clicked: " + all[i].textContent.trim().slice(0, 40);
        }
      }
      return "not found";
    }, [arg]);
    return { ok: true, result };
  }

  if (action === "page_highlight") {
    const tab = await getActiveTab();
    if (!tab) return { ok: false };
    // Подсвечивает элемент — визуальная обратная связь
    await runInTab(tab.id, (text) => {
      const q = text.toLowerCase();
      const all = document.querySelectorAll('a,button,[role="button"],input,select,textarea,label');
      for (let i = 0; i < all.length; i++) {
        if (all[i].textContent.toLowerCase().includes(q) ||
            (all[i].placeholder && all[i].placeholder.toLowerCase().includes(q))) {
          const el = all[i];
          el.scrollIntoView({ block: "center", behavior: "smooth" });
          el.style.outline = "3px solid #ff69b4";
          el.style.outlineOffset = "2px";
          setTimeout(() => { el.style.outline = ""; el.style.outlineOffset = ""; }, 3000);
          return "highlighted: " + (el.textContent.trim().slice(0, 40) || el.placeholder || el.tagName);
        }
      }
      return "not found";
    }, [arg]);
    return { ok: true };
  }

  if (action === "page_fill") {
    // Заполнение формы: arg = "label|value" или "selector|value"
    const tab = await getActiveTab();
    if (!tab) return { ok: false };
    const parts = arg.split("|");
    if (parts.length < 2) return { ok: false, error: "Формат: label|значение" };
    const label = parts[0].trim();
    const value = parts.slice(1).join("|").trim();
    const result = await runInTab(tab.id, (label, value) => {
      // Ищем по label
      const inputs = document.querySelectorAll("input,textarea,select");
      for (let i = 0; i < inputs.length; i++) {
        const inp = inputs[i];
        const ph = (inp.placeholder || "").toLowerCase();
        const nm = (inp.name || "").toLowerCase();
        const id = (inp.id || "").toLowerCase();
        let lb = "";
        if (inp.id) {
          const l = Array.from(document.querySelectorAll("label[for]")).find(x => x.htmlFor === inp.id);
          if (l) lb = l.textContent.toLowerCase();
        }
        if (ph.includes(label.toLowerCase()) || nm.includes(label.toLowerCase()) ||
            id.includes(label.toLowerCase()) || lb.includes(label.toLowerCase())) {
          // Пароли и платёжные поля не заполняем
          const ac = (inp.getAttribute("autocomplete") || "").toLowerCase();
          if ((inp.type || "").toLowerCase() === "password" || ac.indexOf("cc-") === 0 ||
              /card|cvv|cvc|iban|pass/.test(nm + " " + id + " " + ph)) {
            return { protected: true };
          }
          if (inp.tagName === "SELECT") {
            for (let j = 0; j < inp.options.length; j++) {
              if (inp.options[j].text.toLowerCase().includes(value.toLowerCase())) {
                inp.selectedIndex = j;
                inp.dispatchEvent(new Event("change", { bubbles: true }));
                return "selected: " + inp.options[j].text;
              }
            }
          } else {
            inp.focus();
            inp.value = value;
            inp.dispatchEvent(new Event("input", { bubbles: true }));
            inp.dispatchEvent(new Event("change", { bubbles: true }));
            return "filled: " + (inp.name || inp.id || inp.placeholder);
          }
        }
      }
      return "input not found";
    }, [label, value]);
    if (result && result.protected) return { ok: false, error: "поле защищено" };
    return { ok: true, result };
  }

  if (action === "page_select") {
    const tab = await getActiveTab();
    if (!tab) return { ok: false };
    const result = await runInTab(tab.id, (text) => {
      const selects = document.querySelectorAll("select");
      for (const s of selects) {
        for (const o of s.options) {
          if (o.text.toLowerCase().includes(text.toLowerCase())) {
            s.value = o.value;
            s.dispatchEvent(new Event("change", { bubbles: true }));
            return "selected: " + o.text;
          }
        }
      }
      return "select not found";
    }, [arg]);
    return { ok: true, result };
  }

  if (action === "page_submit") {
    const tab = await getActiveTab();
    if (!tab) return { ok: false };
    await runInTab(tab.id, () => {
      const form = document.activeElement?.form || document.querySelector("form");
      if (form) { form.submit(); return "submitted"; }
      return "no form";
    });
    return { ok: true };
  }

  // ══════════════════════════════════════════════════════════════════
  // СКРИНШОТЫ
  // ══════════════════════════════════════════════════════════════════

  if (action === "screenshot") {
    const tab = await getActiveTab();
    if (!tab) return { ok: false };
    try {
      const dataUrl = await chrome.tabs.captureVisibleTab(tab.windowId, { format: "jpeg", quality: 70 });
      const base64 = dataUrl.split(",")[1];
      return { ok: true, screenshot: base64 };
    } catch (e) {
      return { ok: false, error: e.message };
    }
  }

  if (action === "screenshot_element") {
    const tab = await getActiveTab();
    if (!tab) return { ok: false };
    try {
      // Скриншот конкретного элемента
      const results = await chrome.scripting.executeScript({
        target: { tabId: tab.id },
        func: (sel) => {
          const el = document.querySelector(sel);
          if (!el) return null;
          const rect = el.getBoundingClientRect();
          return { x: rect.x, y: rect.y, width: rect.width, height: rect.height };
        },
        args: [arg || "main"],
      });
      const rect = results[0]?.result;
      if (!rect) return { ok: false, error: "Element not found" };
      const dataUrl = await chrome.tabs.captureVisibleTab(tab.windowId, { format: "jpeg", quality: 80 });
      return { ok: true, screenshot: dataUrl.split(",")[1], rect };
    } catch (e) {
      return { ok: false, error: e.message };
    }
  }

  // ══════════════════════════════════════════════════════════════════
  // ПОИСК
  // ══════════════════════════════════════════════════════════════════

  if (action === "search_google") {
    const tab = await chrome.tabs.create({
      url: `https://www.google.com/search?q=${encodeURIComponent(arg)}`
    });
    return { ok: true, id: tab.id };
  }

  if (action === "search_youtube") {
    const tab = await chrome.tabs.create({
      url: `https://www.youtube.com/results?search_query=${encodeURIComponent(arg)}`
    });
    return { ok: true, id: tab.id };
  }

  if (action === "search_yandex") {
    const tab = await chrome.tabs.create({
      url: `https://yandex.ru/search/?text=${encodeURIComponent(arg)}`
    });
    return { ok: true, id: tab.id };
  }

  if (action === "search_ddg") {
    const tab = await chrome.tabs.create({
      url: `https://duckduckgo.com/?q=${encodeURIComponent(arg)}`
    });
    return { ok: true, id: tab.id };
  }

  // ══════════════════════════════════════════════════════════════════
  // ЗАКЛАДКИ
  // ══════════════════════════════════════════════════════════════════

  if (action === "bookmark_add") {
    const tab = await getActiveTab();
    if (!tab) return { ok: false };
    const bm = await chrome.bookmarks.create({
      parentId: (await chrome.bookmarks.getTree())[0].children[1]?.id, // "Bookmarks bar"
      title: arg || tab.title,
      url: tab.url,
    });
    return { ok: true, id: bm.id, title: bm.title };
  }

  if (action === "bookmark_list") {
    const tree = await chrome.bookmarks.getTree();
    const bookmarks = [];
    function walk(nodes) {
      for (const n of nodes) {
        if (n.url) bookmarks.push({ title: n.title, url: n.url, id: n.id });
        if (n.children) walk(n.children);
      }
    }
    walk(tree);
    return { ok: true, bookmarks: bookmarks.slice(0, 50) };
  }

  if (action === "bookmark_search") {
    const results = await chrome.bookmarks.search(arg);
    return { ok: true, bookmarks: results.slice(0, 20).map(b => ({ title: b.title, url: b.url, id: b.id })) };
  }

  if (action === "bookmark_remove") {
    const results = await chrome.bookmarks.search(arg);
    if (results.length) {
      await chrome.bookmarks.remove(results[0].id);
      return { ok: true, removed: results[0].title };
    }
    return { ok: false, error: "Закладка не найдена" };
  }

  // ══════════════════════════════════════════════════════════════════
  // ИСТОРИЯ
  // ══════════════════════════════════════════════════════════════════

  if (action === "history_search") {
    const results = await chrome.history.search({ text: arg, maxResults: 20 });
    return { ok: true, history: results.map(h => ({ title: h.title, url: h.url, lastVisit: h.lastVisitTime })) };
  }

  if (action === "history_recent") {
    const results = await chrome.history.search({ text: "", maxResults: parseInt(arg) || 20 });
    return { ok: true, history: results.map(h => ({ title: h.title, url: h.url })) };
  }

  if (action === "history_clear") {
    await chrome.history.deleteAll();
    return { ok: true };
  }

  // ══════════════════════════════════════════════════════════════════
  // ОКНА
  // ══════════════════════════════════════════════════════════════════

  if (action === "window_list") {
    const wins = await chrome.windows.getAll({ populate: true });
    return wins.map(w => ({
      id: w.id, focused: w.focused, state: w.state,
      tabs: w.tabs.length, type: w.type,
    }));
  }

  if (action === "window_new") {
    const win = await chrome.windows.create({ url: arg || "about:blank" });
    return { ok: true, id: win.id };
  }

  if (action === "window_close") {
    const winId = parseInt(arg) || (await getActiveTab())?.windowId;
    if (winId) { await chrome.windows.remove(winId); return { ok: true }; }
    return { ok: false };
  }

  if (action === "window_focus") {
    const winId = parseInt(arg);
    if (winId) { await chrome.windows.update(winId, { focused: true }); return { ok: true }; }
    return { ok: false };
  }

  // ══════════════════════════════════════════════════════════════════
  // YOUTUBE
  // ══════════════════════════════════════════════════════════════════

  async function getYouTubeTab() {
    const active = await getActiveTab();
    if (active?.url?.includes("youtube.com")) return active;
    const tabs = await chrome.tabs.query({ url: "*://www.youtube.com/*" });
    if (tabs.length) {
      await chrome.tabs.update(tabs[0].id, { active: true });
      return tabs[0];
    }
    return null;
  }

  async function ytRun(func, args = []) {
    const tab = await getYouTubeTab();
    if (!tab) return { ok: false, error: "YouTube не открыт" };
    return await runInTab(tab.id, func, args) || { ok: false };
  }

  // Кнопка плеера по селектору: клик и ответ «сделано» / «not found».
  const ytClick = (sel, done) => ytRun((s, d) => {
    const b = document.querySelector(s);
    if (b) { b.click(); return d; }
    return "not found";
  }, [sel, done]);

  if (action === "youtube_pause") {
    return ytRun(() => {
      const v = document.querySelector("video");
      if (!v) return "no video";
      v.paused ? v.play() : v.pause();
      return v.paused ? "paused" : "playing";
    });
  }

  if (action === "youtube_next") {
    return ytClick(".ytp-next-button", "next");
  }

  if (action === "youtube_prev") {
    return ytRun(() => {
      const v = document.querySelector("video");
      if (v) { v.currentTime = 0; return "restart"; }
      return "no video";
    });
  }

  // Перемотка/позиция: mode = by (относительно) | to (абсолютно).
  const ytSeek = (mode, sec) => ytRun((m, s) => {
    const v = document.querySelector("video");
    if (!v) return "no video";
    if (m === "to") v.currentTime = s; else v.currentTime += s;
    return v.currentTime;
  }, [mode, sec]);

  if (action === "youtube_forward") {
    const sec = parseInt(arg) || 10;
    return ytSeek("by", sec);
  }

  if (action === "youtube_rewind") {
    const sec = parseInt(arg) || 10;
    return ytSeek("by", -sec);
  }

  if (action === "youtube_seek") {
    const sec = parseInt(arg) || 0;
    return ytSeek("to", sec);
  }

  if (action === "youtube_volume") {
    const vol = Math.max(0, Math.min(100, parseInt(arg) || 50)) / 100;
    return ytRun((x) => {
      const v = document.querySelector("video");
      if (v) { v.volume = x; v.muted = false; return Math.round(v.volume * 100); }
      return "no video";
    }, [vol]);
  }

  if (action === "youtube_mute") {
    return ytRun(() => {
      const v = document.querySelector("video");
      if (v) { v.muted = !v.muted; return v.muted ? "muted" : "unmuted"; }
      return "no video";
    });
  }

  if (action === "youtube_speed") {
    const rate = parseFloat(arg) || 1.0;
    return ytRun((r) => {
      const v = document.querySelector("video");
      if (v) { v.playbackRate = r; return r; }
      return "no video";
    }, [rate]);
  }

  if (action === "youtube_speed_up") {
    return ytRun(() => {
      const v = document.querySelector("video");
      if (v) { v.playbackRate = Math.min(v.playbackRate + 0.25, 2); return v.playbackRate; }
      return "no video";
    });
  }

  if (action === "youtube_speed_down") {
    return ytRun(() => {
      const v = document.querySelector("video");
      if (v) { v.playbackRate = Math.max(v.playbackRate - 0.25, 0.25); return v.playbackRate; }
      return "no video";
    });
  }

  if (action === "youtube_fullscreen") {
    return ytClick(".ytp-fullscreen-button", "fullscreen");
  }

  if (action === "youtube_theater") {
    return ytClick(".ytp-size-button", "theater");
  }

  if (action === "youtube_mini") {
    return ytClick(".ytp-miniplayer-button", "mini");
  }

  if (action === "youtube_sub_toggle") {
    return ytClick(".ytp-subtitles-button", "subtitles toggled");
  }

  if (action === "youtube_like") {
    return ytRun(() => {
      let b = document.querySelector('button[aria-label*="айк"]:not([aria-label*="исайк"])');
      if (!b) b = document.querySelector("#top-level-buttons-computed button:first-child");
      if (b) { b.click(); return "liked"; }
      return "not found";
    });
  }

  if (action === "youtube_dislike") {
    return ytClick('button[aria-label*="исайк"]', "disliked");
  }

  if (action === "youtube_subscribe") {
    return ytClick("button#subscribe-button, yt-button-shape#subscribe-button button", "subscribed");
  }

  if (action === "youtube_info") {
    return ytRun(() => {
      const v = document.querySelector("video");
      const title = document.querySelector("h1.ytd-watch-metadata yt-formatted-string");
      const ch = document.querySelector("#channel-name a");
      const desc = document.querySelector("#description-inline-expander");
      return {
        title: title ? title.textContent.trim() : null,
        channel: ch ? ch.textContent.trim() : null,
        description: desc ? desc.textContent.trim().slice(0, 500) : null,
        duration: v ? Math.round(v.duration) : 0,
        position: v ? Math.round(v.currentTime) : 0,
        paused: v ? v.paused : true,
        speed: v ? v.playbackRate : 1,
        url: location.href,
      };
    });
  }

  if (action === "youtube_comments") {
    return ytRun(() => {
      const comments = Array.from(document.querySelectorAll("#content-text")).slice(0, 10);
      return comments.map(c => c.textContent.trim().slice(0, 200));
    });
  }

  if (action === "youtube_playlist") {
    return ytRun(() => {
      const items = Array.from(document.querySelectorAll("ytd-playlist-video-renderer")).slice(0, 20);
      return items.map(i => {
        const title = i.querySelector("#video-title");
        const channel = i.querySelector("#channel-name a");
        return {
          title: title ? title.textContent.trim() : "",
          channel: channel ? channel.textContent.trim() : "",
        };
      });
    });
  }

  if (action === "youtube_search_results") {
    return ytRun(() => {
      const items = Array.from(document.querySelectorAll("ytd-video-renderer")).slice(0, 10);
      return items.map(i => {
        const title = i.querySelector("#video-title");
        const channel = i.querySelector("#channel-name a, .ytd-channel-name a");
        const meta = i.querySelector("#metadata-line");
        return {
          title: title ? title.textContent.trim() : "",
          url: title?.href || "",
          channel: channel ? channel.textContent.trim() : "",
          meta: meta ? meta.textContent.trim() : "",
        };
      });
    });
  }

  // ══════════════════════════════════════════════════════════════════
  // СКАЧИВАНИЯ
  // ══════════════════════════════════════════════════════════════════

  if (action === "downloads_list") {
    const items = await chrome.downloads.search({ limit: 20 });
    return { ok: true, downloads: items.map(d => ({
      filename: d.filename, state: d.state, url: d.url?.slice(0,100),
      totalBytes: d.totalBytes, bytesReceived: d.bytesReceived,
    }))};
  }

  if (action === "download_url") {
    await chrome.downloads.download({ url: arg });
    return { ok: true };
  }

  // ══════════════════════════════════════════════════════════════════
  // JS
  // ══════════════════════════════════════════════════════════════════

  if ((action === "js_exec" || action === "js_exec_url") && !ALLOW_JS_EXEC) {
    return { ok: false, error: "js_exec выключен в расширении (ALLOW_JS_EXEC = false)" };
  }

  if (action === "js_exec") {
    const tab = await getActiveTab();
    if (!tab) return { ok: false };
    return await execInTab(tab.id, arg) || { ok: true };
  }

  if (action === "js_exec_url") {
    // Выполнить JS на конкретном URL (найти вкладку по URL)
    const tab = await findTab(arg);
    if (!tab) return { ok: false, error: "Вкладка не найдена" };
    const code = msg.code || "";
    return await execInTab(tab.id, code) || { ok: true };
  }

  return { ok: false, error: `Неизвестная команда: ${action}` };
}

// ── Статус для popup ──────────────────────────────────────────────

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.type === "get_status") {
    sendResponse({ connected });
  }
  return true;
});

// ── Старт ──────────────────────────────────────────────────────────

// MV3 выгружает service worker через ~30с бездействия — вместе с ним
// умирают WS и цепочка setTimeout. chrome.alarms будит воркер и
// переподнимает соединение; connect() сам делает no-op если оно живо.
chrome.alarms.create("sakura-keepalive", { periodInMinutes: 0.5 });

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === "sakura-keepalive") {
    connect();
  }
});

// Все точки входа пробуждения воркера
chrome.runtime.onStartup.addListener(connect);
chrome.runtime.onInstalled.addListener(connect);
connect();   // холодный старт воркера
