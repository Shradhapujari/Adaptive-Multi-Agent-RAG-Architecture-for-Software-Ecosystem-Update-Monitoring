"""
Provider-agnostic LLM client layer.
====================================
A single `LLMClient` interface over multiple backends so the evaluation
harness (and, later, the agents themselves) can swap models with zero code
change. This is the "decouple the brain from the harness" principle: the
orchestration never hard-codes a model.

Backends:
  - ollama:<model>      local, no API key  (works today: llama3.1, mistral, minimax-m2.7:cloud)
  - openai:<model>      needs OPENAI_API_KEY     (gpt-4o, gpt-4o-mini, ...)
  - anthropic:<model>   needs ANTHROPIC_API_KEY  (claude-*)

Spec format: "<backend>:<model>", e.g. "ollama:llama3.1", "openai:gpt-4o".
A bare model name with no colon defaults to the ollama backend.

Every client exposes:
    client.generate(prompt, system=None, temperature=0.0, max_tokens=1024) -> str
    client.available() -> bool      # can this client actually run right now?
    client.spec  -> str             # canonical "backend:model"
"""

from __future__ import annotations

import json
import os
import urllib.request
import urllib.error
from typing import Optional


class LLMError(Exception):
    pass


class LLMClient:
    """Base interface. Subclasses implement _generate()."""

    backend = "base"

    def __init__(self, model: str):
        self.model = model

    @property
    def spec(self) -> str:
        return f"{self.backend}:{self.model}"

    def available(self) -> bool:
        return True

    def generate(self, prompt: str, system: Optional[str] = None,
                 temperature: float = 0.0, max_tokens: int = 1024) -> str:
        try:
            return self._generate(prompt, system, temperature, max_tokens).strip()
        except Exception as e:  # noqa: BLE001 — surface a uniform error string
            raise LLMError(f"{self.spec}: {e}") from e

    def _generate(self, prompt, system, temperature, max_tokens) -> str:
        raise NotImplementedError


class OllamaClient(LLMClient):
    """Local Ollama REST API at localhost:11434 (no key required)."""

    backend = "ollama"

    def __init__(self, model: str, host: str = "http://localhost:11434", timeout: int = 120):
        super().__init__(model)
        self.host = host.rstrip("/")
        self.timeout = timeout

    def available(self) -> bool:
        try:
            req = urllib.request.Request(f"{self.host}/api/tags", method="GET")
            with urllib.request.urlopen(req, timeout=5) as resp:
                tags = json.loads(resp.read()).get("models", [])
            names = {m.get("name", "").split(":")[0] for m in tags}
            names |= {m.get("name", "") for m in tags}
            return self.model in names or self.model.split(":")[0] in names
        except Exception:
            return False

    def _generate(self, prompt, system, temperature, max_tokens) -> str:
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }
        if system:
            payload["system"] = system
        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            f"{self.host}/api/generate", data=data,
            headers={"Content-Type": "application/json"}, method="POST",
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return json.loads(resp.read()).get("response", "")


class OpenAIClient(LLMClient):
    """OpenAI Chat Completions. Needs OPENAI_API_KEY and the `openai` package."""

    backend = "openai"

    def __init__(self, model: str):
        super().__init__(model)
        self._client = None

    def available(self) -> bool:
        if not os.getenv("OPENAI_API_KEY"):
            return False
        try:
            import openai  # noqa: F401
            return True
        except ImportError:
            return False

    def _ensure(self):
        if self._client is None:
            from openai import OpenAI
            self._client = OpenAI()
        return self._client

    def _generate(self, prompt, system, temperature, max_tokens) -> str:
        client = self._ensure()
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        resp = client.chat.completions.create(
            model=self.model, messages=messages,
            temperature=temperature, max_tokens=max_tokens,
        )
        return resp.choices[0].message.content or ""


class AnthropicClient(LLMClient):
    """Anthropic Messages API. Needs ANTHROPIC_API_KEY and the `anthropic` package."""

    backend = "anthropic"

    def __init__(self, model: str):
        super().__init__(model)
        self._client = None

    def available(self) -> bool:
        if not os.getenv("ANTHROPIC_API_KEY"):
            return False
        try:
            import anthropic  # noqa: F401
            return True
        except ImportError:
            return False

    def _ensure(self):
        if self._client is None:
            import anthropic
            self._client = anthropic.Anthropic()
        return self._client

    def _generate(self, prompt, system, temperature, max_tokens) -> str:
        client = self._ensure()
        kwargs = dict(model=self.model, max_tokens=max_tokens,
                      temperature=temperature,
                      messages=[{"role": "user", "content": prompt}])
        if system:
            kwargs["system"] = system
        resp = client.messages.create(**kwargs)
        return "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")


_BACKENDS = {
    "ollama": OllamaClient,
    "openai": OpenAIClient,
    "anthropic": AnthropicClient,
}


def make_client(spec: str) -> LLMClient:
    """Build an LLMClient from a 'backend:model' spec. Bare name -> ollama."""
    if ":" in spec:
        backend, model = spec.split(":", 1)
        # 'minimax-m2.7:cloud' style ollama tags: treat unknown backend as ollama model
        if backend not in _BACKENDS:
            return OllamaClient(spec)
    else:
        backend, model = "ollama", spec
    return _BACKENDS[backend](model)


if __name__ == "__main__":
    # Quick smoke test of whichever backends are reachable.
    for spec in ["ollama:llama3.1", "ollama:mistral", "openai:gpt-4o-mini",
                 "anthropic:claude-sonnet-4-6"]:
        c = make_client(spec)
        status = "available" if c.available() else "unavailable"
        print(f"{c.spec:35s} {status}")
