/**
 * СКАЗАНИЕ О ДУХЕ ЦВЕТУЩЕЙ САКУРЫ — живые части страницы:
 * сфера духа SakuraCore, переключатель видений, свитки (фильтр и
 * разворачивание), подсветка раздела в навигации и счётчики печатей.
 */

document.addEventListener("DOMContentLoaded", () => {
  initCoreSimulator();
  initVideoPlayer();
  initScrolls();
  initNavSpy();
  initSealCounters();
});

const REDUCED_MOTION = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

/* ==========================================================================
   1. СФЕРА ДУХА — SakuraCore
   Те же цвета и повадки, что у живого ядра на рабочем столе Мастера.
   ========================================================================== */
function initCoreSimulator() {
  const canvas = document.getElementById("core-canvas");
  if (!canvas) return;
  const ctx = canvas.getContext("2d");

  const SIZE = 320;
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  canvas.width = SIZE * dpr;
  canvas.height = SIZE * dpr;
  ctx.scale(dpr, dpr);
  const cx = SIZE / 2;
  const cy = SIZE / 2;

  const STATES = {
    idle: { color: "#FF6AE3", deep: "#3E0074", glow: "rgba(255, 106, 227, 0.42)", kana: "待機中", label: "Тихое дыхание", speed: 1.0, rings: 2 },
    listening: { color: "#4FD8FF", deep: "#1B2A8F", glow: "rgba(79, 216, 255, 0.5)", kana: "聴取中", label: "Внемлет Мастеру", speed: 1.8, rings: 3 },
    thinking: { color: "#FFCF6B", deep: "#6B1F7A", glow: "rgba(255, 207, 107, 0.46)", kana: "思考中", label: "Раздумье", speed: 2.2, rings: 3 },
    speaking: { color: "#FF7EB9", deep: "#5A0F8C", glow: "rgba(255, 126, 185, 0.55)", kana: "発話中", label: "Живой голос", speed: 2.5, rings: 4 },
    offline: { color: "#6B6475", deep: "#1D1628", glow: "rgba(107, 100, 117, 0.2)", kana: "切断", label: "Сон вдали от Мастера", speed: 0.3, rings: 1 },
  };

  let current = "idle";
  let level = 0.2;
  let speaking = false;
  const start = performance.now();

  const stateBtns = document.querySelectorAll(".state-btn");
  const badgeText = document.getElementById("sim-state-text");
  const badgeKana = document.getElementById("sim-state-kana");
  stateBtns.forEach((btn) => {
    btn.addEventListener("click", () => {
      const st = STATES[btn.dataset.state];
      if (!st) return;
      current = btn.dataset.state;
      stateBtns.forEach((b) => {
        b.classList.toggle("active", b === btn);
        b.setAttribute("aria-pressed", String(b === btn));
      });
      if (badgeText) badgeText.textContent = st.label;
      if (badgeKana) {
        badgeKana.textContent = st.kana;
        badgeKana.style.color = st.color;
      }
    });
  });

  const slider = document.getElementById("audio-level-slider");
  const sliderVal = document.getElementById("slider-val-text");
  if (slider) {
    slider.addEventListener("input", (e) => {
      level = parseFloat(e.target.value);
      if (sliderVal) sliderVal.textContent = `${Math.round(level * 100)}%`;
      setSpeaking(false);
    });
  }

  const micBtn = document.getElementById("toggle-mic-btn");
  function setSpeaking(on) {
    speaking = on;
    if (!micBtn) return;
    micBtn.setAttribute("aria-pressed", String(on));
    micBtn.textContent = on ? "Дух говорит — остановить" : "Пусть дух заговорит";
  }
  if (micBtn) micBtn.addEventListener("click", () => setSpeaking(!speaking));

  let visible = true;
  if ("IntersectionObserver" in window) {
    new IntersectionObserver((entries) => {
      visible = entries[0].isIntersecting;
      if (visible) requestAnimationFrame(draw);
    }).observe(canvas);
  }

  function draw(now) {
    const t = ((now || performance.now()) - start) / 1000;
    const st = STATES[current];

    let lv = level;
    if (speaking) {
      lv = 0.3 + 0.45 * Math.abs(Math.sin(t * 8) * Math.cos(t * 3.3));
      if (slider) slider.value = lv;
      if (sliderVal) sliderVal.textContent = `${Math.round(lv * 100)}%`;
    }

    ctx.clearRect(0, 0, SIZE, SIZE);

    const halo = ctx.createRadialGradient(cx, cy, 20, cx, cy, 150);
    halo.addColorStop(0, st.glow);
    halo.addColorStop(1, "rgba(0, 0, 0, 0)");
    ctx.fillStyle = halo;
    ctx.beginPath();
    ctx.arc(cx, cy, 150, 0, Math.PI * 2);
    ctx.fill();

    for (let r = 1; r <= st.rings; r++) {
      const rr = 60 + r * 22 + Math.sin(t * st.speed * 2 + r) * (6 + lv * 12);
      ctx.beginPath();
      ctx.arc(cx, cy, rr, 0, Math.PI * 2);
      ctx.strokeStyle = st.color;
      ctx.lineWidth = 1.5;
      ctx.globalAlpha = Math.max(0.1, 0.45 - r * 0.1);
      ctx.stroke();
      ctx.globalAlpha = 1;
    }

    const sats = current === "offline" ? 1 : 4;
    for (let i = 0; i < sats; i++) {
      const a = t * st.speed * 1.6 + i * ((Math.PI * 2) / sats);
      const dist = 72 + Math.sin(t * 3 + i) * 8 + lv * 14;
      const sx = cx + dist * Math.cos(a);
      const sy = cy + dist * 0.55 * Math.sin(a);
      ctx.beginPath();
      ctx.arc(sx, sy, 3.5 + Math.sin(t * 4 + i) * 1.2, 0, Math.PI * 2);
      ctx.fillStyle = "#ffffff";
      ctx.shadowColor = st.color;
      ctx.shadowBlur = 8;
      ctx.fill();
      ctx.shadowBlur = 0;
    }

    const dropR = 38 + lv * 18 + Math.sin(t * st.speed * 2) * 3;
    const drop = ctx.createRadialGradient(cx - 10, cy - 12, 5, cx, cy, dropR);
    drop.addColorStop(0, st.color);
    drop.addColorStop(0.7, st.deep);
    drop.addColorStop(1, "#0a0614");
    ctx.beginPath();
    ctx.arc(cx, cy, dropR, 0, Math.PI * 2);
    ctx.fillStyle = drop;
    ctx.shadowColor = st.color;
    ctx.shadowBlur = 24;
    ctx.fill();
    ctx.shadowBlur = 0;
    ctx.strokeStyle = "rgba(255, 255, 255, 0.9)";
    ctx.lineWidth = 2.5;
    ctx.stroke();

    ctx.beginPath();
    ctx.ellipse(cx - 12, cy - 14, 12, 6, -Math.PI / 4, 0, Math.PI * 2);
    ctx.fillStyle = "rgba(255, 255, 255, 0.65)";
    ctx.fill();

    if (visible && !REDUCED_MOTION) requestAnimationFrame(draw);
  }

  requestAnimationFrame(draw);
  if (REDUCED_MOTION) {
    // без анимации — перерисовываем только по действию
    document.querySelectorAll(".state-btn, #audio-level-slider").forEach((el) =>
      el.addEventListener(el.tagName === "INPUT" ? "input" : "click", () => requestAnimationFrame(draw)));
  }
}

/* ==========================================================================
   2. ПЕРЕКЛЮЧАТЕЛЬ ВИДЕНИЙ
   ========================================================================== */
function initVideoPlayer() {
  const player = document.getElementById("hero-main-video");
  if (!player) return;
  const tabs = document.querySelectorAll(".v-tab-btn");
  const title = document.getElementById("player-current-title");
  const meta = document.getElementById("player-current-meta");

  const VIDEOS = {
    scrolls: {
      name: "sakura-legend-five-scrolls",
      title: "Пять Свитков: пролог, пять эпох и их Печати Времени",
      meta: "1080p · 30 секунд · MP4 и WebM",
    },
    armor: {
      name: "sakura-legend-invisible-armor",
      title: "Незримый Доспех: две вести, купол и отвергнутый ворон",
      meta: "1080p · 21 секунда · MP4 и WebM",
    },
    trials: {
      name: "sakura-legend-3383-trials",
      title: "Три Тысячи Испытаний: 3 383 бутона и печать 合格",
      meta: "1080p · 20 секунд · MP4 и WebM",
    },
  };

  if (REDUCED_MOTION) {
    player.removeAttribute("autoplay");
    player.pause();
  }

  tabs.forEach((btn) => {
    btn.addEventListener("click", () => {
      const v = VIDEOS[btn.dataset.video];
      if (!v) return;
      tabs.forEach((b) => {
        b.classList.toggle("active", b === btn);
        b.setAttribute("aria-pressed", String(b === btn));
      });
      player.pause();
      player.poster = `media/images/posters/${v.name}.jpg`;
      player.replaceChildren(
        Object.assign(document.createElement("source"), { src: `media/videos/${v.name}.mp4`, type: "video/mp4" }),
        Object.assign(document.createElement("source"), { src: `media/videos/${v.name}.webm`, type: "video/webm" }),
      );
      player.load();
      if (!REDUCED_MOTION) player.play().catch(() => {});
      if (title) title.textContent = v.title;
      if (meta) meta.textContent = v.meta;
    });
  });
}

/* ==========================================================================
   3. СВИТКИ — фильтр и разворачивание при появлении
   ========================================================================== */
function initScrolls() {
  const cards = document.querySelectorAll(".scroll-card");
  const buttons = document.querySelectorAll(".filter-btn");

  const open = (card) => card.classList.add("is-open");
  if ("IntersectionObserver" in window && !REDUCED_MOTION) {
    // Порог 0: свиток раскрывается, как только его край вошёл в кадр. Порог в долях
    // высоты не годится — на узком экране свиток в 4–5 тысяч пикселей до него не доходил.
    const io = new IntersectionObserver(
      (entries) => entries.forEach((e) => {
        if (e.isIntersecting) {
          open(e.target);
          io.unobserve(e.target);
        }
      }),
      { threshold: 0, rootMargin: "0px 0px -10% 0px" },
    );
    cards.forEach((c) => io.observe(c));
    // страховка: всё, что уже выше нижнего края экрана (переход по якорю, печать), открыто
    const sweep = () => cards.forEach((c) => {
      if (!c.classList.contains("is-open") && c.getBoundingClientRect().top < window.innerHeight) open(c);
    });
    window.addEventListener("hashchange", () => setTimeout(sweep, 50));
    window.addEventListener("beforeprint", () => cards.forEach(open));
    setTimeout(sweep, 400);
  } else {
    cards.forEach(open);
  }

  buttons.forEach((btn) => {
    btn.addEventListener("click", () => {
      const which = btn.dataset.scroll;
      buttons.forEach((b) => {
        b.classList.toggle("active", b === btn);
        b.setAttribute("aria-pressed", String(b === btn));
      });
      cards.forEach((card) => {
        const show = which === "all" || card.dataset.scroll === which;
        card.hidden = !show;
        if (show) open(card);
      });
    });
  });
}

/* ==========================================================================
   4. ПОДСВЕТКА РАЗДЕЛА В НАВИГАЦИИ
   ========================================================================== */
function initNavSpy() {
  const links = [...document.querySelectorAll(".nav-link")];
  const sections = links.map((a) => document.querySelector(a.getAttribute("href"))).filter(Boolean);
  if (!("IntersectionObserver" in window) || !sections.length) return;
  const io = new IntersectionObserver(
    (entries) => entries.forEach((e) => {
      if (!e.isIntersecting) return;
      links.forEach((a) => {
        const on = a.getAttribute("href") === `#${e.target.id}`;
        a.classList.toggle("active", on);
        if (on) a.setAttribute("aria-current", "true");
        else a.removeAttribute("aria-current");
      });
    }),
    { rootMargin: "-45% 0px -50% 0px" },
  );
  sections.forEach((s) => io.observe(s));
}

/* ==========================================================================
   5. СЧЁТЧИКИ ПЕЧАТЕЙ
   В разметке уже стоят итоговые числа — без JS страница честна и так.
   ========================================================================== */
function initSealCounters() {
  const counters = document.querySelectorAll(".seal-value[data-target]");
  const section = document.querySelector(".seals-section");
  if (!counters.length || !section || REDUCED_MOTION || !("IntersectionObserver" in window)) return;

  const fmt = (el, v) => {
    const dec = parseInt(el.dataset.decimals || "0", 10);
    const num = v.toLocaleString("ru-RU", { minimumFractionDigits: dec, maximumFractionDigits: dec });
    return `${el.dataset.prefix || ""}${dec ? num.replace(",", ".") : num}${el.dataset.suffix || ""}`;
  };

  const io = new IntersectionObserver((entries) => {
    if (!entries[0].isIntersecting) return;
    io.disconnect();
    counters.forEach((el) => {
      const target = parseFloat(el.dataset.target);
      const t0 = performance.now();
      const step = (now) => {
        const p = Math.min((now - t0) / 1600, 1);
        const eased = 1 - Math.pow(1 - p, 3);
        el.textContent = fmt(el, p < 1 ? target * eased : target);
        if (p < 1) requestAnimationFrame(step);
      };
      requestAnimationFrame(step);
    });
  }, { threshold: 0.35 });
  io.observe(section);
}
