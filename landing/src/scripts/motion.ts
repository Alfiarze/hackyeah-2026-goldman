// Page motion: scroll reveals, rosettes that draw themselves, numbers that count up, the hero
// parallax and the banknote serial. Everything is opt-in through the `motion` class set in the
// <head> (absent with prefers-reduced-motion or without IntersectionObserver), so without it the
// page is static and complete. Only transform and opacity are animated.

const root = document.documentElement;
const motion = root.classList.contains("motion");

if (motion) {
  // ------------------------------------------------------------ reveal
  document.querySelectorAll<HTMLElement>("[data-reveal-group]").forEach((group) => {
    group.querySelectorAll<HTMLElement>("[data-reveal]").forEach((el, i) => {
      el.style.setProperty("--i", String(Math.min(i, 8)));
    });
  });

  const settle = (el: HTMLElement) => {
    // after the entrance, drop the staggered delay so hover transitions answer immediately
    const i = Number(el.style.getPropertyValue("--i") || 0);
    window.setTimeout(() => el.classList.add("is-settled"), 1100 + i * 90);
  };

  const io = new IntersectionObserver(
    (entries) => {
      for (const e of entries) {
        if (!e.isIntersecting) continue;
        const el = e.target as HTMLElement;
        el.classList.add("is-in");
        io.unobserve(el);
        if (el.hasAttribute("data-reveal")) settle(el);
        if (el.hasAttribute("data-count")) countUp(el);
      }
    },
    { rootMargin: "0px 0px -8% 0px", threshold: 0.12 },
  );
  document.querySelectorAll("[data-reveal], [data-draw], [data-count]").forEach((el) => io.observe(el));

  // ------------------------------------------------------------ counters
  function countUp(el: HTMLElement) {
    const target = Number(el.dataset.count);
    if (!Number.isFinite(target)) return;
    const text = el.textContent ?? "";
    el.style.minWidth = `${text.length}ch`;
    const t0 = performance.now();
    const dur = 1400;
    const tick = (now: number) => {
      const p = Math.min(1, (now - t0) / dur);
      const eased = 1 - Math.pow(1 - p, 3);
      el.textContent = p < 1 ? String(Math.round(target * eased)) : text;
      if (p < 1) requestAnimationFrame(tick);
    };
    el.textContent = "0";
    requestAnimationFrame(tick);
  }

  // ------------------------------------------------------------ hero parallax
  const art = document.querySelector<HTMLElement>(".hero-art");
  if (art) {
    let queued = false;
    let heroVisible = true;
    new IntersectionObserver(([e]) => { heroVisible = e.isIntersecting; }).observe(art);
    const apply = () => {
      queued = false;
      if (!heroVisible) return;
      const y = Math.min(window.scrollY, 900);
      art.style.transform = `translate3d(0, ${(y * 0.12).toFixed(1)}px, 0)`;
    };
    window.addEventListener("scroll", () => {
      if (!queued) { queued = true; requestAnimationFrame(apply); }
    }, { passive: true });
  }

  // ------------------------------------------------------------ banknote serial
  const serial = document.querySelector<HTMLElement>("[data-serial]");
  if (serial) {
    let n = Number(serial.dataset.serial) || 4817;
    const digits = () => Array.from(serial.querySelectorAll<HTMLElement>("i"));
    const tick = () => {
      if (document.hidden) return;
      n += 1 + Math.floor(Math.random() * 3);
      const next = String(n % 1_000_000).padStart(6, "0");
      digits().forEach((d, i) => {
        if (d.textContent === next[i]) return;
        d.textContent = next[i];
        d.classList.remove("roll");
        void d.offsetWidth; // restart the roll
        d.classList.add("roll");
      });
    };
    window.setInterval(tick, 2400);
  }
}
