/* First-run guided tour: a dark overlay with a cut-out around one element and a card beside it.
   Two tours: "home" (first start) and "job" (the first time a recording is opened).
   "Already shown" is kept in the backend settings (tour_home_done / tour_job_done).
   window.startTour("home" | "job") starts one by hand. */
(() => {
  const SETTING = { home: "tour_home_done", job: "tour_job_done" };
  const q = (s) => document.querySelector(s);
  const label = (id) => () => q("#" + id)?.closest("label");

  /* target: selector, function returning an element, or null for a centred card */
  const TOURS = {
    home: [
      { k: "tour_home_welcome", target: null },
      { k: "tour_home_drop", target: "#drop" },
      { k: "tour_home_lang", target: "#langMode" },
      { k: "tour_home_meeting", target: label("meetingMode") },
      { k: "tour_home_learn", target: label("learnPeople") },
      { k: "tour_home_jobs", target: () => (q("#jobs")?.children.length ? q("#jobs") : q(".listhead")) },
      { k: "tour_home_people", target: "#peopleBtn" },
      { k: "tour_home_system", target: "#sysBtn" },
      { k: "tour_home_about", target: "#aboutBtn" },
    ],
    job: [
      { k: "tour_job_speakers", target: "#speakers" },
      { k: "tour_job_segs", target: "#segs" },
      { k: "tour_job_review", target: "#reviewBar" },
      { k: "tour_job_search", target: "#filters .searchbox" },
      { k: "tour_job_analysis", target: "#tabAnalysis" },
      { k: "tour_job_export", target: ".toolbar details.menu" },
      { k: "tour_job_player", target: "#player" },
      { k: "tour_job_help", target: "#helpBtn" },
    ],
  };

  const PAD = 6, GAP = 14, MARGIN = 12;
  let cur = null;  // { name, steps, i, root, hole, card, prevFocus, timer, raf }

  const reduced = () => matchMedia("(prefers-reduced-motion: reduce)").matches;
  function el(tag, props = {}, ...kids) {
    const e = Object.assign(document.createElement(tag), props);
    e.append(...kids);
    return e;
  }
  function targetOf(step) {
    if (!step.target) return null;
    return typeof step.target === "function" ? step.target() : q(step.target);
  }
  function visible(e) {
    if (!e || e.hidden || !e.getClientRects().length) return false;
    const r = e.getBoundingClientRect();
    return r.width > 0 && r.height > 0 && getComputedStyle(e).visibility !== "hidden";
  }
  const usable = (step) => !step.target || visible(targetOf(step));

  function markDone(name) {
    call("set_settings", { [SETTING[name]]: true }).catch(() => {});
  }

  /* ---------- drawing ---------- */
  function render() {
    const { steps, i, card } = cur;
    const s = steps[i], last = i === steps.length - 1;
    const vars = { app: t("app") };
    const next = document.createDocumentFragment();
    if (last) next.append(icText("check", t("tour_finish")));
    else next.append(t("tour_next") + " ", ic("arrow-right"));
    card.replaceChildren(
      el("div", { className: "tour-count", textContent: t("tour_step", { n: i + 1, m: steps.length }) }),
      el("h3", { id: "tourTitle", textContent: t(s.k + "_t", vars) }),
      el("p", { id: "tourBody", textContent: t(s.k + "_b", vars) }),
      el("div", { className: "tour-btns" },
        el("button", { className: "tour-skip", type: "button", onclick: () => close(true) }, icText("x", t("tour_skip"))),
        el("span", { className: "spacer" }),
        ...(i > 0 ? [el("button", { type: "button", onclick: () => go(i - 1, -1) }, icText("arrow-left", t("tour_back")))] : []),
        el("button", { className: "primary tour-next", type: "button", onclick: () => (last ? close(true) : go(i + 1, 1)) }, next),
      ));
    card.querySelector(".tour-next").focus({ preventScroll: true });
  }

  function place() {
    if (!cur) return;
    cur.raf = 0;
    const s = cur.steps[cur.i], target = targetOf(s);
    const { hole, card } = cur;
    const vw = innerWidth, vh = innerHeight;
    card.style.width = Math.min(360, vw - 2 * MARGIN) + "px";
    const cw = card.offsetWidth, ch = card.offsetHeight;
    const clamp = (v, lo, hi) => Math.max(lo, Math.min(v, hi));
    if (!target || !visible(target)) {
      hole.hidden = true;
      cur.root.classList.add("dim");
      card.style.left = Math.round((vw - cw) / 2) + "px";
      card.style.top = Math.round(Math.max(MARGIN, (vh - ch) / 2)) + "px";
      return;
    }
    cur.root.classList.remove("dim");
    const r = target.getBoundingClientRect();
    // hole = target plus padding, cut to the window
    const x0 = Math.max(0, r.left - PAD), y0 = Math.max(0, r.top - PAD);
    const x1 = Math.min(vw, r.right + PAD), y1 = Math.min(vh, r.bottom + PAD);
    hole.hidden = false;
    Object.assign(hole.style, { left: x0 + "px", top: y0 + "px", width: Math.max(0, x1 - x0) + "px", height: Math.max(0, y1 - y0) + "px" });
    const cx = clamp(x0 + (x1 - x0) / 2 - cw / 2, MARGIN, vw - cw - MARGIN);
    const cy = clamp(y0 + (y1 - y0) / 2 - ch / 2, MARGIN, vh - ch - MARGIN);
    const spots = [
      [y1 + GAP + ch <= vh - MARGIN, cx, y1 + GAP],              // below
      [y0 - GAP - ch >= MARGIN, cx, y0 - GAP - ch],              // above
      [x1 + GAP + cw <= vw - MARGIN, x1 + GAP, cy],              // right
      [x0 - GAP - cw >= MARGIN, x0 - GAP - cw, cy],              // left
    ];
    const hit = spots.find((p) => p[0]);
    // nothing fits (a very tall target): sit at the bottom of the window, over the target
    const [, px, py] = hit || [0, cx, vh - ch - MARGIN];
    card.style.left = Math.round(px) + "px";
    card.style.top = Math.round(py) + "px";
  }
  function schedule() { if (cur && !cur.raf) cur.raf = requestAnimationFrame(place); }

  /* ---------- navigation ---------- */
  function go(n, dir) {
    // drop steps whose target went missing, then show the nearest one in the travel direction
    while (n >= 0 && n < cur.steps.length && !usable(cur.steps[n])) {
      cur.steps.splice(n, 1);
      if (dir < 0) n--;
    }
    if (n >= cur.steps.length) return close(true);
    if (n < 0) n = 0;
    cur.i = n;
    render();
    const target = targetOf(cur.steps[n]);
    if (target) {
      const tall = target.getBoundingClientRect().height > innerHeight * 0.7;
      target.scrollIntoView({ block: tall ? "start" : "center", inline: "nearest", behavior: reduced() ? "auto" : "smooth" });
    }
    place();
  }

  function onKey(e) {
    if (!cur) return;
    const onButton = e.target instanceof HTMLButtonElement;
    if (e.key === "Escape") close(true);
    else if (e.key === "ArrowRight" || (e.key === "Enter" && !onButton)) { if (cur.i < cur.steps.length - 1) go(cur.i + 1, 1); else close(true); }
    else if (e.key === "ArrowLeft") { if (cur.i > 0) go(cur.i - 1, -1); }
    else if (e.key === "Tab") {  // keep focus inside the card
      const b = [...cur.card.querySelectorAll("button")];
      const at = b.indexOf(document.activeElement);
      b[(at + (e.shiftKey ? -1 : 1) + b.length) % b.length].focus();
    } else return;
    e.preventDefault();
    e.stopImmediatePropagation();
  }

  function close(markIt) {
    if (!cur) return;
    const c = cur;
    cur = null;
    if (markIt) markDone(c.name);
    clearInterval(c.timer);
    cancelAnimationFrame(c.raf);
    removeEventListener("keydown", onKey, true);
    removeEventListener("resize", schedule);
    removeEventListener("scroll", schedule, true);
    c.root.remove();
    try { c.prevFocus?.focus({ preventScroll: true }); } catch (_) {}
  }

  function start(name) {
    if (cur) close(false);
    const steps = TOURS[name].filter(usable);
    if (!steps.length) return;
    const hole = el("div", { className: "tour-hole" });
    const card = el("div", { className: "tour-card", role: "dialog" });
    card.setAttribute("aria-modal", "true");
    card.setAttribute("aria-labelledby", "tourTitle");
    card.setAttribute("aria-describedby", "tourBody");
    const root = el("div", { id: "tour", className: "dim" }, el("div", { className: "tour-block" }), hole, card);
    document.body.append(root);
    cur = { name, steps, i: 0, root, hole, card, prevFocus: document.activeElement, timer: 0, raf: 0 };
    addEventListener("keydown", onKey, true);
    addEventListener("resize", schedule);
    addEventListener("scroll", schedule, true);
    cur.timer = setInterval(() => {  // layout can change under us (lists load, panes switch)
      if (!cur) return;
      if (!usable(cur.steps[cur.i])) go(cur.i, 1); else place();
    }, 400);
    go(0, 1);
  }

  /* ---------- when to start ---------- */
  const home = () => document.getElementById("home");
  const view = () => document.getElementById("view");
  let jobDone = true;

  function whenHomeVisible(fn) {
    let n = 0;
    const id = setInterval(() => {
      if (!home().hidden) { clearInterval(id); fn(); }
      else if (++n > 25) clearInterval(id);
    }, 120);
  }

  /* needChange: the model wizard may be showing, so wait until #home has been hidden and then shown again */
  function watchHome(needChange) {
    let seenHidden = home().hidden;  // the wizard may already have opened the System page before we got here
    const go = () => setTimeout(() => { if (!cur && !home().hidden) start("home"); }, 450);
    const ob = new MutationObserver(() => {
      if (home().hidden) { seenHidden = true; return; }
      if (needChange && !seenHidden) return;
      ob.disconnect();
      go();
    });
    ob.observe(home(), { attributes: true, attributeFilter: ["hidden"] });
    if (!needChange && !home().hidden) { ob.disconnect(); go(); }
  }

  function watchView() {
    new MutationObserver(() => {
      if (view().hidden || cur || jobDone) return;
      setTimeout(() => { if (!view().hidden && !cur && !jobDone) { jobDone = true; start("job"); } }, 700);
    }).observe(view(), { attributes: true, attributeFilter: ["hidden"] });
  }

  async function init() {
    for (let n = 0; document.getElementById("splash") && n < 150; n++) await new Promise((r) => setTimeout(r, 200));
    let st = {};
    try { st = await call("get_settings"); } catch (_) { return; }
    jobDone = !!st.tour_job_done;
    watchView();
    if (st.tour_home_done) return;
    let firstRun = false;
    try { firstRun = !!(await call("get_system_info")).first_run; } catch (_) {}
    watchHome(firstRun);
  }

  window.startTour = (name = "home") => { if (TOURS[name]) start(name); };

  const again = document.getElementById("tourRestart");
  if (again) again.onclick = () => {
    document.getElementById("aboutDlg").close();
    jobDone = false;
    call("set_settings", { tour_job_done: false }).catch(() => {});
    const hb = document.getElementById("homeBtn");
    if (!hb.hidden) hb.click();
    whenHomeVisible(() => setTimeout(() => start("home"), 250));
  };

  init();
})();
