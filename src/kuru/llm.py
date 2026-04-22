"""Shared LLM client — OpenRouter (OpenAI-compatible API)."""
from __future__ import annotations

import os

import openai
from dotenv import load_dotenv

load_dotenv()

# OpenRouter model to use. Override via LLM_MODEL env var if needed.
LLM_MODEL = os.environ.get("LLM_MODEL", "google/gemini-2.5-flash-lite")

_client: openai.OpenAI | None = None


def get_client() -> openai.OpenAI:
    global _client
    if _client is None:
        _client = openai.OpenAI(
            api_key=os.environ["OPENROUTER_API_KEY"],
            base_url="https://openrouter.ai/api/v1",
        )
    return _client
