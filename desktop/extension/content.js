/**
 * content.js — полный контроль DOM страницы.
 *
 * Инжектируется во все кадры страницы (all_frames). Две части:
 *   1. handlePageAction — старые действия по сообщению page_action (без изменений);
 *   2. globalThis.__sakuraAgent — агент браузера (page.*): снимок с ref, действия
 *      по ref, формы, вопросы, пакетное заполнение, загрузка файла, разметка кадра.
 *      background.js вызывает его через chrome.scripting.executeScript({func, args})
 *      в том же изолированном мире — без eval и без сборки кода строкой.
 *
 * Состояние агента — только карта ref последнего снимка этого кадра (S).
 * ref здесь локальный («e12»); префикс кадра «f<frameId>:» добавляет background.
 * Текст страниц и значения полей не логируются.
 */

(function (root) {
  if (root.__sakuraAgent) return;  // повторная инъекция (executeScript files) — no-op

  // ════════════════════════════════════════════════════════════════
  // 1. Старые действия (page_action)
  // ════════════════════════════════════════════════════════════════

  function handlePageAction(action, arg) {
    // ── Текст ──────────────────────────────────────────────────────

    if (action === "get_text") {
      const body = document.body.cloneNode(true);
      body.querySelectorAll("script,style,noscript,svg,nav,header,footer,aside,iframe").forEach(e => e.remove());
      return (body.innerText || body.textContent || "").replace(/\s+/g, " ").trim().slice(0, 12000);
    }

    if (action === "get_article") {
      const article = document.querySelector("article") ||
                      document.querySelector('[role="main"]') ||
                      document.querySelector(".post-content") ||
                      document.querySelector(".article-content") ||
                      document.querySelector("main");
      if (article) {
        return article.innerText.replace(/\s+/g, " ").trim().slice(0, 12000);
      }
      return handlePageAction("get_text");
    }

    if (action === "get_title") {
      const h1 = document.querySelector("h1");
      return h1 ? h1.textContent.trim() : document.title;
    }

    if (action === "get_url") {
      return location.href;
    }

    if (action === "get_selection") {
      const sel = window.getSelection();
      return sel ? sel.toString().trim() : "";
    }

    // ── Ссылки ─────────────────────────────────────────────────────

    if (action === "get_links") {
      return Array.from(document.querySelectorAll("a[href]"))
        .slice(0, 50)
        .map(a => ({ text: a.textContent.trim().slice(0, 80), href: a.href }));
    }

    if (action === "get_visible_links") {
      return Array.from(document.querySelectorAll("a[href]"))
        .filter(a => {
          const rect = a.getBoundingClientRect();
          return rect.top < window.innerHeight && rect.bottom > 0;
        })
        .slice(0, 30)
        .map(a => ({ text: a.textContent.trim().slice(0, 80), href: a.href }));
    }

    // ── Изображения ────────────────────────────────────────────────

    if (action === "get_images") {
      return Array.from(document.querySelectorAll("img[src]"))
        .slice(0, 20)
        .map(img => ({
          src: img.src,
          alt: (img.alt || "").slice(0, 80),
          width: img.naturalWidth,
          height: img.naturalHeight,
        }));
    }

    // ── Мета-данные ────────────────────────────────────────────────

    if (action === "get_meta") {
      const get = (n) => document.querySelector(`meta[name="${n}"]`)?.content ||
                         document.querySelector(`meta[property="${n}"]`)?.content || "";
      return {
        title: document.title,
        description: get("description") || get("og:description"),
        image: get("og:image"),
        url: location.href,
        author: get("author"),
        keywords: get("keywords"),
        og_type: get("og:type"),
      };
    }

    // ── Навигация по DOM ───────────────────────────────────────────

    if (action === "scroll_down") {
      window.scrollBy(0, 500);
      return "scrolled down";
    }

    if (action === "scroll_up") {
      window.scrollBy(0, -500);
      return "scrolled up";
    }

    if (action === "scroll_to") {
      const pct = Math.max(0, Math.min(100, parseInt(arg) || 0));
      window.scrollTo(0, document.body.scrollHeight * pct / 100);
      return `scrolled to ${pct}%`;
    }

    if (action === "scroll_to_element") {
      const el = document.querySelector(arg);
      if (el) {
        el.scrollIntoView({ block: "center", behavior: "smooth" });
        return "scrolled to " + arg;
      }
      return "element not found";
    }

    if (action === "scroll_bottom") {
      window.scrollTo(0, document.body.scrollHeight);
      return "scrolled to bottom";
    }

    if (action === "scroll_top") {
      window.scrollTo(0, 0);
      return "scrolled to top";
    }

    // ── Клики и взаимодействие ─────────────────────────────────────

    if (action === "click_text") {
      const all = document.querySelectorAll("a,button,[role='button'],input[type='submit'],label");
      for (const el of all) {
        if (el.textContent.toLowerCase().includes(arg.toLowerCase())) {
          el.scrollIntoView({ block: "center", behavior: "smooth" });
          el.click();
          return `clicked: ${el.textContent.trim().slice(0, 40)}`;
        }
      }
      return "element not found";
    }

    if (action === "click_selector") {
      const el = document.querySelector(arg);
      if (el) {
        el.scrollIntoView({ block: "center", behavior: "smooth" });
        el.click();
        return `clicked: ${arg}`;
      }
      return "selector not found";
    }

    if (action === "highlight") {
      const all = document.querySelectorAll("a,button,input,textarea,select,label,[role='button']");
      for (const el of all) {
        const text = (el.textContent + " " + (el.placeholder || "") + " " + (el.name || "")).toLowerCase();
        if (text.includes(arg.toLowerCase())) {
          el.scrollIntoView({ block: "center", behavior: "smooth" });
          el.style.outline = "3px solid #ff69b4";
          el.style.outlineOffset = "2px";
          el.style.transition = "outline 0.3s";
          setTimeout(() => { el.style.outline = ""; el.style.outlineOffset = ""; }, 3000);
          return `highlighted: ${el.textContent.trim().slice(0, 40) || el.tagName}`;
        }
      }
      return "not found";
    }

    // ── Формы ──────────────────────────────────────────────────────

    if (action === "fill_field") {
      const parts = arg.split("|");
      if (parts.length < 2) return "format: label|value";
      const label = parts[0].trim().toLowerCase();
      const value = parts.slice(1).join("|").trim();

      const inputs = document.querySelectorAll("input,textarea,select");
      for (const inp of inputs) {
        const search = [
          inp.placeholder, inp.name, inp.id, inp.getAttribute("aria-label"),
          inp.closest("label")?.textContent,
          document.querySelector(`label[for="${inp.id}"]`)?.textContent,
        ].filter(Boolean).join(" ").toLowerCase();

        if (search.includes(label)) {
          if (inp.tagName === "SELECT") {
            for (const opt of inp.options) {
              if (opt.text.toLowerCase().includes(value.toLowerCase())) {
                inp.value = opt.value;
                inp.dispatchEvent(new Event("change", { bubbles: true }));
                return `selected: ${opt.text}`;
              }
            }
            return "option not found";
          }
          inp.focus();
          inp.value = value;
          inp.dispatchEvent(new Event("input", { bubbles: true }));
          inp.dispatchEvent(new Event("change", { bubbles: true }));
          return `filled: ${inp.name || inp.id || inp.placeholder}`;
        }
      }
      return "input not found";
    }

    if (action === "select_option") {
      const selects = document.querySelectorAll("select");
      for (const s of selects) {
        for (const o of s.options) {
          if (o.text.toLowerCase().includes(arg.toLowerCase())) {
            s.value = o.value;
            s.dispatchEvent(new Event("change", { bubbles: true }));
            return `selected: ${o.text}`;
          }
        }
      }
      return "select not found";
    }

    if (action === "submit_form") {
      const form = document.activeElement?.form || document.querySelector("form");
      if (form) { form.submit(); return "submitted"; }
      return "no form";
    }

    if (action === "get_forms") {
      const forms = document.querySelectorAll("form");
      return Array.from(forms).map((f, i) => ({
        index: i,
        action: f.action,
        method: f.method,
        inputs: Array.from(f.querySelectorAll("input,textarea,select")).map(inp => ({
          type: inp.type || inp.tagName.toLowerCase(),
          name: inp.name,
          placeholder: inp.placeholder,
          id: inp.id,
        })),
      }));
    }

    // ── Видео ──────────────────────────────────────────────────────

    if (action === "get_video_info") {
      const v = document.querySelector("video");
      if (!v) return null;
      return {
        paused: v.paused,
        duration: Math.round(v.duration),
        position: Math.round(v.currentTime),
        volume: Math.round(v.volume * 100),
        speed: v.playbackRate,
        muted: v.muted,
        src: v.src?.slice(0, 200),
      };
    }

    if (action === "video_control") {
      const v = document.querySelector("video");
      if (!v) return "no video";
      const [cmd, val] = arg.split(":");
      switch (cmd) {
        case "play": v.play(); return "playing";
        case "pause": v.pause(); return "paused";
        case "toggle": v.paused ? v.play() : v.pause(); return v.paused ? "paused" : "playing";
        case "seek": v.currentTime = parseInt(val) || 0; return `seeked to ${v.currentTime}`;
        case "volume": v.volume = Math.max(0, Math.min(100, parseInt(val) || 50)) / 100; return `volume ${Math.round(v.volume * 100)}`;
        case "speed": v.playbackRate = parseFloat(val) || 1; return `speed ${v.playbackRate}`;
        case "mute": v.muted = !v.muted; return v.muted ? "muted" : "unmuted";
      }
      return "unknown video command";
    }

    // ── Клонирование / парсинг ─────────────────────────────────────

    if (action === "get_table") {
      const table = document.querySelector("table");
      if (!table) return null;
      const rows = Array.from(table.querySelectorAll("tr"));
      return rows.slice(0, 30).map(r =>
        Array.from(r.querySelectorAll("td,th")).map(c => c.textContent.trim().slice(0, 60))
      );
    }

    if (action === "get_structured") {
      // Структурированное содержимое: заголовки, параграфы, списки
      const content = [];
      const elements = document.querySelectorAll("h1,h2,h3,h4,p,li,blockquote,pre");
      for (const el of elements) {
        const tag = el.tagName.toLowerCase();
        const text = el.textContent.trim().slice(0, 200);
        if (text) content.push({ tag, text });
        if (content.length >= 50) break;
      }
      return content;
    }

    return null;
  }

  // ════════════════════════════════════════════════════════════════
  // 2. Агент браузера (page.*)
  // ════════════════════════════════════════════════════════════════

  // Интерактивные элементы снимка (E2).
  const INTERACTIVE = [
    "a", "button", "input:not([type=hidden])", "select", "textarea", "summary",
    "[contenteditable='']", "[contenteditable='true']", "[contenteditable='plaintext-only']", "[onclick]",
    "[role=button]", "[role=link]", "[role=tab]", "[role=menuitem]", "[role=checkbox]",
    "[role=radio]", "[role=option]", "[role=combobox]",
  ].join(",");
  // Поля форм (E4).
  const FIELD_SEL = [
    "input:not([type=hidden]):not([type=submit]):not([type=button]):not([type=reset]):not([type=image])",
    "select", "textarea", "[contenteditable='']", "[contenteditable='true']",
    "[role=combobox]:not(input):not(select)", "[role=textbox]:not(input):not(textarea)",
  ].join(",");
  const SUBMIT_SEL = "button:not([type]), button[type=submit], input[type=submit], input[type=image]";
  const SUBMIT_RX = /отправ|submit|далее|next|сохран|save|войти|log ?in|sign ?in|продолж|continue|готово|finish|заверш|send|регистр|register|оформ|ответ/i;
  const CAPTCHA_RX = /recaptcha|hcaptcha|challenges\.cloudflare\.com|turnstile|smartcaptcha|smart-captcha|showcaptcha|captcha-api\.yandex/i;
  const INPUT_ROLES = {
    checkbox: "checkbox", radio: "radio", submit: "button", button: "button", reset: "button",
    image: "button", range: "slider", number: "spinbutton", search: "searchbox", file: "file",
  };
  const TEXT_TYPES = new Set(["", "text", "search", "email", "url", "tel", "password", "number",
    "date", "time", "datetime-local", "month", "week", "color"]);
  const MAX_CHANGED = 80;

  // Состояние кадра: карта ref последнего снимка. Больше ничего не хранится.
  const S = {
    snap: null,            // snapshot_id последнего page.observe
    byRef: new Map(),      // ref → элемент (только текущий снимок)
    refOf: new WeakMap(),  // элемент → ref (стабилен между снимками: дифф changed)
    n: 0,
    prev: null,            // ref → {sig, role, name} прошлого снимка
    touched: new WeakSet(),// поля, заполненные агентом (показывать ошибки валидации)
  };

  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const norm = (s) => String(s == null ? "" : s).replace(/\s+/g, " ").trim();
  const lower = (s) => norm(s).toLowerCase();
  const cut = (s, n) => { s = norm(s); return s.length > n ? s.slice(0, n - 1) + "…" : s; };

  function rawText(el) {
    const t = typeof el.innerText === "string" ? el.innerText : el.textContent;
    return String(t || "");
  }
  const textOf = (el) => norm(rawText(el));

  function tagOf(el) { return (el.tagName || "").toLowerCase(); }
  function typeOf(el) { return tagOf(el) === "input" ? String(el.type || "text").toLowerCase() : ""; }
  function isEditable(el) {
    const ce = el.getAttribute && el.getAttribute("contenteditable");
    return ce === "" || ce === "true" || ce === "plaintext-only";
  }
  function isTextInput(el) {
    const tag = tagOf(el);
    return tag === "textarea" || (tag === "input" && TEXT_TYPES.has(typeOf(el)));
  }
  function isToggle(el) { const t = typeOf(el); return t === "checkbox" || t === "radio"; }
  function isSensitive(el) {
    const ac = String(el.getAttribute && el.getAttribute("autocomplete") || "").toLowerCase();
    return typeOf(el) === "password" || ac.startsWith("cc-") || ac.includes("password") || ac === "one-time-code";
  }
  function isPayment(el) {
    const ac = String(el.getAttribute && el.getAttribute("autocomplete") || "").toLowerCase();
    const hint = lower([el.name, el.id, el.getAttribute && el.getAttribute("placeholder")].join(" "));
    return ac.startsWith("cc-") || /\b(card ?number|cardnumber|cvv|cvc|cc-?num)\b/.test(hint);
  }

  // Все элементы по селектору, включая открытые shadow root.
  function deepAll(sel, rootNode) {
    const out = [];
    const walk = (r) => {
      r.querySelectorAll(sel).forEach((el) => out.push(el));
      r.querySelectorAll("*").forEach((el) => { if (el.shadowRoot) walk(el.shadowRoot); });
    };
    walk(rootNode || document);
    return out;
  }

  function parentOf(n) {
    if (n.parentElement) return n.parentElement;
    const r = n.getRootNode && n.getRootNode();
    return r && r.host ? r.host : null;
  }

  // Видим ли элемент: не скрыт display/visibility/hidden у себя и предков, имеет размер.
  function shown(el, cache) {
    for (let n = el; n && n.nodeType === 1; n = parentOf(n)) {
      if (cache && cache.has(n)) { if (!cache.get(n)) return false; break; }
      let ok = !n.hidden;
      if (ok) {
        const st = getComputedStyle(n);
        ok = st.display !== "none" && !(n === el && (st.visibility === "hidden" || st.visibility === "collapse"));
      }
      if (cache && n !== el) cache.set(n, ok);
      if (!ok) return false;
    }
    return true;
  }
  function visible(el, cache) {
    if (!shown(el, cache)) return false;
    const r = el.getBoundingClientRect();
    return r.width >= 1 || r.height >= 1 || isToggle(el);
  }

  function rectOf(el) {
    const r = el.getBoundingClientRect();
    return [Math.round(r.left), Math.round(r.top), Math.round(r.width), Math.round(r.height)];
  }
  function inViewport(el) {
    const r = el.getBoundingClientRect();
    return r.bottom > 0 && r.right > 0 && r.top < window.innerHeight && r.left < window.innerWidth;
  }

  function roleOf(el) {
    const r = String(el.getAttribute("role") || "").trim().split(/\s+/)[0];
    if (r) return r;
    const tag = tagOf(el);
    if (tag === "a") return "link";
    if (tag === "button" || tag === "summary") return "button";
    if (tag === "select") return el.multiple || el.size > 1 ? "listbox" : "combobox";
    if (tag === "textarea") return "textbox";
    if (tag === "input") return INPUT_ROLES[typeOf(el)] || "textbox";
    if (isEditable(el)) return "textbox";
    return "button";
  }

  function labelFor(el) {
    if (el.labels && el.labels.length) return Array.from(el.labels).map(textOf).join(" ");
    if (el.id) {
      const l = Array.from(document.querySelectorAll("label")).find((x) => x.htmlFor === el.id);
      if (l) return textOf(l);
    }
    const wrap = el.closest && el.closest("label");
    return wrap ? textOf(wrap) : "";
  }

  // Доступное имя: aria-label → aria-labelledby → label → placeholder → текст → title/alt/name.
  function nameOf(el) {
    const al = el.getAttribute("aria-label");
    if (norm(al)) return cut(al, 150);
    const lb = el.getAttribute("aria-labelledby");
    if (lb) {
      const t = lb.split(/\s+/).map((id) => {
        const n = (el.getRootNode && el.getRootNode().getElementById ? el.getRootNode() : document).getElementById(id);
        return n ? textOf(n) : "";
      }).join(" ");
      if (norm(t)) return cut(t, 150);
    }
    const tag = tagOf(el);
    if (["input", "select", "textarea"].includes(tag)) {
      const l = labelFor(el);
      if (norm(l)) return cut(l, 150);
    }
    const ph = el.getAttribute("placeholder");
    if (norm(ph)) return cut(ph, 150);
    if (tag === "input" && ["submit", "button", "reset"].includes(typeOf(el))) return cut(el.value, 150);
    if (tag !== "select" && tag !== "textarea" && tag !== "input") {
      const t = textOf(el);
      if (t) return cut(t, 150);
      const img = el.querySelector && el.querySelector("img[alt]");
      if (img && norm(img.alt)) return cut(img.alt, 150);
    }
    return cut(el.getAttribute("title") || el.getAttribute("alt") || el.getAttribute("name") || "", 150);
  }

  function valueOf(el) {
    const tag = tagOf(el);
    if (tag === "select") {
      return cut(Array.from(el.selectedOptions || []).map((o) => textOf(o) || o.value).join("; "), 200);
    }
    if (tag === "input") {
      const t = typeOf(el);
      if (t === "checkbox" || t === "radio") return undefined;
      if (t === "file") return cut(Array.from(el.files || []).map((f) => f.name).join("; "), 200);
      if (isSensitive(el)) return el.value ? "••••" : "";
      return cut(el.value, 200);
    }
    if (tag === "textarea") return cut(el.value, 200);
    if (isEditable(el)) return cut(textOf(el), 200);
    return undefined;
  }

  function checkedOf(el) {
    if (isToggle(el)) return !!el.checked;
    const ac = el.getAttribute("aria-checked");
    if (ac === "true" || ac === "mixed") return true;
    if (ac === "false") return false;
    const as = el.getAttribute("aria-selected");
    if (as === "true") return true;
    if (as === "false") return false;
    if (tagOf(el) === "option") return !!el.selected;
    return undefined;
  }

  function enabledOf(el) {
    return !el.disabled && el.getAttribute("aria-disabled") !== "true" && !(el.closest && el.closest("fieldset[disabled]"));
  }

  function describe(el) {
    const d = { role: roleOf(el), name: nameOf(el) };
    const tag = tagOf(el);
    // Поля ввода: тип (сервер отличает пароль и submit) и ошибка валидации тем же поиском, что в page.forms.
    if (tag === "input" || tag === "textarea" || tag === "select") {
      d.type = tag === "input" ? typeOf(el) : tag === "select" ? (el.multiple ? "select-multiple" : "select") : "textarea";
      const err = fieldError(el);
      if (err || el.getAttribute("aria-invalid") === "true" || userInvalid(el)) {
        d.invalid = true;
        if (err) d.error = cut(err, 200);
      }
    }
    const v = valueOf(el);
    if (v !== undefined) d.value = v;
    d.enabled = enabledOf(el);
    const c = checkedOf(el);
    if (c !== undefined) d.checked = c;
    d.in_viewport = inViewport(el);
    d.bbox = rectOf(el);
    return d;
  }

  function refFor(el) {
    let r = S.refOf.get(el);
    if (!r) { r = "e" + (++S.n); S.refOf.set(el, r); }
    S.byRef.set(r, el);
    return r;
  }

  function resolve(snapshotId, ref) {
    if (!snapshotId || snapshotId !== S.snap) return null;
    const el = S.byRef.get(ref);
    return el && el.isConnected ? el : null;
  }

  const sig = (e) => JSON.stringify([e.role, e.name, e.value, e.enabled, e.checked, e.invalid, e.error]);

  function pageText(limit) {
    if (!document.body) return "";
    const t = rawText(document.body)
      .replace(/[ \t ]+/g, " ").replace(/ *\n */g, "\n").replace(/\n{2,}/g, "\n").trim();
    return t.length > limit ? t.slice(0, limit) : t;
  }

  function parseClock(s) {
    const p = s.split(":").map((x) => parseInt(x, 10));
    if (p.some((x) => Number.isNaN(x))) return undefined;
    return p.reduce((acc, x) => acc * 60 + x, 0);
  }

  // Обратный отсчёт: элементы-таймеры (Moodle #quiz-time-left, *timer*, *countdown*) или «Осталось 12:34».
  function findTimer() {
    const CLOCK = /(\d{1,2}:)?\d{1,2}:\d{2}/;
    const cands = deepAll('[role=timer], [id*=timer], [class*=timer], [id*=Timer], [class*=Timer], ' +
      '[id*=countdown], [class*=countdown], [id*=time-left], [class*=time-left], [id*=timeleft], ' +
      '[class*=timeleft], [data-timer]');
    for (const el of cands) {
      if (!shown(el)) continue;
      const t = textOf(el);
      const m = t.match(CLOCK);
      if (m) return { text: cut(t, 80), seconds_left: parseClock(m[0]) };
    }
    const body = pageText(20000);
    const m = body.match(/(осталось|оставшееся время|до конца|time left|remaining)[^\d\n]{0,30}((\d{1,2}:)?\d{1,2}:\d{2})/i);
    if (m) return { text: cut(m[0], 80), seconds_left: parseClock(m[2]) };
    const mm = body.match(/(осталось|time left|remaining)[^\d\n]{0,20}(\d{1,3})\s*(мин|min)/i);
    if (mm) return { text: cut(mm[0], 80), seconds_left: parseInt(mm[2], 10) * 60 };
    return undefined;
  }

  function captchaDetected() {
    if (CAPTCHA_RX.test(location.href)) return true;
    const widgets = deepAll(".g-recaptcha, .h-captcha, .cf-turnstile, .smart-captcha, [data-smartcaptcha], " +
      "iframe[src*=captcha], iframe[src*=turnstile], iframe[title*=captcha], iframe[title*=CAPTCHA]");
    for (const el of widgets) {
      if (el.classList && el.classList.contains("grecaptcha-badge")) continue;  // невидимая v3
      if (tagOf(el) === "iframe" && !CAPTCHA_RX.test(el.src || "") && !/captcha/i.test(el.title || "")) continue;
      if (!shown(el)) continue;
      const r = el.getBoundingClientRect();
      if (r.width >= 30 || r.height >= 30) return true;
    }
    return false;
  }

  function mediaFlags() {
    const big = (el) => { const r = el.getBoundingClientRect(); return shown(el) && r.width >= 50 && r.height >= 50; };
    return {
      has_canvas: deepAll("canvas").some(big),
      has_video: deepAll("video").some(big),
    };
  }

  function iframesInfo() {
    let crossOrigin = 0;
    const list = [];
    for (const f of document.querySelectorAll("iframe, frame")) {
      let doc = null;
      try { doc = f.contentDocument; } catch (_) { doc = null; }
      if (!doc) crossOrigin += 1;
      if (!shown(f)) continue;
      list.push({ src: f.src || "about:blank", bbox: rectOf(f) });
    }
    return { cross_origin_frames: crossOrigin, iframes: list };
  }

  // ── page.observe ───────────────────────────────────────────────
  function observe(a) {
    const max = Math.max(1, Number(a.max_elements) || 300);
    const textLimit = Math.max(0, Number(a.text_limit) || 8000);
    const cache = new Map();
    let items = deepAll(INTERACTIVE).filter((el) => visible(el, cache)).map((el) => ({ el, d: describe(el) }));
    const total = items.length;
    if (items.length > max) {
      // Сначала видимые в окне, затем остальные — в порядке документа.
      const keep = new Set(items.filter((i) => i.d.in_viewport).concat(items.filter((i) => !i.d.in_viewport)).slice(0, max));
      items = items.filter((i) => keep.has(i));
    }
    S.snap = a.snapshot_id;
    const prevRefs = S.byRef;
    S.byRef = new Map();
    const elements = items.map(({ el, d }) => Object.assign({ ref: refFor(el) }, d));
    // Ссылки из page.forms / page.questions (блок вопроса, варианты) действуют и в следующих снимках,
    // пока элемент на странице: сервер просит кадр вопроса по его ref уже после нового page_observe.
    for (const [ref, el] of prevRefs) if (!S.byRef.has(ref) && el.isConnected) S.byRef.set(ref, el);

    const now = new Map(elements.map((e) => [e.ref, { sig: sig(e), role: e.role, name: e.name }]));
    let changed;
    if (S.prev) {
      changed = [];
      for (const e of elements) {
        const p = S.prev.get(e.ref);
        if (!p || p.sig !== now.get(e.ref).sig) {
          const c = { ref: e.ref, change: p ? "changed" : "added", role: e.role, name: e.name };
          if (e.value !== undefined) c.value = e.value;
          if (e.checked !== undefined) c.checked = e.checked;
          changed.push(c);
        }
      }
      for (const [ref, p] of S.prev) {
        if (!now.has(ref)) changed.push({ ref, change: "removed", role: p.role, name: p.name });
      }
      changed = changed.slice(0, MAX_CHANGED);
    }
    S.prev = now;

    const fr = iframesInfo();
    const out = {
      href: location.href, title: document.title, is_top: window.top === window,
      viewport: { w: window.innerWidth, h: window.innerHeight, dpr: window.devicePixelRatio || 1 },
      elements, total, text: pageText(textLimit),
      has_canvas: false, has_video: false,
      cross_origin_frames: fr.cross_origin_frames, captcha_detected: captchaDetected(), iframes: fr.iframes,
    };
    Object.assign(out, mediaFlags());
    if (changed) out.changed = changed;
    const timer = findTimer();
    if (timer) out.timer = timer;
    return out;
  }

  // ── события ────────────────────────────────────────────────────
  const PE = typeof PointerEvent === "function" ? PointerEvent : MouseEvent;

  function center(el) {
    const r = el.getBoundingClientRect();
    return { clientX: r.left + r.width / 2, clientY: r.top + r.height / 2 };
  }
  function fire(el, type, Ctor, init) {
    const C = Ctor || Event;
    return el.dispatchEvent(new C(type, Object.assign({ bubbles: true, cancelable: true, composed: true }, init || {})));
  }
  function scrollTo(el) {
    try { el.scrollIntoView({ block: "center", inline: "nearest" }); } catch (_) { /* jsdom */ }
  }
  function focusEl(el) {
    try { el.focus({ preventScroll: true }); } catch (_) { /* не фокусируется */ }
  }
  function clickEl(el) {
    scrollTo(el);
    const c = center(el);
    fire(el, "pointerdown", PE, c); fire(el, "mousedown", MouseEvent, c);
    focusEl(el);
    fire(el, "pointerup", PE, c); fire(el, "mouseup", MouseEvent, c);
    el.click();
  }
  function hoverEl(el) {
    const c = center(el);
    fire(el, "pointerover", PE, c); fire(el, "mouseover", MouseEvent, c);
    fire(el, "pointerenter", PE, Object.assign({ bubbles: false }, c));
    fire(el, "mouseenter", MouseEvent, Object.assign({ bubbles: false }, c));
    fire(el, "pointermove", PE, c); fire(el, "mousemove", MouseEvent, c);
  }

  // Нативный сеттер value: React (controlled input) отслеживает значение через свой
  // сеттер на экземпляре — прямое присваивание обновило бы и его, и onChange не сработал бы.
  function setNativeValue(el, value) {
    const proto = tagOf(el) === "textarea" ? HTMLTextAreaElement.prototype
      : tagOf(el) === "select" ? HTMLSelectElement.prototype : HTMLInputElement.prototype;
    const desc = Object.getOwnPropertyDescriptor(proto, "value");
    if (desc && desc.set) desc.set.call(el, value); else el.value = value;
  }
  function inputEvent(el, data) {
    const IE = typeof InputEvent === "function" ? InputEvent : Event;
    fire(el, "input", IE, { inputType: "insertText", data: data == null ? null : String(data), cancelable: false });
  }
  function blurEl(el) {
    if (typeof el.blur === "function" && document.activeElement === el) el.blur();
    else { fire(el, "blur", FocusEvent, { bubbles: false }); fire(el, "focusout", FocusEvent); }
  }

  function setText(el, value) {
    const v = value == null ? "" : String(value);
    focusEl(el);
    if (isEditable(el)) {
      let done = false;
      try {
        const sel = window.getSelection && window.getSelection();
        if (sel && document.createRange) {
          const r = document.createRange(); r.selectNodeContents(el); sel.removeAllRanges(); sel.addRange(r);
        }
        if (typeof document.execCommand === "function") done = document.execCommand("insertText", false, v);
      } catch (_) { done = false; }
      if (!done || rawText(el).trim() !== v.trim()) { el.textContent = v; inputEvent(el, v); }
    } else {
      setNativeValue(el, v);
      inputEvent(el, v);
      fire(el, "change");
    }
    blurEl(el);
    S.touched.add(el);
    return { status: "done", detail: "заполнено" };
  }

  function matchBy(list, want, textFn) {
    const w = lower(want);
    if (!w) return null;
    const t = list.map((o) => [o, lower(textFn(o))]);
    const hit = t.find(([, x]) => x === w) || t.find(([, x]) => x.startsWith(w)) || t.find(([, x]) => x && x.includes(w));
    return hit ? hit[0] : null;
  }

  function selectNative(sel, want) {
    const opts = Array.from(sel.options);
    const wants = Array.isArray(want) ? want : [want];
    if (sel.multiple) {
      const picked = wants.map((w) => matchBy(opts, w, (o) => textOf(o) || o.label) || opts.find((o) => o.value === String(w)));
      if (picked.some((p) => !p)) return { status: "not_found", detail: "нет такого варианта" };
      for (const o of opts) o.selected = picked.includes(o);
    } else {
      const o = matchBy(opts, wants[0], (x) => textOf(x) || x.label) || opts.find((x) => x.value === String(wants[0]));
      if (!o) return { status: "not_found", detail: "нет такого варианта" };
      setNativeValue(sel, o.value);
      o.selected = true;
    }
    focusEl(sel);
    inputEvent(sel, null);
    fire(sel, "change");
    blurEl(sel);
    S.touched.add(sel);
    return { status: "done", detail: "выбрано" };
  }

  const BOOL = { true: true, false: false, on: true, off: false, "1": true, "0": false, "да": true, "нет": false,
    yes: true, no: false, checked: true, unchecked: false };
  const boolish = (v) => (typeof v === "boolean" ? v : BOOL[lower(v)]);

  function setChecked(el, want) {
    const cur = checkedOf(el);
    if (cur === want) return { status: "done", detail: "уже так" };
    if (!want && (typeOf(el) === "radio" || roleOf(el) === "radio")) {
      return { status: "unsupported", detail: "переключатель снимается выбором другого варианта" };
    }
    clickEl(el);
    if (isToggle(el) && el.checked !== want) {
      el.checked = want;
      inputEvent(el, null);
      fire(el, "change");
    }
    S.touched.add(el);
    return checkedOf(el) === want ? { status: "done", detail: want ? "отмечено" : "снято" }
      : { status: "error", detail: "состояние не изменилось" };
  }

  // Варианты внутри контейнера: radio/checkbox и role=radio|checkbox|option.
  function optionsIn(container) {
    return Array.from(container.querySelectorAll("input[type=radio], input[type=checkbox], [role=radio], " +
      "[role=checkbox], [role=option], [role=menuitemradio], [role=menuitemcheckbox]"));
  }
  function optionText(o) {
    const n = nameOf(o);
    return n || (isToggle(o) ? o.value : "");
  }
  function radioGroup(el) {
    if (!el.name) return [el];
    const scope = el.form || el.getRootNode() || document;
    return Array.from(scope.querySelectorAll("input[type=radio]")).filter((r) => r.name === el.name);
  }
  function checkboxGroup(el) {
    if (!el.name) return [el];
    const scope = el.form || el.getRootNode() || document;
    return Array.from(scope.querySelectorAll("input[type=checkbox]")).filter((r) => r.name === el.name);
  }

  function pickOptions(opts, value) {
    const wants = Array.isArray(value) ? value : [value];
    const multi = Array.isArray(value) || opts.some((o) => typeOf(o) === "checkbox" || roleOf(o) === "checkbox");
    const picked = [];
    for (const w of wants) {
      const o = matchBy(opts, w, optionText);
      if (!o) return { status: "not_found", detail: `нет варианта «${cut(w, 60)}»` };
      picked.push(o);
    }
    for (const o of opts) {
      const want = picked.includes(o);
      if (want) setChecked(o, true);
      else if (multi && checkedOf(o) && (typeOf(o) === "checkbox" || roleOf(o) === "checkbox")) setChecked(o, false);
    }
    return picked.every((o) => checkedOf(o) !== false)
      ? { status: "done", detail: "выбрано: " + picked.map((o) => cut(optionText(o), 40)).join("; ") }
      : { status: "error", detail: "вариант не отметился" };
  }

  const LIB_OPTIONS = "[role=option], [role=menuitem], .select2-results__option, .choices__item--choice, " +
    ".ant-select-item-option, .MuiAutocomplete-option, [class*=react-select__option], .vs__dropdown-option, " +
    ".dropdown-item, .el-select-dropdown__item";

  function popupOptions(el) {
    const ids = norm([el.getAttribute("aria-controls"), el.getAttribute("aria-owns")].join(" ")).split(" ").filter(Boolean);
    const found = [];
    for (const id of ids) {
      const box = document.getElementById(id);
      if (box) found.push(...box.querySelectorAll("[role=option], li, [data-value]"));
    }
    const list = found.length ? found : deepAll(LIB_OPTIONS);
    return list.filter((o) => o !== el && shown(o));
  }

  // Кастомный выпадающий список: открыть → найти вариант → клик.
  async function pickCustom(el, want) {
    clickEl(el);
    await sleep(150);
    let opts = popupOptions(el);
    const typeInto = isTextInput(el) ? el : el.querySelector && el.querySelector("input:not([type=hidden])");
    if (!opts.length && typeInto) {
      setNativeValue(typeInto, String(want)); inputEvent(typeInto, want);
      await sleep(250);
      opts = popupOptions(el);
    }
    const o = matchBy(opts, want, (x) => textOf(x) || nameOf(x));
    if (!o) {
      fire(el, "keydown", KeyboardEvent, { key: "Escape" });
      return { status: "not_found", detail: `нет варианта «${cut(want, 60)}»` };
    }
    clickEl(o);
    await sleep(100);
    S.touched.add(el);
    return { status: "done", detail: "выбрано: " + cut(textOf(o), 60) };
  }

  function isCustomSelect(el) {
    const r = roleOf(el);
    return r === "combobox" || r === "listbox" || el.getAttribute("aria-haspopup") === "listbox" ||
      (el.getAttribute("aria-expanded") !== null && tagOf(el) !== "a");
  }

  async function fillOne(el, value) {
    if (isPayment(el)) return { status: "unsupported", detail: "платёжные поля заполняет только Мастер" };
    if (!enabledOf(el)) return { status: "error", detail: "поле недоступно" };
    const tag = tagOf(el);
    const t = typeOf(el);
    if (t === "file") return { status: "unsupported", detail: "файл — через page_upload" };
    if (t === "checkbox") {
      const b = boolish(value);
      if (b !== undefined && !Array.isArray(value)) return setChecked(el, b);
      return pickOptions(checkboxGroup(el), value);
    }
    if (t === "radio") {
      const b = boolish(value);
      if (b !== undefined && !Array.isArray(value)) return setChecked(el, b);
      return pickOptions(radioGroup(el), value);
    }
    if (tag === "select") return selectNative(el, value);
    if (tag === "option") {
      const sel = el.closest("select");
      return sel ? selectNative(sel, textOf(el)) : { status: "unsupported", detail: "вариант вне списка" };
    }
    if (isTextInput(el) || isEditable(el)) {
      if (Array.isArray(value)) return { status: "error", detail: "для текстового поля нужна строка" };
      if (roleOf(el) === "combobox" && el.getAttribute("aria-autocomplete") === "list") return pickCustom(el, value);
      return setText(el, value);
    }
    const r = roleOf(el);
    if (["checkbox", "radio", "switch", "option", "menuitemcheckbox", "menuitemradio"].includes(r)) {
      const b = boolish(value);
      if (b === undefined) return { status: "error", detail: "нужно да/нет" };
      return setChecked(el, b);
    }
    const opts = optionsIn(el);
    if (opts.length) return pickOptions(opts, value);
    if (isCustomSelect(el)) return pickCustom(el, Array.isArray(value) ? value[0] : value);
    const inner = Array.from(el.querySelectorAll("input, textarea, select, [contenteditable='true']"))
      .filter((x) => typeOf(x) !== "hidden");
    if (inner.length === 1) return fillOne(inner[0], value);
    return { status: "unsupported", detail: "не поле ввода" };
  }

  // ── ошибки валидации ───────────────────────────────────────────
  const ERR_SEL = ".error, .invalid-feedback, .error-message, .field-error, .form-error, .errorlist, " +
    "[role=alert], .help-block, .text-danger, .validation-message, [class*=error-text], [class*=errorText]";

  function idsText(el, attr) {
    const ids = norm(el.getAttribute(attr)).split(" ").filter(Boolean);
    return ids.map((id) => { const n = document.getElementById(id); return n && shown(n) ? textOf(n) : ""; })
      .filter(Boolean).join(" ");
  }
  function userInvalid(el) {
    try { return el.matches(":user-invalid"); } catch (_) { return false; }
  }
  function fieldError(el) {
    const msgs = [];
    if (el.getAttribute("aria-invalid") === "true") {
      const t = idsText(el, "aria-errormessage") || idsText(el, "aria-describedby");
      msgs.push(t || "поле помечено как неверное");
    }
    const touched = S.touched.has(el) || userInvalid(el) || !!(el.closest && el.closest(".was-validated"));
    if (touched && el.willValidate && el.validity && !el.validity.valid) {
      msgs.push(el.validationMessage || "неверное значение");
    }
    // Соседние сообщения: в родителе и родителе родителя, если в этом блоке нет других полей.
    for (let box = el.parentElement, i = 0; box && i < 2; box = box.parentElement, i += 1) {
      const others = Array.from(box.querySelectorAll(FIELD_SEL))
        .filter((x) => x !== el && !(isToggle(x) && x.name && x.name === el.name));
      if (others.length || tagOf(box) === "form" || box === document.body) break;
      for (const m of box.querySelectorAll(ERR_SEL)) {
        if (m.contains(el) || !shown(m)) continue;
        if (m.classList.contains("help-block") && !/error|invalid/.test(String(box.className))) continue;
        const t = textOf(m);
        if (t) msgs.push(t);
      }
      if (msgs.length) break;
    }
    const uniq = Array.from(new Set(msgs.map((m) => cut(m, 160))));
    return uniq.length ? cut(uniq.join("; "), 240) : undefined;
  }

  // ── page.forms ─────────────────────────────────────────────────
  function commonAncestor(list) {
    let a = list[0];
    while (a && !list.every((x) => a.contains(x))) a = a.parentElement;
    return a || document.body;
  }
  function groupContainer(inputs) {
    const box = commonAncestor(inputs);
    const named = box.closest && box.closest("fieldset, [role=radiogroup], [role=group]");
    return named && inputs.every((x) => named.contains(x)) ? named : box;
  }
  function groupLabel(container, fallback) {
    const legend = tagOf(container) === "fieldset" && container.querySelector("legend");
    if (legend && textOf(legend)) return cut(textOf(legend), 200);
    const aria = container.getAttribute && (container.getAttribute("aria-label") || container.getAttribute("aria-labelledby"));
    if (aria) return nameOf(container);
    let prev = container.previousElementSibling;
    for (let i = 0; prev && i < 3; prev = prev.previousElementSibling, i += 1) {
      const t = textOf(prev);
      if (t) return cut(t, 200);
    }
    return fallback || "";
  }

  function describeField(el) {
    const tag = tagOf(el);
    const f = {
      ref: refFor(el), label: nameOf(el), name: el.getAttribute("name") || "",
      type: tag === "input" ? typeOf(el) : tag === "select" ? (el.multiple ? "select-multiple" : "select")
        : tag === "textarea" ? "textarea" : isEditable(el) ? "contenteditable" : roleOf(el),
      required: !!el.required || el.getAttribute("aria-required") === "true",
      autocomplete: el.getAttribute("autocomplete") || "",
    };
    if (tag === "select") {
      f.options = Array.from(el.options).slice(0, 50).map((o) => ({ text: cut(textOf(o) || o.label, 80), value: o.value, selected: o.selected }));
    }
    const v = valueOf(el);
    f.value = v === undefined ? "" : v;
    if (isToggle(el) || roleOf(el) === "checkbox" || roleOf(el) === "switch") f.checked = !!checkedOf(el);
    const err = fieldError(el);
    if (err) f.error = err;
    return f;
  }

  function fieldsFrom(list) {
    const out = [];
    const seenGroups = new Set();
    for (const el of list) {
      const t = typeOf(el);
      const group = t === "radio" ? radioGroup(el) : t === "checkbox" ? checkboxGroup(el) : null;
      if (group && (t === "radio" || group.length > 1)) {
        const key = t + ":" + (el.name || refFor(el));
        if (seenGroups.has(key)) continue;
        seenGroups.add(key);
        const box = groupContainer(group);
        const opts = group.map((o) => ({ ref: refFor(o), text: cut(optionText(o), 120), checked: !!o.checked }));
        const fld = {
          ref: refFor(box), label: groupLabel(box, el.name), name: el.name || "", type: t,
          required: group.some((o) => o.required), autocomplete: "", options: opts,
          value: opts.filter((o) => o.checked).map((o) => o.text).join("; "),
        };
        const err = group.map(fieldError).find(Boolean);
        if (err) fld.error = err;
        out.push(fld);
        continue;
      }
      out.push(describeField(el));
    }
    return out;
  }

  function forms(a) {
    if (!a.snapshot_id || a.snapshot_id !== S.snap) return { stale: true };
    const out = [];
    const cache = new Map();
    for (const f of deepAll("form")) {
      const own = Array.from(f.elements || []).filter((el) => el.matches(FIELD_SEL));
      const extra = Array.from(f.querySelectorAll("[contenteditable='true'], [contenteditable=''], [role=combobox]:not(input):not(select), [role=textbox]:not(input):not(textarea)"));
      const fields = own.concat(extra.filter((x) => !own.includes(x))).filter((el) => visible(el, cache));
      if (!fields.length) continue;
      let host = location.host;
      try { host = new URL(f.getAttribute("action") || location.href, location.href).host; } catch (_) { /* как есть */ }
      const submits = Array.from(f.querySelectorAll(SUBMIT_SEL));
      if (f.id) submits.push(...document.querySelectorAll(`button[form="${f.id.replace(/"/g, "")}"], input[type=submit][form="${f.id.replace(/"/g, "")}"]`));
      out.push({
        form_ref: refFor(f), action_host: host, fields: fieldsFrom(fields),
        submit_refs: Array.from(new Set(submits)).filter((b) => visible(b, cache)).map(refFor),
      });
    }
    const loose = deepAll(FIELD_SEL).filter((el) => !el.form && !(el.closest && el.closest("form")) && visible(el, cache));
    if (loose.length) {
      const buttons = deepAll("button, [role=button], input[type=submit], input[type=button], a")
        .filter((b) => !(b.closest && b.closest("form")) && visible(b, cache) && SUBMIT_RX.test(nameOf(b)))
        .slice(0, 5);
      out.push({ form_ref: null, pseudo: true, action_host: location.host, fields: fieldsFrom(loose), submit_refs: buttons.map(refFor) });
    }
    return { forms: out };
  }

  // ── page.questions ─────────────────────────────────────────────
  const TEXT_IN = "input[type=text], input:not([type]), input[type=number], input[type=email], input[type=url], " +
    "input[type=tel], input[type=search], input[type=date], textarea, [contenteditable='true'], [contenteditable='']";

  function hasMedia(box) {
    for (const m of box.querySelectorAll("img, video, audio, canvas, svg, picture, iframe, object, embed")) {
      if (!shown(m)) continue;
      if (tagOf(m) === "audio") return true;
      const r = m.getBoundingClientRect();
      const w = Math.max(r.width, Number(m.getAttribute("width")) || 0, m.naturalWidth || 0);
      const h = Math.max(r.height, Number(m.getAttribute("height")) || 0, m.naturalHeight || 0);
      if ((w === 0 && h === 0) || (w >= 32 && h >= 32)) return true;  // размер неизвестен — считаем медиа
    }
    return false;
  }

  function rowLabel(sel) {
    const tr = sel.closest("tr");
    if (tr) {
      const cell = Array.from(tr.children).find((c) => !c.contains(sel) && textOf(c));
      if (cell) return cut(textOf(cell), 150);
    }
    return nameOf(sel);
  }

  // Сопоставление и порядок: строка — tr/li/role=row вокруг списка выбора (или сам список).
  function rowOf(sel, box) {
    const r = sel.closest("tr, li, [role=row]");
    return r && r !== box && box.contains(r) ? r : sel;
  }
  function rowText(row, sel) {
    if (row === sel) return nameOf(sel);
    if (tagOf(row) === "tr") return rowLabel(sel);
    let t = "";
    const w = document.createTreeWalker(row, NodeFilter.SHOW_TEXT);
    for (let n = w.nextNode(); n; n = w.nextNode()) {
      if (!n.parentElement.closest("select, .sr-only, .accesshide")) t += " " + n.nodeValue;
    }
    return cut(t, 150) || nameOf(sel);
  }
  // Варианты списка без заглушки «Выбрать...».
  function choiceTexts(sel) {
    return Array.from(sel.options).map((o) => cut(textOf(o), 80)).filter((t) => t && !/^(выбрать|choose)/i.test(t));
  }
  // Списки номеров 1…n в каждой строке — это порядок, а не сопоставление.
  function numberedRows(selects) {
    return selects.every((s) => {
      const t = choiceTexts(s);
      return t.length === selects.length && t.every((x, i) => x === String(i + 1));
    });
  }
  const positionOptions = (n) => Array.from({ length: n }, (_, i) => ({ text: String(i + 1) }));

  function questionText(box, given) {
    if (norm(given)) return cut(given, 600);
    const pick = box.querySelector(".qtext, legend, h1, h2, h3, h4, h5, h6, p, [class*=question], [class*=Question]");
    if (pick && textOf(pick)) return cut(textOf(pick), 600);
    let t = textOf(box);
    for (const o of optionsIn(box)) { const ot = optionText(o); if (ot) t = t.replace(ot, ""); }
    return cut(t, 600);
  }

  function buildQuestion(box, text, claimed, index) {
    const free = (el) => !claimed.has(el) && visible(el);
    const radios = Array.from(box.querySelectorAll("input[type=radio], [role=radio]")).filter(free);
    const checks = Array.from(box.querySelectorAll("input[type=checkbox], [role=checkbox]")).filter(free);
    const selects = Array.from(box.querySelectorAll("select")).filter(free);
    const texts = Array.from(box.querySelectorAll(TEXT_IN)).filter(free);
    const roleOpts = Array.from(box.querySelectorAll("[role=option]")).filter(free);
    const order = Array.from(box.querySelectorAll(".sortableitem, [class*=sortable] > li, li[draggable=true], [data-sortable-item]"))
      .filter((x) => shown(x));

    const q = { q_ref: refFor(box), index, text: questionText(box, text), kind: "", options: [] };
    const take = (els) => els.forEach((e) => claimed.add(e));
    // match/order: строки rows [{row_ref, text}] и общий список вариантов options [{text}];
    // у порядка варианты — позиции 1…n. Ответ — пары {row_ref, option_text} (fill_form).
    if (order.length >= 2 && (box.classList.contains("ordering") || !radios.length && !checks.length && !texts.length)) {
      q.kind = "order";
      q.rows = order.map((li) => ({ row_ref: refFor(li), text: cut(textOf(li), 150) }));
      q.options = positionOptions(order.length);
      take(order);
    } else if (selects.length >= 2) {
      q.kind = numberedRows(selects) ? "order" : "match";
      q.rows = selects.map((s) => { const row = rowOf(s, box); return { row_ref: refFor(row), text: rowText(row, s) }; });
      q.options = q.kind === "order" ? positionOptions(selects.length) : choiceTexts(selects[0]).map((text) => ({ text }));
      take(selects);
    } else if (radios.length) {
      q.kind = "single";
      q.options = radios.map((o) => ({ ref: refFor(o), text: cut(optionText(o), 150), checked: !!checkedOf(o) }));
      take(radios);
    } else if (checks.length) {
      q.kind = "multi";
      q.options = checks.map((o) => ({ ref: refFor(o), text: cut(optionText(o), 150), checked: !!checkedOf(o) }));
      take(checks);
    } else if (roleOpts.length) {
      const lb = roleOpts[0].closest("[role=listbox]");
      q.kind = lb && lb.getAttribute("aria-multiselectable") === "true" ? "multi" : "single";
      q.options = roleOpts.map((o) => ({ ref: refFor(o), text: cut(optionText(o), 150), checked: !!checkedOf(o) }));
      take(roleOpts);
    } else if (selects.length === 1) {
      q.kind = selects[0].multiple ? "multi" : "single";
      q.input_ref = refFor(selects[0]);
      q.options = Array.from(selects[0].options).filter((o) => norm(o.value) || textOf(o))
        .map((o) => ({ ref: refFor(o), text: cut(textOf(o), 150), checked: o.selected }));
      take(selects);
    } else if (texts.length) {
      q.kind = "text";
      q.input_ref = refFor(texts[0]);
      take(texts.slice(0, 1));
    } else {
      return null;
    }
    q.bbox = rectOf(box);
    q.has_media = hasMedia(box);
    return q;
  }

  const NUMBERED = /^\s*(?:вопрос|question|задание)?\s*№?\s*(\d{1,3})\s*[.):]/i;

  function questions(a) {
    if (!a.snapshot_id || a.snapshot_id !== S.snap) return { stale: true };
    const claimed = new WeakSet();
    const found = [];
    const add = (box, text, index) => {
      if (found.some((f) => f.box === box)) return;
      const q = buildQuestion(box, text, claimed, index);
      if (q) found.push({ box, q });
    };
    // 1. Moodle: .que с .qtext и номером .qno.
    for (const que of deepAll(".que")) {
      const qt = que.querySelector(".qtext");
      const qno = que.querySelector(".qno");
      add(que, qt ? textOf(qt) : "", qno ? parseInt(textOf(qno), 10) || undefined : undefined);
    }
    // 2. fieldset с legend.
    for (const fs of deepAll("fieldset")) {
      const lg = fs.querySelector("legend");
      if (lg && textOf(lg)) add(fs, textOf(lg));
    }
    // 3. role=radiogroup | listbox.
    for (const g of deepAll("[role=radiogroup], [role=listbox]")) add(g, nameOf(g) || groupLabel(g, ""));
    // 4. Блоки с нумерацией «1.», «2)», «Вопрос 3:».
    const loose = deepAll("input:not([type=hidden]), select, textarea, [role=radio], [role=checkbox]")
      .filter((el) => !claimed.has(el) && visible(el) && !["submit", "button", "reset", "image", "file"].includes(typeOf(el)));
    for (const el of loose) {
      if (claimed.has(el)) continue;
      for (let up = el.parentElement, i = 0; up && up !== document.body && i < 6; up = up.parentElement, i += 1) {
        const m = textOf(up).match(NUMBERED);
        if (m) { add(up, "", parseInt(m[1], 10)); break; }
      }
    }
    // 5. Группы radio/checkbox с общим name.
    const byName = new Map();
    for (const el of deepAll("input[type=radio], input[type=checkbox]")) {
      if (claimed.has(el) || !el.name || !visible(el)) continue;
      if (!byName.has(el.name)) byName.set(el.name, []);
      byName.get(el.name).push(el);
    }
    for (const group of byName.values()) {
      if (group.length < 2 && typeOf(group[0]) === "checkbox") continue;
      const box = groupContainer(group);
      add(box, groupLabel(box, ""));
    }
    found.sort((x, y) => (x.box.compareDocumentPosition(y.box) & Node.DOCUMENT_POSITION_FOLLOWING ? -1 : 1));
    return {
      questions: found.map(({ q }, i) => Object.assign(q, { index: q.index || i + 1 })),
    };
  }

  // ── сопоставление и порядок: пары {row_ref, option_text} ───────
  // Значение поля {pairs, kind?}: в строке есть список выбора — вариант по тексту (selectNative);
  // строк без списков (порядок) — перестановка синтетическими DnD- и pointer-событиями по bbox,
  // затем проверка порядка по DOM. option_text порядка — позиция с 1.
  const isPairs = (v) => !!v && typeof v === "object" && !Array.isArray(v) && Array.isArray(v.pairs);
  const pairRefs = (v) => (isPairs(v) ? v.pairs.map((p) => p && p.row_ref) : []);
  const rowSelect = (row) => (tagOf(row) === "select" ? row : row.querySelector("select"));
  const selectedText = (sel) => { const o = sel.options[sel.selectedIndex]; return o ? cut(textOf(o), 80) : ""; };

  function targetOrder(rows) {
    const nums = rows.map((r) => Number(norm(r.text)));
    const ranked = nums.every((n) => Number.isInteger(n) && n >= 1) && new Set(nums).size === nums.length;
    return ranked ? rows.slice().sort((x, y) => Number(norm(x.text)) - Number(norm(y.text))) : rows.slice();
  }

  // Сначала HTML5 DnD (dragstart/dragover/drop); не сдвинулось — pointer/mouse по прямоугольникам.
  async function dragBefore(src, dst, moved) {
    scrollTo(src);
    const s = center(src);
    const box = dst.getBoundingClientRect();
    const d = { clientX: box.left + box.width / 2, clientY: box.top + Math.max(1, box.height / 4) };
    const DE = typeof DragEvent === "function" ? DragEvent : MouseEvent;
    const dt = typeof DataTransfer === "function" ? new DataTransfer() : null;
    const drag = (el, type, at) => fire(el, type, DE, Object.assign({ dataTransfer: dt }, at));
    drag(src, "dragstart", s);
    drag(dst, "dragenter", d); drag(dst, "dragover", d); drag(dst, "drop", d);
    drag(src, "dragend", d);
    await sleep(50);
    if (moved()) return true;

    const under = (p, fallback) => (document.elementFromPoint && document.elementFromPoint(p.clientX, p.clientY)) || fallback;
    const ptr = (el, type, p) => {
      fire(el, "pointer" + type, PE, Object.assign({ pointerId: 1, isPrimary: true, buttons: type === "up" ? 0 : 1 }, p));
      fire(el, "mouse" + type, MouseEvent, Object.assign({ buttons: type === "up" ? 0 : 1 }, p));
    };
    ptr(src, "down", s);
    const steps = 6;
    for (let i = 1; i <= steps; i += 1) {
      const p = { clientX: s.clientX + (d.clientX - s.clientX) * i / steps, clientY: s.clientY + (d.clientY - s.clientY) * i / steps };
      ptr(under(p, i < steps / 2 ? src : dst), "move", p);
      await sleep(16);
    }
    ptr(under(d, dst), "up", d);
    await sleep(50);
    return moved();
  }

  async function reorder(rows) {
    const els = rows.map((r) => r.el);
    const parent = els[0].parentElement;
    if (!parent || els.some((el) => el.parentElement !== parent)) {
      return { status: "unsupported", detail: "строки не в одном списке" };
    }
    const want = targetOrder(rows);
    const current = () => Array.from(parent.children).filter((c) => els.includes(c));
    const texts = want.map((r) => cut(textOf(r.el), 40));
    for (let i = 0; i < want.length; i += 1) {
      const cur = current();
      if (cur[i] === want[i].el) continue;
      if (!(await dragBefore(want[i].el, cur[i], () => current()[i] === want[i].el))) break;
    }
    await sleep(100);
    const final = current();
    const ok = final.length === want.length && final.every((el, i) => el === want[i].el);
    const rowsOut = final.map((el, i) => ({ row_ref: refFor(el), value: String(i + 1) }));
    if (!ok) return { status: "unsupported", detail: "порядок не принят страницей", rows: rowsOut };
    els.forEach((el) => S.touched.add(el));
    return { status: "done", detail: "порядок: " + texts.join(" → "), rows: rowsOut };
  }

  async function fillPairs(box, spec, snapshotId) {
    const rows = spec.pairs.map((p) => ({ ref: p.row_ref, el: resolve(snapshotId, p.row_ref), text: String(p.option_text) }));
    if (!rows.length) return { status: "error", detail: "нет пар" };
    const sels = rows.map((r) => rowSelect(r.el));
    if (sels.every(Boolean)) {
      const results = [];
      for (let i = 0; i < rows.length; i += 1) results.push(await fillOne(sels[i], rows[i].text));
      const bad = results.findIndex((r) => r.status !== "done");
      const out = rows.map((r, i) => ({ row_ref: r.ref, value: selectedText(sels[i]) }));
      if (bad >= 0) return { status: results[bad].status, detail: `строка ${bad + 1}: ${results[bad].detail}`, rows: out };
      return { status: "done", detail: `выбрано в ${rows.length} строках`, rows: out };
    }
    if (sels.some(Boolean)) return { status: "unsupported", detail: "строки разного вида" };
    if (spec.kind && spec.kind !== "order") return { status: "unsupported", detail: "сопоставление без списков выбора" };
    return reorder(rows);
  }

  // ── page.fill_form ─────────────────────────────────────────────
  async function fill(a) {
    if (!a.snapshot_id || a.snapshot_id !== S.snap) return { status: "stale", detail: "снимок устарел — нужен новый page_observe" };
    const entries = Object.entries(a.values || {});
    const refs = entries.flatMap(([ref, value]) => [ref, ...pairRefs(value)]);
    const stale = refs.filter((ref) => !resolve(a.snapshot_id, ref));
    if (stale.length) return { status: "stale", detail: "элементы из устаревшего снимка", stale_refs: stale };
    const results = [];
    for (const [ref, value] of entries) {
      const el = resolve(a.snapshot_id, ref);
      let r;
      try {
        r = isPairs(value) ? await fillPairs(el, value, a.snapshot_id) : await fillOne(el, value);
      } catch (e) {
        r = { status: "error", detail: String(e && e.message || e) };
      }
      results.push(Object.assign({ ref }, r));
    }
    await sleep(Number(a.settle_ms) >= 0 ? Number(a.settle_ms) : 250);
    const fields = results.map((r) => {
      const el = resolve(a.snapshot_id, r.ref);
      const f = { ref: r.ref, status: r.status, detail: r.detail };
      if (r.rows) f.rows = r.rows;
      if (!el) return f;
      const v = valueOf(el);
      if (v !== undefined) f.value = v;
      const c = checkedOf(el);
      if (c !== undefined) f.checked = c;
      const opts = isToggle(el) ? (typeOf(el) === "radio" ? radioGroup(el) : checkboxGroup(el)) : optionsIn(el);
      if (opts.length > 1 || (opts.length === 1 && opts[0] !== el)) {
        f.options = opts.map((o) => ({ ref: refFor(o), text: cut(optionText(o), 80), checked: !!checkedOf(o) }));
      }
      const err = fieldError(el) || opts.map(fieldError).find(Boolean);
      if (err) f.error = err;
      return f;
    });
    const ok = fields.filter((f) => f.status === "done").length;
    return {
      status: ok === fields.length ? "done" : "error",
      detail: `заполнено ${ok} из ${fields.length}`,
      fields,
    };
  }

  // ── page.upload ────────────────────────────────────────────────
  function b64ToBytes(b64) {
    const bin = atob(b64 || "");
    const out = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i += 1) out[i] = bin.charCodeAt(i);
    return out;
  }
  function upload(a) {
    const el = resolve(a.snapshot_id, a.ref);
    if (!el) return { status: "stale", detail: "элемент из устаревшего снимка" };
    if (typeof DataTransfer !== "function") return { status: "unsupported", detail: "DataTransfer недоступен" };
    const file = new File([b64ToBytes(a.data_b64)], a.name || "file", { type: a.mime || "application/octet-stream" });
    const dt = new DataTransfer();
    dt.items.add(file);
    if (typeOf(el) === "file") {
      if (!enabledOf(el)) return { status: "error", detail: "поле недоступно" };
      el.files = dt.files;
      inputEvent(el, null);
      fire(el, "change");
      S.touched.add(el);
      const n = el.files ? el.files.length : 0;
      return n ? { status: "done", detail: "файл выбран" } : { status: "error", detail: "файл не установлен" };
    }
    // Зона перетаскивания: dragenter → dragover → drop с тем же DataTransfer.
    const DE = typeof DragEvent === "function" ? DragEvent : Event;
    for (const type of ["dragenter", "dragover", "drop"]) {
      const ev = new DE(type, { bubbles: true, cancelable: true });
      if (!ev.dataTransfer) Object.defineProperty(ev, "dataTransfer", { value: dt });
      el.dispatchEvent(ev);
    }
    return { status: "done", detail: "файл брошен в зону загрузки" };
  }

  // ── page.act ───────────────────────────────────────────────────
  const KEYS = {
    Enter: [13, "Enter"], Tab: [9, "Tab"], Escape: [27, "Escape"], Backspace: [8, "Backspace"],
    ArrowDown: [40, "ArrowDown"], ArrowUp: [38, "ArrowUp"], ArrowLeft: [37, "ArrowLeft"],
    ArrowRight: [39, "ArrowRight"], Space: [32, "Space"], " ": [32, "Space"], Home: [36, "Home"],
    End: [35, "End"], PageDown: [34, "PageDown"], PageUp: [33, "PageUp"], Delete: [46, "Delete"],
  };
  const FOCUSABLE = "a[href], button, input:not([type=hidden]), select, textarea, [tabindex], [contenteditable='true']";

  function pressKey(el, rawKey) {
    const key = rawKey === "Space" ? " " : String(rawKey || "Enter");
    const k = KEYS[key] || [key.length === 1 ? key.toUpperCase().charCodeAt(0) : 0, key.length === 1 ? "Key" + key.toUpperCase() : key];
    const init = { key, code: k[1], keyCode: k[0], which: k[0] };
    focusEl(el);
    const go = fire(el, "keydown", KeyboardEvent, init);
    if (key.length === 1 || key === "Enter") fire(el, "keypress", KeyboardEvent, init);
    if (go && key === "Enter" && tagOf(el) === "input" && el.form) {
      const f = el.form;
      const hasSubmit = f.querySelector(SUBMIT_SEL);
      const single = Array.from(f.elements).filter((x) => isTextInput(x) && tagOf(x) === "input").length === 1;
      if (hasSubmit || single) { if (typeof f.requestSubmit === "function") f.requestSubmit(); else f.submit(); }
    }
    if (go && key === "Tab") {
      const all = deepAll(FOCUSABLE).filter((x) => visible(x) && enabledOf(x) && x.getAttribute("tabindex") !== "-1");
      const next = all[all.indexOf(el) + 1];
      if (next) focusEl(next);
    }
    fire(el, "keyup", KeyboardEvent, init);
    return { status: "done", detail: "нажата " + key };
  }

  async function act(a) {
    const el = resolve(a.snapshot_id, a.ref);
    if (!el) return { status: "stale", detail: "элемент из устаревшего снимка — нужен новый page_observe" };
    const op = a.op;
    try {
      switch (op) {
        case "click":
          if (!enabledOf(el)) return { status: "error", detail: "элемент недоступен" };
          clickEl(el);
          return { status: "done", detail: "нажато" };
        case "fill":
          if (!(isTextInput(el) || isEditable(el))) return { status: "unsupported", detail: "не текстовое поле" };
          if (isPayment(el)) return { status: "unsupported", detail: "платёжные поля заполняет только Мастер" };
          return setText(el, a.value);
        case "select":
          return await fillOne(el, a.value);
        case "check":
        case "uncheck":
          return setChecked(el, op === "check");
        case "press":
          return pressKey(el, a.value);
        case "hover":
          scrollTo(el); hoverEl(el);
          return { status: "done", detail: "наведено" };
        case "focus":
          focusEl(el);
          return { status: "done", detail: "фокус" };
        case "scroll_into_view":
          scrollTo(el);
          return { status: "done", detail: "прокручено" };
        default:
          return { status: "unsupported", detail: `неизвестная операция: ${String(op).slice(0, 40)}` };
      }
    } catch (e) {
      return { status: "error", detail: String(e && e.message || e).slice(0, 200) };
    }
  }

  // ── page.scroll ────────────────────────────────────────────────
  function scroll(a) {
    if (a.ref) {
      const el = resolve(a.snapshot_id, a.ref);
      if (!el) return { status: "stale", detail: "элемент из устаревшего снимка" };
      scrollTo(el);
    } else if (a.to === "top") {
      window.scrollTo(0, 0);
    } else if (a.to === "bottom") {
      window.scrollTo(0, document.documentElement.scrollHeight);
    } else if (typeof a.to === "number") {
      window.scrollTo(0, document.documentElement.scrollHeight * Math.max(0, Math.min(100, a.to)) / 100);
    } else {
      // dy ±1 — маркер «экран вверх/вниз» (0.8 высоты окна); иначе пиксели; нет dy — экран вниз.
      const dy = Number(a.dy) || 0;
      const screen = Math.round(window.innerHeight * 0.8);
      window.scrollBy(0, dy === 0 ? screen : Math.abs(dy) === 1 ? Math.sign(dy) * screen : dy);
    }
    return { status: "done", detail: `прокрутка ${Math.round(window.scrollY)}` };
  }

  // ── кадр: прямоугольник ref и разметка номеров ─────────────────
  function rect(a) {
    const el = resolve(a.snapshot_id || S.snap, a.ref);
    if (!el) return null;
    if (a.scroll) scrollTo(el);
    return { bbox: rectOf(el), viewport: { w: window.innerWidth, h: window.innerHeight, dpr: window.devicePixelRatio || 1 } };
  }

  const ANNOT_ID = "__sakura_annot__";
  function annotate(a) {
    const old = document.getElementById(ANNOT_ID);
    if (old) old.remove();
    if (!a.on || !S.snap) return { count: 0 };
    const layer = document.createElement("div");
    layer.id = ANNOT_ID;
    layer.setAttribute("aria-hidden", "true");
    layer.style.cssText = "position:fixed;left:0;top:0;width:100vw;height:100vh;pointer-events:none;z-index:2147483647;";
    let count = 0;
    for (const [ref, el] of S.byRef) {
      if (!el.isConnected || !inViewport(el)) continue;
      const [x, y, w, h] = rectOf(el);
      const box = document.createElement("div");
      box.style.cssText = `position:absolute;left:${x}px;top:${y}px;width:${w}px;height:${h}px;` +
        "outline:2px solid #ff2d8a;box-sizing:border-box;";
      const tag = document.createElement("span");
      tag.textContent = (a.prefix || "") + ref;
      tag.style.cssText = "position:absolute;left:0;top:-14px;font:bold 11px/13px monospace;color:#fff;" +
        "background:#ff2d8a;padding:0 2px;white-space:nowrap;";
      box.appendChild(tag);
      layer.appendChild(box);
      count += 1;
    }
    (document.body || document.documentElement).appendChild(layer);
    return { count };
  }

  // Ссылки из списка, которых нет в снимке (fill_form проверяет все кадры до заполнения).
  function missing(a) {
    return (a.refs || []).filter((ref) => !resolve(a.snapshot_id, ref));
  }

  const Agent = {
    version: "3.2.0",
    current: () => S.snap,
    iframes: () => iframesInfo().iframes,
    missing,
    observe, act, forms, questions, fill, upload, scroll, rect, annotate,
  };
  root.__sakuraAgent = Agent;

  if (root.chrome && root.chrome.runtime && root.chrome.runtime.onMessage) {
    root.chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
      if (msg.type === "page_action") {
        try {
          const result = handlePageAction(msg.action, msg.arg);
          sendResponse({ ok: true, result });
        } catch (e) {
          sendResponse({ ok: false, error: e.message });
        }
      }
      return true;
    });
  }
})(globalThis);
