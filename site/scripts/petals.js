/**
 * Floating Sakura Petals Canvas Particle System
 * Elegant, subtle, reactive to wind and cursor movement.
 */

(function () {
  const canvas = document.getElementById("petals-canvas");
  if (!canvas) return;
  const ctx = canvas.getContext("2d");

  let width = (canvas.width = window.innerWidth);
  let height = (canvas.height = window.innerHeight);

  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (reducedMotion) return;

  const PETAL_COUNT = 38;
  const petals = [];

  class Petal {
    constructor() {
      this.reset(true);
    }

    reset(initial = false) {
      this.x = Math.random() * width;
      this.y = initial ? Math.random() * height : -30;
      this.size = 8 + Math.random() * 12;
      this.speedY = 1.2 + Math.random() * 2.2;
      this.speedX = -0.8 + Math.random() * 1.6;
      this.rot = Math.random() * Math.PI * 2;
      this.rotSpeed = (Math.random() - 0.5) * 0.03;
      this.flip = Math.random() * Math.PI;
      this.flipSpeed = 0.02 + Math.random() * 0.03;
      this.opacity = 0.35 + Math.random() * 0.45;
      this.sway = Math.random() * 2;
      this.swaySpeed = 0.015 + Math.random() * 0.02;
    }

    update(mouseX, mouseY) {
      this.y += this.speedY;
      this.x += this.speedX + Math.sin(this.sway) * 1.2;
      this.sway += this.swaySpeed;
      this.rot += this.rotSpeed;
      this.flip += this.flipSpeed;

      // Cursor gentle wind interaction
      if (mouseX !== null && mouseY !== null) {
        const dx = this.x - mouseX;
        const dy = this.y - mouseY;
        const dist = Math.sqrt(dx * dx + dy * dy);
        if (dist < 140) {
          const force = (1 - dist / 140) * 2;
          this.x += (dx / dist) * force;
          this.y += (dy / dist) * force;
        }
      }

      if (this.y > height + 40 || this.x < -40 || this.x > width + 40) {
        this.reset();
      }
    }

    draw(ctx) {
      ctx.save();
      ctx.translate(this.x, this.y);
      ctx.rotate(this.rot);
      ctx.scale(1, Math.cos(this.flip));

      ctx.beginPath();
      ctx.moveTo(0, 0);
      ctx.bezierCurveTo(
        -this.size / 2, -this.size / 2,
        -this.size / 2, this.size / 2,
        0, this.size
      );
      ctx.bezierCurveTo(
        this.size / 2, this.size / 2,
        this.size / 2, -this.size / 2,
        0, 0
      );

      const grad = ctx.createLinearGradient(-this.size / 2, 0, this.size / 2, this.size);
      grad.addColorStop(0, `rgba(255, 182, 193, ${this.opacity})`);
      grad.addColorStop(1, `rgba(255, 106, 227, ${this.opacity * 0.7})`);

      ctx.fillStyle = grad;
      ctx.fill();
      ctx.restore();
    }
  }

  for (let i = 0; i < PETAL_COUNT; i++) {
    petals.push(new Petal());
  }

  let mouseX = null;
  let mouseY = null;

  window.addEventListener("mousemove", (e) => {
    mouseX = e.clientX;
    mouseY = e.clientY;
  });

  window.addEventListener("mouseleave", () => {
    mouseX = null;
    mouseY = null;
  });

  window.addEventListener("resize", () => {
    width = canvas.width = window.innerWidth;
    height = canvas.height = window.innerHeight;
  });

  function render() {
    ctx.clearRect(0, 0, width, height);
    for (let i = 0; i < petals.length; i++) {
      petals[i].update(mouseX, mouseY);
      petals[i].draw(ctx);
    }
    requestAnimationFrame(render);
  }

  render();
})();
