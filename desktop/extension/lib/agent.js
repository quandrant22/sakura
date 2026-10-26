/**
 * lib/agent.js — действия агента браузера (версия 3.2.0): вкладки и окна по tab_id/window_id,
 * page.* через функции content.js (chrome.scripting.executeScript({func, args}) — без eval).
 *
 * Ответ любого действия: {ok, status: done|stale|not_found|unsupported|error, detail, data?, observe?}.
 * Состояния задачи здесь нет: tab_id/window_id/snapshot_id приходят из desktop core,
 * карта ref живёт в content.js каждого кадра. ref = "f<frameId>:e<n>".
 */

(function (root) {
  const ACTIONS = new Set([
    "tabs.list", "tabs.activate", "tabs.close", "tabs.reload", "tabs.mute", "tabs.pin", "tabs.move", "tabs.new",
    "agent_window.open", "agent_window.close",
    "page.observe", "page.act", "page.forms", "page.questions", "page.fill_form", "page.upload",
    "page.shot", "page.scroll",
  ]);
  const MAX_ELEMENTS = 300;
  const TEXT_LIMIT = 8000;
  const MAX_CHANGED = 80;
  const SETTLE_MS = 300;
  const LOAD_WAIT_MS = 8000;
  const OPEN_SETTLE_MS = 500;   // новое окно Opera достраивает вкладки после windows.create
  const REF_RX = /^f(\d+):(e\d+)$/;

  const result = (status, detail, extra) =>
    Object.assign({ ok: status === "done", status, detail: detail || "" }, extra || {});

  const parseRef = (ref) => {
    const m = REF_RX.exec(String(ref || ""));
    return m ? { frameId: Number(m[1]), local: m[2] } : null;
  };
  const pref = (frameId, local) => (local ? `f${frameId}:${local}` : local);

  function safeUrl(url) {
    const u = String(url || "about:blank").trim();
    if (u === "about:blank") return u;
    try {
      const p = new URL(/^[a-z][a-z0-9+.-]*:/i.test(u) ? u : "https://" + u);
      return p.protocol === "http:" || p.protocol === "https:" ? p.href : null;
    } catch (_) {
      return null;
    }
  }

  const sameUrl = (a, b) => String(a || "").split("#")[0] === String(b || "").split("#")[0];

  /**
   * Смещения кадров относительно окна вкладки: iframe родителя сопоставляется с кадром
   * webNavigation по URL. Не нашли — null (bbox остаётся в координатах кадра).
   */
  function frameOffsets(iframesByFrame, navFrames) {
    const off = new Map([[0, [0, 0]]]);
    const used = new Map();
    const rest = (navFrames || []).filter((f) => f.frameId !== 0).sort((a, b) => a.frameId - b.frameId);
    let progress = true;
    while (progress) {
      progress = false;
      for (const f of rest) {
        if (off.has(f.frameId) || !off.has(f.parentFrameId)) continue;
        const po = off.get(f.parentFrameId);
        const list = iframesByFrame.get(f.parentFrameId) || [];
        const u = used.get(f.parentFrameId) || new Set();
        const idx = po ? list.findIndex((x, i) => !u.has(i) && sameUrl(x.src, f.url)) : -1;
        if (idx >= 0) {
          u.add(idx);
          used.set(f.parentFrameId, u);
          off.set(f.frameId, [po[0] + list[idx].bbox[0], po[1] + list[idx].bbox[1]]);
        } else {
          off.set(f.frameId, null);
        }
        progress = true;
      }
    }
    return off;
  }

  // Результаты observe по кадрам → одно observation по контракту.
  function mergeObservation(tab, snapshotId, results, navFrames, opts) {
    const max = Math.max(1, Number(opts && opts.max_elements) || MAX_ELEMENTS);
    const textLimit = Math.max(0, Number(opts && opts.text_limit) || TEXT_LIMIT);
    const frames = (results || []).filter((r) => r && r.result).sort((a, b) => a.frameId - b.frameId);
    const iframes = new Map(frames.map((r) => [r.frameId, r.result.iframes || []]));
    const offsets = frameOffsets(iframes, navFrames);
    const top = frames.find((r) => r.frameId === 0);
    const vw = top ? top.result.viewport.w : 0;
    const vh = top ? top.result.viewport.h : 0;

    const all = [];
    const changed = [];
    let text = "";
    let timer;
    let total = 0;
    const out = {
      snapshot_id: snapshotId, window_id: tab.windowId, tab_id: tab.id, url: tab.url || "", title: tab.title || "",
      elements: [], text: "", has_canvas: false, has_video: false, cross_origin_frames: 0, captcha_detected: false,
    };
    for (const { frameId, result: r } of frames) {
      const off = offsets.has(frameId) ? offsets.get(frameId) : null;
      total += r.total || 0;
      for (const e of r.elements || []) {
        const el = Object.assign({}, e, { ref: pref(frameId, e.ref) });
        if (frameId !== 0) {
          if (off) {
            el.bbox = [e.bbox[0] + off[0], e.bbox[1] + off[1], e.bbox[2], e.bbox[3]];
            el.in_viewport = e.in_viewport && el.bbox[1] < vh && el.bbox[0] < vw &&
              el.bbox[1] + el.bbox[3] > 0 && el.bbox[0] + el.bbox[2] > 0;
          } else {
            el.frame_local = true;
          }
        }
        all.push(el);
      }
      for (const c of r.changed || []) changed.push(Object.assign({}, c, { ref: pref(frameId, c.ref) }));
      if (r.text) {
        const part = frameId === 0 ? r.text : `\n[кадр f${frameId}]\n${r.text}`;
        text += part;
      }
      if (!timer && r.timer) timer = r.timer;
      out.has_canvas = out.has_canvas || !!r.has_canvas;
      out.has_video = out.has_video || !!r.has_video;
      out.captcha_detected = out.captcha_detected || !!r.captcha_detected;
      out.cross_origin_frames += r.cross_origin_frames || 0;
      if (r.changed) out.changed = true;
    }
    // Лимит элементов: сначала видимые в окне, порядок кадров и документа сохраняется.
    let elements = all;
    if (all.length > max) {
      const keep = new Set(all.filter((e) => e.in_viewport).concat(all.filter((e) => !e.in_viewport)).slice(0, max));
      elements = all.filter((e) => keep.has(e));
    }
    out.elements = elements;
    out.text = text.length > textLimit ? text.slice(0, textLimit) : text;
    if (out.changed) out.changed = changed.slice(0, MAX_CHANGED); else delete out.changed;
    if (timer) out.timer = timer;
    if (total > elements.length) out.truncated = total - elements.length;
    return out;
  }

  // Префикс кадра для ref в ответах forms/questions/fill.
  function prefixForms(frameId, list) {
    return (list || []).map((f) => Object.assign({}, f, {
      form_ref: f.form_ref ? pref(frameId, f.form_ref) : null,
      submit_refs: (f.submit_refs || []).map((r) => pref(frameId, r)),
      fields: (f.fields || []).map((x) => Object.assign({}, x, {
        ref: pref(frameId, x.ref),
        ...(x.options ? { options: x.options.map((o) => (o.ref ? Object.assign({}, o, { ref: pref(frameId, o.ref) }) : o)) } : {}),
      })),
    }));
  }
  function prefixQuestions(frameId, list, off) {
    return (list || []).map((q) => {
      const out = Object.assign({}, q, {
        q_ref: pref(frameId, q.q_ref),
        options: (q.options || []).map((o) => Object.assign({}, o, { ref: pref(frameId, o.ref) })),
      });
      if (q.input_ref) out.input_ref = pref(frameId, q.input_ref);
      if (frameId !== 0) {
        if (off) out.bbox = [q.bbox[0] + off[0], q.bbox[1] + off[1], q.bbox[2], q.bbox[3]];
        else out.frame_local = true;
      }
      return out;
    });
  }
  function prefixFields(frameId, fields) {
    return (fields || []).map((f) => Object.assign({}, f, {
      ref: pref(frameId, f.ref),
      ...(f.options ? { options: f.options.map((o) => Object.assign({}, o, { ref: pref(frameId, o.ref) })) } : {}),
    }));
  }

  /**
   * deps: chrome, capture(windowId, opts) — очередь захвата, codec?, sleep?, fetchUpload(token).
   */
  function create(deps) {
    const chrome = deps.chrome;
    const sleep = deps.sleep || ((ms) => new Promise((r) => setTimeout(r, ms)));
    const Capture = deps.Capture || root.SakuraCapture;
    let snapCounter = 0;
    const newSnapshotId = () => `s${Date.now().toString(36)}${(++snapCounter).toString(36)}`;

    async function getTab(tabId) {
      try { return await chrome.tabs.get(Number(tabId)); } catch (_) { return null; }
    }

    async function exec(tabId, target, func, args) {
      return chrome.scripting.executeScript({ target: Object.assign({ tabId }, target), func, args: args || [] });
    }

    async function ensureAgent(tabId) {
      const probe = await exec(tabId, { allFrames: true }, () => !!globalThis.__sakuraAgent);
      const missing = probe.filter((r) => !r.result).map((r) => r.frameId);
      if (missing.length) {
        await chrome.scripting.executeScript({ target: { tabId, frameIds: missing }, files: ["content.js"] });
      }
    }

    async function navFrames(tabId) {
      try { return (await chrome.webNavigation.getAllFrames({ tabId })) || []; } catch (_) { return []; }
    }

    async function offsetsFor(tabId) {
      const res = await exec(tabId, { allFrames: true },
        () => (globalThis.__sakuraAgent ? globalThis.__sakuraAgent.iframes() : []));
      const iframes = new Map(res.map((r) => [r.frameId, r.result || []]));
      return frameOffsets(iframes, await navFrames(tabId));
    }

    async function settle(tabId, ms) {
      await sleep(ms == null ? SETTLE_MS : ms);
      const until = Date.now() + LOAD_WAIT_MS;
      for (;;) {
        const tab = await getTab(tabId);
        if (!tab || tab.status === "complete" || Date.now() > until) return;
        await sleep(200);
      }
    }

    async function observeTab(tabId, opts) {
      const tab = await getTab(tabId);
      if (!tab) return { error: result("not_found", "вкладка не найдена") };
      try {
        await ensureAgent(tab.id);
      } catch (_) {
        return { error: result("unsupported", "страница недоступна расширению (служебная страница браузера)") };
      }
      const snapshotId = newSnapshotId();
      const args = {
        snapshot_id: snapshotId,
        max_elements: (opts && opts.max_elements) || MAX_ELEMENTS,
        text_limit: (opts && opts.text_limit) || TEXT_LIMIT,
      };
      const res = await exec(tab.id, { allFrames: true },
        (a) => (globalThis.__sakuraAgent ? globalThis.__sakuraAgent.observe(a) : null), [args]);
      return { obs: mergeObservation(tab, snapshotId, res, await navFrames(tab.id), args) };
    }

    async function observeAfter(tabId, opts) {
      try {
        const o = await observeTab(tabId, opts);
        return o.obs || null;
      } catch (_) {
        return null;
      }
    }

    async function currentSnapshot(tabId) {
      try {
        const [r] = await exec(tabId, { frameIds: [0] },
          () => (globalThis.__sakuraAgent ? globalThis.__sakuraAgent.current() : null));
        return r ? r.result : null;
      } catch (_) {
        return null;
      }
    }

    // forms / questions: в снимке текущей вкладки; снимка нет или он устарел — сначала observe.
    async function collect(tabId, method) {
      const tab = await getTab(tabId);
      if (!tab) return { error: result("not_found", "вкладка не найдена") };
      try { await ensureAgent(tab.id); } catch (_) {
        return { error: result("unsupported", "страница недоступна расширению (служебная страница браузера)") };
      }
      let snap = await currentSnapshot(tab.id);
      for (let attempt = 0; attempt < 2; attempt += 1) {
        if (!snap) {
          const o = await observeTab(tab.id, {});
          if (o.error) return o;
          snap = o.obs.snapshot_id;
        }
        const res = await exec(tab.id, { allFrames: true },
          (m, a) => (globalThis.__sakuraAgent ? globalThis.__sakuraAgent[m](a) : { stale: true }), [method, { snapshot_id: snap }]);
        if (res.some((r) => r.result && r.result.stale)) { snap = null; continue; }
        return { snap, res };
      }
      return { error: result("stale", "страница меняется — снимок не удержался") };
    }

    async function execFrame(tabId, frameId, func, args) {
      const [r] = await exec(tabId, { frameIds: [frameId] }, func, args);
      return r ? r.result : undefined;
    }

    // ── вкладки и окна ─────────────────────────────────────────────
    const tabInfo = (t) => ({
      tab_id: t.id, window_id: t.windowId, title: t.title || "", url: t.url || "", active: !!t.active,
      audible: !!t.audible, muted: !!(t.mutedInfo && t.mutedInfo.muted), pinned: !!t.pinned,
      group_id: t.groupId == null ? -1 : t.groupId, last_accessed: t.lastAccessed || null,
    });

    async function withTab(a, fn) {
      const tab = await getTab(a.tab_id);
      if (!tab) return result("not_found", "вкладка не найдена");
      return fn(tab);
    }

    const handlers = {
      async "tabs.list"(a) {
        const q = a.window_id != null ? { windowId: Number(a.window_id) } : {};
        const tabs = await chrome.tabs.query(q);
        return result("done", `${tabs.length} вкладок`, { data: tabs.map(tabInfo) });
      },
      async "tabs.activate"(a) {
        // Только вкладка внутри своего окна: окно не фокусируется (фокус пользователя не трогаем).
        return withTab(a, async (t) => { await chrome.tabs.update(t.id, { active: true }); return result("done", "вкладка активна"); });
      },
      async "tabs.close"(a) {
        return withTab(a, async (t) => { await chrome.tabs.remove(t.id); return result("done", "вкладка закрыта"); });
      },
      async "tabs.reload"(a) {
        return withTab(a, async (t) => {
          await chrome.tabs.reload(t.id);
          await settle(t.id);
          return result("done", "обновлено");
        });
      },
      async "tabs.mute"(a) {
        return withTab(a, async (t) => {
          const muted = a.muted == null ? !(t.mutedInfo && t.mutedInfo.muted) : !!a.muted;
          await chrome.tabs.update(t.id, { muted });
          return result("done", muted ? "звук выключен" : "звук включён", { data: { muted } });
        });
      },
      async "tabs.pin"(a) {
        return withTab(a, async (t) => {
          const pinned = a.pinned == null ? !t.pinned : !!a.pinned;
          await chrome.tabs.update(t.id, { pinned });
          return result("done", pinned ? "закреплена" : "откреплена", { data: { pinned } });
        });
      },
      async "tabs.move"(a) {
        return withTab(a, async (t) => {
          const props = { index: a.index == null ? -1 : Number(a.index) };
          if (a.window_id != null) props.windowId = Number(a.window_id);
          await chrome.tabs.move(t.id, props);
          return result("done", "перемещена");
        });
      },
      async "tabs.new"(a) {
        const url = safeUrl(a.url);
        if (!url) return result("error", "адрес только http(s) или about:blank");
        const props = { url, active: a.active == null ? a.window_id != null : !!a.active };
        if (a.window_id != null) props.windowId = Number(a.window_id);
        const t = await chrome.tabs.create(props);
        return result("done", "вкладка открыта", { data: { tab_id: t.id, window_id: t.windowId } });
      },
      async "agent_window.open"(a) {
        const url = safeUrl(a.url);
        if (!url) return result("error", "адрес только http(s) или about:blank");
        let prev = null;
        try { prev = await chrome.windows.getLastFocused(); } catch (_) { prev = null; }
        // Отдельное окно агента без фокуса: пользователь продолжает работать в своём.
        const w = await chrome.windows.create({
          url, focused: false, type: "normal",
          width: Number(a.width) || 1280, height: Number(a.height) || 900,
        });
        // Opera GX кладёт в каждое новое окно свою стартовую вкладку (GX Corner) — первой и активной,
        // её нельзя скриптовать и снимать. Делаем активной вкладку с нашим адресом. Стартовую не закрываем:
        // chrome.tabs.remove для неё в Opera GX 137 не завершается никогда (живая проверка 26.10).
        await sleep(OPEN_SETTLE_MS);
        const tabs = await chrome.tabs.query({ windowId: w.id });
        const tab = tabs.find((t) => sameUrl(t.pendingUrl || t.url, url)) || tabs[tabs.length - 1];
        if (tab && !tab.active) await chrome.tabs.update(tab.id, { active: true });
        const extra = tabs.filter((t) => tab && t.id !== tab.id).length;
        // Opera GX 137 игнорирует focused:false (живая проверка 26.10): фокус — обратно окну пользователя.
        let refocused = false;
        try {
          const now = await chrome.windows.get(w.id);
          if (now.focused) {
            if (prev && prev.focused && prev.id !== w.id) await chrome.windows.update(prev.id, { focused: true });
            else await chrome.windows.update(w.id, { focused: false });
            refocused = true;
          }
        } catch (_) { /* окно закрыли */ }
        return result("done", "окно агента открыто",
          { data: { window_id: w.id, tab_id: tab ? tab.id : null, extra_tabs: extra, refocused } });
      },
      async "agent_window.close"(a) {
        try { await chrome.windows.remove(Number(a.window_id)); } catch (_) { return result("not_found", "окно не найдено"); }
        return result("done", "окно агента закрыто");
      },

      // ── страница ─────────────────────────────────────────────────
      async "page.observe"(a) {
        const o = await observeTab(a.tab_id, a);
        return o.error || result("done", `${o.obs.elements.length} элементов`, { data: o.obs });
      },

      async "page.act"(a) {
        const tab = await getTab(a.tab_id);
        if (!tab) return result("not_found", "вкладка не найдена");
        const p = parseRef(a.ref);
        let r;
        if (!p || !a.snapshot_id) {
          r = { status: "stale", detail: "нет snapshot_id или ref" };
        } else {
          try {
            r = await execFrame(tab.id, p.frameId,
              (x) => (globalThis.__sakuraAgent ? globalThis.__sakuraAgent.act(x)
                : { status: "stale", detail: "страница сменилась" }),
              [{ snapshot_id: a.snapshot_id, ref: p.local, op: a.op, value: a.value }]);
          } catch (_) {
            r = { status: "stale", detail: "кадр недоступен — страница сменилась" };
          }
          if (r == null) r = { status: "done", detail: "страница сменилась во время действия" };
        }
        if (r.status === "done") await settle(tab.id);
        return result(r.status, r.detail, { observe: await observeAfter(tab.id, a) });
      },

      async "page.forms"(a) {
        const c = await collect(a.tab_id, "forms");
        if (c.error) return c.error;
        const forms = [];
        for (const r of c.res) if (r.result && r.result.forms) forms.push(...prefixForms(r.frameId, r.result.forms));
        return result("done", `${forms.length} форм`, { data: { snapshot_id: c.snap, forms } });
      },

      async "page.questions"(a) {
        const c = await collect(a.tab_id, "questions");
        if (c.error) return c.error;
        const off = c.res.length > 1 ? await offsetsFor(a.tab_id) : new Map([[0, [0, 0]]]);
        const qs = [];
        for (const r of c.res) {
          if (r.result && r.result.questions) qs.push(...prefixQuestions(r.frameId, r.result.questions, off.get(r.frameId)));
        }
        return result("done", `${qs.length} вопросов`, { data: { snapshot_id: c.snap, questions: qs } });
      },

      async "page.fill_form"(a) {
        const tab = await getTab(a.tab_id);
        if (!tab) return result("not_found", "вкладка не найдена");
        const byFrame = new Map();
        const bad = [];
        for (const [ref, value] of Object.entries(a.values || {})) {
          const p = parseRef(ref);
          if (!p) { bad.push(ref); continue; }
          if (!byFrame.has(p.frameId)) byFrame.set(p.frameId, {});
          byFrame.get(p.frameId)[p.local] = value;
        }
        if (!a.snapshot_id || bad.length || !byFrame.size) {
          return result("stale", "нет snapshot_id или неверные ref", { data: { stale_refs: bad }, observe: await observeAfter(tab.id, a) });
        }
        // Сначала проверка всех кадров: устаревший ref — ничего не заполняем.
        const stale = [];
        for (const [frameId, values] of byFrame) {
          let miss;
          try {
            miss = await execFrame(tab.id, frameId,
              (x) => (globalThis.__sakuraAgent ? globalThis.__sakuraAgent.missing(x) : x.refs),
              [{ snapshot_id: a.snapshot_id, refs: Object.keys(values) }]);
          } catch (_) {
            miss = Object.keys(values);
          }
          for (const m of miss || []) stale.push(pref(frameId, m));
        }
        if (stale.length) {
          return result("stale", "элементы из устаревшего снимка", { data: { stale_refs: stale }, observe: await observeAfter(tab.id, a) });
        }
        const fields = [];
        for (const [frameId, values] of byFrame) {
          let r;
          try {
            r = await execFrame(tab.id, frameId,
              (x) => (globalThis.__sakuraAgent ? globalThis.__sakuraAgent.fill(x) : { status: "stale", fields: [] }),
              [{ snapshot_id: a.snapshot_id, values }]);
          } catch (e) {
            r = { status: "error", fields: Object.keys(values).map((ref) => ({ ref, status: "error", detail: "кадр недоступен" })) };
          }
          fields.push(...prefixFields(frameId, (r && r.fields) || []));
        }
        const ok = fields.filter((f) => f.status === "done").length;
        await settle(tab.id, 0);
        return result(ok === fields.length && fields.length ? "done" : "error", `заполнено ${ok} из ${fields.length}`,
          { data: { fields }, observe: await observeAfter(tab.id, a) });
      },

      async "page.upload"(a) {
        const tab = await getTab(a.tab_id);
        if (!tab) return result("not_found", "вкладка не найдена");
        const p = parseRef(a.ref);
        if (!p) return result("stale", "неверный ref");
        if (!a.file_token) return result("error", "нет file_token");
        const file = await deps.fetchUpload(a.file_token);
        if (!file || !file.ok) return result("error", (file && file.error) || "файл не получен от ядра");
        let r;
        try {
          r = await execFrame(tab.id, p.frameId,
            (x) => (globalThis.__sakuraAgent ? globalThis.__sakuraAgent.upload(x) : { status: "stale", detail: "страница сменилась" }),
            [{ snapshot_id: a.snapshot_id || null, ref: p.local, name: file.name, mime: file.mime, data_b64: file.data_b64 }]);
        } catch (_) {
          r = { status: "stale", detail: "кадр недоступен" };
        }
        // snapshot_id не передан — берём текущий снимок кадра (как page.shot crop_ref).
        if (r && r.status === "stale" && !a.snapshot_id) {
          const snap = await currentSnapshot(tab.id);
          if (snap) {
            r = await execFrame(tab.id, p.frameId,
              (x) => globalThis.__sakuraAgent.upload(x),
              [{ snapshot_id: snap, ref: p.local, name: file.name, mime: file.mime, data_b64: file.data_b64 }]);
          }
        }
        r = r || { status: "error", detail: "нет ответа страницы" };
        if (r.status === "done") await settle(tab.id);
        return result(r.status, r.detail, { observe: await observeAfter(tab.id, a) });
      },

      async "page.scroll"(a) {
        const tab = await getTab(a.tab_id);
        if (!tab) return result("not_found", "вкладка не найдена");
        const p = a.ref ? parseRef(a.ref) : { frameId: 0, local: null };
        if (!p) return result("stale", "неверный ref");
        let r;
        try {
          r = await execFrame(tab.id, p.frameId,
            (x) => (globalThis.__sakuraAgent ? globalThis.__sakuraAgent.scroll(x) : { status: "stale", detail: "страница сменилась" }),
            [{ snapshot_id: a.snapshot_id || null, ref: p.local, dy: a.dy, to: a.to }]);
        } catch (_) {
          try { await ensureAgent(tab.id); } catch (e) { return result("unsupported", "страница недоступна расширению"); }
          r = await execFrame(tab.id, p.frameId, (x) => globalThis.__sakuraAgent.scroll(x),
            [{ snapshot_id: a.snapshot_id || null, ref: p.local, dy: a.dy, to: a.to }]);
        }
        r = r || { status: "error", detail: "нет ответа страницы" };
        if (r.status === "done") await sleep(150);
        return result(r.status, r.detail, { observe: await observeAfter(tab.id, a) });
      },

      async "page.shot"(a) {
        let tab;
        if (a.tab_id != null) {
          tab = await getTab(a.tab_id);
          if (!tab) return result("not_found", "вкладка не найдена");
          // Захват — только видимой вкладки окна. Неактивную вкладку не активируем.
          if (!tab.active) return result("unsupported", "вкладка неактивна — захват невозможен без её активации");
        } else if (a.window_id != null) {
          [tab] = await chrome.tabs.query({ windowId: Number(a.window_id), active: true });
          if (!tab) return result("not_found", "окно не найдено");
        } else {
          return result("error", "нужен tab_id или window_id");
        }
        try {
          const win = await chrome.windows.get(tab.windowId);
          if (win && win.state === "minimized") return result("unsupported", "окно свёрнуто — кадр недоступен");
        } catch (_) {
          return result("not_found", "окно не найдено");
        }

        let crop = null;
        let viewportWidth = null;
        if (a.crop_ref) {
          const p = parseRef(a.crop_ref);
          if (!p) return result("stale", "неверный crop_ref");
          let r = null;
          try {
            r = await execFrame(tab.id, p.frameId,
              (x) => (globalThis.__sakuraAgent ? globalThis.__sakuraAgent.rect(x) : null),
              [{ snapshot_id: a.snapshot_id || null, ref: p.local, scroll: true }]);
          } catch (_) { r = null; }
          if (!r) return result("stale", "элемент для обрезки не найден в снимке");
          let off = [0, 0];
          if (p.frameId !== 0) {
            const offs = await offsetsFor(tab.id);
            off = offs.get(p.frameId);
            if (!off) return result("unsupported", "положение кадра на странице неизвестно");
            const [top] = await exec(tab.id, { frameIds: [0] }, () => ({ w: window.innerWidth }));
            viewportWidth = top && top.result ? top.result.w : r.viewport.w;
          } else {
            viewportWidth = r.viewport.w;
          }
          crop = [r.bbox[0] + off[0], r.bbox[1] + off[1], r.bbox[2], r.bbox[3]];
          await sleep(150);  // прокрутка к элементу
        }

        const annotated = a.mode === "annotated";
        const frameIds = annotated ? (await navFrames(tab.id)).map((f) => f.frameId) : [];
        if (annotated && !frameIds.length) frameIds.push(0);
        const mark = async (on) => {
          for (const id of frameIds) {
            try {
              await execFrame(tab.id, id, (x) => (globalThis.__sakuraAgent ? globalThis.__sakuraAgent.annotate(x) : null),
                [{ on, prefix: `f${id}:` }]);
            } catch (_) { /* кадр ушёл */ }
          }
        };
        let dataUrl;
        try {
          if (annotated) await mark(true);
          dataUrl = await deps.capture(tab.windowId, { format: "png" });
        } catch (e) {
          return result("unsupported", "захват недоступен: " + String(e && e.message || e).slice(0, 120));
        } finally {
          if (annotated) await mark(false);  // разметка снимается сразу после кадра
        }
        try {
          const img = await Capture.compress(dataUrl, {
            crop, viewportWidth, codec: deps.codec,
            limit: crop ? Capture.LIMITS.crop : Capture.LIMITS.page,
          });
          return result("done", `${img.width}x${img.height} q${img.quality}`,
            { data: Object.assign(img, { tab_id: tab.id, window_id: tab.windowId, mode: annotated ? "annotated" : "plain" }) });
        } catch (e) {
          return result("error", "кадр не обработан: " + String(e && e.message || e).slice(0, 120));
        }
      },
    };

    async function handle(action, args) {
      const fn = handlers[action];
      if (!fn) return result("unsupported", `неизвестное действие: ${action}`);
      try {
        return await fn(args || {});
      } catch (e) {
        return result("error", String(e && e.message || e).slice(0, 200));
      }
    }

    return { handle, observeTab, settle };
  }

  root.SakuraAgent = {
    ACTIONS, create, mergeObservation, frameOffsets, parseRef, safeUrl,
    handles: (action) => ACTIONS.has(action),
  };
})(globalThis);
