"""Minimal Google Gemini client (REST, streaming) — a paid-API alternative to
the local Ollama backend for the chat endpoint.

Mirrors the small slice of OllamaClient that the chat path needs:
`chat_messages_stream(messages)` yielding ("thinking"|"answer", chunk) pairs,
so the API layer can swap providers without caring which one it's talking to.

Only dependency is `requests`. Uses the OpenAI-incompatible native endpoint
(`streamGenerateContent?alt=sse`) since that's what the user's key is for.
"""

from __future__ import annotations

import json
import time
from typing import Any, Iterator

import requests

from .ollama_client import OllamaClient, _loads_lenient

API_ROOT = "https://generativelanguage.googleapis.com/v1beta"


class GeminiError(RuntimeError):
    pass


class GeminiClient:
    def __init__(self, api_key: str, model: str = "gemini-2.5-flash",
                 timeout: int = 600):
        if not api_key:
            raise GeminiError("No Gemini API key configured (set GEMINI_API_KEY).")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    def _headers(self) -> dict:
        return {"Content-Type": "application/json", "X-goog-api-key": self.api_key}

    @staticmethod
    def _to_payload(messages: list[dict], temperature: float) -> dict:
        """Convert our chat messages to Gemini's request shape.

        Gemini wants a separate `systemInstruction`, role "model" (not
        "assistant"), and `contents` for the turn-by-turn history.
        """
        system_txt = "\n\n".join(
            m["content"] for m in messages if m["role"] == "system")
        contents = []
        for m in messages:
            if m["role"] == "system":
                continue
            role = "model" if m["role"] == "assistant" else "user"
            contents.append({"role": role, "parts": [{"text": m["content"]}]})
        payload: dict = {
            "contents": contents,
            "generationConfig": {"temperature": temperature},
        }
        if system_txt:
            payload["systemInstruction"] = {"parts": [{"text": system_txt}]}
        return payload

    def chat_messages_stream(
        self,
        model: str | None,
        messages: list[dict],
        *,
        think=None,            # accepted for signature parity; unused here
        temperature: float = 0.3,
        num_ctx=None,          # ignored (server-managed)
        num_predict=None,      # ignored
    ) -> Iterator[tuple[str, str]]:
        mdl = model or self.model
        url = f"{API_ROOT}/models/{mdl}:streamGenerateContent?alt=sse"
        payload = self._to_payload(messages, temperature)
        try:
            with requests.post(url, headers=self._headers(), json=payload,
                               timeout=self.timeout, stream=True) as r:
                if r.status_code != 200:
                    raise GeminiError(
                        f"Gemini returned {r.status_code}: {r.text[:300]}")
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
                    for kind, chunk in _extract_parts(obj):
                        yield kind, chunk
        except requests.RequestException as e:
            raise GeminiError(f"Gemini request failed: {e}") from e

    # --- one-shot generation (pipeline interface, mirrors OllamaClient) -----

    # Gemini answers are already clean (reasoning goes to a separate field), but
    # reuse Ollama's stripper defensively in case stray <think> tags appear.
    strip_think = staticmethod(OllamaClient.strip_think)

    def _generate(self, model: str | None, system: str, user: str, *,
                  json_mode: bool = False, temperature: float = 0.0,
                  think=None) -> str:
        mdl = model or self.model
        url = f"{API_ROOT}/models/{mdl}:generateContent"
        gen_cfg: dict = {"temperature": temperature}
        if json_mode:
            gen_cfg["responseMimeType"] = "application/json"
        # The pipeline passes think=False everywhere; disable thinking to cut
        # cost/latency on the many structured calls (Flash supports budget 0).
        if not think:
            gen_cfg["thinkingConfig"] = {"thinkingBudget": 0}

        def _post(cfg: dict) -> requests.Response:
            payload: dict = {
                "contents": [{"role": "user", "parts": [{"text": user}]}],
                "generationConfig": cfg,
            }
            if system:
                payload["systemInstruction"] = {"parts": [{"text": system}]}
            return requests.post(url, headers=self._headers(), json=payload,
                                 timeout=self.timeout)

        try:
            r = _post(gen_cfg)
            # Some models reject thinkingBudget=0; retry once without it.
            if r.status_code == 400 and "thinking" in r.text.lower():
                gen_cfg.pop("thinkingConfig", None)
                r = _post(gen_cfg)
        except requests.RequestException as e:
            raise GeminiError(f"Gemini request failed: {e}") from e
        if r.status_code != 200:
            raise GeminiError(f"Gemini returned {r.status_code}: {r.text[:300]}")
        cands = r.json().get("candidates") or []
        if not cands:
            raise GeminiError("Gemini returned no candidates.")
        parts = cands[0].get("content", {}).get("parts") or []
        return "".join(p.get("text", "") for p in parts if not p.get("thought"))

    def chat(self, model: str, system: str, user: str, *, fmt=None,
             think=None, temperature: float = 0.0, num_ctx=None,
             num_predict=None) -> str:
        json_mode = fmt == "json" or isinstance(fmt, dict)
        return self._generate(model, system, user, json_mode=json_mode,
                              temperature=temperature, think=think)

    def chat_json(self, model: str, system: str, user: str, *, schema=None,
                  think=None, num_ctx=None, num_predict=None,
                  retries: int = 2) -> Any:
        """Parsed JSON via Gemini's JSON mime mode + lenient parse. We don't pass
        the JSON schema (Gemini's responseSchema is a stricter OpenAPI subset);
        the prompts already describe the shape and lenient parsing handles it."""
        last_err = None
        for attempt in range(retries + 1):
            try:
                raw = self._generate(model, system, user, json_mode=True,
                                     temperature=0.0, think=think)
                return _loads_lenient(self.strip_think(raw))
            except Exception as e:  # noqa: BLE001
                last_err = e
                if attempt < retries:
                    user = (user + "\n\nIMPORTANT: Respond with ONLY valid JSON. "
                            "No prose, no markdown fences, no commentary.")
                    time.sleep(0.5)
        raise GeminiError(
            f"Failed to get valid JSON from {model or self.model}: {last_err}")

    def ping(self) -> bool:
        """Lightweight reachability/auth check."""
        url = f"{API_ROOT}/models/{self.model}"
        try:
            r = requests.get(url, headers=self._headers(), timeout=10)
            return r.status_code == 200
        except requests.RequestException:
            return False


def _extract_parts(obj: dict) -> Iterator[tuple[str, str]]:
    candidates = obj.get("candidates") or []
    if not candidates:
        return
    parts = candidates[0].get("content", {}).get("parts") or []
    for p in parts:
        txt = p.get("text")
        if not txt:
            continue
        # Gemini marks reasoning summaries with thought=True (only present when
        # includeThoughts is enabled); route them to the "thinking" channel.
        yield ("thinking" if p.get("thought") else "answer", txt)
