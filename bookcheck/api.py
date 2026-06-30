"""FastAPI HTTP layer over the bookcheck pipeline.

This wraps the existing CLI pipeline so a web front end (and, later, a hosted
SaaS) can drive it: upload a manuscript, kick off a run, poll progress, fetch
the report + structured story bible, and chat with the model about the book.

Run it with:

    uv run uvicorn bookcheck.api:app --reload

Single-user / single-DB by design (see jobs.py). The story bible in book.db is
the source of truth; everything here is a read or a job kick-off.
"""

from __future__ import annotations

import json
import os

# Load .env (GEMINI_API_KEY etc.) before reading config. No-op if absent.
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse, StreamingResponse
from pydantic import BaseModel

from . import bible, jobs, providers, store
from .deepseek_client import DeepSeekError
from .fileparse import extract_text
from .gemini_client import GeminiError
from .ollama_client import OllamaClient, OllamaError
from .textfmt import dedash

DEFAULT_DB = os.environ.get("BOOKCHECK_DB", "data/book.db")
DEFAULT_REPORT = os.environ.get("BOOKCHECK_REPORT", "reports/report.md")
# 4b for chat: ~2x the tok/s of 8b on an 8GB card, plenty for Q&A over a digest.
CHAT_MODEL = os.environ.get("BOOKCHECK_CHAT_MODEL", "qwen3:4b")

# Chat provider: "ollama" (local, default) or "gemini" (paid API). Each /api/chat
# request may override this with its own `provider` field.
CHAT_PROVIDER = os.environ.get("BOOKCHECK_CHAT_PROVIDER", "ollama").lower()
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash")

# Light personalization for the local/single-user setup (no real auth yet).
USERNAME = os.environ.get("BOOKCHECK_USERNAME", "")

app = FastAPI(title="bookcheck", version="0.2.0")

# The Vite dev server runs on a different origin; allow it in dev.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _connect():
    return store.connect(DEFAULT_DB)


# --- health ---------------------------------------------------------------

@app.get("/api/health")
def health():
    client = OllamaClient()
    try:
        models = client.ensure_up()
        ollama_ok = True
    except OllamaError:
        models = []
        ollama_ok = False
    conn = _connect()
    last_run = jobs.latest()
    return {
        "ok": True,
        "ollama": ollama_ok,
        "models": models,
        "has_manuscript": bible.has_data(conn),
        "has_source": jobs.has_source(DEFAULT_DB),
        "chat_provider": CHAT_PROVIDER,
        "gemini_configured": bool(GEMINI_API_KEY),
        "deepseek_configured": bool(DEEPSEEK_API_KEY),
        "last_provider": (last_run.provider if last_run else None),
        "last_model": (last_run.model if last_run else None),
        "username": USERNAME,
    }


# --- runs -----------------------------------------------------------------

@app.post("/api/runs")
async def create_run(
    file: UploadFile | None = File(default=None),
    text: str | None = Form(default=None),
    provider: str = Form(default="ollama"),
    extract_model: str | None = Form(default=None),
    deep: bool = Form(default=False),
    wip: bool | None = Form(default=None),
    reuse: bool = Form(default=False),
):
    """Start an analysis run from an uploaded file, pasted text, or — with
    `reuse=true` — the previously-uploaded manuscript (for re-running with a
    different model without re-uploading)."""
    if file is not None:
        raw = await file.read()
        manuscript = extract_text(file.filename or "manuscript.txt", raw)
    elif text:
        manuscript = text
    elif reuse and jobs.has_source(DEFAULT_DB):
        manuscript = jobs.read_source(DEFAULT_DB)
    elif reuse:
        raise HTTPException(
            400, "No previous manuscript to re-run — upload one first.")
    else:
        raise HTTPException(400, "Provide a manuscript `file` or `text`.")
    if not manuscript.strip():
        raise HTTPException(400, "Manuscript is empty.")

    job = jobs.start_run(
        manuscript, db=DEFAULT_DB, out=DEFAULT_REPORT, provider=provider,
        extract_model=extract_model or None, deep=deep, wip=wip)
    return job.to_dict()


@app.get("/api/runs/{job_id}")
def get_run(job_id: str):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(404, "No such run.")
    return job.to_dict()


@app.get("/api/runs")
def latest_run():
    job = jobs.latest()
    return job.to_dict() if job else {"status": "none"}


# --- results --------------------------------------------------------------

@app.get("/api/report", response_class=PlainTextResponse)
def get_report():
    if not os.path.exists(DEFAULT_REPORT):
        raise HTTPException(404, "No report yet — run an analysis first.")
    with open(DEFAULT_REPORT, encoding="utf-8") as f:
        # dedash here too so a report.md generated before this change still
        # serves clean without a re-run.
        return dedash(f.read())


@app.get("/api/bible")
def get_bible():
    conn = _connect()
    if not bible.has_data(conn):
        raise HTTPException(404, "No manuscript analyzed yet.")
    return bible.story_bible(conn)


# --- chat -----------------------------------------------------------------

class ChatMessage(BaseModel):
    role: str  # "user" | "assistant"
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]
    provider: str | None = None  # "ollama" | "gemini"; falls back to server default


_CHAT_SYSTEM = (
    "You are a thoughtful writing assistant helping a novelist discuss their "
    "own manuscript. Use the STORY BIBLE below - extracted from their draft - "
    "as your grounding. Answer specifically about THIS book; cite chapters or "
    "characters by name. If something isn't in the bible, say so plainly rather "
    "than inventing details.\n\n"
    "STYLE: Keep answers short and direct. Default to a few concise bullet "
    "points, or 1-3 short sentences for a simple question. Lead with the answer; "
    "do not pad, restate the question, or add a summary. Only write a long, "
    "detailed response when the user explicitly asks for more detail or depth. "
    "Never use em dashes or en dashes; use a comma, a colon, or a plain hyphen "
    "instead.\n\n=== STORY BIBLE ===\n{context}\n=== END ==="
)


@app.post("/api/chat")
def chat(req: ChatRequest):
    conn = _connect()
    if not bible.has_data(conn):
        raise HTTPException(404, "Analyze a manuscript before chatting about it.")
    if not req.messages:
        raise HTTPException(400, "No messages provided.")

    context = bible.chat_context(conn)
    messages = [{"role": "system", "content": _CHAT_SYSTEM.format(context=context)}]
    messages += [{"role": m.role, "content": m.content} for m in req.messages]

    provider = (req.provider or CHAT_PROVIDER).lower()
    try:
        stream = _chat_stream_factory(provider, messages)
    except (GeminiError, DeepSeekError, OllamaError, ValueError) as e:
        raise HTTPException(400, str(e))

    def sse(event: str, data) -> str:
        return f"event: {event}\ndata: {json.dumps(data)}\n\n"

    def event_stream():
        # SSE with two channels: "thinking" (live reasoning, FE shows collapsed)
        # and "answer" (the clean reply). Ends with "done".
        try:
            for kind, chunk in stream:
                # Strip em/en dashes from the visible text channels. Safe per
                # chunk: the dashes are single codepoints, never split across
                # chunks. (Gemini ignores the no-dash prompt rule.)
                if kind in ("answer", "thinking"):
                    chunk = dedash(chunk)
                yield sse(kind, chunk)
        except Exception as e:  # noqa: BLE001
            yield sse("error", str(e))
        yield sse("done", "")

    return StreamingResponse(event_stream(), media_type="text/event-stream")


def _chat_stream_factory(provider: str, messages: list[dict]):
    """Return a (thinking|answer, chunk) generator for the chosen provider."""
    client = providers.make_client(provider)
    if provider in ("gemini", "deepseek"):
        # Cloud clients manage their own context/model; reasoning (if any) comes
        # back on the "thinking" channel automatically.
        return client.chat_messages_stream(None, messages)
    # think=True keeps qwen3's reasoning out of the answer (see ollama_client).
    return client.chat_messages_stream(CHAT_MODEL, messages, think=True,
                                       num_ctx=8192)
