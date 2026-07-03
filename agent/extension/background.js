/**
 * background.js — Service Worker (Manifest V3)
 *
 * Полное управление браузером для Сакуры:
 *   Вкладки, навигация, закладки, история, YouTube, формы, скриншоты,
 *   управление окнами, mute/pin, reader mode, и т.д.
 */

const WS_URL       = "ws://127.0.0.1:8766";
const RECONNECT_MS = 3000;

let ws        = null;
let connected = false;

// ── WebSocket ──────────────────────────────────────────────────────

function connect() {
  if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) {
    return;
  }
  try {
    ws = new WebSocket(WS_URL);
  } catch (e) {
    setTimeout(connect, RECONNECT_MS);
    return;
  }

  ws.onopen = () => {
    connected = true;
    console.log("[Sakura] Подключено к агенту");
    send({ type: "extension_ready", version: "3.0.0" });
  };

  ws.onmessage = async (event) => {
    let msg;
    try { msg = JSON.parse(event.data); } catch { return; }
    const result = await handleCommand(msg);
    if (result !== undefined) {
      send({ type: "extension_result", id: msg.id, action: msg.action, result });
    }
  };

  ws.onclose = () => {
    connected = false;
    console.log("[Sakura] Обрыв — реконнект через 3с");
    ws = null;
    setTimeout(connect, RECONNECT_MS);
  };

  ws.onerror = (e) => {
    console.log("[Sakura] Ошибка WS:", e.message);
    ws.close();
  };
}

function send(data) {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify(data));
  }
}

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
    const content = await execInTab(tab.id, `
      (function() {
        var body = document.body.cloneNode(true);
        body.querySelectorAll('script,style,noscript,svg,nav,header,footer,aside,iframe').forEach(e => e.remove());
        return (body.innerText || body.textContent || '').replace(/\\s+/g, ' ').trim().slice(0, 12000);
      })()
    `);
    return { ok: true, content: content || "", url: tab.url, title: tab.title };
  }

  if (action === "page_article") {
    // Reader mode — извлекает чистую статью
    const tab = await getActiveTab();
    if (!tab) return { ok: false };
    const content = await execInTab(tab.id, `
      (function() {
        // Ищем основной контент
        var article = document.querySelector('article') ||
                      document.querySelector('[role="main"]') ||
                      document.querySelector('.post-content') ||
                      document.querySelector('.article-content') ||
                      document.querySelector('.entry-content') ||
                      document.querySelector('.content') ||
                      document.querySelector('main');
        if (!article) {
          var body = document.body.cloneNode(true);
          body.querySelectorAll('script,style,noscript,svg,nav,header,footer,aside,iframe,form').forEach(e => e.remove());
          article = body;
        }
        var text = (article.innerText || article.textContent || '').replace(/\\s+/g, ' ').trim();
        // Извлекаем заголовок
        var h1 = document.querySelector('h1');
        var title = h1 ? h1.textContent.trim() : document.title;
        return { title: title, content: text.slice(0, 12000), url: location.href };
      })()
    `);
    return { ok: true, ...(content || {}) };
  }

  if (action === "page_links") {
    const tab = await getActiveTab();
    if (!tab) return { ok: false };
    const links = await execInTab(tab.id, `
      Array.from(document.querySelectorAll('a[href]')).slice(0, 50).map(a => ({
        text: a.textContent.trim().slice(0, 80),
        href: a.href,
      }))
    `);
    return { ok: true, links: links || [] };
  }

  if (action === "page_images") {
    const tab = await getActiveTab();
    if (!tab) return { ok: false };
    const images = await execInTab(tab.id, `
      Array.from(document.querySelectorAll('img[src]')).slice(0, 20).map(img => ({
        src: img.src,
        alt: img.alt?.slice(0, 80) || '',
        width: img.naturalWidth,
        height: img.naturalHeight,
      }))
    `);
    return { ok: true, images: images || [] };
  }

  if (action === "page_meta") {
    const tab = await getActiveTab();
    if (!tab) return { ok: false };
    const meta = await execInTab(tab.id, `
      (function() {
        var get = (n) => document.querySelector('meta[name="'+n+'"]')?.content ||
                         document.querySelector('meta[property="'+n+'"]')?.content || '';
        return {
          title: document.title,
          description: get('description') || get('og:description'),
          image: get('og:image'),
          url: location.href,
          author: get('author'),
          keywords: get('keywords'),
        };
      })()
    `);
    return { ok: true, ...(meta || {}) };
  }

  // ══════════════════════════════════════════════════════════════════
  // СТРАНИЦА — взаимодействие
  // ══════════════════════════════════════════════════════════════════

  if (action === "page_scroll") {
    const tab = await getActiveTab();
    if (!tab) return { ok: false };
    const dir = arg === "up" ? -500 : arg === "down" ? 500 : parseInt(arg) || 500;
    await execInTab(tab.id, `window.scrollBy(0, ${dir})`);
    return { ok: true };
  }

  if (action === "page_scroll_to") {
    const tab = await getActiveTab();
    if (!tab) return { ok: false };
    const pct = Math.max(0, Math.min(100, parseInt(arg) || 0));
    await execInTab(tab.id, `window.scrollTo(0, document.body.scrollHeight * ${pct} / 100)`);
    return { ok: true };
  }

  if (action === "page_click") {
    const tab = await getActiveTab();
    if (!tab) return { ok: false };
    const result = await execInTab(tab.id, `
      (function() {
        var all = document.querySelectorAll('a,button,[role="button"],input[type="submit"]');
        for (var i = 0; i < all.length; i++) {
          if (all[i].textContent.toLowerCase().includes('${arg.replace(/'/g, "\\'")}'.toLowerCase())) {
            all[i].scrollIntoView({block:'center'});
            all[i].click();
            return 'clicked: ' + all[i].textContent.trim().slice(0,40);
          }
        }
        return 'not found';
      })()
    `);
    return { ok: true, result };
  }

  if (action === "page_highlight") {
    const tab = await getActiveTab();
    if (!tab) return { ok: false };
    // Подсвечивает элемент — визуальная обратная связь
    await execInTab(tab.id, `
      (function() {
        var all = document.querySelectorAll('a,button,[role="button"],input,select,textarea,label');
        for (var i = 0; i < all.length; i++) {
          if (all[i].textContent.toLowerCase().includes('${arg.replace(/'/g, "\\'")}'.toLowerCase()) ||
              (all[i].placeholder && all[i].placeholder.toLowerCase().includes('${arg.replace(/'/g, "\\'")}'.toLowerCase()))) {
            all[i].scrollIntoView({block:'center', behavior:'smooth'});
            all[i].style.outline = '3px solid #ff69b4';
            all[i].style.outlineOffset = '2px';
            setTimeout(() => { all[i].style.outline = ''; all[i].style.outlineOffset = ''; }, 3000);
            return 'highlighted: ' + (all[i].textContent.trim().slice(0,40) || all[i].placeholder || all[i].tagName);
          }
        }
        return 'not found';
      })()
    `);
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
    const result = await execInTab(tab.id, `
      (function() {
        var label = '${label.replace(/'/g, "\\'")}';
        var value = '${value.replace(/'/g, "\\'")}';
        // Ищем по label
        var lbl = document.querySelector('label[for]');
        var inputs = document.querySelectorAll('input,textarea,select');
        for (var i = 0; i < inputs.length; i++) {
          var inp = inputs[i];
          var ph = (inp.placeholder || '').toLowerCase();
          var nm = (inp.name || '').toLowerCase();
          var id = (inp.id || '').toLowerCase();
          var lb = '';
          if (inp.id) { var l = document.querySelector('label[for="'+inp.id+'"]'); if (l) lb = l.textContent.toLowerCase(); }
          if (ph.includes(label.toLowerCase()) || nm.includes(label.toLowerCase()) ||
              id.includes(label.toLowerCase()) || lb.includes(label.toLowerCase())) {
            if (inp.tagName === 'SELECT') {
              for (var j = 0; j < inp.options.length; j++) {
                if (inp.options[j].text.toLowerCase().includes(value.toLowerCase())) {
                  inp.selectedIndex = j;
                  inp.dispatchEvent(new Event('change', {bubbles:true}));
                  return 'selected: ' + inp.options[j].text;
                }
              }
            } else {
              inp.focus();
              inp.value = value;
              inp.dispatchEvent(new Event('input', {bubbles:true}));
              inp.dispatchEvent(new Event('change', {bubbles:true}));
              return 'filled: ' + (inp.name || inp.id || inp.placeholder);
            }
          }
        }
        return 'input not found';
      })()
    `);
    return { ok: true, result };
  }

  if (action === "page_select") {
    const tab = await getActiveTab();
    if (!tab) return { ok: false };
    const result = await execInTab(tab.id, `
      (function() {
        var text = '${arg.replace(/'/g, "\\'")}';
        var selects = document.querySelectorAll('select');
        for (var s of selects) {
          for (var o of s.options) {
            if (o.text.toLowerCase().includes(text.toLowerCase())) {
              s.value = o.value;
              s.dispatchEvent(new Event('change', {bubbles:true}));
              return 'selected: ' + o.text;
            }
          }
        }
        return 'select not found';
      })()
    `);
    return { ok: true, result };
  }

  if (action === "page_submit") {
    const tab = await getActiveTab();
    if (!tab) return { ok: false };
    await execInTab(tab.id, `
      (function() {
        var form = document.activeElement?.form || document.querySelector('form');
        if (form) { form.submit(); return 'submitted'; }
        return 'no form';
      })()
    `);
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

  async function ytExec(code) {
    const tab = await getYouTubeTab();
    if (!tab) return { ok: false, error: "YouTube не открыт" };
    return await execInTab(tab.id, code) || { ok: false };
  }

  if (action === "youtube_pause") {
    return ytExec(`(function(){var v=document.querySelector('video');if(!v)return'no video';v.paused?v.play():v.pause();return v.paused?'paused':'playing';})()`);
  }

  if (action === "youtube_next") {
    return ytExec(`(function(){var b=document.querySelector('.ytp-next-button');if(b){b.click();return'next';}return 'not found';})()`);
  }

  if (action === "youtube_prev") {
    return ytExec(`(function(){var v=document.querySelector('video');if(v){v.currentTime=0;return'restart';}return'no video';})()`);
  }

  if (action === "youtube_forward") {
    const sec = parseInt(arg) || 10;
    return ytExec(`(function(){var v=document.querySelector('video');if(v){v.currentTime+=${sec};return v.currentTime;}return'no video';})()`);
  }

  if (action === "youtube_rewind") {
    const sec = parseInt(arg) || 10;
    return ytExec(`(function(){var v=document.querySelector('video');if(v){v.currentTime-=${sec};return v.currentTime;}return'no video';})()`);
  }

  if (action === "youtube_seek") {
    const sec = parseInt(arg) || 0;
    return ytExec(`(function(){var v=document.querySelector('video');if(v){v.currentTime=${sec};return v.currentTime;}return'no video';})()`);
  }

  if (action === "youtube_volume") {
    const vol = Math.max(0, Math.min(100, parseInt(arg) || 50)) / 100;
    return ytExec(`(function(){var v=document.querySelector('video');if(v){v.volume=${vol};v.muted=false;return Math.round(v.volume*100);}return'no video';})()`);
  }

  if (action === "youtube_mute") {
    return ytExec(`(function(){var v=document.querySelector('video');if(v){v.muted=!v.muted;return v.muted?'muted':'unmuted';}return'no video';})()`);
  }

  if (action === "youtube_speed") {
    const rate = parseFloat(arg) || 1.0;
    return ytExec(`(function(){var v=document.querySelector('video');if(v){v.playbackRate=${rate};return ${rate};}return'no video';})()`);
  }

  if (action === "youtube_speed_up") {
    return ytExec(`(function(){var v=document.querySelector('video');if(v){v.playbackRate=Math.min(v.playbackRate+0.25,2);return v.playbackRate;}return'no video';})()`);
  }

  if (action === "youtube_speed_down") {
    return ytExec(`(function(){var v=document.querySelector('video');if(v){v.playbackRate=Math.max(v.playbackRate-0.25,0.25);return v.playbackRate;}return'no video';})()`);
  }

  if (action === "youtube_fullscreen") {
    return ytExec(`(function(){var b=document.querySelector('.ytp-fullscreen-button');if(b){b.click();return'fullscreen';}return'not found';})()`);
  }

  if (action === "youtube_theater") {
    return ytExec(`(function(){var b=document.querySelector('.ytp-size-button');if(b){b.click();return'theater';}return'not found';})()`);
  }

  if (action === "youtube_mini") {
    return ytExec(`(function(){var b=document.querySelector('.ytp-miniplayer-button');if(b){b.click();return'mini';}return'not found';})()`);
  }

  if (action === "youtube_sub_toggle") {
    return ytExec(`(function(){var b=document.querySelector('.ytp-subtitles-button');if(b){b.click();return'subtitles toggled';}return'not found';})()`);
  }

  if (action === "youtube_like") {
    return ytExec(`(function(){
      var b=document.querySelector('button[aria-label*="айк"]:not([aria-label*="исайк"])');
      if(!b) b=document.querySelector('#top-level-buttons-computed button:first-child');
      if(b){b.click();return'liked';}return'not found';
    })()`);
  }

  if (action === "youtube_dislike") {
    return ytExec(`(function(){
      var b=document.querySelector('button[aria-label*="исайк"]');
      if(b){b.click();return'disliked';}return'not found';
    })()`);
  }

  if (action === "youtube_subscribe") {
    return ytExec(`(function(){
      var b=document.querySelector('button#subscribe-button, yt-button-shape#subscribe-button button');
      if(b){b.click();return'subscribed';}return'not found';
    })()`);
  }

  if (action === "youtube_info") {
    return ytExec(`(function(){
      var v=document.querySelector('video');
      var title=document.querySelector('h1.ytd-watch-metadata yt-formatted-string');
      var ch=document.querySelector('#channel-name a');
      var desc=document.querySelector('#description-inline-expander');
      return {
        title: title?title.textContent.trim():null,
        channel: ch?ch.textContent.trim():null,
        description: desc?desc.textContent.trim().slice(0,500):null,
        duration: v?Math.round(v.duration):0,
        position: v?Math.round(v.currentTime):0,
        paused: v?v.paused:true,
        speed: v?v.playbackRate:1,
        url: location.href,
      };
    })()`);
  }

  if (action === "youtube_comments") {
    return ytExec(`(function(){
      var comments = Array.from(document.querySelectorAll('#content-text')).slice(0,10);
      return comments.map(c => c.textContent.trim().slice(0,200));
    })()`);
  }

  if (action === "youtube_playlist") {
    return ytExec(`(function(){
      var items = Array.from(document.querySelectorAll('ytd-playlist-video-renderer')).slice(0,20);
      return items.map(i => {
        var title = i.querySelector('#video-title');
        var channel = i.querySelector('#channel-name a');
        return {
          title: title?title.textContent.trim():'',
          channel: channel?channel.textContent.trim():'',
        };
      });
    })()`);
  }

  if (action === "youtube_search_results") {
    return ytExec(`(function(){
      var items = Array.from(document.querySelectorAll('ytd-video-renderer')).slice(0,10);
      return items.map(i => {
        var title = i.querySelector('#video-title');
        var channel = i.querySelector('#channel-name a, .ytd-channel-name a');
        var meta = i.querySelector('#metadata-line');
        return {
          title: title?title.textContent.trim():'',
          url: title?.href || '',
          channel: channel?channel.textContent.trim():'',
          meta: meta?meta.textContent.trim():'',
        };
      });
    })()`);
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
connect();
