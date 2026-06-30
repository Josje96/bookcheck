"""Minimal DeepSeek client (OpenAI-compatible REST, streaming) — a paid-API
alternative to Ollama/Gemini for BOTH chat and the analysis pipeline.

DeepSeek's API is OpenAI-compatible (Bearer auth, POST /chat/completions). The V4
models are reasoning models: a response carries `reasoning_content` separately
from `content`, which maps cleanly onto our two-channel (thinking|answer) stream.
JSON mode is `response_format={"type":"json_object"}` and requires the word
"json" somewhere in the prompt (our pipeline prompts already say "valid JSON").

Mirrors the same duck-typed interface as GeminiClient/OllamaClient (see
providers.py). Only dependency is `requests`.
"""

from __future__ import annotations

import json
import time
from typing import Any, Iterator

import requests

from .ollama_client import OllamaClient, _loads_lenient

API_ROOT = "https://api.deepseek.com"


class DeepSeekError(RuntimeError):
    pass


class DeepSeekClient:
    def __init__(self, api_key: str, model: str = "deepseek-v4-flash",
                 timeout: int = 600):
        if not api_key:
            raise DeepSeekError(
                "No DeepSeek API key configured (set DEEPSEEK_API_KEY).")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"}

    # DeepSeek answers are already clean (reasoning is a separate field), but
    # reuse Ollama's stripper defensively in case stray <think> tags appear.
    strip_think = staticmethod(OllamaClient.strip_think)

    # --- streaming chat (chat endpoint) -------------------------------------

    def chat_messages_stream(
        self,
        model: str | None,
        messages: list[dict],
        *,
        think=None,            # accepted for signature parity; unused
        temperature: float = 0.3,
        num_ctx=None,          # ignored (server-managed)
        num_predict=None,      # ignored
    ) -> Iterator[tuple[str, str]]:
        mdl = model or self.model
        payload = {"model": mdl, "messages": messages,
                   "temperature": temperature, "stream": True}
        try:
            with requests.post(f"{API_ROOT}/chat/completions",
                               headers=self._headers(), json=payload,
                               timeout=self.timeout, stream=True) as r:
                if r.status_code != 200:
                    raise DeepSeekError(
                        f"DeepSeek returned {r.status_code}: {r.text[:300]}")
                for line in r.iter_lines():
                    if not line:
                        continue
                    text = line.decode("utf-8") if isinstance(line, bytes) else line
                    if not text.startswith("data:"):
                        continue
                    data = text[len("data:"):].strip()
                    if not data or data == "[DONE]":
                        continue
                    try:
                        obj = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    delta = (obj.get("choices") or [{}])[0].get("delta") or {}
                    rc = delta.get("reasoning_content")
                    if rc:
                        yield ("thinking", rc)
                    c = delta.get("content")
                    if c:
                        yield ("answer", c)
        except requests.RequestException as e:
            raise DeepSeekError(f"DeepSeek request failed: {e}") from e

    # --- one-shot generation (pipeline interface) ---------------------------

    def _complete(self, model: str | None, system: str, user: str, *,
                  json_mode: bool = False, temperature: float = 0.0,
                  thinking: bool = False) -> str:
        mdl = model or self.model
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": user})
        payload: dict = {"model": mdl, "messages": messages,
                         "temperature": temperature}
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        # V4 models think by default; the pipeline doesn't need reasoning, so
        # disable it to cut tokens/latency. (Top-level field for the raw REST
        # API; the OpenAI SDK's `extra_body` wrapper isn't needed here.)
        payload["thinking"] = {"type": "enabled" if thinking else "disabled"}
        try:
            r = requests.post(f"{API_ROOT}/chat/completions",
                              headers=self._headers(), json=payload,
                              timeout=self.timeout)
        except requests.RequestException as e:
            raise DeepSeekError(f"DeepSeek request failed: {e}") from e
        if r.status_code != 200:
            raise DeepSeekError(f"DeepSeek returned {r.status_code}: {r.text[:300]}")
        choices = r.json().get("choices") or []
        if not choices:
            raise DeepSeekError("DeepSeek returned no choices.")
        return choices[0].get("message", {}).get("content") or ""

    def chat(self, model: str, system: str, user: str, *, fmt=None,
             think=None, temperature: float = 0.0, num_ctx=None,
             num_predict=None) -> str:
        json_mode = fmt == "json" or isinstance(fmt, dict)
        return self._complete(model, system, user, json_mode=json_mode,
                              temperature=temperature, thinking=bool(think))

    def chat_json(self, model: str, system: str, user: str, *, schema=None,
                  think=None, num_ctx=None, num_predict=None,
                  retries: int = 2) -> Any:
        """Parsed JSON from DeepSeek. First attempt uses free-form response
        (relying on the prompt to say "valid JSON" and _loads_lenient to parse),
        fallback retries use json_object mode which can produce empty structures."""
        last_err = None
        for attempt in range(retries + 1):
            json_mode = attempt > 0  # only json_object on retries
            try:
                raw = self._complete(model, system, user, json_mode=json_mode,
                                     temperature=0.0,
                                     thinking=bool(think))
                return _loads_lenient(self.strip_think(raw))
            except Exception as e:  # noqa: BLE001
                last_err = e
                if attempt < retries:
                    user = (user + "\n\nIMPORTANT: Respond with ONLY valid JSON. "
                            "No prose, no markdown fences, no commentary.")
                    time.sleep(0.5)
        raise DeepSeekError(
            f"Failed to get valid JSON from {model or self.model}: {last_err}")

    def ping(self) -> bool:
        """Lightweight reachability/auth check (lists models)."""
        try:
            r = requests.get(f"{API_ROOT}/models", headers=self._headers(),
                             timeout=10)
            return r.status_code == 200
        except requests.RequestException:
            return False
