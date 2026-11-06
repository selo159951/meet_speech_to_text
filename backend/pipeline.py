"""convert -> transcribe -> diarize -> merge, with progress persisted to the job file."""
from __future__ import annotations

import threading
import traceback
from pathlib import Path

from . import store
from .merge import assign_speakers, build_segments

_queue_lock = threading.Lock()  # one heavy job at a time


def run_job(job_id: str, src: Path) -> None:
    def stage(name: str, progress: float = 0.0, **extra):
        store.update_job(job_id, status="running", stage=name, progress=round(progress, 3), **extra)

    try:
        with _queue_lock:
            from . import asr, audio, diarize

            jp = store.job_path(job_id)
            stage("converting")
            samples, duration = audio.convert(src, jp / "audio.mp3")
            stage("loading_model", duration=duration)
            asr.load_model()
            stage("transcribing", 0.0, device=asr.status()["device_in_use"])
            last = [0.0]

            def tprog(p):
                if p - last[0] >= 0.01:
                    last[0] = p
                    stage("transcribing", p)

            words, lang = asr.transcribe(samples, duration, tprog)
            stage("diarizing", 0.0, language=lang)
            last[0] = 0.0

            def dprog(p):
                if p - last[0] >= 0.02:
                    last[0] = p
                    stage("diarizing", p)

            turns = diarize.diarize(samples, lambda p: dprog(p * 0.7))
            spk = assign_speakers(words, turns)
            spk = diarize.refine_by_sentence(samples, words, spk, lambda p: dprog(0.7 + p * 0.3))
            segments = build_segments(words, turns, speakers=spk)
            n = len({s["speaker"] for s in segments}) or 1
            speakers = {str(i): f"Speaker {i + 1}" for i in range(n)}
            from .names import detect_names

            for spk, name in detect_names(segments, speakers).items():
                speakers[str(spk)] = name
            store.update_job(
                job_id, status="done", stage="done", progress=1.0, segments=segments,
                speakers=speakers,
                # frozen copy of the model output for the "Original" export
                original_segments=[{k: s[k] for k in ("start", "end", "speaker", "text_original")}
                                   for s in segments],
            )
    except ValueError as e:  # user-facing problems (bad file etc.)
        store.update_job(job_id, status="error", stage="error", error=str(e))
    except Exception as e:  # surfaced in UI
        traceback.print_exc()
        store.update_job(job_id, status="error", stage="error", error=f"{type(e).__name__}: {e}")
    finally:
        try:
            src.unlink(missing_ok=True)
        except OSError:
            pass
