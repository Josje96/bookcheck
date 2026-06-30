"""Provider registry: build an LLM client for a named provider and check it's
ready. Both clients expose the same duck-typed interface the pipeline uses
(`chat`, `chat_json`, `strip_think`) and the chat endpoint uses
(`chat_messages_stream`), so callers don't branch on provider beyond this module.

Adding a provider = implement that interface in a new client module and add a
branch in `make_client` / `check_ready` here.
"""

from __future__ import annotations

import os

from .deepseek_client import DeepSeekClient
from .gemini_client import GeminiClient
from .ollama_client import OllamaClient, OllamaError

PROVIDERS = ["ollama", "gemini", "deepseek"]


def make_client(provider: str, model: str | None = None):
    """Construct a client for the provider. `model` is the provider-specific
    model id (Gemini/DeepSeek) or the extraction-model override (Ollama)."""
    p = (provider or "ollama").lower()
    if p == "gemini":
        key = os.environ.get("GEMINI_API_KEY", "")
        gm = model or os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
        return GeminiClient(key, model=gm)
    if p == "deepseek":
        key = os.environ.get("DEEPSEEK_API_KEY", "")
        dm = model or os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash")
        return DeepSeekClient(key, model=dm)
    if p == "ollama":
        return OllamaClient()
    raise ValueError(f"Unknown provider: {provider!r}")


def check_ready(provider: str, needed_models: list[str]) -> tuple[bool, str]:
    """Return (ok, detail). For Ollama, verifies the server is up and the needed
    models are pulled. For Gemini, verifies a key is set and the API answers."""
    p = (provider or "ollama").lower()
    if p == "gemini":
        key = os.environ.get("GEMINI_API_KEY", "")
        if not key:
            return False, "GEMINI_API_KEY is not set — configure it in .env."
        gm = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
        if not GeminiClient(key, model=gm).ping():
            return False, "Could not reach Gemini (check the API key / network)."
        return True, ""
    if p == "deepseek":
        key = os.environ.get("DEEPSEEK_API_KEY", "")
        if not key:
            return False, "DEEPSEEK_API_KEY is not set — configure it in .env."
        dm = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash")
        if not DeepSeekClient(key, model=dm).ping():
            return False, "Could not reach DeepSeek (check the API key / network)."
        return True, ""
    if p == "ollama":
        client = OllamaClient()
        try:
            have = client.ensure_up()
        except OllamaError as e:
            return False, str(e)
        missing = [m for m in needed_models if m not in have]
        if missing:
            return False, (
                "Missing Ollama models: " + ", ".join(missing) + ". Pull with: "
                + " && ".join(f"ollama pull {m}" for m in missing))
        return True, ""
    return False, f"Unknown provider: {provider!r}"
