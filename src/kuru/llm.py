"""Shared LLM clients — Google AI for chat/OCR, Typhoon for Thai OCR, OpenRouter for routing."""
from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field as _field

import openai
from dotenv import load_dotenv

load_dotenv()

# ── Usage tracking ───────────────────────────────────────────────────────────
# Approximate prices: USD per 1M tokens (input, output).
_PRICE_TABLE: dict[str, tuple[float, float]] = {
    "google/gemini-2.5-flash":         (0.15,  3.50),
    "google/gemini-2.5-flash-lite":    (0.075, 0.30),
    "google/gemini-2.5-flash-preview": (0.15,  3.50),
    "google/gemini-flash-1.5":         (0.075, 0.30),
    "typhoon-ocr":                     (0.0,   0.0),
}
_PRICE_DEFAULT = (0.50, 1.50)


@dataclass
class _SessionUsage:
    _lock: threading.Lock = _field(default_factory=threading.Lock, repr=False)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    calls: int = 0
    estimated_cost_usd: float = 0.0

    def add(self, model: str, usage: object) -> None:
        prompt = getattr(usage, "prompt_tokens", 0) or 0
        completion = getattr(usage, "completion_tokens", 0) or 0
        inp, out = _PRICE_TABLE.get(model, _PRICE_DEFAULT)
        cost = (prompt * inp + completion * out) / 1_000_000
        with self._lock:
            self.prompt_tokens += prompt
            self.completion_tokens += completion
            self.calls += 1
            self.estimated_cost_usd += cost

    def reset(self) -> None:
        with self._lock:
            self.prompt_tokens = 0
            self.completion_tokens = 0
            self.calls = 0
            self.estimated_cost_usd = 0.0

    def summary(self) -> str:
        with self._lock:
            return (
                f"{self.prompt_tokens:,}in+{self.completion_tokens:,}out tok "
                f"({self.calls} calls) ~${self.estimated_cost_usd:.4f}"
            )


session_usage = _SessionUsage()

# ── Models ───────────────────────────────────────────────────────────────────

# RAG answer-generation model — routed through OpenRouter (needs provider/model format).
# Override via GENERATION_MODEL in .env, e.g. "google/gemini-2.5-flash" for higher quality.
GENERATION_MODEL = os.environ.get("GENERATION_MODEL", "google/gemini-2.5-flash-lite")

# Google-native model name (no provider prefix) for direct Gemini API calls
# (structured_extractor, plo_extractor, tcas_extractor all use get_client()).
LLM_MODEL = os.environ.get("LLM_MODEL", "gemini-2.5-flash-lite")

# Vision OCR model.
# - "typhoon-ocr"          → Typhoon API (requires TYPHOON_API_KEY)
# - "gemini-2.5-flash"     → Google native SDK (requires GEMINI_API_KEY)
# - "google/gemini-2.5-flash" or any "provider/model" → OpenRouter (requires OPENROUTER_API_KEY)
OCR_MODEL = os.environ.get("OCR_MODEL", "gemini-2.5-flash")


def _is_openrouter_model(model: str) -> bool:
    """OpenRouter model names contain a slash, e.g. 'google/gemini-2.5-flash'."""
    return "/" in model and not model.startswith("typhoon")


_client: openai.OpenAI | None = None
_ocr_client: openai.OpenAI | None = None
_openrouter_client: openai.OpenAI | None = None
_gemini_local = threading.local()  # per-thread Gemini client — avoids "client closed" errors


def get_client() -> openai.OpenAI:
    """OpenAI-compatible client for chat/generation (Google Gemini)."""
    global _client
    if _client is None:
        _client = openai.OpenAI(
            api_key=os.environ["GEMINI_API_KEY"],
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        )
    return _client


def get_gemini_client():
    """Native google-genai client — one instance per thread to avoid connection-closed errors."""
    if not hasattr(_gemini_local, "client"):
        from google import genai  # noqa: PLC0415
        _gemini_local.client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    return _gemini_local.client


def get_ocr_client() -> openai.OpenAI:
    """OpenAI-compatible client for Typhoon OCR."""
    global _ocr_client
    if _ocr_client is None:
        _ocr_client = openai.OpenAI(
            api_key=os.environ["TYPHOON_API_KEY"],
            base_url="https://api.opentyphoon.ai/v1",
        )
    return _ocr_client


def get_openrouter_client() -> openai.OpenAI:
    """OpenAI-compatible client for OpenRouter (supports any provider/model vision calls)."""
    global _openrouter_client
    if _openrouter_client is None:
        _openrouter_client = openai.OpenAI(
            api_key=os.environ["OPENROUTER_API_KEY"],
            base_url="https://openrouter.ai/api/v1",
        )
    return _openrouter_client
