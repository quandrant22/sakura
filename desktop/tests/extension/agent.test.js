// lib/agent.js: ref с префиксом кадра, stale без действия, fill_form по кадрам, page.shot, вкладки.
import { beforeEach, describe, expect, test, vi } from "vitest";

import { fixture, loadContent, loadLib, stubRects } from "./helpers.js";

loadLib("lib/capture.js");
loadLib("lib/agent.js");
const { SakuraAgent, SakuraCapture } = globalThis;

// Кадр 5 — платёжный iframe: свой «content.js» с готовым снимком.
function frameAgent() {
  return {
    current: () => "snap-frame",
    iframes: () => [],
    missing: vi.fn((a) => a.refs.filter((r) => r !== "e1")),
    observe: vi.fn((a) => ({
      href: "https://pay.example/frame", title: "pay", is_top: false, viewport: { w: 400, h: 200, dpr: 1 },
      elements: [{ ref: "e1", role: "button", name: "Оплатить", enabled: true, in_viewport: true, bbox: [10, 20, 80, 30] }],
      total: 1, text: "Оплата картой", has_canvas: false, has_video: false, cross_origin_frames: 0,
      captcha_detected: false, iframes: [], snap: a.snapshot_id,
    })),
    act: vi.fn(async () => ({ status: "done", detail: "нажато" })),
    fill: vi.fn(async (a) => ({ status: "done", fields: Object.keys(a.values).map((ref) => ({ ref, status: "done" })) })),
    annotate: vi.fn(() => ({ count: 1 })),
    rect: vi.fn(() => ({ bbox: [10, 20, 80, 30], viewport: { w: 400, h: 200, dpr: 1 } })),
  };
}

function setup({ tabs, frames = [{ frameId: 0, parentFrameId: -1, url: "https://shop.example/" }] } = {}) {
  const top = globalThis.__sakuraAgent;
  const f5 = frameAgent();
  const agents = { 0: top, 5: f5 };
  const log = [];
  const allTabs = tabs || [{ id: 11, windowId: 7, active: true, url: "https://shop.example/", title: "Магазин", status: "complete" }];
  // Выполнить func «в кадре»: подменяем globalThis.__sakuraAgent на агента этого кадра.
  const runIn = (frameId, func, args) => {
    const saved = globalThis.__sakuraAgent;
    globalThis.__sakuraAgent = agents[frameId];
    try { return func(...args); } finally { globalThis.__sakuraAgent = saved; }
  };
  const chrome = {
    tabs: {
      get: vi.fn(async (id) => { const t = allTabs.find((x) => x.id === id); if (!t) throw new Error("No tab"); return t; }),
      query: vi.fn(async (q) => allTabs.filter((t) => (q.windowId == null || t.windowId === q.windowId) && (q.active == null || t.active === q.active))),
      update: vi.fn(async () => ({})),
      create: vi.fn(async (p) => ({ id: 99, windowId: p.windowId || 1 })),
      remove: vi.fn(async () => {}),
      reload: vi.fn(async () => {}),
      move: vi.fn(async () => {}),
    },
    windows: {
      get: vi.fn(async (id) => ({ id, state: "normal", focused: false })),
      getLastFocused: vi.fn(async () => ({ id: 7, focused: true })),
      create: vi.fn(async (p) => {
        allTabs.push({ id: 420, windowId: 42, active: true, url: "", pendingUrl: p.url });
        return { id: 42, tabs: [{ id: 420 }] };
      }),
      update: vi.fn(async () => ({})),
      remove: vi.fn(async () => {}),
    },
    webNavigation: { getAllFrames: vi.fn(async () => frames) },
    scripting: {
      executeScript: vi.fn(async ({ target, func, args, files }) => {
        const ids = target.allFrames ? frames.map((f) => f.frameId) : target.frameIds;
        log.push({ frameIds: ids, files: !!files, args });
        if (files) return ids.map((frameId) => ({ frameId }));
        const out = [];
        for (const frameId of ids) out.push({ frameId, result: await runIn(frameId, func, args || []) });
        return out;
      }),
    },
  };
  const capture = vi.fn(async () => "data:image/png;base64,AAAA");
  const encodes = [];
  const codec = {
    decode: vi.fn(async () => ({ width: 2048, height: 1536 })),
    encode: vi.fn(async (img, src, w, h, q) => { encodes.push({ src, w, h, q }); return new Uint8Array(1000); }),
  };
  const fetchUpload = vi.fn(async () => ({ ok: true, name: "a.txt", mime: "text/plain", data_b64: "" }));
  const agent = SakuraAgent.create({ chrome, capture, codec, fetchUpload, sleep: async () => {} });
  return { agent, chrome, capture, codec, encodes, log, f5, fetchUpload };
}

const twoFrames = [
  { frameId: 0, parentFrameId: -1, url: "https://shop.example/" },
  { frameId: 5, parentFrameId: 0, url: "https://pay.example/frame" },
];

beforeEach(() => {
  document.body.innerHTML = "";
  stubRects();
  loadContent();
});

describe("ref с frameId", () => {
  test("observe: префикс кадра, смещение bbox по iframe, текст кадра", async () => {
    fixture("observe.html");
    const { agent } = setup({ frames: twoFrames });
    const r = await agent.handle("page.observe", { tab_id: 11 });
    expect(r).toMatchObject({ ok: true, status: "done" });
    const o = r.data;
    expect(o).toMatchObject({ tab_id: 11, window_id: 7, url: "https://shop.example/", title: "Магазин", captcha_detected: true, has_canvas: true });
    expect(o.snapshot_id).toMatch(/^s/);
    const pay = o.elements.find((e) => e.name === "Оплатить");
    expect(pay.ref).toBe("f5:e1");
    expect(pay.bbox).toEqual([210, 320, 80, 30]);   // iframe в [200,300]
    expect(o.elements.filter((e) => e.ref.startsWith("f0:e")).length).toBe(o.elements.length - 1);
    expect(o.text).toContain("[кадр f5]\nОплата картой");
  });

  test("act по ref f5:e1 уходит в кадр 5 с локальным e1", async () => {
    fixture("observe.html");
    const { agent, log, f5 } = setup({ frames: twoFrames });
    const o = (await agent.handle("page.observe", { tab_id: 11 })).data;
    log.length = 0;
    const r = await agent.handle("page.act", { tab_id: 11, snapshot_id: o.snapshot_id, ref: "f5:e1", op: "click" });
    expect(r.status).toBe("done");
    expect(log[0].frameIds).toEqual([5]);
    expect(log[0].args[0]).toMatchObject({ ref: "e1", op: "click", snapshot_id: o.snapshot_id });
    expect(f5.act).toHaveBeenCalledTimes(1);
    expect(r.observe.snapshot_id).not.toBe(o.snapshot_id);   // свежий снимок после действия
  });

  test("mergeObservation: кадр без найденного iframe — bbox в координатах кадра", () => {
    const tab = { id: 1, windowId: 2, url: "u", title: "t" };
    const base = { viewport: { w: 800, h: 600 }, elements: [], total: 0, iframes: [] };
    const res = [
      { frameId: 0, result: { ...base, elements: [{ ref: "e1", bbox: [0, 0, 1, 1], in_viewport: true }], total: 1 } },
      { frameId: 3, result: { ...base, elements: [{ ref: "e1", bbox: [5, 5, 1, 1], in_viewport: true }], total: 1 } },
    ];
    const o = SakuraAgent.mergeObservation(tab, "s1", res, [{ frameId: 3, parentFrameId: 0, url: "https://x/" }], {});
    expect(o.elements.map((e) => e.ref)).toEqual(["f0:e1", "f3:e1"]);
    expect(o.elements[1]).toMatchObject({ bbox: [5, 5, 1, 1], frame_local: true });
  });
});

describe("stale: действие не выполняется", () => {
  test("старый snapshot_id → stale, клика нет, в ответе свежий observe", async () => {
    fixture("observe.html");
    const click = vi.fn();
    document.getElementById("buy").addEventListener("click", click);
    const { agent } = setup();
    const o1 = (await agent.handle("page.observe", { tab_id: 11 })).data;
    await agent.handle("page.observe", { tab_id: 11 });
    const ref = o1.elements.find((e) => e.name === "Купить").ref;
    const r = await agent.handle("page.act", { tab_id: 11, snapshot_id: o1.snapshot_id, ref, op: "click" });
    expect(r).toMatchObject({ ok: false, status: "stale" });
    expect(click).not.toHaveBeenCalled();
    expect(r.observe.elements.length).toBeGreaterThan(0);
  });

  test("fill_form: устаревший ref в одном кадре — не заполняется ни один кадр", async () => {
    document.body.innerHTML = '<input aria-label="Имя">';
    const { agent, f5 } = setup({ frames: twoFrames });
    const o = (await agent.handle("page.observe", { tab_id: 11 })).data;
    const name = o.elements.find((e) => e.name === "Имя").ref;
    const r = await agent.handle("page.fill_form", { tab_id: 11, snapshot_id: o.snapshot_id, values: { [name]: "Анна", "f5:e9": "x" } });
    expect(r).toMatchObject({ status: "stale", data: { stale_refs: ["f5:e9"] } });
    expect(document.querySelector("input").value).toBe("");
    expect(f5.fill).not.toHaveBeenCalled();
  });

  test("fill_form по двум кадрам: ref в ответе с префиксом", async () => {
    document.body.innerHTML = '<input aria-label="Имя">';
    const { agent } = setup({ frames: twoFrames });
    const o = (await agent.handle("page.observe", { tab_id: 11 })).data;
    const name = o.elements.find((e) => e.name === "Имя").ref;
    const r = await agent.handle("page.fill_form", { tab_id: 11, snapshot_id: o.snapshot_id, values: { [name]: "Анна", "f5:e1": "1" } });
    expect(r.status).toBe("done");
    expect(r.data.fields.map((f) => f.ref).sort()).toEqual([name, "f5:e1"].sort());
    expect(document.querySelector("input").value).toBe("Анна");
  });
});

describe("forms / questions через background", () => {
  test("forms без снимка — сначала observe, ref с префиксом", async () => {
    fixture("forms.html");
    const { agent } = setup();
    const r = await agent.handle("page.forms", { tab_id: 11 });
    expect(r.status).toBe("done");
    expect(r.data.snapshot_id).toMatch(/^s/);
    expect(r.data.forms[0].fields[0].ref).toMatch(/^f0:e\d+$/);
    expect(r.data.forms[0].submit_refs[0]).toMatch(/^f0:e\d+$/);
  });

  test("questions: q_ref и варианты с префиксом", async () => {
    fixture("moodle_quiz.html");
    const { agent } = setup();
    const r = await agent.handle("page.questions", { tab_id: 11 });
    expect(r.data.questions).toHaveLength(4);
    expect(r.data.questions[0].q_ref).toMatch(/^f0:e\d+$/);
    expect(r.data.questions[0].options[0].ref).toMatch(/^f0:e\d+$/);
  });

  test("upload: файл по токену из ядра", async () => {
    globalThis.DataTransfer = class { constructor() { this.l = []; this.items = { add: (f) => this.l.push(f) }; } get files() { return this.l; } };
    document.body.innerHTML = '<div role="button" aria-label="Зона">Сюда</div>';
    const { agent, fetchUpload } = setup();
    const o = (await agent.handle("page.observe", { tab_id: 11 })).data;
    const r = await agent.handle("page.upload", { tab_id: 11, snapshot_id: o.snapshot_id, ref: o.elements[0].ref, file_token: "tok" });
    expect(fetchUpload).toHaveBeenCalledWith("tok");
    expect(r.status).toBe("done");
    delete globalThis.DataTransfer;
  });
});

describe("page.shot", () => {
  test("неактивная вкладка — unsupported, вкладку не активирует", async () => {
    const { agent, chrome, capture } = setup({ tabs: [{ id: 11, windowId: 7, active: false, url: "u", status: "complete" }] });
    const r = await agent.handle("page.shot", { tab_id: 11 });
    expect(r).toMatchObject({ ok: false, status: "unsupported" });
    expect(chrome.tabs.update).not.toHaveBeenCalled();
    expect(capture).not.toHaveBeenCalled();
  });

  test("window_id — активная вкладка окна агента, без активации", async () => {
    const { agent, chrome, capture, encodes } = setup();
    const r = await agent.handle("page.shot", { window_id: 7 });
    expect(r.status).toBe("done");
    expect(capture).toHaveBeenCalledWith(7, { format: "png" });
    expect(chrome.tabs.update).not.toHaveBeenCalled();
    expect(chrome.windows.create).not.toHaveBeenCalled();
    expect(r.data).toMatchObject({ mime: "image/jpeg", width: 1280, height: 960, quality: 60, tab_id: 11, window_id: 7 });
    expect(encodes[0].src).toEqual({ x: 0, y: 0, w: 2048, h: 1536 });
  });

  test("свёрнутое окно — unsupported", async () => {
    const { agent, chrome, capture } = setup();
    chrome.windows.get.mockResolvedValue({ id: 7, state: "minimized" });
    expect((await agent.handle("page.shot", { window_id: 7 })).status).toBe("unsupported");
    expect(capture).not.toHaveBeenCalled();
  });

  test("annotated: разметка до кадра и снятие после", async () => {
    document.body.innerHTML = "<button>Один</button>";
    const { agent, capture } = setup();
    await agent.handle("page.observe", { tab_id: 11 });
    let during = null;
    capture.mockImplementation(async () => {
      during = document.querySelectorAll("#__sakura_annot__ span").length;
      return "data:image/png;base64,AAAA";
    });
    const r = await agent.handle("page.shot", { tab_id: 11, mode: "annotated" });
    expect(r.status).toBe("done");
    expect(during).toBe(1);
    expect(document.getElementById("__sakura_annot__")).toBeNull();
  });

  test("crop_ref: обрезка по bbox + 16 px с учётом масштаба кадра, лимит 200 КБ", async () => {
    document.body.innerHTML = '<button data-rect="100,200,300,50">Цель</button>';
    const { agent, encodes, codec } = setup();
    const o = (await agent.handle("page.observe", { tab_id: 11 })).data;
    codec.decode.mockResolvedValue({ width: 2048, height: 1536 });   // окно 1024 CSS px → масштаб 2
    const r = await agent.handle("page.shot", { tab_id: 11, crop_ref: o.elements[0].ref });
    expect(r.status).toBe("done");
    expect(encodes[0].src).toEqual({ x: 168, y: 368, w: 664, h: 164 });
    expect(r.data.width).toBe(664);
  });

  test("ошибка захвата — unsupported, разметка снята", async () => {
    document.body.innerHTML = "<button>Один</button>";
    const { agent, capture } = setup();
    await agent.handle("page.observe", { tab_id: 11 });
    capture.mockRejectedValue(new Error("Cannot capture"));
    const r = await agent.handle("page.shot", { tab_id: 11, mode: "annotated" });
    expect(r.status).toBe("unsupported");
    expect(document.getElementById("__sakura_annot__")).toBeNull();
  });
});

describe("вкладки и окно агента", () => {
  test("tabs.list — поля по контракту", async () => {
    const { agent } = setup({ tabs: [{ id: 3, windowId: 1, title: "A", url: "https://a/", active: true, audible: true, mutedInfo: { muted: false }, pinned: true, groupId: -1, lastAccessed: 5 }] });
    const r = await agent.handle("tabs.list", {});
    expect(r.data).toEqual([{ tab_id: 3, window_id: 1, title: "A", url: "https://a/", active: true, audible: true, muted: false, pinned: true, group_id: -1, last_accessed: 5 }]);
  });

  test("agent_window.open — отдельное окно без фокуса", async () => {
    const { agent, chrome } = setup();
    const r = await agent.handle("agent_window.open", { url: "https://lms.example.edu/" });
    expect(r.data).toEqual({ window_id: 42, tab_id: 420, extra_tabs: 0, refocused: false });
    expect(chrome.windows.create.mock.calls[0][0]).toMatchObject({ url: "https://lms.example.edu/", focused: false });
    expect(chrome.windows.update).not.toHaveBeenCalled();
    expect(chrome.tabs.remove).not.toHaveBeenCalled();
  });

  test("Opera GX: наша вкладка активна, стартовая GX Corner не закрывается (remove в Opera зависает); фокус — окну пользователя", async () => {
    const tabs = [{ id: 11, windowId: 7, active: true, url: "https://shop.example/", status: "complete" }];
    const { agent, chrome } = setup({ tabs });
    chrome.windows.create.mockImplementation(async (p) => {
      tabs.push({ id: 500, windowId: 42, active: true, url: "https://gxcorner.games/" });
      tabs.push({ id: 501, windowId: 42, active: false, url: "", pendingUrl: p.url });
      return { id: 42, tabs: [{ id: 500 }] };
    });
    chrome.windows.get.mockImplementation(async (id) => ({ id, state: "normal", focused: id === 42 }));
    const r = await agent.handle("agent_window.open", { url: "https://lms.example.edu/" });
    expect(r.data).toEqual({ window_id: 42, tab_id: 501, extra_tabs: 1, refocused: true });
    expect(chrome.tabs.update).toHaveBeenCalledWith(501, { active: true });
    expect(chrome.tabs.remove).not.toHaveBeenCalled();
    expect(chrome.windows.update).toHaveBeenCalledWith(7, { focused: true });
  });

  test("Opera GX забрала фокус, а браузер до этого был не в фокусе — окно агента снимается с фокуса", async () => {
    const { agent, chrome } = setup();
    chrome.windows.getLastFocused.mockResolvedValue({ id: 7, focused: false });
    chrome.windows.get.mockImplementation(async (id) => ({ id, state: "normal", focused: id === 42 }));
    const r = await agent.handle("agent_window.open", { url: "about:blank" });
    expect(r.data.refocused).toBe(true);
    expect(chrome.windows.update).toHaveBeenCalledWith(42, { focused: false });
  });

  test("tabs.activate не фокусирует окно; tabs.new отвергает javascript:", async () => {
    const { agent, chrome } = setup();
    expect((await agent.handle("tabs.activate", { tab_id: 11 })).status).toBe("done");
    expect(chrome.tabs.update).toHaveBeenCalledWith(11, { active: true });
    expect((await agent.handle("tabs.new", { url: "javascript:alert(1)" })).status).toBe("error");
    expect(chrome.tabs.create).not.toHaveBeenCalled();
    expect((await agent.handle("tabs.new", { url: "example.org", window_id: 7 })).data).toEqual({ tab_id: 99, window_id: 7 });
    expect(chrome.tabs.create).toHaveBeenCalledWith({ url: "https://example.org/", active: true, windowId: 7 });
  });

  test("неизвестная вкладка — not_found; неизвестное действие — unsupported", async () => {
    const { agent } = setup();
    expect((await agent.handle("tabs.close", { tab_id: 5 })).status).toBe("not_found");
    expect((await agent.handle("page.nope", {})).status).toBe("unsupported");
  });
});

test("SakuraCapture доступен для lib/agent.js", () => {
  expect(typeof SakuraCapture.compress).toBe("function");
});
