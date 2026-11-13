/**
 * SAKURA AI — INTERACTIVE APPLICATION SCRIPT
 * Handles Core Orb Canvas simulation, video switching, timeline filtering,
 * architecture tabs, and metrics counters.
 */

document.addEventListener("DOMContentLoaded", () => {
  initCoreSimulator();
  initVideoPlayer();
  initTimelineFilters();
  initArchTabs();
  initMetricCounters();
  initCopyButtons();
});

/* ==========================================================================
   1. SAKURA CORE ORB CANVAS SIMULATOR
   (Faithfully adapted from desktop/ui/src/core-gfx/coreFrame.ts & stateStyle.ts)
   ========================================================================== */
function initCoreSimulator() {
  const canvas = document.getElementById("core-canvas");
  if (!canvas) return;
  const ctx = canvas.getContext("2d");

  const W = (canvas.width = 320);
  const H = (canvas.height = 320);
  const cx = W / 2;
  const cy = H / 2;

  const STATES = {
    idle: {
      color: "#FF6AE3",
      deep: "#3E0074",
      glow: "rgba(255, 106, 227, 0.45)",
      kana: "待機中",
      label: "Онлайн (待機中)",
      speed: 1.0,
      ringCount: 2,
    },
    listening: {
      color: "#4FD8FF",
      deep: "#1B2A8F",
      glow: "rgba(79, 216, 255, 0.55)",
      kana: "聴取中",
      label: "Слушаю (聴取中)",
      speed: 1.8,
      ringCount: 3,
    },
    thinking: {
      color: "#FFCF6B",
      deep: "#6B1F7A",
      glow: "rgba(255, 207, 107, 0.50)",
      kana: "思考中",
      label: "Думаю (思考中)",
      speed: 2.2,
      ringCount: 3,
    },
    speaking: {
      color: "#FF7EB9",
      deep: "#5A0F8C",
      glow: "rgba(255, 126, 185, 0.60)",
      kana: "発話中",
      label: "Говорю (発話中)",
      speed: 2.5,
      ringCount: 4,
    },
    offline: {
      color: "#6B6475",
      deep: "#1D1628",
      glow: "rgba(107, 100, 117, 0.20)",
      kana: "切断",
      label: "Нет связи (切断)",
      speed: 0.3,
      ringCount: 1,
    },
  };

  let currentState = "idle";
  let manualAudioLevel = 0.2;
  let isSimulatingMic = false;
  let startTime = performance.now();

  // State button listeners
  const stateBtns = document.querySelectorAll(".state-btn");
  const stateBadgeText = document.getElementById("sim-state-text");
  const stateBadgeKana = document.getElementById("sim-state-kana");

  stateBtns.forEach((btn) => {
    btn.addEventListener("click", () => {
      const state = btn.dataset.state;
      if (STATES[state]) {
        currentState = state;
        stateBtns.forEach((b) => b.classList.remove("active"));
        btn.classList.add("active");

        if (stateBadgeText) stateBadgeText.textContent = STATES[state].label;
        if (stateBadgeKana) stateBadgeKana.textContent = STATES[state].kana;
        if (stateBadgeKana) stateBadgeKana.style.color = STATES[state].color;
      }
    });
  });

  // Audio level slider
  const slider = document.getElementById("audio-level-slider");
  const sliderVal = document.getElementById("slider-val-text");
  if (slider) {
    slider.addEventListener("input", (e) => {
      manualAudioLevel = parseFloat(e.target.value);
      if (sliderVal) sliderVal.textContent = `${Math.round(manualAudioLevel * 100)}%`;
      isSimulatingMic = false;
    });
  }

  // Mic test toggle
  const micBtn = document.getElementById("toggle-mic-btn");
  if (micBtn) {
    micBtn.addEventListener("click", () => {
      isSimulatingMic = !isSimulatingMic;
      micBtn.classList.toggle("active", isSimulatingMic);
      micBtn.textContent = isSimulatingMic ? "Микрофон: АКТИВЕН" : "Включить симуляцию речи";
    });
  }

  function drawFrame() {
    const now = performance.now();
    const t = (now - startTime) / 1000;
    const style = STATES[currentState];

    let effectiveLevel = manualAudioLevel;
    if (isSimulatingMic) {
      effectiveLevel = 0.3 + 0.45 * Math.abs(Math.sin(t * 8) * Math.cos(t * 3.3));
      if (slider) slider.value = effectiveLevel;
      if (sliderVal) sliderVal.textContent = `${Math.round(effectiveLevel * 100)}%`;
    }

    ctx.clearRect(0, 0, W, H);

    // Radial background glow
    const bgGrad = ctx.createRadialGradient(cx, cy, 20, cx, cy, 140);
    bgGrad.addColorStop(0, style.glow);
    bgGrad.addColorStop(1, "rgba(0, 0, 0, 0)");
    ctx.fillStyle = bgGrad;
    ctx.beginPath();
    ctx.arc(cx, cy, 140, 0, Math.PI * 2);
    ctx.fill();

    // Concentric outer ripple rings
    for (let r = 1; r <= style.ringCount; r++) {
      const ringRadius = 60 + r * 22 + Math.sin(t * style.speed * 2 + r) * (6 + effectiveLevel * 12);
      ctx.beginPath();
      ctx.arc(cx, cy, ringRadius, 0, Math.PI * 2);
      ctx.strokeStyle = style.color;
      ctx.lineWidth = 1.5;
      ctx.globalAlpha = Math.max(0.1, 0.45 - r * 0.1);
      ctx.stroke();
      ctx.globalAlpha = 1.0;
    }

    // Orbiting Satellites (from coreFrame.ts)
    const satCount = currentState === "offline" ? 1 : 4;
    for (let i = 0; i < satCount; i++) {
      const satAng = t * style.speed * 1.6 + i * ((Math.PI * 2) / satCount);
      const satDist = 72 + Math.sin(t * 3 + i) * 8 + effectiveLevel * 14;
      const sx = cx + satDist * Math.cos(satAng);
      const sy = cy + satDist * 0.55 * Math.sin(satAng);
      const satR = 3.5 + Math.sin(t * 4 + i) * 1.2;

      ctx.beginPath();
      ctx.arc(sx, sy, satR, 0, Math.PI * 2);
      ctx.fillStyle = "#ffffff";
      ctx.shadowColor = style.color;
      ctx.shadowBlur = 8;
      ctx.fill();
      ctx.shadowBlur = 0;
    }

    // Main Liquid Drop (Sakura Drop Core)
    const dropR = 38 + effectiveLevel * 18 + Math.sin(t * style.speed * 2) * 3;
    const dropGrad = ctx.createRadialGradient(cx - 10, cy - 12, 5, cx, cy, dropR);
    dropGrad.addColorStop(0, style.color);
    dropGrad.addColorStop(0.7, style.deep);
    dropGrad.addColorStop(1, "#0a0614");

    ctx.beginPath();
    ctx.arc(cx, cy, dropR, 0, Math.PI * 2);
    ctx.fillStyle = dropGrad;
    ctx.shadowColor = style.color;
    ctx.shadowBlur = 24;
    ctx.fill();
    ctx.shadowBlur = 0;

    ctx.strokeStyle = "#ffffff";
    ctx.lineWidth = 2.5;
    ctx.stroke();

    // Specular glossy reflection
    ctx.beginPath();
    ctx.ellipse(cx - 12, cy - 14, 12, 6, -Math.PI / 4, 0, Math.PI * 2);
    ctx.fillStyle = "rgba(255, 255, 255, 0.65)";
    ctx.fill();

    requestAnimationFrame(drawFrame);
  }

  drawFrame();
}

/* ==========================================================================
   2. HERO VIDEO SWITCHER
   ========================================================================== */
function initVideoPlayer() {
  const player = document.getElementById("hero-main-video");
  const tabBtns = document.querySelectorAll(".v-tab-btn");
  const videoTitle = document.getElementById("player-current-title");
  const videoMeta = document.getElementById("player-current-meta");

  if (!player) return;

  const VIDEOS = {
    hud: {
      mp4: "media/videos/sakura-hud-voice-core.mp4",
      webm: "media/videos/sakura-hud-voice-core.webm",
      title: "Голосовой HUD и аудио-волна (GigaAM + Silero VAD)",
      meta: "1080p Full HD • H.264 / VP8 • 12 Мбит/с",
    },
    noise: {
      mp4: "media/videos/sakura-noise-handshake.mp4",
      webm: "media/videos/sakura-noise-handshake.webm",
      title: "Криптографический протокол Noise_IK_25519_ChaChaPoly_BLAKE2s",
      meta: "1080p Full HD • ProVerif доказан • DPAPI ключи",
    },
    tests: {
      mp4: "media/videos/sakura-test-suite-3297.mp4",
      webm: "media/videos/sakura-test-suite-3297.webm",
      title: "Прогон CI/CD матрицы: 3 297+ проходящих автотестов",
      meta: "1080p Full HD • 0 регрессий • 100% Green",
    },
  };

  tabBtns.forEach((btn) => {
    btn.addEventListener("click", () => {
      const vKey = btn.dataset.video;
      const vData = VIDEOS[vKey];
      if (!vData) return;

      tabBtns.forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");

      // Smooth switch video source
      player.pause();
      player.innerHTML = `
        <source src="${vData.mp4}" type="video/mp4">
        <source src="${vData.webm}" type="video/webm">
        Ваш браузер не поддерживает воспроизведение HTML5 видео.
      `;
      player.load();
      player.play().catch(() => {});

      if (videoTitle) videoTitle.textContent = vData.title;
      if (videoMeta) videoMeta.textContent = vData.meta;
    });
  });
}

/* ==========================================================================
   3. TIMELINE FILTER
   ========================================================================== */
function initTimelineFilters() {
  const filterBtns = document.querySelectorAll(".filter-btn");
  const timelineItems = document.querySelectorAll(".timeline-item");

  filterBtns.forEach((btn) => {
    btn.addEventListener("click", () => {
      filterBtns.forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");

      const epoch = btn.dataset.epoch;
      timelineItems.forEach((item) => {
        if (epoch === "all" || item.dataset.epoch === epoch) {
          item.style.display = "block";
        } else {
          item.style.display = "none";
        }
      });
    });
  });
}

/* ==========================================================================
   4. ARCHITECTURE TABS
   ========================================================================== */
function initArchTabs() {
  const tabBtns = document.querySelectorAll(".arch-tab-btn");
  const panels = document.querySelectorAll(".arch-panel");

  tabBtns.forEach((btn) => {
    btn.addEventListener("click", () => {
      tabBtns.forEach((b) => b.classList.remove("active"));
      panels.forEach((p) => p.classList.remove("active"));

      btn.classList.add("active");
      const targetId = btn.dataset.panel;
      const targetPanel = document.getElementById(targetId);
      if (targetPanel) {
        targetPanel.classList.add("active");
      }
    });
  });
}

/* ==========================================================================
   5. METRIC COUNTERS (ANIMATED COUNT-UP)
   ========================================================================== */
function initMetricCounters() {
  const counters = document.querySelectorAll(".metric-value[data-target]");
  let started = false;

  const observer = new IntersectionObserver(
    (entries) => {
      if (entries[0].isIntersecting && !started) {
        started = true;
        counters.forEach((counter) => {
          const target = parseInt(counter.dataset.target, 10);
          const duration = 1800;
          const start = performance.now();

          function step(now) {
            const progress = Math.min((now - start) / duration, 1);
            const current = Math.floor(progress * target);
            counter.textContent = current.toLocaleString("ru-RU");
            if (progress < 1) {
              requestAnimationFrame(step);
            } else {
              counter.textContent = target.toLocaleString("ru-RU") + (counter.dataset.suffix || "");
            }
          }
          requestAnimationFrame(step);
        });
      }
    },
    { threshold: 0.3 }
  );

  const metricsSection = document.querySelector(".metrics-section");
  if (metricsSection) observer.observe(metricsSection);
}

/* ==========================================================================
   6. COPY TO CLIPBOARD BUTTONS
   ========================================================================== */
function initCopyButtons() {
  const copyBtns = document.querySelectorAll(".copy-btn");
  copyBtns.forEach((btn) => {
    btn.addEventListener("click", () => {
      const codeId = btn.dataset.copyTarget;
      const codeEl = document.getElementById(codeId);
      if (codeEl) {
        navigator.clipboard.writeText(codeEl.innerText).then(() => {
          const origText = btn.textContent;
          btn.textContent = "Скопировано!";
          btn.style.borderColor = "var(--accent-green)";
          btn.style.color = "var(--accent-green)";
          setTimeout(() => {
            btn.textContent = origText;
            btn.style.borderColor = "";
            btn.style.color = "";
          }, 2000);
        });
      }
    });
  });
}
