"""Pluggable AI backends. Standard library only, so the add-on stays small.

Each provider exposes ask(prompt, images=None, want_json=False, system=None, max_tokens=None, timeout=None) -> str.
"""

import json
import logging
import re
import urllib.error
import urllib.request

log = logging.getLogger("wardrobe.ai")


class AIError(RuntimeError):
    pass


def _post(url: str, payload: dict, headers: dict, timeout: int) -> dict:
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(), method="POST",
        headers={"content-type": "application/json", **headers},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")[:400]
        raise AIError(f"{exc.code} from AI backend: {body}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise AIError(f"Could not reach AI backend at {url}: {exc}") from exc


class OllamaProvider:
    name = "ollama"

    def __init__(self, url: str, model: str):
        self.url = url.rstrip("/")
        self.model = model

    def ask(self, prompt, images=None, want_json=False, system=None, max_tokens=None, timeout=None) -> str:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        msg = {"role": "user", "content": prompt}
        if images:
            msg["images"] = [b64 for _, b64 in images]
        messages.append(msg)
        payload = {"model": self.model, "messages": messages, "stream": False,
                   "options": {"temperature": 0.3}}
        if want_json:
            payload["format"] = "json"
        data = _post(f"{self.url}/api/chat", payload, {}, timeout=max(180, timeout or 0))
        return data.get("message", {}).get("content", "")


class ClaudeProvider:
    name = "claude"
    API = "https://api.anthropic.com/v1/messages"

    def __init__(self, api_key: str, model: str):
        self.api_key = api_key
        self.model = model

    def ask(self, prompt, images=None, want_json=False, system=None, max_tokens=None, timeout=None) -> str:
        content = []
        for media_type, b64 in images or []:
            content.append({"type": "image",
                            "source": {"type": "base64", "media_type": media_type, "data": b64}})
        if want_json:
            prompt += "\n\nRespond with a single JSON object and nothing else."
        content.append({"type": "text", "text": prompt})
        payload = {"model": self.model, "max_tokens": max_tokens or 1500,
                   "messages": [{"role": "user", "content": content}]}
        if system:
            payload["system"] = system
        data = _post(self.API, payload,
                     {"x-api-key": self.api_key, "anthropic-version": "2023-06-01"}, timeout=timeout or 90)
        return "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")


def parse_json(text: str) -> dict:
    """Pull the first JSON object out of a model reply (tolerates code fences and chatter)."""
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    if fence:
        text = fence.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise AIError("AI reply did not contain JSON")
    try:
        return json.loads(text[start:end + 1])
    except ValueError as exc:
        raise AIError("AI reply contained malformed JSON") from exc


def build(kind: str, opts: dict):
    """kind is 'text' or 'vision'. Returns a provider or None when switched off/misconfigured."""
    choice = (opts.get(f"ai_{kind}_provider") or "none").lower()
    if choice == "ollama" and opts.get("ollama_url"):
        model = opts.get("ollama_vision_model" if kind == "vision" else "ollama_text_model")
        return OllamaProvider(opts["ollama_url"], model)
    if choice == "claude" and opts.get("claude_api_key"):
        return ClaudeProvider(opts["claude_api_key"], opts.get("claude_model") or "claude-sonnet-5-5")
    return None


def describe(opts: dict) -> dict:
    out = {}
    for kind in ("text", "vision"):
        p = build(kind, opts)
        out[kind] = {"enabled": p is not None, "provider": p.name if p else "none",
                     "model": getattr(p, "model", None)}
    return out
