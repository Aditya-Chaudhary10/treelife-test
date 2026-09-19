"""Thin LLM client over any OpenAI-compatible API (Groq by default).

Design goals:
  * every call is metered (tokens + call count) so the UI can show real cost
  * JSON responses are parsed defensively and repaired once if malformed
  * 429 / 5xx are retried with backoff (Groq free tier = 8k tokens/min)
  * a context budget is enforced so no single call can balloon
"""
from __future__ import annotations

import contextvars
import json
import re
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Iterator

from openai import APIStatusError, APITimeoutError, OpenAI, RateLimitError

from .config import settings


# ----------------------------------------------------------------------------- usage metering
@dataclass
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    calls: int = 0
    by_step: dict[str, dict[str, int]] = field(default_factory=dict)

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def add(self, step: str, prompt: int, completion: int) -> None:
        self.prompt_tokens += prompt
        self.completion_tokens += completion
        self.calls += 1
        s = self.by_step.setdefault(step, {"prompt": 0, "completion": 0, "calls": 0})
        s["prompt"] += prompt
        s["completion"] += completion
        s["calls"] += 1

    def as_dict(self) -> dict[str, Any]:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "llm_calls": self.calls,
            "by_step": self.by_step,
        }


_current_usage: contextvars.ContextVar[Usage | None] = contextvars.ContextVar("usage", default=None)


@contextmanager
def track_usage() -> Iterator[Usage]:
    """Everything called inside this block is metered into the yielded Usage."""
    u = Usage()
    token = _current_usage.set(u)
    try:
        yield u
    finally:
        _current_usage.reset(token)


def approx_tokens(text: str) -> int:
    """Deliberately conservative token estimate (~3 chars/token): tables, numbers and markdown tokenize
    worse than prose, and over-estimating keeps every request under the provider's per-request cap."""
    return max(1, len(text) // 3)


def truncate_to_budget(text: str, budget_tokens: int) -> str:
    limit = budget_tokens * 3
    if len(text) <= limit:
        return text
    return text[:limit] + "\n...[truncated to fit context budget]"


# ----------------------------------------------------------------------------- client
class LLMNotConfigured(RuntimeError):
    pass


_client: OpenAI | None = None


def client() -> OpenAI:
    global _client
    if not settings.llm_configured:
        raise LLMNotConfigured("Set LLM_API_KEY (see .env.example)")
    if _client is None:
        _client = OpenAI(api_key=settings.llm_api_key, base_url=settings.llm_base_url, timeout=90, max_retries=0)
    return _client


def _extra_body(model: str, reasoning: str | None) -> dict[str, Any]:
    # gpt-oss on Groq accepts reasoning_effort; other providers may reject unknown keys, so gate it.
    if reasoning and "gpt-oss" in model:
        return {"reasoning_effort": reasoning}
    return {}


def chat(
    messages: list[dict[str, str]],
    *,
    model: str | None = None,
    json_mode: bool = False,
    temperature: float = 0.0,
    max_tokens: int | None = None,
    reasoning: str | None = "low",
    step: str = "llm",
) -> str:
    """One chat completion with retry + metering. Returns the text content."""
    model = model or settings.model_strong
    kwargs: dict[str, Any] = dict(model=model, messages=messages, temperature=temperature)
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    if max_tokens:
        kwargs["max_tokens"] = max_tokens
    extra = _extra_body(model, reasoning)
    if extra:
        kwargs["extra_body"] = extra

    delay = 2.0
    last_err: Exception | None = None
    for _attempt in range(6):
        try:
            resp = client().chat.completions.create(**kwargs)
            usage = _current_usage.get()
            if usage is not None and resp.usage:
                usage.add(step, resp.usage.prompt_tokens or 0, resp.usage.completion_tokens or 0)
            return (resp.choices[0].message.content or "").strip()
        except RateLimitError as e:  # 429: respect retry-after when present
            last_err = e
            wait = delay
            try:
                ra = e.response.headers.get("retry-after")
                if ra:
                    wait = max(float(ra), 1.0)
            except Exception:
                pass
            time.sleep(min(wait, 30))
            delay = min(delay * 2, 30)
        except APITimeoutError as e:
            last_err = e
            time.sleep(delay)
            delay = min(delay * 2, 30)
        except APIStatusError as e:
            last_err = e
            if e.status_code == 413:
                # Groq answers 413 when a request does not fit the REMAINING tokens-per-minute budget.
                # Wait for the window to reset (header) and retry a few times before giving up.
                if _attempt < 3:
                    wait = 20.0
                    try:
                        reset = e.response.headers.get("x-ratelimit-reset-tokens") or ""
                        m = re.search(r"(\d+(?:\.\d+)?)s", reset)
                        if m:
                            wait = float(m.group(1)) + 1.0
                        m2 = re.search(r"(\d+)m", reset)
                        if m2:
                            wait += 60 * float(m2.group(1))
                    except Exception:
                        pass
                    time.sleep(min(wait, 65))
                    continue
                size = sum(len(m.get("content", "")) for m in messages)
                raise RuntimeError(f"The request ({size // 3} est. tokens + {max_tokens or 0} completion) exceeded the model's token limit; narrow the question or lower LLM_CONTEXT_BUDGET.") from e
            if e.status_code and e.status_code >= 500:
                time.sleep(delay)
                delay = min(delay * 2, 30)
                continue
            raise
    raise RuntimeError(f"LLM call failed after retries: {last_err}")


_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def parse_json(text: str) -> Any:
    """Parse JSON from model output, tolerating code fences and leading prose."""
    cleaned = _FENCE.sub("", text.strip())
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    candidates = [i for i in (cleaned.find("{"), cleaned.find("[")) if i >= 0]
    if not candidates:
        raise ValueError(f"No JSON object in model output: {text[:200]}")
    start = min(candidates)
    end = max(cleaned.rfind("}"), cleaned.rfind("]"))
    return json.loads(cleaned[start : end + 1])


def chat_json(
    messages: list[dict[str, str]],
    *,
    model: str | None = None,
    temperature: float = 0.0,
    max_tokens: int | None = None,
    reasoning: str | None = "low",
    step: str = "llm",
) -> Any:
    """Chat completion that must return JSON. One repair round-trip if it isn't."""
    text = chat(
        messages,
        model=model,
        json_mode=True,
        temperature=temperature,
        max_tokens=max_tokens,
        reasoning=reasoning,
        step=step,
    )
    try:
        return parse_json(text)
    except (ValueError, json.JSONDecodeError):
        fix = chat(
            [
                {"role": "system", "content": "You fix malformed JSON. Output only the corrected JSON object, nothing else."},
                {"role": "user", "content": text},
            ],
            model=settings.model_fast,
            json_mode=True,
            reasoning="low",
            step=step + ":repair",
        )
        return parse_json(fix)
