/* People page + voice recognition UI. Uses helpers from app.js ($, el, t, call, toast, save, applyJob, job, spkNames). */
(() => {
  const root = $("people");
  const MIN_SPEECH = 30, TARGET = 40;
  const TEXTS = {
    tr: "Sabah erkenden kalkıp pencereyi açtım. Dışarıda hafif bir yağmur yağıyordu ve havada toprak kokusu vardı. Çayımı demledikten sonra bugün yapılacak işleri bir kâğıda yazdım: önce toplantı notlarını düzenleyecek, öğleden sonra ise müşterilere göndereceğim raporu hazırlayacaktım. Telefonum çaldığında arkadaşım, akşam için yeni açılan lokantada yer ayırttığını söyledi. Güldüm, çünkü geçen hafta da aynı şeyi planlamıştık, ama sonunda hepimiz yağmurdan dolayı evde kalmıştık. Yine de gitmeye karar verdim. Şehrin kalabalığında yürümeyi, vitrinlere bakmayı ve eski dostlarla uzun uzun sohbet etmeyi çok severim. Belki yarın hafta sonu için küçük bir gezi de düzenleriz; deniz kenarında yürüyüş, sıcak simit ve güzel bir manzara gayet iyi olur.",
    en: "I woke up early this morning and opened the window. A light rain was falling, and the air smelled of fresh earth. After brewing a pot of tea, I wrote down everything I needed to do today: first, organize the notes from yesterday's meeting, and in the afternoon, prepare the report for our clients. When my phone rang, a friend told me she had booked a table at the new restaurant downtown. I laughed, because we had planned the very same thing last week, but the storm kept all of us at home. Still, I decided to go. I enjoy walking through the busy streets, looking at shop windows, and talking for hours with old friends. Maybe tomorrow we will even organize a small trip for the weekend: a walk by the sea, warm bread, and a beautiful view would be just perfect.",
  };
  const S = { list: [], textLang: null, adding: false, rec: null, error: "" };
  const msg = (e) => (e && e.message) || String(e);

  async function refresh(render = true) {
    try { S.list = await call("list_people"); } catch (e) { S.error = msg(e); }
    if (render && !root.hidden) draw();
  }

  /* ---------- page ---------- */
  async function open() {
    if (job) await save();
    audio.pause();
    for (const id of ["home", "view", "player"]) $(id).hidden = true;
    root.hidden = false; $("homeBtn").hidden = false;
    S.error = "";
    await refresh();
  }
  function close() { root.hidden = true; if (S.rec) cancelRec(); S.adding = false; }
  $("peopleBtn").onclick = open;
  $("homeBtn").addEventListener("click", close);
  $("langSel").addEventListener("change", () => { if (!root.hidden) draw(); });

  function draw() {
    if (S.rec) return; // the recording panel updates itself
    const qLabel = (w) => t("q_" + w);
    const cards = S.list.map((p) => {
      const name = el("input", { value: p.name, className: "pname", title: t("rename_speaker") });
      name.onchange = async () => {
        try { await call("rename_person", p.id, name.value); } catch (e) { S.error = msg(e); }
        refresh();
      };
      const bits = [t("voice_secs", { n: Math.round(p.seconds) })];
      const tags = [];
      if (p.weak) tags.push(el("span", { className: "ptag warn", textContent: t("weak_voice") }));
      for (const w of p.warnings) tags.push(el("span", { className: "ptag warn", textContent: qLabel(w) }));
      if (!p.weak && !p.warnings.length) tags.push(el("span", { className: "ptag ok", textContent: "✓" }));
      const addFile = el("button", { className: "small", textContent: t("from_file") });
      addFile.onclick = () => run(() => call("add_person_sample_file", p.id));
      const addMic = el("button", { className: "small", textContent: t("from_mic") });
      addMic.onclick = () => startRec(p.id, null);
      const del = el("button", { className: "small", textContent: t("delete_person") });
      del.onclick = async () => {
        if (!confirm(t("confirm_delete_person", { n: p.name }))) return;
        await call("delete_person", p.id); refresh();
      };
      return el("div", { className: "pcard" },
        el("div", { className: "prow" }, name, el("span", { className: "pmeta", textContent: bits.join(" · ") }), ...tags),
        el("div", { className: "prow pbtns" }, el("span", { className: "pmeta", textContent: t("add_voice") + ":" }), addFile, addMic, el("span", { className: "spacer" }), del));
    });
    root.replaceChildren(
      el("div", { className: "toolbar" }, el("h2", { textContent: t("people") }), el("span", { className: "spacer" }), addPanel()),
      el("p", { className: "hint", textContent: t("people_hint") }),
      ...(S.error ? [el("p", { className: "perr", textContent: S.error })] : []),
      ...(cards.length ? cards : [el("p", { className: "hint", textContent: t("no_people") })]));
  }

  function addPanel() {
    if (!S.adding) {
      const b = el("button", { textContent: t("add_person") });
      b.onclick = () => { S.adding = true; draw(); };
      return b;
    }
    const name = el("input", { placeholder: t("person_name_ph"), className: "pname" });
    const file = el("button", { textContent: t("from_file") });
    const mic = el("button", { textContent: "🎤 " + t("from_mic") });
    const cancel = el("button", { className: "small", textContent: t("cancel_btn") });
    const need = () => { const n = name.value.trim(); if (!n) { name.focus(); S.error = t("name_needed"); draw(); } return n; };
    file.onclick = () => { const n = need(); if (n) run(() => call("add_person_sample_file", null, n)); };
    mic.onclick = () => { const n = need(); if (n) startRec(null, n); };
    cancel.onclick = () => { S.adding = false; S.error = ""; draw(); };
    queueMicrotask(() => name.focus());
    return el("div", { className: "paddbox" }, name, file, mic, cancel);
  }

  async function run(fn) {
    S.error = ""; toast(t("working"));
    try {
      const r = await fn();
      if (r && r.cancelled) { $("toast").hidden = true; return; }
      S.adding = false; if (r && r.name) toast(t("person_saved", { n: r.name }));
    } catch (e) { S.error = msg(e); $("toast").hidden = true; }
    refresh();
  }

  /* ---------- microphone ---------- */
  async function startRec(pid, name) {
    S.error = ""; S.adding = false;
    const lang = S.textLang || (LANG === "en" ? "en" : "tr");
    const text = el("p", { className: "rtext", textContent: TEXTS[lang] });
    const sel = el("select", {}, new Option("Türkçe", "tr"), new Option("English", "en"));
    sel.value = lang; sel.onchange = () => { S.textLang = sel.value; text.textContent = TEXTS[sel.value]; };
    const fill = el("div", { className: "rfill" });
    const meter = el("div", { className: "rmeter" }, fill);
    const prog = el("div", { className: "rbar" }, el("div", { className: "rbarfill" }));
    const label = el("div", { className: "rlabel" });
    const state = el("div", { className: "pmeta" });
    const stop = el("button", { textContent: t("rec_stop"), disabled: true });
    const cancel = el("button", { textContent: t("rec_cancel") });
    const r = S.rec = { timer: null, busy: false };
    stop.onclick = () => finish();
    cancel.onclick = () => cancelRec();
    root.replaceChildren(
      el("div", { className: "toolbar" }, el("h2", { textContent: t("rec_title") }), el("span", { className: "spacer" }),
        el("label", { className: "pmeta" }, t("rec_text_lang") + " ", sel)),
      text, meter, prog, label, state,
      el("p", { className: "hint", textContent: t("rec_tip", { n: MIN_SPEECH }) }),
      el("div", { className: "prow" }, stop, cancel));
    try { await call("start_recording"); } catch (e) { S.rec = null; S.error = t("rec_mic_error") + ": " + msg(e); return draw(); }
    r.stop = stop; r.finish = finish;
    r.timer = setInterval(async () => {
      if (r.busy) return;
      let st;
      try { st = await call("recording_status"); } catch { return; }
      fill.style.width = Math.round(st.level * 100) + "%";
      const got = Math.round(st.speech_seconds);
      prog.firstChild.style.width = Math.min(100, (st.speech_seconds / TARGET) * 100) + "%";
      label.textContent = t("rec_collected", { a: got, b: TARGET }) + `  ·  ${Math.round(st.seconds)} s`;
      stop.disabled = st.speech_seconds < MIN_SPEECH;
      state.textContent = st.speech_seconds >= MIN_SPEECH ? t("rec_enough") : t("rec_wait");
      if (st.done) finish();
    }, 300);
    async function finish() {
      if (r.busy) return;
      r.busy = true; clearInterval(r.timer); state.textContent = t("rec_saving"); stop.disabled = cancel.disabled = true;
      try {
        const p = await call("stop_recording", pid, name);
        toast(t("person_saved", { n: p.name }));
      } catch (e) { S.error = msg(e); }
      S.rec = null; refresh();
    }
  }
  async function cancelRec() {
    const r = S.rec; if (!r) return;
    clearInterval(r.timer); S.rec = null;
    try { await call("cancel_recording"); } catch {}
    if (!root.hidden) refresh();
  }

  /* ---------- transcript view hooks ---------- */
  const isDefault = (n) => !n || /^(?:Speaker|Konuşmacı) \d+$/.test(n);
  window.peopleHooks = {
    speakerMenu(i, menu) {
      if (!job) return;
      menu.append(el("div", { className: "menulabel", textContent: t("save_to_people") }));
      const save1 = async (pid, name) => {
        toast(t("working"));
        try {
          const p = await call("save_speaker_as_person", job.id, i, pid, name);
          toast(t("saved_voice", { n: p.name }) + (p.weak ? " - " + t("weak_voice") : ""));
          refresh(false);
        } catch (e) { toast(msg(e)); }
      };
      const nm = el("input", { placeholder: t("new_person") + "…", value: isDefault(spkNames[i]) ? "" : spkNames[i] });
      const go = el("button", { className: "small", textContent: t("save_btn") });
      go.onclick = () => nm.value.trim() ? save1(null, nm.value.trim()) : (toast(t("name_needed")), nm.focus());
      menu.append(el("div", { className: "prow" }, nm, go));
      for (const p of S.list) {
        const b = el("button", { className: "small", textContent: "→ " + p.name });
        b.onclick = () => save1(p.id, null);
        menu.append(b);
      }
      if (S.list.length) {
        const rm = el("button", { className: "small", textContent: "↻ " + t("rematch") });
        rm.onclick = async () => {
          await save(); toast(t("working"));
          try { applyJob(await call("rematch_job", job.id)); toast(t("rematched")); } catch (e) { toast(msg(e)); }
        };
        menu.append(rm);
      }
    },
    speakerCard(i, card) {
      const m = job?.voice_matches?.[i], s = job?.voice_suggestions?.[i];
      if (m && m.name === spkNames[i]) {
        card.querySelector(".stats")?.append(el("span", {
          className: "vbadge", textContent: `%${Math.round(m.score * 100)}`, title: t("match_title", { p: Math.round(m.score * 100) }) }));
      } else if (s && isDefault(spkNames[i])) {
        const b = el("button", { className: "small vsuggest", textContent: t("maybe_person", { n: s.name }) + " ✓", title: t("accept_title") });
        b.onclick = async () => {
          await save();
          try { applyJob(await call("accept_suggestion", job.id, i, s.person_id)); } catch (e) { toast(msg(e)); }
        };
        card.append(b);
      }
    },
  };
  bridgeReady.then(() => refresh(false));
})();
