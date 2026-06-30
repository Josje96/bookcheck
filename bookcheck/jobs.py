"""In-memory background job runner for the analysis pipeline.

The CLI runs the pipeline synchronously and prints progress. The HTTP API
needs it to run in the background while the front end polls for progress, so
this module re-orchestrates the same module functions (not the `cmd_*` CLI
wrappers, which print and `sys.exit`) inside a daemon thread, updating a
thread-safe `Job` record between steps.

Single-process, single-DB by design — this is the local-first tool. Real
multi-tenant job storage is a SaaS-phase concern.
"""

from __future__ import annotations

import os
import threading
import time
import traceback
import uuid

from . import (
    conflict, extract, ingest, providers, report, resolve, store, summarize,
    verify,
)

# Capture the stock Ollama model assignments at import (before any run mutates
# these module-level globals) so every run can reset to a known baseline.
_OLLAMA_DEFAULTS = {
    "extract": extract.EXTRACT_MODEL,
    "consistency": conflict.CONSISTENCY_MODEL,
    "final": conflict.FINAL_MODEL,
    "verify": verify.VERIFY_MODEL,
    "summary": summarize.SUMMARY_MODEL,
}

# (key, human label) in execution order. Used for progress display.
STEPS = [
    ("ingest", "Splitting the manuscript"),
    ("extract", "Reading scenes & building the story bible"),
    ("check", "Checking for contradictions"),
    ("understand", "Summarizing chapters & characters"),
    ("report", "Writing the report"),
]
_STEP_KEYS = [k for k, _ in STEPS]


class Job:
    def __init__(self, db: str, out: str, *, provider="ollama",
                 extract_model=None, deep=False, wip=None):
        self.id = uuid.uuid4().hex[:12]
        self.db = db
        self.out = out
        self.provider = (provider or "ollama").lower()
        self.extract_model = extract_model  # provider-specific model override
        self.model = None               # resolved primary model (set at run time)
        self.deep = deep
        self.wip = wip  # None = auto-detect
        self.status = "queued"          # queued | running | done | error
        self.step = None                # current step key
        self.step_index = 0
        self.message = "Queued"
        self.error = None
        self.created_at = time.time()
        self.started_at = None
        self.finished_at = None
        self._lock = threading.Lock()

    def _set(self, step_key: str):
        label = dict(STEPS).get(step_key, step_key)
        with self._lock:
            self.step = step_key
            self.step_index = _STEP_KEYS.index(step_key)
            self.message = label

    def to_dict(self) -> dict:
        with self._lock:
            elapsed = ((self.finished_at or time.time()) - self.started_at) \
                if self.started_at else 0
            return {
                "id": self.id,
                "status": self.status,
                "step": self.step,
                "step_index": self.step_index,
                "total_steps": len(STEPS),
                "message": self.message,
                "error": self.error,
                "elapsed_s": round(elapsed, 1),
                "provider": self.provider,
                "model": self.model,
                "finished_at": self.finished_at,
                "steps": [{"key": k, "label": l} for k, l in STEPS],
            }


_jobs: dict[str, Job] = {}
_jobs_lock = threading.Lock()
_latest_id: str | None = None


def get(job_id: str) -> Job | None:
    with _jobs_lock:
        return _jobs.get(job_id)


def latest() -> Job | None:
    with _jobs_lock:
        return _jobs.get(_latest_id) if _latest_id else None


def _resolve_models(provider: str, model: str | None) -> dict[str, str]:
    """Decide which model each pass uses. For a paid provider every pass uses
    the one configured model; for Ollama the per-pass defaults stand, with an
    optional extraction-model override."""
    d = _OLLAMA_DEFAULTS
    if provider == "gemini":
        gm = model or os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
        return {k: gm for k in d}
    if provider == "deepseek":
        dm = model or os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash")
        return {k: dm for k in d}
    em = model or d["extract"]
    return {"extract": em, "consistency": em, "final": d["final"],
            "verify": d["verify"], "summary": d["summary"]}


def _apply_models(m: dict[str, str]) -> None:
    extract.EXTRACT_MODEL = m["extract"]
    conflict.CONSISTENCY_MODEL = m["consistency"]
    conflict.FINAL_MODEL = m["final"]
    verify.VERIFY_MODEL = m["verify"]
    summarize.SUMMARY_MODEL = m["summary"]


def source_path(db: str) -> str:
    """Where the raw uploaded manuscript is stashed, so a run can be repeated
    (e.g. with a different model) without re-uploading the file."""
    return os.path.join(os.path.dirname(os.path.abspath(db)), "source.txt")


def has_source(db: str) -> bool:
    return os.path.exists(source_path(db))


def read_source(db: str) -> str:
    with open(source_path(db), encoding="utf-8") as f:
        return f.read()


def save_source(db: str, text: str) -> None:
    p = source_path(db)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(text)


def start_run(manuscript_text: str, *, db: str, out: str, provider="ollama",
              extract_model=None, deep=False, wip=None) -> Job:
    save_source(db, manuscript_text)
    job = Job(db, out, provider=provider, extract_model=extract_model,
              deep=deep, wip=wip)
    global _latest_id
    with _jobs_lock:
        _jobs[job.id] = job
        _latest_id = job.id
    t = threading.Thread(target=_run, args=(job, manuscript_text), daemon=True)
    t.start()
    return job


def _run(job: Job, text: str) -> None:
    job.started_at = time.time()
    job.status = "running"
    try:
        # Resolve + apply per-pass models for this provider, then fail fast with
        # a clear message if the provider isn't ready (Ollama down / model not
        # pulled, or Gemini key missing / unreachable).
        models = _resolve_models(job.provider, job.extract_model)
        job.model = models["extract"]  # surfaced to the UI for the "last run" note
        _apply_models(models)
        ok, detail = providers.check_ready(job.provider, sorted(set(models.values())))
        if not ok:
            raise RuntimeError(detail)
        client = providers.make_client(job.provider, job.extract_model)

        conn = store.connect(job.db)

        job._set("ingest")
        store.init_db(conn, reset=True)
        chunks = ingest.split_manuscript(text)
        for c in chunks:
            store.insert_chunk(conn, c)
        conn.commit()
        if not chunks:
            raise ValueError("No scenes found — is this a manuscript file?")

        job._set("extract")
        extract.run_extraction(conn, client)
        store.merge_subset_characters(conn)
        resolve.run_entity_resolution(conn, client, model=models["extract"])

        job._set("check")
        conflict.run_entity_pass(conn, client)
        verify.run_verification(conn, client)
        if job.deep:
            conflict.run_final_pass(conn, client)

        job._set("understand")
        wip = job.wip if job.wip is not None else store.detect_wip(conn)
        # Pass model explicitly: run_all_comprehension's default is bound at
        # import, so the module-global override wouldn't reach it.
        summarize.run_all_comprehension(
            conn, client, model=models["summary"], wip=wip)

        job._set("report")
        report.generate(conn, job.out)

        with job._lock:
            job.status = "done"
            job.message = "Done"
    except Exception as e:  # noqa: BLE001 - surface any failure to the client
        traceback.print_exc()
        with job._lock:
            job.status = "error"
            job.error = str(e)
            job.message = "Failed"
    finally:
        job.finished_at = time.time()
