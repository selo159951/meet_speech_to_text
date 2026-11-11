"""People: saved voices that are recognised in new recordings ("this voice is Selim").

A person is a folder data_dir/people/<id>/ with person.json and samples/*.wav (speech only,
16 kHz mono). Their voice print is the mean of L2-normalised 3 s voice prints made with the
same model as the speaker separation (diarize.EMB_MODEL). Everything stays on this PC.
"""
from __future__ import annotations

import itertools
import json
import shutil
import threading
import time
import uuid
import wave
from pathlib import Path

import numpy as np

from . import store

SR = 16000
WIN = 3.0            # seconds of speech per voice print window
MIN_WIN = 1.5        # a shorter tail is dropped
MIN_SPEECH = 30.0    # net speech a sample needs
TARGET = 40.0        # what the UI asks for
MAX_USED = 60.0      # at most this much speech of one sample is used
MAX_JOB_SPEECH = 120.0  # speech per speaker used when matching (bounds the time on long meetings)

# Calibrated on a real 20-person recording (see docs/toplanti-modu-rapor.md): the same person is 0.81-0.91 alike,
# two different people 0.28 on average and 0.66 at most (99% below 0.62). A wrong name is far worse than no name.
MATCH = 0.65         # at least this similar (and clearly better than the next person) -> the name is applied
SUGGEST = 0.50       # between SUGGEST and MATCH -> "Selim olabilir?"
MATCH_MARGIN = 0.08  # the best person must beat the second best by this much to be applied automatically
LEARN_MIN_SPEECH = 15.0   # net speech needed before a voice is learned from a meeting
LEARN_COHESION = 0.75     # the 3 s windows of the speaker must be this alike (otherwise it is several people)
LEARN_SAME_NAME = 0.60    # a new voice under an existing name must be at least this close to that person
LEARN_CONFLICT = 0.70     # a voice this close to a person with ANOTHER name is not learned
MULTI_VOICE = 0.45   # two clusters of windows less similar than this -> "more than one voice"
QUIET_DB = -45.0     # speech quieter than this (dBFS rms) is "too quiet"
CLIP_FRAC = 0.002    # share of clipped samples that counts as clipping

_lock = threading.RLock()
_ex = None


# ---------------------------------------------------------------- messages
def _lang() -> str:
    try:
        from . import asr

        return asr.get_settings().get("ui_lang") or "tr"
    except Exception:
        return "tr"


def _m(tr: str, en: str) -> str:
    return tr if _lang() == "tr" else en


# ---------------------------------------------------------------- voice prints
def _extractor():
    global _ex
    with _lock:
        if _ex is None:
            import sherpa_onnx as so

            from . import diarize

            _ex = so.SpeakerEmbeddingExtractor(so.SpeakerEmbeddingExtractorConfig(
                model=str(diarize.models_dir() / diarize.EMB_MODEL), num_threads=diarize.THREADS))
        return _ex


def embed(samples: np.ndarray) -> np.ndarray:
    ex = _extractor()
    st = ex.create_stream()
    st.accept_waveform(SR, np.ascontiguousarray(samples, dtype=np.float32))
    st.input_finished()
    e = np.array(ex.compute(st), dtype=np.float32)
    return e / (np.linalg.norm(e) + 1e-9)


def _unit(v: np.ndarray) -> np.ndarray:
    return v / (np.linalg.norm(v) + 1e-9)


def window_embeddings(speech: np.ndarray, max_seconds: float = MAX_USED) -> np.ndarray:
    """One normalised embedding per ~3 s window of (speech-only) audio; shape (n, dim)."""
    n, w = len(speech), int(WIN * SR)
    starts = list(range(0, n, w))
    if starts and n - starts[-1] < int(MIN_WIN * SR):
        starts.pop()
    if len(starts) * WIN > max_seconds:  # spread evenly over the whole sample
        idx = np.linspace(0, len(starts) - 1, int(max_seconds / WIN)).round().astype(int)
        starts = [starts[i] for i in sorted(set(idx))]
    if not starts:
        return np.zeros((0, 0), np.float32)
    return np.stack([embed(speech[a:a + w]) for a in starts])


def speech_only(samples: np.ndarray, regions=None) -> np.ndarray:
    """Keep only the voiced parts (Silero VAD), glued together."""
    if regions is None:
        from .chunking import speech_regions

        regions = speech_regions(samples)
    if not regions:
        return samples[:0]
    return np.concatenate([samples[int(a * SR):int(b * SR)] for a, b in regions])


def quality(speech: np.ndarray, embs: np.ndarray) -> list[str]:
    """Warning codes: too_quiet, clipping, multiple_voices."""
    out = []
    if len(speech):
        rms = float(np.sqrt(np.mean(speech.astype(np.float64) ** 2)) + 1e-12)
        if 20 * np.log10(rms) < QUIET_DB:
            out.append("too_quiet")
        if float(np.mean(np.abs(speech) >= 0.99)) > CLIP_FRAC:
            out.append("clipping")
    if _multiple_voices(embs):
        out.append("multiple_voices")
    return out


def _multiple_voices(E: np.ndarray) -> bool:
    """2-means on the window embeddings: two sizeable, clearly different groups."""
    if len(E) < 6:
        return False
    sim = E @ E.T
    i, j = np.unravel_index(np.argmin(sim), sim.shape)
    c = [E[i], E[j]]
    for _ in range(5):
        lab = (E @ c[1] > E @ c[0]).astype(int)
        if lab.min() == lab.max():
            return False
        c = [_unit(E[lab == k].sum(0)) for k in (0, 1)]
    small = min(lab.mean(), 1 - lab.mean())
    return small >= 0.2 and float(c[0] @ c[1]) < MULTI_VOICE


# ---------------------------------------------------------------- storage
def people_dir() -> Path:
    d = store.data_dir() / "people"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _pdir(pid: str) -> Path:
    if not pid or not pid.isalnum():
        raise ValueError("bad person id")
    return people_dir() / pid


def _read(pid: str) -> dict:
    try:
        return json.loads((_pdir(pid) / "person.json").read_text("utf-8"))
    except (FileNotFoundError, ValueError):
        raise ValueError(_m("Kişi bulunamadı", "Person not found")) from None


def _write(p: dict) -> None:
    f = _pdir(p["id"]) / "person.json"
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(p, ensure_ascii=False, indent=1), "utf-8")
    tmp.replace(f)


def _public(p: dict) -> dict:
    secs = sum(s["seconds"] for s in p["samples"])
    return {"id": p["id"], "name": p["name"], "created": p["created"], "seconds": round(secs, 1),
            "samples": len(p["samples"]), "weak": bool(p.get("weak")), "has_voice": bool(p.get("embedding")),
            "auto": bool(p.get("auto")), "confirmed": bool(p.get("confirmed", not p.get("auto"))),
            "meetings": int(p.get("meetings", len(p["samples"]) and 1)),
            "warnings": sorted({w for s in p["samples"] for w in s.get("warnings", [])})}


def _all() -> list[dict]:
    out = []
    for f in sorted(people_dir().glob("*/person.json")):
        try:
            out.append(json.loads(f.read_text("utf-8")))
        except (OSError, ValueError):
            pass
    return sorted(out, key=lambda p: p["created"])


def list_people() -> list[dict]:
    return [_public(p) for p in _all()]


def get_person(pid: str) -> dict:
    return _public(_read(pid))


def create_person(name: str) -> dict:
    name = (name or "").strip()
    if not name:
        raise ValueError(_m("Bir isim yazın", "Enter a name"))
    with _lock:
        pid = uuid.uuid4().hex[:10]
        (_pdir(pid) / "samples").mkdir(parents=True)
        p = {"id": pid, "name": name, "created": time.time(), "samples": [], "embedding": None,
             "emb_model": _model_name(), "weak": False}
        _write(p)
    return _public(p)


def rename_person(pid: str, name: str) -> dict:
    name = (name or "").strip()
    if not name:
        raise ValueError(_m("Bir isim yazın", "Enter a name"))
    with _lock:
        p = _read(pid)
        p["name"] = name
        _write(p)
    return _public(p)


def delete_person(pid: str) -> None:
    with _lock:
        d = _pdir(pid)
        if d.exists():
            shutil.rmtree(d)


def _model_name() -> str:
    from . import diarize

    return diarize.EMB_MODEL


def _save_wav(path: Path, x: np.ndarray) -> None:
    pcm = (np.clip(x, -1, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes(pcm.tobytes())


def _recompute(p: dict) -> None:
    """person embedding = mean of the samples' window embeddings (weighted by window count)."""
    tot, n = None, 0
    for s in p["samples"]:
        e = np.array(s["emb"], np.float32) * s["windows"]
        tot = e if tot is None else tot + e
        n += s["windows"]
    p["embedding"] = _unit(tot).tolist() if tot is not None and n else None
    p["weak"] = sum(s["seconds"] for s in p["samples"]) < MIN_SPEECH


def _enroll(pid: str, speech: np.ndarray, source: str, min_speech: float) -> dict:
    """Add a speech-only sample to a person (raises ValueError if there is too little speech)."""
    secs = len(speech) / SR
    if secs < min_speech:
        raise ValueError(_m(
            f"Bu kayıtta yalnızca {secs:.0f} sn konuşma bulundu; en az {min_speech:.0f} sn gerekiyor "
            f"(en iyisi {TARGET:.0f} sn). Daha uzun bir kayıt deneyin.",
            f"Only {secs:.0f} s of speech was found in this recording; at least {min_speech:.0f} s are needed "
            f"({TARGET:.0f} s is best). Try a longer recording."))
    speech = speech[:int(MAX_USED * SR)]
    E = window_embeddings(speech)
    if not len(E):
        raise ValueError(_m("Konuşma bulunamadı", "No speech found"))
    warns = quality(speech, E)
    with _lock:
        p = _read(pid)
        name = f"{int(time.time() * 1000)}.wav"
        _save_wav(_pdir(pid) / "samples" / name, speech)
        p["samples"].append({"file": name, "seconds": round(len(speech) / SR, 1), "source": source,
                             "warnings": warns, "windows": len(E), "emb": _unit(E.sum(0)).tolist()})
        _recompute(p)
        _write(p)
    return _public(p)


def add_sample_from_array(pid: str, samples: np.ndarray, source: str, min_speech: float = MIN_SPEECH) -> dict:
    _read(pid)
    return _enroll(pid, speech_only(samples), source, min_speech)


def add_sample_from_file(pid: str, path: str, min_speech: float = MIN_SPEECH) -> dict:
    from . import audio

    _read(pid)
    samples, _ = audio.decode(Path(path))
    return _enroll(pid, speech_only(samples), "file:" + Path(path).name, min_speech)


def add_sample_from_job(job_id: str, speaker: int, pid: str | None, name: str | None = None) -> dict:
    """Use this speaker's longest lines of a finished recording. Less than MIN_SPEECH is allowed
    (the person is then marked weak)."""
    from . import audio

    job = store.read_transcript(job_id)
    segs = sorted((s for s in job.get("segments", []) if s["speaker"] == int(speaker)),
                  key=lambda s: s["end"] - s["start"], reverse=True)
    if not segs:
        raise ValueError(_m("Bu konuşmacının satırı yok", "This speaker has no lines"))
    samples, _ = audio.decode(store.job_path(job_id) / "audio.mp3")
    from .chunking import speech_regions

    regions = speech_regions(samples)
    parts, got = [], 0.0
    for s in segs:  # longest first, only the voiced parts inside the line
        for a, b in regions:
            a, b = max(a, s["start"]), min(b, s["end"])
            if b - a > 0.2:
                parts.append(samples[int(a * SR):int(b * SR)]); got += b - a
        if got >= MAX_USED:
            break
    speech = np.concatenate(parts) if parts else samples[:0]
    if len(speech) / SR < 3.0:
        raise ValueError(_m("Bu konuşmacıdan yeterli ses yok", "Not enough audio from this speaker"))
    if pid is None:
        pid = create_person(name or "")["id"]
    else:
        _read(pid)
    return _enroll(pid, speech, f"job:{job_id}:{speaker}", 3.0)


# ---------------------------------------------------------------- matching
def speaker_prints(samples: np.ndarray, segments: list[dict], regions=None) -> dict[int, np.ndarray]:
    """{speaker: voice print} from the speaker's voiced audio (same procedure as enrolment)."""
    if regions is None:
        from .chunking import speech_regions

        regions = speech_regions(samples)
    out = {}
    for spk in sorted({s["speaker"] for s in segments}):
        parts = []
        for s in segments:
            if s["speaker"] != spk:
                continue
            for a, b in regions:
                a, b = max(a, s["start"]), min(b, s["end"])
                if b - a > 0.2:
                    parts.append(samples[int(a * SR):int(b * SR)])
        if not parts:
            continue
        speech = np.concatenate(parts)
        if len(speech) < int(MIN_WIN * SR):  # less than one window: too little for a voice print
            continue
        E = window_embeddings(speech, MAX_JOB_SPEECH)
        if len(E):
            out[int(spk)] = _unit(E.sum(0))
    return out


def assign(sim: dict[int, dict[str, float]], suggest: float = SUGGEST, match: float = MATCH):
    """sim[speaker][person_id] = cosine. One person per speaker, maximising the total similarity
    among pairs >= suggest (brute force: there are only a few speakers).
    Returns (matches, suggestions) as {speaker: (person_id, score)}."""
    spks = list(sim)
    pids = sorted({p for d in sim.values() for p in d})
    best, best_total = {}, -1.0

    def rec(i, used, cur, total):
        nonlocal best, best_total
        if i == len(spks):
            if total > best_total:
                best, best_total = dict(cur), total
            return
        rec(i + 1, used, cur, total)  # this speaker stays unknown
        for p in pids:
            sc = sim[spks[i]].get(p)
            if p not in used and sc is not None and sc >= suggest:
                cur[spks[i]] = (p, sc)
                rec(i + 1, used | {p}, cur, total + sc)
                del cur[spks[i]]

    rec(0, frozenset(), {}, 0.0)
    matches = {s: v for s, v in best.items() if v[1] >= match}
    return matches, {s: v for s, v in best.items() if v[1] < match}


def match_prints(prints: dict[int, np.ndarray], people: list[dict] | None = None) -> dict:
    """-> {"matches": {spk: {person_id, name, score}}, "suggestions": {...}} (string keys)."""
    people = [p for p in (people if people is not None else _all()) if p.get("embedding")]
    if not people or not prints:
        return {"matches": {}, "suggestions": {}}
    names = {p["id"]: p["name"] for p in people}
    emb = {p["id"]: np.array(p["embedding"], np.float32) for p in people}
    sim = {s: {pid: float(v @ e) for pid, e in emb.items()} for s, v in prints.items()}
    m, sg = assign(sim)
    trusted = {p["id"] for p in people if not p.get("auto") or p.get("confirmed") or int(p.get("meetings", 1)) >= 2}
    for s in list(m):  # applied automatically only when clearly better than everybody else, and the person is trusted
        pid, sc = m[s]
        second = max((v for q, v in sim[s].items() if q != pid), default=-1.0)
        if sc - second < MATCH_MARGIN or pid not in trusted:
            sg[s] = m.pop(s)
    fmt = lambda d: {str(s): {"person_id": p, "name": names[p], "score": round(sc, 3)} for s, (p, sc) in d.items()}  # noqa: E731
    return {"matches": fmt(m), "suggestions": fmt(sg)}


def apply_to_job(samples: np.ndarray, segments: list[dict], speakers: dict, keep: dict | None = None) -> dict:
    """Recognise saved people in this recording. Renames the speakers in `speakers` (a dict
    "0" -> label) in place and returns the fields to store in the job. Costs nothing without people.
    `keep`: labels the user chose (speaker -> label) are not overwritten."""
    people = [p for p in _all() if p.get("embedding")]
    if not people:
        return {"voice_matches": {}, "voice_suggestions": {}}
    try:
        res = match_prints(speaker_prints(samples, segments), people)
    except Exception:  # recognising voices must never fail a transcription
        import traceback

        traceback.print_exc()
        return {"voice_matches": {}, "voice_suggestions": {}}
    for k, m in res["matches"].items():
        if not keep or k not in keep:
            speakers[k] = m["name"]
    return {"voice_matches": res["matches"], "voice_suggestions": res["suggestions"]}


def rematch_job(job_id: str) -> dict:
    """Recompute from the saved audio (for recordings made before a person was added)."""
    from . import audio

    job = store.read_transcript(job_id)
    if not job.get("segments"):
        raise ValueError(_m("Bu kayıtta konuşma yok", "This recording has no speech"))
    samples, _ = audio.decode(store.job_path(job_id) / "audio.mp3")
    speakers = dict(job.get("speakers") or {})
    old = job.get("voice_matches") or {}
    # a label the user typed is kept; defaults and earlier voice matches may be replaced
    keep = {k: v for k, v in speakers.items()
            if v and not v.startswith(("Speaker ", "Konuşmacı ")) and old.get(k, {}).get("name") != v}
    extra = apply_to_job(samples, job["segments"], speakers, keep)
    return store.update_job(job_id, speakers=speakers, **extra)


def accept_suggestion(job_id: str, speaker: int, pid: str) -> dict:
    job = store.read_transcript(job_id)
    p = get_person(pid)
    k = str(int(speaker))
    sug = (job.get("voice_suggestions") or {}).pop(k, None)
    matches = job.get("voice_matches") or {}
    matches[k] = {"person_id": pid, "name": p["name"], "score": (sug or {}).get("score", 0)}
    speakers = dict(job.get("speakers") or {})
    speakers[k] = p["name"]
    return store.update_job(job_id, speakers=speakers, voice_matches=matches,
                            voice_suggestions=job.get("voice_suggestions") or {})


def confirm_person(pid: str) -> dict:
    """The user checked a person that was learned automatically: from now on the voice names speakers by itself."""
    with _lock:
        p = _read(pid)
        p["confirmed"] = True
        _write(p)
    return _public(p)


def _speaker_speech(samples: np.ndarray, segments: list[dict], spk: int, regions) -> np.ndarray:
    parts = []
    for s in segments:
        if s["speaker"] != spk:
            continue
        for a, b in regions:
            a, b = max(a, s["start"]), min(b, s["end"])
            if b - a > 0.2:
                parts.append(samples[int(a * SR):int(b * SR)])
    return np.concatenate(parts) if parts else samples[:0]


def learn_from_job(job_id: str, intros: dict[int, str]) -> list[dict]:
    """Learn the voices of the people who introduced themselves in this recording ("my name is X").
    Careful on purpose: a speaker is only learned with enough clean speech from ONE voice; a name that
    already exists is only enriched by a voice that sounds like that person; a voice that sounds like
    somebody with another name is left alone. New people are marked automatic and name speakers by
    themselves only after the user confirms them or they were heard in a second meeting.
    Returns what was done, e.g. [{"speaker": 3, "name": "Elif", "action": "created"}]."""
    from . import audio
    from .chunking import speech_regions

    job = store.read_transcript(job_id)
    segs = job.get("segments") or []
    if not intros or not segs:
        return []
    samples, _ = audio.decode(store.job_path(job_id) / "audio.mp3")
    regions = speech_regions(samples)
    known = [p for p in _all() if p.get("embedding")]
    norm = lambda n: " ".join(str(n).casefold().split())  # noqa: E731
    done = []
    for spk, name in sorted(intros.items()):
        row = {"speaker": int(spk), "name": name}
        try:
            speech = _speaker_speech(samples, segs, int(spk), regions)
            if len(speech) / SR < LEARN_MIN_SPEECH:
                done.append({**row, "action": "skipped", "why": "too_little_speech"})
                continue
            E = window_embeddings(speech[:int(MAX_USED * SR)])
            c = _unit(E.sum(0))
            if len(E) >= 3 and float(np.mean(E @ c)) < LEARN_COHESION or "multiple_voices" in quality(speech, E):
                done.append({**row, "action": "skipped", "why": "several_voices"})
                continue
            other = max(((float(c @ np.array(p["embedding"], np.float32)), p) for p in known if norm(p["name"]) != norm(name)),
                        key=lambda t: t[0], default=(-1.0, None))
            if other[0] >= LEARN_CONFLICT:
                done.append({**row, "action": "skipped", "why": "sounds_like:" + other[1]["name"]})
                continue
            same = next((p for p in known if norm(p["name"]) == norm(name)), None)
            if same is not None:
                if float(c @ np.array(same["embedding"], np.float32)) < LEARN_SAME_NAME:
                    done.append({**row, "action": "skipped", "why": "same_name_other_voice"})
                    continue
                if job_id in (same.get("learned_from") or []):
                    continue
                add_sample_from_job(job_id, int(spk), same["id"])
                with _lock:
                    p = _read(same["id"])
                    p["meetings"] = int(p.get("meetings", 1)) + 1
                    p["learned_from"] = sorted(set(p.get("learned_from") or []) | {job_id})
                    _write(p)
                done.append({**row, "action": "enriched", "person_id": same["id"]})
            else:
                pub = add_sample_from_job(job_id, int(spk), None, name)
                with _lock:
                    p = _read(pub["id"])
                    p.update(auto=True, confirmed=False, meetings=1, learned_from=[job_id])
                    _write(p)
                done.append({**row, "action": "created", "person_id": pub["id"]})
                known.append(_read(pub["id"]))
        except Exception as e:  # learning is a bonus: it must never fail a recording
            done.append({**row, "action": "error", "why": str(e)[:120]})
    return done


# ---------------------------------------------------------------- microphone
READ_AT = 60.0


class Recorder:
    """Records the default microphone into memory; a helper thread measures the net speech."""

    def __init__(self):
        self.chunks: list[np.ndarray] = []
        self.level = 0.0
        self.speech_seconds = 0.0
        self.done = False
        self.error: str | None = None
        self._stream = None
        self._stop = threading.Event()
        self._n = 0

    def start(self):
        import sounddevice as sd

        def cb(indata, frames, t, status):
            x = indata[:, 0].copy()
            self.chunks.append(x)
            self._n += len(x)
            self.level = float(min(1.0, np.sqrt(np.mean(x ** 2)) * 8))
            if self._n >= READ_AT * SR:
                self.done = True

        self._stream = sd.InputStream(samplerate=SR, channels=1, dtype="float32", callback=cb, blocksize=1600)
        self._stream.start()
        threading.Thread(target=self._vad_loop, daemon=True).start()

    def audio(self) -> np.ndarray:
        return np.concatenate(self.chunks) if self.chunks else np.zeros(0, np.float32)

    def _vad_loop(self):
        from .chunking import speech_regions

        while not self._stop.is_set():
            time.sleep(0.8)
            x = self.audio()
            if len(x) > SR:
                try:
                    self.speech_seconds = sum(b - a for a, b in speech_regions(x))
                except Exception:
                    pass
            if self.done:
                self.close()
                return

    def seconds(self) -> float:
        return self._n / SR

    def close(self):
        self._stop.set()
        if self._stream is not None:
            try:
                self._stream.stop(); self._stream.close()
            except Exception:
                pass
            self._stream = None


_rec: Recorder | None = None


def start_recording() -> dict:
    global _rec
    if _rec is not None:
        _rec.close()
    r = Recorder()
    try:
        r.start()
    except Exception as e:
        raise ValueError(_m(f"Mikrofon açılamadı: {e}", f"Could not open the microphone: {e}")) from None
    _rec = r
    return {"ok": True}


def recording_status() -> dict:
    r = _rec
    if r is None:
        return {"seconds": 0, "speech_seconds": 0, "level": 0, "done": False, "active": False}
    return {"seconds": round(r.seconds(), 1), "speech_seconds": round(r.speech_seconds, 1),
            "level": round(r.level, 3), "done": r.done, "active": not r._stop.is_set() or r.done}


def stop_recording(pid: str | None, name: str | None = None) -> dict:
    """Stop and save the recording as a sample of person pid (or of a new person `name`)."""
    global _rec
    r, _rec = _rec, None
    if r is None:
        raise ValueError(_m("Kayıt yapılmıyor", "Not recording"))
    r.close()
    x = r.audio()
    if pid is None:
        if not (name or "").strip():
            raise ValueError(_m("Bir isim yazın", "Enter a name"))
        speech = speech_only(x)  # check first, so a failed recording does not leave an empty person
        if len(speech) / SR < MIN_SPEECH:
            too_short(speech)
        pid = create_person(name)["id"]
        return _enroll(pid, speech, "microphone", MIN_SPEECH)
    return add_sample_from_array(pid, x, "microphone")


def too_short(speech):
    raise ValueError(_m(
        f"Yalnızca {len(speech) / SR:.0f} sn konuşma kaydedildi; en az {MIN_SPEECH:.0f} sn gerekiyor. Tekrar deneyin.",
        f"Only {len(speech) / SR:.0f} s of speech was recorded; at least {MIN_SPEECH:.0f} s are needed. Try again."))


def cancel_recording() -> dict:
    global _rec
    if _rec is not None:
        _rec.close()
        _rec = None
    return {"ok": True}
