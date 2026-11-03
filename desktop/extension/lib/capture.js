/**
 * lib/capture.js — захват кадра вкладки для агента браузера (page.shot).
 *
 *   createQueue — очередь captureVisibleTab: вызовы по одному, не чаще 2 в секунду
 *                 (лимит Chrome MAX_CAPTURE_VISIBLE_TAB_CALLS_PER_SECOND);
 *   compress    — JPEG: ширина ≤ 1280, q60, ≤ 400 КБ (обрезка ≤ 200 КБ);
 *                 больше лимита — q50, затем ширина 1024;
 *   cropRect    — прямоугольник обрезки по bbox элемента + 16 px.
 *
 * Кадры не логируются и не сохраняются. Кодек (decode/encode) подменяется в тестах.
 */

(function (root) {
  const LIMITS = { page: 400 * 1024, crop: 200 * 1024 };
  const MAX_WIDTH = 1280;
  const FALLBACK_WIDTH = 1024;
  const CROP_PAD = 16;
  const MIN_INTERVAL_MS = 500;
  // Ступени качества: q60 → q50 → ширина 1024 при q50.
  const STEPS = [
    { width: MAX_WIDTH, quality: 0.6 },
    { width: MAX_WIDTH, quality: 0.5 },
    { width: FALLBACK_WIDTH, quality: 0.5 },
  ];

  const defaultSleep = (ms) => new Promise((r) => setTimeout(r, ms));

  function createQueue({ capture, minInterval = MIN_INTERVAL_MS, now = () => Date.now(), sleep = defaultSleep }) {
    let last = -Infinity;
    let chain = Promise.resolve();
    return function enqueue(windowId, options) {
      const run = async () => {
        const wait = last + minInterval - now();
        if (wait > 0) await sleep(wait);
        last = now();
        return capture(windowId, options);
      };
      const p = chain.then(run, run);
      chain = p.catch(() => {});
      return p;
    };
  }

  // bbox [x, y, w, h] в CSS-пикселях окна → прямоугольник в пикселях кадра (scale = кадр / окно).
  function cropRect(bbox, imgW, imgH, scale) {
    const s = scale > 0 ? scale : 1;
    const x0 = Math.max(0, Math.floor((bbox[0] - CROP_PAD) * s));
    const y0 = Math.max(0, Math.floor((bbox[1] - CROP_PAD) * s));
    const x1 = Math.min(imgW, Math.ceil((bbox[0] + bbox[2] + CROP_PAD) * s));
    const y1 = Math.min(imgH, Math.ceil((bbox[1] + bbox[3] + CROP_PAD) * s));
    if (x1 - x0 < 1 || y1 - y0 < 1) return null;
    return { x: x0, y: y0, w: x1 - x0, h: y1 - y0 };
  }

  function toBase64(bytes) {
    let bin = "";
    const CHUNK = 0x8000;
    for (let i = 0; i < bytes.length; i += CHUNK) {
      bin += String.fromCharCode.apply(null, bytes.subarray(i, i + CHUNK));
    }
    return btoa(bin);
  }

  // Кодек service worker: createImageBitmap + OffscreenCanvas.
  const defaultCodec = {
    async decode(dataUrl) {
      const blob = await (await fetch(dataUrl)).blob();
      const bmp = await createImageBitmap(blob);
      return { width: bmp.width, height: bmp.height, source: bmp, close: () => bmp.close() };
    },
    async encode(img, src, width, height, quality) {
      const canvas = new OffscreenCanvas(width, height);
      const ctx = canvas.getContext("2d");
      ctx.drawImage(img.source, src.x, src.y, src.w, src.h, 0, 0, width, height);
      const blob = await canvas.convertToBlob({ type: "image/jpeg", quality });
      return new Uint8Array(await blob.arrayBuffer());
    },
  };

  /**
   * dataUrl кадра → {mime, data_b64, width, height, quality, bytes, over_limit}.
   * opts: crop (bbox CSS px), viewportWidth (для масштаба обрезки), limit, codec.
   */
  async function compress(dataUrl, opts = {}) {
    const codec = opts.codec || defaultCodec;
    const crop = !!opts.crop;
    const limit = opts.limit || (crop ? LIMITS.crop : LIMITS.page);
    const img = await codec.decode(dataUrl);
    try {
      let src = { x: 0, y: 0, w: img.width, h: img.height };
      if (crop) {
        const scale = opts.viewportWidth ? img.width / opts.viewportWidth : 1;
        src = cropRect(opts.crop, img.width, img.height, scale);
        if (!src) throw new Error("элемент вне кадра");
      }
      let out = null;
      for (const step of STEPS) {
        const width = Math.max(1, Math.min(step.width, src.w));
        const height = Math.max(1, Math.round(src.h * width / src.w));
        const bytes = await codec.encode(img, src, width, height, step.quality);
        out = { bytes, width, height, quality: Math.round(step.quality * 100) };
        if (bytes.length <= limit) break;
      }
      return {
        mime: "image/jpeg", data_b64: toBase64(out.bytes), width: out.width, height: out.height,
        quality: out.quality, bytes: out.bytes.length, over_limit: out.bytes.length > limit,
      };
    } finally {
      if (typeof img.close === "function") img.close();
    }
  }

  root.SakuraCapture = { LIMITS, MAX_WIDTH, FALLBACK_WIDTH, CROP_PAD, MIN_INTERVAL_MS, createQueue, cropRect, compress, toBase64 };
})(globalThis);
