# BookCheck

Check out the demo [Here](https://ai-book-analysis.pages.dev/)

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

  available VRAM/RAM, and either recommend a local model size or steer
  the user toward a cloud key if local would be too slow
