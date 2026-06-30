"""Minimal Ollama client: /api/chat with JSON-schema-constrained output,
thinking control, and a repair-retry for small models that emit stray text.

Only dependency is `requests`. Everything else is stdlib.
"""

from __future__ import annotations

import json
import re
import time
from typing import Any, Optional

import requests

DEFAULT_HOST = "http://localhost:11434"

# deepseek-r1 wraps its reasoning in <think>...</think>; strip it before parsing.
_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_DANGLING_THINK_RE = re.compile(r"^.*?</think>", re.DOTALL | re.IGNORECASE)


class OllamaError(RuntimeError):
    pass


class OllamaClient:
    def __init__(self, host: str = DEFAULT_HOST, timeout: int = 1800):
        self.host = host.rstrip("/")
        self.timeout = timeout

    def _post(self, payload: dict) -> dict:
        r = requests.post(f"{self.host}/api/chat", json=payload,
                          timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    def chat(
        self,
        model: str,
        system: str,
        user: str,
        *,
        fmt: Optional[Any] = None,      # JSON schema dict, "json", or None
        think: Optional[bool] = None,    # False to disable qwen3/r1 thinking
        temperature: float = 0.0,
        num_ctx: int = 8192,
        num_predict: int = -1,           # cap generation length (-1 = no cap)
    ) -> str:
        payload: dict = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
            "options": {"temperature": temperature, "num_ctx": num_ctx,
                        "num_predict": num_predict},
        }
        if fmt is not None:
            payload["format"] = fmt
        if think is not None:
            payload["think"] = think
        data = self._post(payload)
        return data.get("message", {}).get("content", "")

    def chat_messages_stream(
        self,
        model: str,
        messages: list[dict],
        *,
        think: Optional[bool] = True,
        temperature: float = 0.3,
        num_ctx: int = 8192,
        num_predict: int = -1,
    ):
        """Stream a multi-turn chat, yielding ("thinking"|"answer", chunk) pairs.

        `messages` is the full conversation (including any system message).
        Streaming matters here: on an 8GB GPU generation is ~5 tok/s, so the
        front end needs tokens as they arrive rather than a 60s blank wait.

        With `think=True`, Ollama routes qwen3's reasoning into a separate
        `thinking` field and keeps `content` clean — so we can show live
        reasoning in a collapsible panel without it polluting the answer.
        (`think=False` is *not* honored by qwen3 here: it dumps reasoning into
        `content` with a dangling `</think>` instead.)
        """
        payload: dict = {
            "model": model,
            "messages": messages,
            "stream": True,
            "options": {"temperature": temperature, "num_ctx": num_ctx,
                        "num_predict": num_predict},
        }
        if think is not None:
            payload["think"] = think
        with requests.post(f"{self.host}/api/chat", json=payload,
                           timeout=self.timeout, stream=True) as r:
            r.raise_for_status()
            for line in r.iter_lines():
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                msg = obj.get("message", {})
                if msg.get("thinking"):
                    yield ("thinking", msg["thinking"])
                if msg.get("content"):
                    yield ("answer", msg["content"])
                if obj.get("done"):
                    break

    @staticmethod
    def strip_think(text: str) -> str:
        text = _THINK_RE.sub("", text)
        # If a closing tag survived without an opening one (truncated stream),
        # drop everything up to it.
        if "</think>" in text.lower():
            text = _DANGLING_THINK_RE.sub("", text)
        return text.strip()

    def chat_json(
        self,
        model: str,
        system: str,
        user: str,
        *,
        schema: Optional[dict] = None,
        think: Optional[bool] = None,
        num_ctx: int = 8192,
        num_predict: int = -1,
        retries: int = 2,
    ) -> Any:
        """Return parsed JSON. Tries schema-constrained generation first, then
        falls back to free JSON mode + a lenient extract-and-repair parse."""
        last_err = None
        for attempt in range(retries + 1):
            fmt: Any
            if attempt == 0 and schema is not None:
                fmt = schema
            else:
                fmt = "json"
            try:
                raw = self.chat(model, system, user, fmt=fmt, think=think,
                                num_ctx=num_ctx, num_predict=num_predict)
                cleaned = self.strip_think(raw)
                return _loads_lenient(cleaned)
            except Exception as e:  # noqa: BLE001 - retry on any parse/HTTP issue
                last_err = e
                if attempt < retries:
                    # Nudge the model toward strict JSON on retry.
                    user = (user + "\n\nIMPORTANT: Respond with ONLY valid JSON. "
                            "No prose, no markdown fences, no commentary.")
                    time.sleep(1.0)
        raise OllamaError(f"Failed to get valid JSON from {model}: {last_err}")

    def ensure_up(self) -> list[str]:
        """Return installed model names; raise if the server is unreachable."""
        try:
            r = requests.get(f"{self.host}/api/tags", timeout=10)
            r.raise_for_status()
        except Exception as e:  # noqa: BLE001
            raise OllamaError(
                f"Ollama server not reachable at {self.host}. Is it running?"
            ) from e
        return [m["name"] for m in r.json().get("models", [])]


def _loads_lenient(text: str) -> Any:
    """Parse JSON, tolerating markdown fences and surrounding prose."""
    text = text.strip()
    if not text:
        raise ValueError("empty response")
    # Strip ```json ... ``` fences.
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Grab the outermost JSON object or array.
    for open_c, close_c in (("{", "}"), ("[", "]")):
        start = text.find(open_c)
        end = text.rfind(close_c)
        if start != -1 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                continue
    raise ValueError(f"could not parse JSON from: {text[:200]!r}")
