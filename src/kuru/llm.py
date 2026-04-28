"""Shared LLM client — Google AI (OpenAI-compatible API)."""
from __future__ import annotations

import os

import openai
from dotenv import load_dotenv

load_dotenv()

# Chat / answer-generation model — cheap and fast.
LLM_MODEL = os.environ.get("LLM_MODEL", "gemini-2.5-flash-lite-preview-06-17")

# Vision OCR model — stronger than LLM_MODEL because flash-lite hallucinates badly
# on poor scans (า า า า า garbage, cross-batch loops, choices=None responses).
# Override to "gemini-2.5-pro" for the very few files flash still fails on.
OCR_MODEL = os.environ.get("OCR_MODEL", "gemini-2.0-flash")

_client: openai.OpenAI | None = None


def get_client() -> openai.OpenAI:
    global _client
    if _client is None:
        _client = openai.OpenAI(
            api_key=os.environ["GEMINI_API_KEY"],
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        )
    return _client
