"""Shared LLM clients — Google AI for chat/OCR, Typhoon for Thai OCR."""
from __future__ import annotations

import os

import openai
from dotenv import load_dotenv

load_dotenv()

# Chat / answer-generation model — cheap and fast.
LLM_MODEL = os.environ.get("LLM_MODEL", "gemini-2.5-flash-lite")

# Vision OCR model — gemini-2.5-flash via native SDK (thinking disabled = no cost blowup).
# Set OCR_MODEL=typhoon-ocr to use Typhoon instead (requires TYPHOON_API_KEY).
OCR_MODEL = os.environ.get("OCR_MODEL", "gemini-2.5-flash")

import threading

_client: openai.OpenAI | None = None
_ocr_client: openai.OpenAI | None = None
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
