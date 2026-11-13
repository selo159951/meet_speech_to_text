"""Job storage: one folder per job under the app-data dir."""
from __future__ import annotations

import json
import logging
import os
import shutil
import threading
import time
import uuid
from pathlib import Path

_lock = threading.RLock()  # re-entrant: update_job holds it across read + write
_log = logging.getLogger(__name__)


APP_DIR = "SesDefteri"
# the older names still work, so existing scripts and data keep working
HOME_ENVS = ("SESDEFTERI_HOME", "KATIP_HOME", "MEETTRANSCRIBER_HOME")


def _home_override() -> str | None:
    return next((os.environ[k] for k in HOME_ENVS if os.environ.get(k)), None)


def data_dir() -> Path:
    override = _home_override()
    if override:
        base = Path(override)
    elif os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home())) / APP_DIR
    else:
        base = Path.home() / ".local" / "share" / APP_DIR
    base.mkdir(parents=True, exist_ok=True)
    return base


def migrate_old_data() -> bool:
    """Bring the data of an earlier version over once.
    %APPDATA%\\Katip (the previous name) is renamed: instant, and the models in it are several GB.
    If that folder is in use, or only the oldest %APPDATA%\\MeetTranscriber exists, it is copied
    instead and the old folder is left as it was."""
    if _home_override():
        return False
    appdata = Path(os.environ.get("APPDATA", Path.home()))
    new, tmp = appdata / APP_DIR, appdata / (APP_DIR + ".tmp")
    if new.exists():
        return False
    katip, oldest = appdata / "Katip", appdata / "MeetTranscriber"
    if katip.exists():
        try:
            katip.rename(new)
            return True
        except OSError:
            _log.exception("could not rename the Katip data folder, copying it instead")
        src = katip
    elif oldest.exists():
        src = oldest
    else:
        return False
    try:
        if tmp.exists():  # leftover from an interrupted copy
            shutil.rmtree(tmp)
        shutil.copytree(src, tmp, ignore=shutil.ignore_patterns("webview"))
        tmp.rename(new)
        return True
    except Exception:
        _log.exception("could not copy the old data folder %s", src)
        return False


def jobs_dir() -> Path:
    d = data_dir() / "jobs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def job_path(job_id: str) -> Path:
    if not job_id.isalnum():
        raise ValueError("bad job id")
    return jobs_dir() / job_id


def create_job(filename: str) -> str:
    job_id = uuid.uuid4().hex[:12]
    p = job_path(job_id)
    p.mkdir(parents=True)
    write_transcript(
        job_id,
        {
            "id": job_id,
            "filename": filename,
            "created": time.time(),
            "status": "queued",
            "stage": "queued",
            "progress": 0.0,
            "error": None,
            "language": None,
            "duration": None,
            "speakers": {},  # "0": "Speaker 1"
            "segments": [],
        },
    )
    return job_id


def read_transcript(job_id: str) -> dict:
    with _lock:
        return json.loads((job_path(job_id) / "transcript.json").read_text("utf-8"))


def write_transcript(job_id: str, data: dict) -> None:
    p = job_path(job_id) / "transcript.json"
    tmp = p.with_suffix(".tmp")
    with _lock:
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), "utf-8")
        os.replace(tmp, p)


def update_job(job_id: str, **fields) -> dict:
    with _lock:  # atomic read-modify-write (progress is written from several threads)
        data = read_transcript(job_id)
        data.update(fields)
        write_transcript(job_id, data)
        return data


def mark_interrupted() -> list[str]:
    """At start-up: jobs that were still running when the app closed can be resumed."""
    ids = []
    for j in list_jobs():
        if j["status"] in ("running", "queued"):
            update_job(j["id"], status="interrupted", stage="interrupted")
            ids.append(j["id"])
        try:
            a = read_transcript(j["id"]).get("analysis") or {}
            if a.get("state") in ("running", "queued"):
                update_job(j["id"], analysis={**a, "state": "cancelled"})
        except (OSError, ValueError):
            pass
    return ids


def _fold(s: str) -> str:
    """Forgiving case-insensitive compare: i / ı / İ / I all match each other."""
    return s.replace("İ", "i").replace("I", "i").replace("ı", "i").lower()


def _snippet(text: str, q: str, width: int = 60) -> str:
    i = _fold(text).find(q)
    a, b = max(0, i - width), min(len(text), i + len(q) + width)
    return ("…" if a else "") + text[a:b] + ("…" if b < len(text) else "")


def list_jobs(q: str = "") -> list[dict]:
    """Summary of every job. With q: only jobs whose name, speakers or text contain q."""
    q = _fold(q.strip())
    out = []
    for p in jobs_dir().iterdir():
        f = p / "transcript.json"
        if not f.exists():
            continue
        try:
            d = json.loads(f.read_text("utf-8"))
        except Exception:
            continue
        segs = d.get("segments") or []
        names = [v for k, v in sorted(d.get("speakers", {}).items())
                 if any(s["speaker"] == int(k) for s in segs)]
        item = {k: d.get(k) for k in ("id", "filename", "created", "status", "duration", "language", "error")}
        if d.get("analysis"):
            item["analysis"] = {"state": d["analysis"].get("state")}
        item.update(speakers=names, lines=len(segs),
                    edited=sum(1 for s in segs if s["text_edited"] != s["text_original"]))
        if q:
            spk_names = d.get("speakers", {})
            hits = [s for s in segs if q in _fold(s["text_edited"])]
            item["name_match"] = q in _fold(d.get("filename", ""))
            item["speaker_match"] = [n for n in names if q in _fold(n)]
            if not (hits or item["name_match"] or item["speaker_match"]):
                continue
            item["count"] = sum(_fold(s["text_edited"]).count(q) for s in hits)
            item["matches"] = [  # where the word appears in the conversation (first 8 lines)
                {"seg": s["id"], "start": s["start"], "speaker": spk_names.get(str(s["speaker"]), ""),
                 "text": _snippet(s["text_edited"], q)}
                for s in hits[:8]
            ]
            item["more"] = max(0, len(hits) - 8)
        out.append(item)
    return sorted(out, key=lambda d: d["created"] or 0, reverse=True)


def rename_job(job_id: str, name: str) -> dict:
    name = name.strip()
    if not name:
        raise ValueError("empty name")
    return update_job(job_id, filename=name[:200])


def delete_job(job_id: str) -> None:
    shutil.rmtree(job_path(job_id), ignore_errors=True)


def split(job_id: str, seg_id: int, a: int, b: int, speaker: int) -> dict:
    from .merge import split_segment

    data = read_transcript(job_id)
    segs = data["segments"]
    idx = next((i for i, s in enumerate(segs) if s["id"] == seg_id), None)
    if idx is None:
        raise KeyError(seg_id)
    next_id = max(s["id"] for s in segs) + 1
    segs[idx:idx + 1] = split_segment(segs[idx], a, b, speaker, next_id)
    data["speakers"].setdefault(str(speaker), f"Speaker {speaker + 1}")
    write_transcript(job_id, data)
    return data


def apply_detected_names(job_id: str) -> tuple[dict, dict]:
    """Fill in names for speakers that still have a default 'Speaker N' label."""
    from .names import detect_names

    data = read_transcript(job_id)
    found = detect_names(data["segments"], data["speakers"])
    data["speakers"].update({str(k): v for k, v in found.items()})
    write_transcript(job_id, data)
    return data, found


def replace_transcript(job_id: str, segments: list[dict], speakers: dict) -> dict:
    """Save the whole edited transcript (add/delete/merge lines, undo).

    text_original and word timings of known segments are kept from disk, so the
    model's output can't be changed from the UI; new lines have no original text.
    """
    data = read_transcript(job_id)
    old = {s["id"]: s for s in data["segments"]}
    out, seen = [], set()
    for s in segments:
        sid = int(s["id"])
        if sid in seen:
            raise ValueError(f"duplicate segment id {sid}")
        seen.add(sid)
        prev = old.get(sid, {})
        start = max(0.0, float(s["start"]))
        out.append({
            "id": sid, "start": round(start, 2), "end": round(max(start, float(s["end"])), 2),
            "speaker": int(s["speaker"]), "text_edited": str(s["text_edited"]),
            "text_original": prev.get("text_original", s.get("text_original", "")),
            "words": prev.get("words", s.get("words", [])),
            # confidence marks of the model's own lines (a line the user gave to another speaker is no longer in doubt)
            **{k: prev[k] for k in ("conf", "low_words") if k in prev},
            **({"spk_conf": prev["spk_conf"]} if "spk_conf" in prev and int(s["speaker"]) == prev.get("speaker") else {}),
        })
    data["segments"] = sorted(out, key=lambda s: (s["start"], s["id"]))
    data["speakers"] = {str(k): str(v) for k, v in speakers.items()}
    write_transcript(job_id, data)
    return data


def _learn(seg: dict, new_text: str) -> None:
    """A corrected spelling in the model's line is remembered (glossary) so the next recording gets it right."""
    try:
        orig = seg.get("text_original") or ""
        if orig and new_text != seg.get("text_edited") and new_text != orig:
            from . import glossary

            glossary.learn(orig, new_text)
    except Exception:
        pass  # learning is a bonus, saving the edit must never fail


def save_edits(job_id: str, edits: dict[int, str] | None = None, speakers: dict | None = None,
               segment_speakers: dict[int, int] | None = None) -> dict:
    """Edits only touch text_edited / speaker labels; text_original is never modified."""
    data = read_transcript(job_id)
    by_id = {s["id"]: s for s in data["segments"]}
    for sid, text in (edits or {}).items():
        if sid in by_id:
            _learn(by_id[sid], text)
            by_id[sid]["text_edited"] = text
    for sid, spk in (segment_speakers or {}).items():
        if sid in by_id:
            by_id[sid]["speaker"] = spk
    if speakers:
        data["speakers"].update({str(k): v for k, v in speakers.items()})
    write_transcript(job_id, data)
    return data
