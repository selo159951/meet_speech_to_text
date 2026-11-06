/* System page: hardware, engine, model, speed test, first-launch wizard, header chip and ETA helper.
   Loaded after app.js (uses its $, el, call, t, LANG). Adds its own strings to I18N. */
Object.assign(I18N.en, {
  system: "System", sys_title: "Your computer", sys_chip_title: "Open the System page",
  chip_gpu: "GPU", chip_gpu_vulkan: "GPU (Vulkan)", chip_cpu: "CPU",
  v_ok: "✓ Your graphics card is good enough", v_tight: "⚠ Borderline — a smaller model is recommended",
  v_cpu: "No usable graphics card — it will run on the processor (slower)",
  v_cpu_gpu_unused: "The graphics card cannot be used here — it will run on the processor (slower)",
  details: "Technical details", gpu: "Graphics card", cpu: "Processor", ram: "Memory (RAM)",
  engine_model: "Engine and model", no_gpu: "No graphics card found", vram: "{g} GB video memory",
  vram_free: "{g} GB free", cores_n: "{n} logical cores", ram_total: "{g} GB in total", ram_free: "{g} GB free",
  in_use: "In use", engine_label: "Engine", model_label: "Model", device_label: "Runs on", compute_label: "Precision",
  dev_cuda: "NVIDIA graphics card (CUDA)", dev_vulkan: "Graphics card (Vulkan)", dev_cpu: "Processor (CPU)",
  speed_title: "Speed", speed_line: "1 minute of audio ≈ {a} s transcription + {d} s speaker separation",
  speed_default: "Estimate for this kind of PC - run the speed test for your real numbers.",
  speed_measured: "Measured on this PC.", speed_run: "Run speed test", speed_running: "Testing…",
  speed_done: "Speed test finished.", speed_err: "Speed test failed: {e}",
  st_loading: "Loading the model…", st_transcribing: "Transcribing the sample…", st_diarizing: "Separating speakers…",
  choose_engine: "Engine", eng_auto: "Automatic (recommended)", eng_ct2_cuda: "NVIDIA graphics card (CUDA)",
  eng_ct2_cpu: "Processor only (CPU)", eng_whispercpp: "Graphics card (Vulkan - AMD / Intel)",
  r_no_nvidia: "no NVIDIA graphics card", r_no_cuda: "CUDA libraries could not be loaded", r_no_gpu: "no graphics card",
  r_no_vulkan: "no Vulkan driver", r_wcpp_missing: "not included in this version",
  choose_model: "Model", m_large: "Large (large-v3-turbo)", m_medium: "Medium", m_small: "Small",
  m_large_d: "Most accurate. Needs a fast graphics card; slow on the processor.",
  m_medium_d: "Balanced: good accuracy, medium speed.",
  m_small_d: "Fast and light, but makes more mistakes.",
  recommended: "Recommended", downloaded: "Downloaded", download: "Download", use_model: "Use",
  downloading: "Downloading…", dl_error: "Download failed: {e}", fit_tight: "tight on this graphics card",
  fit_too_big: "too big for this graphics card", plan_fallback: "The chosen engine is not available here, so the automatic choice is used.",
  wiz_title: "Welcome - let's set things up", wiz_s1: "Check this computer", wiz_s2: "Download the speech model",
  wiz_s3: "Quick speed test", wiz_download: "Download the model ({m}, {s})", wiz_ready: "All set - you can add a recording now.",
  wiz_note: "The model is downloaded once; afterwards everything works offline.", back_home: "Start",
  eta_total: "≈ {d} to process", eta_left: "~{d} left", dur_s: "{n} sec", dur_m: "{n} min", dur_h: "{h} h {m} min",
});
Object.assign(I18N.tr, {
  system: "Sistem", sys_title: "Bilgisayarınız", sys_chip_title: "Sistem sayfasını aç",
  chip_gpu: "GPU", chip_gpu_vulkan: "GPU (Vulkan)", chip_cpu: "İşlemci",
  v_ok: "✓ Ekran kartınız yeterli", v_tight: "⚠ Sınırda — daha küçük model önerilir",
  v_cpu: "Ekran kartı kullanılamıyor, işlemciyle çalışacak (daha yavaş)",
  v_cpu_gpu_unused: "Ekran kartı burada kullanılamıyor, işlemciyle çalışacak (daha yavaş)",
  details: "Teknik ayrıntılar", gpu: "Ekran kartı", cpu: "İşlemci", ram: "Bellek (RAM)",
  engine_model: "Motor ve model", no_gpu: "Ekran kartı bulunamadı", vram: "{g} GB video belleği",
  vram_free: "{g} GB boş", cores_n: "{n} mantıksal çekirdek", ram_total: "toplam {g} GB", ram_free: "{g} GB boş",
  in_use: "Kullanımda", engine_label: "Motor", model_label: "Model", device_label: "Çalıştığı yer", compute_label: "Hassasiyet",
  dev_cuda: "NVIDIA ekran kartı (CUDA)", dev_vulkan: "Ekran kartı (Vulkan)", dev_cpu: "İşlemci (CPU)",
  speed_title: "Hız", speed_line: "1 dakikalık ses ≈ {a} sn yazıya dökme + {d} sn konuşmacı ayırma",
  speed_default: "Bu tür bilgisayarlar için tahmin - gerçek değerler için hız testini çalıştırın.",
  speed_measured: "Bu bilgisayarda ölçüldü.", speed_run: "Hız testi yap", speed_running: "Test ediliyor…",
  speed_done: "Hız testi bitti.", speed_err: "Hız testi başarısız: {e}",
  st_loading: "Model yükleniyor…", st_transcribing: "Örnek yazıya dökülüyor…", st_diarizing: "Konuşmacılar ayrılıyor…",
  choose_engine: "Motor", eng_auto: "Otomatik (önerilen)", eng_ct2_cuda: "NVIDIA ekran kartı (CUDA)",
  eng_ct2_cpu: "Sadece işlemci (CPU)", eng_whispercpp: "Ekran kartı (Vulkan - AMD / Intel)",
  r_no_nvidia: "NVIDIA ekran kartı yok", r_no_cuda: "CUDA kütüphaneleri yüklenemedi", r_no_gpu: "ekran kartı yok",
  r_no_vulkan: "Vulkan sürücüsü yok", r_wcpp_missing: "bu sürümde yok",
  choose_model: "Model", m_large: "Büyük (large-v3-turbo)", m_medium: "Orta", m_small: "Küçük",
  m_large_d: "En doğru sonuç. Hızlı ekran kartı ister; işlemcide yavaştır.",
  m_medium_d: "Dengeli: iyi doğruluk, orta hız.",
  m_small_d: "Hızlı ve hafif, ama daha çok hata yapar.",
  recommended: "Önerilen", downloaded: "İndirildi", download: "İndir", use_model: "Kullan",
  downloading: "İndiriliyor…", dl_error: "İndirme başarısız: {e}", fit_tight: "bu ekran kartında sınırda",
  fit_too_big: "bu ekran kartı için çok büyük", plan_fallback: "Seçilen motor burada kullanılamıyor, otomatik seçim kullanılıyor.",
  wiz_title: "Hoş geldiniz - hızlıca kuralım", wiz_s1: "Bilgisayarı denetle", wiz_s2: "Konuşma modelini indir",
  wiz_s3: "Kısa hız testi", wiz_download: "Modeli indir ({m}, {s})", wiz_ready: "Hazır - şimdi bir kayıt ekleyebilirsiniz.",
  wiz_note: "Model bir kez indirilir; sonrasında her şey internetsiz çalışır.", back_home: "Başla",
  eta_total: "≈ {d} sürer", eta_left: "kalan ~{d}", dur_s: "{n} sn", dur_m: "{n} dk", dur_h: "{h} sa {m} dk",
});

(() => {
  const GB = 1024 ** 3;
  const gb = (b) => (b / GB).toFixed(1).replace(/\.0$/, "").replace(".", LANG === "tr" ? "," : ".");
  const ENG_KEY = { auto: "eng_auto", "ct2-cuda": "eng_ct2_cuda", "ct2-cpu": "eng_ct2_cpu", whispercpp: "eng_whispercpp" };
  const MODEL_KEY = { "large-v3-turbo": "m_large", medium: "m_medium", small: "m_small" };
  const MODEL_DESC = { "large-v3-turbo": "m_large_d", medium: "m_medium_d", small: "m_small_d" };
  let info = null, wiz = false, pollT = null, lastStatus = null;

  /* ---------- duration / ETA (also used by watch() in app.js) ---------- */
  function dur(s) {
    s = Math.max(0, Math.round(s));
    if (s < 60) return t("dur_s", { n: Math.max(5, Math.round(s / 5) * 5) });
    const m = Math.round(s / 60);
    return m < 60 ? t("dur_m", { n: m }) : t("dur_h", { h: Math.floor(m / 60), m: m % 60 });
  }
  const estCache = {};
  window.etaText = (j, secs, overall) => {
    if (!j.duration || j.status !== "running") return "";
    if (!(j.id in estCache)) {
      estCache[j.id] = null;
      call("estimate", j.duration).then((e) => (estCache[j.id] = e)).catch(() => {});
    }
    const e = estCache[j.id];
    if (!e) return "";
    if (overall < 0.12) return t("eta_total", { d: dur(Math.max(e.seconds - secs, e.seconds * 0.3)) });
    const left = (secs * (1 - overall)) / overall; // from real progress once it is meaningful
    return t("eta_left", { d: dur(left) });
  };

  /* ---------- header: only the System button; the device shows as its tooltip ---------- */
  const chip = $("sysBtn");
  function paintChip(st) {
    const dev = st.plan?.device || (st.gpu_available ? "cuda" : "cpu");
    const g = st.hardware?.gpus?.length ? st.hardware.gpus.reduce((a, b) => (b.vram > a.vram ? b : a)) : null;
    chip.title = { cuda: t("dev_cuda"), vulkan: t("dev_vulkan"), cpu: t("dev_cpu") }[dev] + (dev !== "cpu" && g ? " · " + g.name : "");
  }
  // app.js calls showGpu(st) on start and on language change; it forwards here
  window.onSysStatus = (st) => { lastStatus = st; paintChip(st); if (!$("system").hidden && info) render(); };

  /* ---------- page ---------- */
  const page = $("system");
  function open() {
    $("home").hidden = true; $("view").hidden = true; $("player").hidden = true;
    page.hidden = false; $("homeBtn").hidden = false;
    refresh();
  }
  function close() { page.hidden = true; }
  $("sysBtn").onclick = open;
  $("homeBtn").addEventListener("click", close);

  async function refresh() {
    info = await call("get_system_info");
    render();
    const test = info.test.state === "running", dl = info.download.state === "running";
    clearTimeout(pollT);
    if ((test || dl) && !page.hidden) pollT = setTimeout(refresh, 700);
    else if (wiz) wizStep();
  }

  const card = (title, ...kids) => el("section", { className: "scard" }, el("h3", { textContent: title }), ...kids);
  const line = (txt, cls = "") => el("div", { className: "sline " + cls, textContent: txt });
  const devName = (d) => t({ cuda: "dev_cuda", vulkan: "dev_vulkan", cpu: "dev_cpu" }[d]);

  function render() {
    if (!info) return;
    const hw = info.hardware, plan = info.plan, v = info.verdict, set = info.settings;
    const kids = [el("h2", { textContent: t("sys_title") })];
    if (wiz) kids.push(wizard());
    kids.push(el("div", { className: "verdict " + v.level, textContent: t(v.key) }));
    if (info.settings.engine !== "auto" && plan.fallback_from) kids.push(line(t("plan_fallback"), "warn"));

    // hardware cards
    const gpuLines = hw.gpus.length
      ? hw.gpus.map((g) => el("div", {}, line(g.name, "strong"),
          line([g.vram ? t("vram", { g: gb(g.vram) }) : "", g.free ? t("vram_free", { g: gb(g.free) }) : ""].filter(Boolean).join(" · "), "dim")))
      : [line(t("no_gpu"), "dim")];
    const ram = hw.ram;
    const grid = el("div", { className: "sgrid" },
      card(t("gpu"), ...gpuLines),
      card(t("cpu"), line(hw.cpu.name, "strong"), line(t("cores_n", { n: hw.cpu.cores }), "dim")),
      card(t("ram"), line(t("ram_total", { g: gb(ram.total) }), "strong"), line(t("ram_free", { g: gb(ram.available) }), "dim")),
      card(t("engine_model"),
        line(devName(plan.device), "strong"),
        line(`${t("model_label")}: ${t(MODEL_KEY[set.model])}`, "dim")));
    kids.push(grid);

    // speed
    const sp = info.speed, tst = info.test;
    const speedBtn = el("button", { className: "primary", textContent: tst.state === "running" ? t("speed_running") : t("speed_run"),
      disabled: tst.state === "running" || !info.model_downloaded || info.download.state === "running" });
    speedBtn.onclick = async () => { await call("run_speed_test").catch(() => {}); refresh(); };
    const speedKids = [line(t("speed_line", { a: sp.asr_spm.toFixed(1), d: sp.diar_spm.toFixed(1) }), "strong"),
      line(t(sp.source === "measured" ? "speed_measured" : "speed_default"), "dim")];
    if (tst.state === "running") {
      speedKids.push(el("div", { className: "bar" }, el("div", { style: `width:${Math.round(tst.progress * 100)}%` })),
        line(t("st_" + tst.stage), "dim"));
    }
    if (tst.state === "error") speedKids.push(line(t("speed_err", { e: tst.error }), "warn"));
    speedKids.push(speedBtn);
    kids.push(card(t("speed_title"), ...speedKids));

    // engine choice
    const sel = el("select");
    info.engines.concat([{ id: "auto", ok: true }]).sort((a, b) => ["auto", "ct2-cuda", "ct2-cpu", "whispercpp"].indexOf(a.id) - ["auto", "ct2-cuda", "ct2-cpu", "whispercpp"].indexOf(b.id))
      .forEach((e) => sel.append(el("option", { value: e.id, disabled: !e.ok, selected: e.id === set.engine,
        textContent: t(ENG_KEY[e.id]) + (e.ok ? "" : ` - ${t("r_" + e.reason)}`) })));
    sel.onchange = async () => { info = await call("set_engine", sel.value); render(); };
    kids.push(card(t("choose_engine"), sel));

    // model choice
    const rows = info.models.map((m) => {
      const dl = info.download, busy = dl.state === "running" && dl.model === m.id;
      const btn = el("button", { className: m.downloaded ? "" : "primary" });
      if (m.current && m.downloaded) { btn.textContent = "✓ " + t("in_use"); btn.disabled = true; }
      else if (m.downloaded) { btn.textContent = t("use_model"); btn.onclick = async () => { info = await call("set_model", m.id); render(); }; }
      else if (busy) { btn.textContent = t("downloading"); btn.disabled = true; }
      else { btn.textContent = `${t("download")} (${gb(m.size)} GB)`; btn.disabled = dl.state === "running";
        btn.onclick = async () => { await call("set_model", m.id); await call("download_model", m.id); refresh(); }; }
      const tags = [m.recommended ? t("recommended") : "", m.fit === "tight" ? t("fit_tight") : m.fit === "too_big" ? t("fit_too_big") : ""].filter(Boolean);
      const row = el("div", { className: "mrow" + (m.current ? " cur" : "") },
        el("div", { className: "minfo" }, line(t(MODEL_KEY[m.id]) + (tags.length ? "  ·  " + tags.join(" · ") : ""), "strong"), line(t(MODEL_DESC[m.id]), "dim")), btn);
      if (busy) row.append(el("div", { className: "bar full" }, el("div", { style: `width:${Math.round((dl.done / Math.max(dl.total, 1)) * 100)}%` })));
      if (dl.state === "error" && dl.model === m.id) row.append(line(t("dl_error", { e: dl.error }), "warn"));
      return row;
    });
    kids.push(card(t("choose_model"), ...rows));

    // technical details
    const tech = { plan, settings: set, engines: info.engines, hardware: hw };
    kids.push(el("details", { className: "tech" }, el("summary", { textContent: t("details") }), el("pre", { textContent: JSON.stringify(tech, null, 2) })));
    page.replaceChildren(...kids);
  }

  /* ---------- first-launch wizard: check -> download -> speed test ---------- */
  function wizard() {
    const dl = info.download, tst = info.test;
    const rec = info.models.find((m) => m.recommended) || info.models[0];
    const s2 = info.model_downloaded, s3 = tst.state === "done" || info.speed.source === "measured";
    const steps = [[true, "wiz_s1"], [s2, "wiz_s2"], [s3, "wiz_s3"]];
    const box = el("div", { className: "wiz" }, el("h3", { textContent: t("wiz_title") }),
      el("ol", {}, ...steps.map(([ok, k]) => el("li", { className: ok ? "ok" : "", textContent: (ok ? "✓ " : "• ") + t(k) }))));
    if (!s2 && dl.state !== "running") {
      const b = el("button", { className: "primary", textContent: t("wiz_download", { m: t(MODEL_KEY[rec.id]), s: gb(rec.size) + " GB" }) });
      b.onclick = async () => { await call("set_model", rec.id); await call("download_model", rec.id); refresh(); };
      box.append(b, line(t("wiz_note"), "dim"));
      if (dl.state === "error") box.append(line(t("dl_error", { e: dl.error }), "warn"));
    } else if (s3 && tst.state !== "running") {
      const b = el("button", { className: "primary", textContent: t("back_home") });
      b.onclick = () => { wiz = false; $("homeBtn").click(); };
      box.append(line(t("wiz_ready"), "strong"), b);
    }
    return box;
  }
  async function wizStep() {
    if (!wiz || !info) return;
    if (info.model_downloaded && info.speed.source !== "measured" && info.test.state === "idle") {
      await call("run_speed_test").catch(() => {});
      refresh();
    }
  }

  // start: show the wizard when no model has been downloaded yet
  call("get_system_info").then((i) => { info = i; if (i.first_run) { wiz = true; open(); } }).catch(() => {});
  setInterval(() => { if (lastStatus && !page.hidden) return; }, 60000);
})();
