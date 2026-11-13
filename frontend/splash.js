/* Opening screen: an animated bar that moves with the real start-up steps.
   splash.step(percent, key) is called by app.js; splash.done() fades it out (never sooner than MIN_MS). */
(() => {
  const MIN_MS = 1100;
  const T = {
    tr: { tag: "Toplantıların yazılı hâli", boot: "Başlatılıyor…", bridge: "Uygulama bağlanıyor…", settings: "Ayarlar yükleniyor…", ready: "Hazır" },
    en: { tag: "Your meetings, written down", boot: "Starting…", bridge: "Connecting…", settings: "Loading settings…", ready: "Ready" },
  };
  const lang = (navigator.language || "tr").toLowerCase().startsWith("tr") ? "tr" : "en";
  const root = document.getElementById("splash");
  if (!root) { window.splash = { step() {}, done() {} }; return; }
  const fill = root.querySelector(".sfill"), msg = root.querySelector(".smsg"), pct = root.querySelector(".spct");
  root.querySelector(".stag").textContent = T[lang].tag;
  const t0 = performance.now();
  let shown = 0, target = 0, finished = false, raf = 0;

  function draw() {  // ease toward the target so the bar glides instead of jumping
    shown += (target - shown) * 0.12;
    if (target - shown < 0.3) shown = target;
    fill.style.width = shown.toFixed(1) + "%";
    pct.textContent = Math.round(shown) + "%";
    if (shown < target || !finished) raf = requestAnimationFrame(draw);
    else if (shown >= 100) hide();
  }
  function hide() {
    cancelAnimationFrame(raf);
    root.classList.add("out");
    setTimeout(() => root.remove(), 450);
  }
  function step(p, key) {
    if (key && T[lang][key] && p >= target) msg.textContent = T[lang][key];  // a late, lower step never moves the text back
    target = Math.max(target, Math.min(p, 100));
  }
  function done() {
    const wait = Math.max(0, MIN_MS - (performance.now() - t0));
    setTimeout(() => { step(100, "ready"); finished = true; cancelAnimationFrame(raf); raf = requestAnimationFrame(draw); }, wait);
  }
  step(15, "boot");
  raf = requestAnimationFrame(draw);
  setTimeout(() => { if (document.getElementById("splash")) { step(100, "ready"); finished = true; } }, 15000);  // never stay forever
  window.splash = { step, done };
})();
