# BookCheck

BookCheck gives authors an automated first-pass read of a novel: chapter
summaries, character profiles, a timeline, relationship map, and a
"things to fix" list (duplicate passages, draft notes, verified
contradictions) - the kind of read-through pass you'd otherwise pay an
editor for.

It's a fullstack app (Python/FastAPI + React) that runs on a single
machine. **It works best with a cheap cloud model** - a full analysis
costs a few cents and takes 3-5 minutes on Gemini Flash or DeepSeek
V4 Flash. **Ollama is fully supported as a free, local, bring-your-own-LLM
option**, but consumer GPUs will feel it: on an 8GB AMD card (RX 6600,
Vulkan backend, no ROCm) qwen3:8b runs at ~5.5 tok/s and a full run takes
much longer than the cloud path. If you have a beefier GPU, or don't mind
the wait, the local path is genuinely free and your manuscript never
leaves your machine.

Bottom line: bring an API key for speed, or bring Ollama for privacy/cost.
Both are first-class - pick per-run from the UI.

Please read licensing - this is a GPL-licensed repo. See the letter of
intent for more on why this project exists and how it's meant to be used.

## Prereqs

- Python, Node, [uv](https://docs.astral.sh/uv/)
- An API key for a cloud provider (recommended - cheap and fast):
  - [Gemini](https://aistudio.google.com/apikey)
  - [DeepSeek](https://platform.deepseek.com)
- [Ollama](https://ollama.com) - only needed for the fully local path

## Installation guide

1. Install the prereqs above.
2. Clone/download this repo.
3. Copy `.env.example` to `.env` and fill in your provider key(s) (or
   leave them blank if you're going Ollama-only).
4. `uv sync --extra api` (add `--extra api` for the HTTP API/web app).
5. `cd frontend && npm install`
6. Run it:
   - Backend: `uv run uvicorn bookcheck.api:app --port 8000`
   - Frontend: `npm run dev` (from `frontend/`)
7. Open the frontend, upload a manuscript, pick an analysis engine
   (Gemini / DeepSeek / local Ollama model), and run.

## Roadmap

### Done

- Multi-provider pipeline: Ollama (local), Gemini, DeepSeek - swappable
  per run, including for chat
- Chapter summaries, murky-spot flags, beta-reader-style overall
  impression
- Character profiles (role, arc, strengths/weaknesses, species,
  aliases), relationship map, visual timeline, locations
- Deterministic duplicate-passage detection + verified-contradiction
  pipeline (LLM re-reads source before a contradiction is reported)
- DOCX/PDF upload, re-run on the same manuscript without re-uploading
- Persistent chat grounded in the story bible, with streamed
  "thinking" + "answer" channels
- Theming, last-run summary, toasts, polish pass

### Now - polish & robustness

- Chat: ability to clear context / start a new conversation, and
  switch which character/thread you're focused on
- Investigate undercounted characters on some DeepSeek runs
- Per-character timeline in chat ("what scenes did I miss with X")
- Pin an exact model per pipeline pass (not just per provider)

### Next - deployment

- Docker Compose file for single-command startup
- Hardware-aware onboarding: detect whether Ollama is present, gauge
  available VRAM/RAM, and either recommend a local model size or steer
  the user toward a cloud key if local would be too slow

### Later - SaaS

- Host as a pay-as-you-go hosted service, so users who don't want to
  manage API keys or local hardware at all can just use it
