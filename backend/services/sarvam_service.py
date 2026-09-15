"""
Sarvam AI voice service.

Handles the low-latency, asynchronous streaming pipeline that
connects Twilio's audio websocket to Sarvam AI's STT (Speech-to-Text)
and TTS (Text-to-Speech) models for multi-lingual conversations.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

import httpx

from backend.config import settings

logger = logging.getLogger(__name__)

_client: httpx.AsyncClient | None = None


async def _get_client() -> httpx.AsyncClient:
    """Lazily initialise the shared httpx client for Sarvam API."""
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            base_url=settings.sarvam_base_url,
            headers={
                "api-subscription-key": settings.sarvam_api_key,
            },
            timeout=30.0,
        )
    return _client


# ── STT — Speech-to-Text ─────────────────────────────────────────

async def transcribe_audio(
    audio_bytes: bytes,
    language: str = "en-IN",
    model: str = "saarika:v2.5",
) -> Dict[str, Any]:
    """
    Send raw audio bytes to Sarvam STT and return the transcript.
    """
    client = await _get_client()

    # Sarvam expects multipart/form-data for audio uploads.
    # We must NOT have application/json in the headers here.
    files = {"file": ("audio.wav", audio_bytes, "audio/wav")}
    data = {
        "language_code": language,
        "model": model,
        "with_timestamps": "false",
    }

    try:
        resp = await client.post("/speech-to-text", files=files, data=data)
        resp.raise_for_status()
        result = resp.json()
        logger.info("STT transcript (%s): %s", language, result.get("transcript", "")[:80])
        return result
    except httpx.HTTPStatusError as exc:
        logger.error("Sarvam STT error: %s", exc.response.text)
        raise


# ── TTS — Text-to-Speech ─────────────────────────────────────────

async def synthesize_speech(
    text: str,
    language: str = "en-IN",
    speaker: str = "kavya",
    model: str = "bulbul:v3",
) -> bytes:
    """
    Convert text to speech audio using Sarvam TTS.
    """
    client = await _get_client()
    payload = {
        "inputs": [text],
        "target_language_code": language,
        "speaker": speaker,
        "model": model,
    }

    try:
        resp = await client.post("/text-to-speech", json=payload, headers={"Content-Type": "application/json"})
        resp.raise_for_status()
        result = resp.json()
        # Sarvam returns base64-encoded audio in the response.
        import base64
        audio_b64 = result.get("audios", [None])[0]
        if audio_b64:
            return base64.b64decode(audio_b64)
        logger.warning("TTS returned empty audio for text: %s", text[:60])
        return b""
    except httpx.HTTPStatusError as exc:
        logger.error("Sarvam TTS error: %s", exc.response.text)
        raise


# ── Translate (helper) ───────────────────────────────────────────

async def translate_text(
    text: str,
    source_lang: str = "en-IN",
    target_lang: str = "hi-IN",
) -> str:
    """
    Translate text between Indian languages via Sarvam Translate API.
    Useful for generating localised voice prompts.
    """
    client = await _get_client()
    payload = {
        "input": text,
        "source_language_code": source_lang,
        "target_language_code": target_lang,
        "model": "mayura:v1",
        "enable_preprocessing": True,
    }

    try:
        resp = await client.post("/translate", json=payload)
        resp.raise_for_status()
        result = resp.json()
        translated = result.get("translated_text", text)
        logger.info("Translated (%s→%s): %s", source_lang, target_lang, translated[:80])
        return translated
    except httpx.HTTPStatusError as exc:
        logger.error("Sarvam translate error: %s", exc.response.text)
        return text  # Fallback to original text on error.


# ── Language mapping helper ───────────────────────────────────────

LANGUAGE_TO_BCP47 = {
    "english": "en-IN",
    "hindi": "hi-IN",
    "tamil": "ta-IN",
}


def get_bcp47_code(language: str) -> str:
    """Map our internal language enum to Sarvam BCP-47 codes."""
    return LANGUAGE_TO_BCP47.get(language.lower(), "en-IN")


# ── Cleanup ───────────────────────────────────────────────────────

async def close() -> None:
    """Gracefully close the httpx client."""
    global _client
    if _client and not _client.is_closed:
        await _client.aclose()
        _client = None
