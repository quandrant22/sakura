/**
 * content.js — полный контроль DOM страницы.
 *
 * Инжектируется на каждую страницу. Слушает команды от background.js.
 * Живёт постоянно — имеет доступ к DOM без executeScript.
 */

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
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
