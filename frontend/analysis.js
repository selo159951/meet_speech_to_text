/* Analysis tab for meeting mode. Uses helpers from app.js: $, el, t, call, toast, fmt, mmss,
   displayName, spkClass, jumpToSeg, playRange, refreshSearch, save and applyJob.
   All text from the backend is inserted with textContent (never innerHTML), so the DOM escapes it. */

/* Manual test sample: paste this into `state` in load() or return it from get_analysis while developing.
const SAMPLE_ANALYSIS = {
  version: 1, model: "gemma-3-4b", device: "vulkan", lang: "tr",
  created: 1731270000.0, seconds: 84.2, transcript_hash: "abc",
  stats: { duration: 912.4, balance: 0.71,
    speakers: [{ id: 0, name: "Deniz", seconds: 430.1, share: 0.52, turns: 31, words: 980, questions: 7, longest_turn: 48.0 },
               { id: 1, name: "Burak", seconds: 482.3, share: 0.48, turns: 28, words: 870, questions: 3, longest_turn: 39.0 }] },
  summary: "Ekip yeni sürümün takvimini ve müşteri geri bildirimlerini konuştu. Beta tarihi kararlaştırıldı.",
  topics: [{ title: "Sürüm takvimi", summary: "Beta tarihi ve test planı.", start: 0.0, end: 181.0, line: 1 }],
  decisions: [{ text: "Beta 3 Kasım'da yayınlanacak.", line: 23 }],
  tasks: [{ owner: 1, task: "Test planını yaz.", due: "Cuma", line: 40 }],
  open_questions: [{ asker: 2, text: "Ses kaydı saklanacak mı?", line: 55 }],
  people: [{ id: 0, contribution: "Takvimi netleştirdi.", gained: "Test yükünü paylaştı.", evidence: [12, 40] },
           { id: 1, contribution: "Teknik riskleri anlattı.", gained: "Sorumluluk aldı.", evidence: [23] }],
  score: { overall: 68, decisions: 70, focus: 60, repetition: 75, balance: 55,
    comment: "Verimli ama zaman zaman dağılan bir toplantı.", tips: ["Gündemi baştan paylaşın.", "Her konuyu bir kararla kapatın."] },
  name_suggestions: [{ speaker: 1, name: "Burak", confidence: 0.8, line: 9, source: "llm" }],
};
*/

(() => {
  const pane = $("paneAnalysis"), textPane = $("paneText");
  const tabText = $("tabText"), tabAnalysis = $("tabAnalysis");
  let tab = "text", jobId = null, last = null, pollT = null;

  const apiHas = (name) => !!(window.pywebview?.api && typeof window.pywebview.api[name] === "function");
  const stopPoll = () => { clearTimeout(pollT); pollT = null; };
  const devName = (d) => t({ vulkan: "dev_vulkan", cuda: "dev_cuda", cpu: "dev_cpu" }[d] || "dev_cpu");
  const card = (title, ...kids) => el("div", { className: "acard" }, el("h3", { textContent: title }), ...kids);

  function setTab(which) {
    tab = which;
    tabText.classList.toggle("active", which === "text");
    tabAnalysis.classList.toggle("active", which === "analysis");
    textPane.hidden = which !== "text";
    pane.hidden = which !== "analysis";
    if (which === "analysis") load(); else stopPoll();
  }
  tabText.onclick = () => setTab("text");
  tabAnalysis.onclick = () => setTab("analysis");

  /* ---------- names / transcript links ---------- */
  const speakerName = (id) => {
    if (id === null || id === undefined) return "—";
    const n = job?.speakers?.[String(id)] ?? job?.speakers?.[id];
    return displayName(n) || t("speaker_n", { n: Number(id) + 1 });
  };
  const segOf = (line) => job?.segments?.find((s) => s.id === line) || null;

  /* Switch to the Metin tab, make the line visible, scroll to it and play it. */
  function jumpAndPlay(line) {
    if (line === null || line === undefined || !job) return;
    const seg = segOf(line);
    setTab("text");
    if (!seg) return;
    if ($("fSpk").value !== "" && +$("fSpk").value !== seg.speaker) { $("fSpk").value = ""; refreshSearch(false); }
    jumpToSeg(line);
    playRange(seg.start, seg.end);
  }

  const linkChip = (line) => {
    const b = el("button", { className: "alinkchip", textContent: line === null || line === undefined ? "—" : t("line_chip", { n: line }), title: t("open_line") });
    if (line === null || line === undefined) b.disabled = true; else b.onclick = () => jumpAndPlay(line);
    return b;
  };

  /* ---------- actions ---------- */
  async function start() {
    if (!job || !apiHas("analyze_job")) return;
    try { await call("analyze_job", job.id); } catch (e) { toast(String(e?.message || e)); return; }
    load();
  }
  async function cancel() {
    if (!job || !apiHas("cancel_analysis")) return;
    try { await call("cancel_analysis", job.id); } catch (e) { toast(String(e?.message || e)); }
    load();
  }

  /* ---------- loading / polling ---------- */
  async function load() {
    stopPoll();
    if (!job) { pane.replaceChildren(); return; }
    const id = job.id;
    jobId = id;
    let st;
    if (!apiHas("get_analysis")) {
      // backend not present yet (this worktree): show the "none" state with no model
      st = { state: "none", llm_ready: false };
    } else {
      try { st = await call("get_analysis", id); }
      catch (e) { st = { state: "error", error: String(e?.message || e) }; }
    }
    if (tab !== "analysis" || jobId !== id) return; // tab or job changed while waiting
    last = st;
    render(st);
    if (st.state === "queued" || st.state === "running") pollT = setTimeout(() => { if (tab === "analysis" && jobId === id) load(); }, 1500);
  }

  /* ---------- render ---------- */
  function render(st) {
    if (!job) return pane.replaceChildren();
    if (st.state === "queued" || st.state === "running") return pane.replaceChildren(progressCard(st));
    if (st.state === "error" || st.state === "cancelled") return pane.replaceChildren(errorCard(st));
    if ((st.state === "done" || st.state === "stale") && st.analysis) return pane.replaceChildren(...analysisCards(st));
    pane.replaceChildren(noneCard(st));
  }

  function noneCard(st) {
    const box = card(t("tab_analysis"), el("p", { textContent: t("an_none_desc") }));
    if (st.llm_ready === false) {
      box.append(el("div", { className: "anotice", textContent: t("an_no_llm") }));
      const b = el("button", { className: "primary", textContent: t("an_open_system") });
      b.onclick = () => $("sysBtn").click();
      box.append(b);
    } else {
      const b = el("button", { className: "primary", textContent: t("an_run") });
      b.onclick = start;
      box.append(b);
    }
    return box;
  }

  function progressCard(st) {
    const p = Math.max(0, Math.min(1, Number(st.progress) || 0));
    let label;
    if (st.stage === "notes") label = t("an_stage_notes", { i: st.part || 0, n: st.parts || 0 });
    else if (st.stage === "stats" || st.stage === "names" || st.stage === "merge") label = t("an_stage_" + st.stage);
    else label = st.state === "queued" ? t("an_stage_queued") : t("an_stage_stats");
    const b = el("button", { className: "small", textContent: t("an_cancel") });
    b.onclick = () => { b.disabled = true; cancel(); };
    return card(t("tab_analysis"),
      el("div", { className: "anrow" }, el("span", { textContent: label }), el("span", { className: "ameta", textContent: `${Math.round(p * 100)}%` })),
      el("div", { className: "bar" }, el("div", { style: `width:${Math.round(p * 100)}%` })),
      b);
  }

  function errorCard(st) {
    const text = st.error || (st.state === "cancelled" ? t("an_cancelled") : t("error"));
    const b = el("button", { className: "primary", textContent: t("an_retry") });
    b.onclick = start;
    return card(t("tab_analysis"), el("div", { className: "anotice warn", textContent: text }), b);
  }

  function analysisCards(st) {
    const a = st.analysis, out = [];
    if (st.state === "stale") {
      const banner = el("div", { className: "abanner" },
        el("span", { textContent: t("an_stale") }));
      const re = el("button", { className: "small", textContent: t("an_reanalyse") });
      re.onclick = start;
      banner.append(re);
      out.push(banner);
    }

    // header: model, device, duration, disclaimer
    const meta = [];
    if (a.model) meta.push(`${t("an_model")}: ${a.model}`);
    if (a.device) meta.push(`${t("an_device")}: ${devName(a.device)}`);
    if (a.seconds !== null && a.seconds !== undefined) meta.push(t("an_seconds", { s: Math.round(a.seconds) }));
    out.push(el("div", { className: "acard" },
      el("div", { className: "ahead" }, ...meta.map((x) => el("span", { textContent: x }))),
      el("div", { className: "ameta note", textContent: t("an_disclaimer") })));

    // meeting score
    const sc = a.score || {};
    const big = el("div", { className: "big" });
    big.append(String(sc.overall ?? "—"), el("small", { textContent: " / 100" }));
    const mini = el("div", { className: "amini" });
    for (const [key, label] of [["decisions", "an_decisions"], ["focus", "an_focus"], ["repetition", "an_repetition"], ["balance", "an_balance"]]) {
      const v = Math.max(0, Math.min(100, Number(sc[key]) || 0));
      mini.append(el("div", { className: "row" },
        el("span", { textContent: t(label) }),
        el("div", { className: "bar" }, el("div", { style: `width:${v}%` })),
        el("span", { className: "ameta", textContent: sc[key] === undefined ? "—" : String(sc[key]) })));
    }
    const scoreCard = el("div", { className: "acard" }, el("h3", { textContent: t("an_score") }), el("div", { className: "ascore" }, big, mini));
    if (sc.comment) scoreCard.append(el("p", { textContent: sc.comment }));
    if (sc.tips?.length) scoreCard.append(el("div", { className: "alabel", textContent: t("an_tips") }),
      el("ul", { className: "alist" }, ...sc.tips.map((x) => el("li", { textContent: x }))));
    out.push(scoreCard);

    if (a.summary) out.push(card(t("an_summary"), el("p", { textContent: a.summary })));

    // topics timeline
    if (a.topics?.length) {
      const c = card(t("an_topics"));
      for (const tp of a.topics) {
        const time = el("button", { className: "chip", textContent: `${fmt(tp.start || 0)} – ${fmt(tp.end || 0)}`, title: t("play_part") });
        time.onclick = () => jumpAndPlay(tp.line);
        c.append(el("div", { className: "atopic" }, time,
          el("div", {}, el("div", { className: "astrong", textContent: tp.title || "" }), el("div", { className: "ameta", textContent: tp.summary || "" }))));
      }
      out.push(c);
    }

    // decisions
    if (a.decisions?.length) {
      out.push(card(t("an_decisions"), ...a.decisions.map((d) =>
        el("div", { className: "arow" }, el("span", { className: "atext", textContent: d.text || "" }), linkChip(d.line)))));
    }

    // tasks: owner, task, due
    if (a.tasks?.length) {
      out.push(card(t("an_tasks"), ...a.tasks.map((tk) =>
        el("div", { className: "arow" },
          el("span", { className: "who", textContent: speakerName(tk.owner) }),
          el("span", { className: "atext", textContent: tk.task || "" }),
          el("span", { className: "ameta", textContent: `${t("an_due")}: ${tk.due || "—"}` }),
          linkChip(tk.line)))));
    }

    // open questions
    if (a.open_questions?.length) {
      out.push(card(t("an_open_questions"), ...a.open_questions.map((q) =>
        el("div", { className: "arow" },
          el("span", { className: "who", textContent: speakerName(q.asker) }),
          el("span", { className: "atext", textContent: q.text || "" }),
          linkChip(q.line)))));
    }

    // people
    const stats = new Map((a.stats?.speakers || []).map((s) => [s.id, s]));
    const people = a.people?.length ? a.people : (a.stats?.speakers || []).map((s) => ({ id: s.id }));
    if (people.length) {
      const c = card(t("an_people"));
      for (const p of people) {
        const sp = stats.get(p.id) || {};
        const pct = Math.round((Number(sp.share) || 0) * 100);
        const evidence = (p.evidence || []).map((line) => {
          const b = el("button", { className: "alinkchip", textContent: t("line_chip", { n: line }), title: t("open_line") });
          b.onclick = () => jumpAndPlay(line);
          return b;
        });
        c.append(el("div", { className: "aperson" },
          el("div", { className: "top" },
            el("span", { className: "name " + spkClass(p.id), textContent: speakerName(p.id) }),
            el("span", { className: "ameta", textContent: `${t("an_share")} · ${pct}%` })),
          el("div", { className: "asharebar" }, el("div", { style: `width:${pct}%` })),
          el("div", { className: "ameta", textContent: [
            `${sp.turns || 0} ${t("an_turns")}`, `${sp.words || 0} ${t("an_words")}`,
            `${sp.questions || 0} ${t("an_questions")}`, t("an_longest", { s: mmss(sp.longest_turn || 0) })].join("  ·  ") }),
          el("div", {}, el("span", { className: "alabel", textContent: t("an_contribution") + "  " }), p.contribution || "—"),
          el("div", {}, el("span", { className: "alabel", textContent: t("an_gained") + "  " }), p.gained || "—"),
          ...(evidence.length ? [el("div", { className: "aevidence" },
            el("span", { className: "alabel", textContent: t("an_evidence") + "  " }), ...evidence)] : [])));
      }
      out.push(c);
    }

    // name suggestions
    if (a.name_suggestions?.length) {
      const wrap = el("div", { className: "aevidence" });
      for (const s of a.name_suggestions) {
        const chip = el("span", { className: "asugchip" },
          el("span", { textContent: t("an_suggestion", { s: speakerName(s.speaker), n: s.name }) }));
        const ok = el("button", { className: "small", textContent: "✓", title: t("an_accept") });
        ok.onclick = async () => {
          if (!apiHas("accept_name_suggestion")) return;
          try {
            await save();
            applyJob(await call("accept_name_suggestion", job.id, s.speaker, s.name)); // returns the updated job
          } catch (e) { toast(String(e?.message || e)); return; }
          load();
        };
        const no = el("button", { className: "small", textContent: "✕", title: t("an_dismiss") });
        no.onclick = () => chip.remove();
        chip.append(ok, no);
        wrap.append(chip);
      }
      out.push(card(t("an_name_suggestions"), wrap));
    }

    return out;
  }

  /* ---------- hooks from app.js ---------- */
  window.analysisHooks = {
    opened(j) { // a job was opened: back to Metin and drop any pending poll
      stopPoll();
      jobId = j?.id ?? null;
      last = null;
      pane.replaceChildren();
      setTab("text");
    },
  };
  $("langSel").addEventListener("change", () => { if (tab === "analysis" && last) render(last); });
})();
