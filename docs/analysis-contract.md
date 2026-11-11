# Meeting mode: contract between modules

Everything runs on the PC. No HTTP server, no port, no Ollama. Speakers are the keys of
`job["speakers"]` (`"0"`, `"1"`, ...); `segment["speaker"]` is the same number as int.
"line" always means a segment `id`.

## 1. LLM engine: `backend/llm/__init__.py`
```python
class LlmError(Exception): ...
class Cancelled(Exception): ...
def available() -> bool                    # binary present AND a model downloaded
def plan() -> dict                          # {"model": name, "path": str, "device": "vulkan"|"cpu", "gpu_index": int|None, "ctx": int}
def generate(prompt: str, schema: dict | None = None, system: str | None = None,
             max_tokens: int = 2048, temperature: float = 0.2,
             cancel: threading.Event | None = None) -> dict | str
    # schema given -> output is constrained to it and returned parsed (dict); else text.
    # Raises LlmError (with the tail of stderr), Cancelled when cancel is set (process is killed).
def approx_tokens(text: str) -> int         # cheap estimate, no model needed (len/3 for Turkish)
```
- Runs `vendor/llamacpp/llama-completion.exe` (frozen app: `<app>/_internal/llamacpp`) as a child process per call:
  `-m <gguf> -f <prompt file> -sysf <system file> --json-schema <schema> -no-cnv --jinja --simple-io --no-display-prompt --log-disable -ngl 999|0 -dev VulkanN -c <ctx> -n <max_tokens> --temp <t> --reasoning-budget 0`,
  UTF-8 in and out, `CREATE_NO_WINDOW`. Same pattern as `backend/engines/whispercpp.py`.
- Device: same rule as `backend/engines/__init__.py::choose` (real card -> Vulkan, onboard/none -> CPU).
- Model catalog and downloads: `backend/llm/catalog.py` (`CATALOG`, `recommend(hw)`, `fit(name, hw)`,
  `is_downloaded`, `start_download`, `download_status`), files in `<models root>/llm/*.gguf`
  (`backend/models.py::root`). Setting `llm_model`: `"auto"` or a catalog name.

## 2. Analysis: `backend/analysis.py`
```python
def stats(segments, speakers) -> dict                     # no LLM, exact numbers
def run(job_id: str, cancel: threading.Event | None = None, generate=llm.generate) -> dict   # blocking; writes files
def start(job_id: str) -> dict                             # background thread, one at a time (queue)
def cancel(job_id: str) -> dict
def status(job_id: str) -> dict                            # see get_analysis below
```
Stages: `stats` -> `notes` (one LLM call per ~3000-token chunk of lines, saved to
`jobs/<id>/analysis/parts/<n>.json`, skipped when present and the chunk hash matches) -> `names`
(`names_llm.suggest`) -> `merge` (one LLM call over all notes + stats).
`generate` is injectable so tests use a fake.

### `jobs/<id>/analysis.json`
```json
{
  "version": 1, "model": "gemma-...", "device": "vulkan", "lang": "tr",
  "created": 1731270000.0, "seconds": 84.2, "transcript_hash": "sha1 of (id, speaker, text_edited) of all lines",
  "stats": {
    "duration": 912.4, "balance": 0.71,
    "speakers": [{"id": 0, "name": "Deniz", "seconds": 430.1, "share": 0.52, "turns": 31, "words": 980,
                  "questions": 7, "longest_turn": 48.0}]
  },
  "summary": "3-6 sentences",
  "topics": [{"title": "", "summary": "", "start": 0.0, "end": 181.0, "line": 1}],
  "decisions": [{"text": "", "line": 23}],
  "tasks": [{"owner": 1, "task": "", "due": "" , "line": 40}],
  "open_questions": [{"asker": 2, "text": "", "line": 55}],
  "people": [{"id": 0, "contribution": "", "gained": "", "evidence": [12, 40]}],
  "score": {"overall": 68, "decisions": 70, "tasks": 60, "questions": 80, "repetition": 75, "balance": 55,
            "comment": "", "tips": ["", ""]},
  "name_suggestions": [{"speaker": 1, "name": "Burak", "confidence": 0.8, "line": 9, "source": "llm|rule|both"}]
}
```
- `owner` / `asker` are speaker ids or `null`. `due` is free text or `""`. Sub-scores are 0-100 or null (nothing to judge).
  Version 2: every number is computed from the transcript by `analysis.compute_score` (decisions per minute, tasks with owner and due, answered questions, repetition, balance); the model only writes `comment` and `tips`. `overall` is the mean of the non-null parts. `short` = true (under 60 s or 6 lines) has no score and no person review; `warnings` lists steps that failed softly.
- Every `line` / `evidence` id must exist in the transcript: drop or repair invalid ones after generation.
- Text is written in the language of the recording (`job["language"]`), names taken from `job["speakers"]`.

### Job fields (inside the job json, so lists and `get_job` show it)
`job["analysis"] = {"state": "queued|running|done|error|cancelled", "stage": "stats|notes|names|merge",
"progress": 0.0-1.0, "part": 3, "parts": 9, "error": ""}`. State `stale` is computed on read when
`transcript_hash` no longer matches.

## 3. Names: `backend/names_llm.py`
```python
def suggest(segments, speakers, generate) -> list[dict]     # [{"speaker","name","confidence","line"}]
def combine(rule: dict[int, str], llm: list[dict], voice: dict) -> tuple[dict[int, str], list[dict]]
    # -> (names to apply automatically, suggestions to show)
```
Priority: voice match (`people.apply_to_job`) > rule (`names.detect_names`) and LLM agree -> apply
automatically > only one source -> suggestion ("Burak olabilir?"). Never overwrite a name the user typed.

## 4. Bridge (`backend/bridge.py`, called from JS as `window.pywebview.api.*`)
```
analyze_job(job_id) -> {"ok": true}            cancel_analysis(job_id) -> {"ok": true}
get_analysis(job_id) -> {"state": "none|queued|running|done|error|cancelled|stale", "stage", "progress",
                         "part", "parts", "error", "analysis": {...} | null, "llm_ready": bool}
accept_name_suggestion(job_id, speaker, name) -> job      # renames the speaker, removes the suggestion
get_llm_info() -> {"binary": bool, "device": "vulkan|cpu", "gpu": "name"|null, "model": "auto|name",
                   "active": name, "models": [{"name","label","size_gb","need_gb","downloaded","fit":"ok|tight|no","recommended"}],
                   "download": {"name","done","total","running","error"}}
set_llm_model(name) -> get_llm_info()          download_llm(name=None) -> {...}
```
Settings (`get_settings` / `set_settings`): `meeting_mode: bool` (default false), `llm_model`.
Meeting mode on: `pipeline._transcribe_and_finish` marks the job done first, then calls `analysis.start(job_id)`.
When the LLM is not ready the job simply has no analysis; the UI shows "download the model" instead.

## 5. Rules for everyone
- New UI strings go into `frontend/i18n.js` in both `tr` and `en`.
- Tests never touch `%APPDATA%`; use the `MEETTRANSCRIBER_HOME` temp-dir fixture in `tests/`.
- No real meeting text in tests or prompts sent anywhere: use `tests/data/meeting_tr.txt` (fictional).
- No new network listeners. No git push.
