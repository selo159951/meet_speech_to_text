"""decode -> split into parts -> transcribe parts (+ speakers in parallel) -> merge.

Progress is written to the job file. Every finished part is saved to
jobs/<id>/parts/<n>.json, so a job interrupted by closing the app resumes where
it stopped (run_job(..., resume=True)).
"""
from __future__ import annotations

import json
import threading
import time
import traceback
from collections import Counter
from pathlib import Path

from . import store
from .merge import Word, assign_speakers, build_segments

SR = 16000
_queue_lock = threading.Lock()  # one heavy job at a time


def run_job(job_id: str, src: Path | None, keep_source: bool = True, resume: bool = False) -> None:
    """keep_source=True: src is the user's own file and must never be deleted."""
    t_start = time.time()
    try:
        with _queue_lock:
            _run(job_id, src, resume, t_start)
    except ValueError as e:  # user-facing problems (bad file etc.)
        store.update_job(job_id, status="error", stage="error", error=str(e))
    except Exception as e:  # surfaced in UI
        traceback.print_exc()
        store.update_job(job_id, status="error", stage="error", error=f"{type(e).__name__}: {e}")
    finally:
        if src is not None and not keep_source:  # only temporary copies are removed
            try:
                Path(src).unlink(missing_ok=True)
            except OSError:
                pass


def _run(job_id: str, src: Path | None, resume: bool, t_start: float) -> None:
    from . import asr, audio, chunking, diarize

    jp = store.job_path(job_id)
    job = store.read_transcript(job_id)
    status = {"stage": "converting", "progress": 0.0, "dprogress": 0.0}

    def push(**extra):
        store.update_job(job_id, status="running", stage=status["stage"],
                         progress=round(status["progress"], 3), dprogress=round(status["dprogress"], 3), **extra)

    push()
    if resume and (jp / "audio.mp3").exists():
        samples, duration = audio.decode(jp / "audio.mp3")
    else:
        samples, duration = audio.convert(src, jp / "audio.mp3")
    t_decoded = time.time()

    parts = job.get("parts") if resume and job.get("parts") else chunking.split(samples)
    status["stage"] = "loading_model"
    push(duration=duration, parts=parts)
    asr.load_model()
    device = asr.status()["device_in_use"]

    # Speakers are found on the whole recording (so a voice keeps one label across parts).
    # With a GPU doing the transcription, the CPU is free: run both at the same time.
    diar: dict = {}
    cancel = threading.Event()  # stops speaker separation if transcription fails
    last_d = [0.0]

    def dprog(p):
        status["dprogress"] = p
        if p - last_d[0] >= 0.02:
            last_d[0] = p
            push()

    def run_diar():
        t0 = time.time()
        try:
            diar["turns"] = diarize.diarize(samples, lambda p: dprog(p * 0.85), cancel)
        except Exception as e:  # re-raised in the main thread
            diar["error"] = e
        diar["secs"] = time.time() - t0

    parallel = device != "cpu" and _parallel_enabled()
    th = threading.Thread(target=run_diar, daemon=True) if parallel else None
    if th:
        th.start()
    try:
        return _transcribe_and_finish(job_id, jp, job, samples, duration, parts, device, parallel,
                                      th, diar, run_diar, dprog, push, status, resume, t_start, t_decoded)
    finally:
        cancel.set()  # no-op when finished; stops a still running separation after an error


def _parallel_enabled() -> bool:
    import os

    return os.environ.get("MEETTRANSCRIBER_SEQUENTIAL") != "1"


def _transcribe_and_finish(job_id, jp, job, samples, duration, parts, device, parallel,
                           th, diar, run_diar, dprog, push, status, resume, t_start, t_decoded):
    from . import asr, diarize

    status["stage"] = "transcribing"
    push(device=device)
    part_dir = jp / "parts"
    part_dir.mkdir(exist_ok=True)
    words: list[Word] = []
    langs: Counter = Counter()
    last_t = [0.0]
    t_asr = time.time()
    for i, (a, b) in enumerate(parts):
        f = part_dir / f"{i}.json"
        if resume and f.exists():  # already done before the app was closed
            saved = json.loads(f.read_text("utf-8"))
        else:
            def tprog(p, a=a, b=b):
                status["progress"] = (a + p * (b - a)) / duration
                if status["progress"] - last_t[0] >= 0.01:
                    last_t[0] = status["progress"]
                    push(part=i + 1)

            ws, lang = asr.transcribe(samples[int(a * SR):int(b * SR)], b - a, tprog)
            saved = {"lang": lang, "words": [[round(w.start + a, 3), round(w.end + a, 3), w.text] for w in ws]}
            f.write_text(json.dumps(saved, ensure_ascii=False), "utf-8")
        words += [Word(s, e, t) for s, e, t in saved["words"]]
        langs[saved["lang"]] += b - a
        status["progress"] = b / duration
        push(part=i + 1)
    asr_secs = time.time() - t_asr
    language = langs.most_common(1)[0][0] if langs else None

    status["stage"] = "diarizing"
    push(language=language)
    if th:
        th.join()
    else:
        run_diar()
    if "error" in diar:
        raise diar["error"]
    turns = diar["turns"]
    t_ref = time.time()
    spk = assign_speakers(words, turns)
    spk = diarize.refine_by_sentence(samples, words, spk, lambda p: dprog(0.85 + p * 0.15))
    segments = build_segments(words, turns, speakers=spk)

    n = len({s["speaker"] for s in segments}) or 1
    speakers = {str(i): f"Speaker {i + 1}" for i in range(n)}
    from .names import detect_names

    for k, name in detect_names(segments, speakers).items():
        speakers[str(k)] = name
    from . import people  # ---- people: saved voices override the guesses (free when nobody is saved)

    voices = people.apply_to_job(samples, segments, speakers)
    timings = {"audio": round(duration, 1), "device": device, "parallel": parallel,
               "decode": round(t_decoded - t_start, 1), "asr": round(asr_secs, 1),
               "diar": round(diar["secs"] + (time.time() - t_ref), 1), "total": round(time.time() - t_start, 1)}
    store.update_job(
        job_id, status="done", stage="done", progress=1.0, dprogress=1.0, segments=segments,
        speakers=speakers, timings=timings, **voices,
        # frozen copy of the model output for the "Original" export
        original_segments=[{k: s[k] for k in ("start", "end", "speaker", "text_original")} for s in segments],
    )
