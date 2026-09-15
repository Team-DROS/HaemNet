"""
Real-time voice pipeline: Twilio audio ↔ Sarvam AI.

Manages a per-call ``VoiceSession`` that:
  1. Accumulates raw audio chunks from Twilio
  2. Sends buffered audio to Sarvam STT for transcription
  3. Extracts donor intent (accepted / declined / unknown)
  4. Generates a localised TTS response via Sarvam
  5. Returns audio bytes to stream back to the caller

This module is imported by ``api/callbacks.py`` which handles the
WebSocket transport layer.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional, Tuple

from backend.services.audio_utils import create_wav_from_mulaw, create_mulaw_from_wav
from backend.services.sarvam_service import (
    get_bcp47_code,
    synthesize_speech,
    transcribe_audio,
    translate_text,
)

logger = logging.getLogger(__name__)

# ── Active session registry ───────────────────────────────────────

active_sessions: Dict[str, "VoiceSession"] = {}

# ── Intent keywords (multi-lingual) ──────────────────────────────

_ACCEPT_KEYWORDS = {
    "english": [
        "yes", "sure", "okay", "ok", "coming", "on my way",
        "i can", "i will", "accept", "available", "ready",
        "i'll come", "be there", "count me in", "definitely",
    ],
    "hindi": [
        "haan", "haa", "theek", "theek hai", "aa raha", "aa rahi",
        "aa rahe", "bilkul", "zaroor", "main aaunga", "main aaungi",
        "tayyar", "ha ji", "हाँ", "ठीक", "आ", "जरूर", "तैयार", "यस"
    ],
    "tamil": [
        "aama", "seri", "varuven", "vara mudiyum", "varen",
        "sarri", "ok", "ready", "ஆம்", "சரி", "வருவேன்", "முடியும்", "வரேன்", "எஸ்", "ஓகே"
    ],
}

_DECLINE_KEYWORDS = {
    "english": [
        "no", "sorry", "can't", "cannot", "not available",
        "busy", "unable", "decline", "not possible", "won't",
    ],
    "hindi": [
        "nahi", "naa", "nahin", "maaf", "nahi aa sakta",
        "nahi aa sakti", "busy", "mushkil", "नहीं", "माफ़", "व्यस्त", "मुश्किल", "नो"
    ],
    "tamil": [
        "illa", "mudiyathu", "mudiyadu", "varamudiyathu",
        "sorry", "busy", "இல்லை", "முடியாது", "வர முடியாது", "நோ"
    ],
}

# Audio buffer threshold (bytes) — roughly 2 seconds of 8kHz 16-bit PCM.
_AUDIO_BUFFER_THRESHOLD = 32_000


# ── Voice Session ─────────────────────────────────────────────────

class VoiceSession:
    """
    Manages a single donor's AI voice conversation during a dispatch.

    Lifecycle:
        1. Created when Twilio audio WebSocket connects
        2. Receives audio chunks → transcribes → extracts intent
        3. Generates localised TTS responses
        4. Destroyed when call ends or intent is resolved
    """

    def __init__(
        self,
        call_sid: str,
        dispatch_id: str,
        donor_id: str,
        donor_name: str,
        language: str = "english",
        hospital_id: str = "",
        blood_group: str = "",
    ) -> None:
        self.call_sid = call_sid
        self.dispatch_id = dispatch_id
        self.donor_id = donor_id
        self.donor_name = donor_name
        self.language = language
        self.hospital_id = hospital_id
        self.blood_group = blood_group

        self._audio_buffer = bytearray()
        self._conversation: List[Dict[str, str]] = []
        self._greeting_sent = False
        self._intent_resolved = False
        self.eta_minutes: Optional[int] = None

    # ── Main entry point ──────────────────────────────────────────

    async def handle_audio_chunk(
        self, audio_bytes: bytes
    ) -> Tuple[Optional[bytes], Optional[str]]:
        """
        Process an incoming audio chunk from Twilio.

        Returns
        -------
        (response_audio, intent)
            response_audio : bytes or None — TTS audio to send back
            intent         : str or None   — 'accepted', 'declined', or None
        """
        # Send the greeting on the first chunk.
        if not self._greeting_sent:
            self._greeting_sent = True
            greeting_audio = await self._generate_greeting()
            return greeting_audio, None

        # Accumulate audio into the buffer.
        self._audio_buffer.extend(audio_bytes)

        # Only process when we have enough audio (avoids sending tiny fragments).
        if len(self._audio_buffer) < _AUDIO_BUFFER_THRESHOLD:
            return None, None

        # Flush the buffer and transcribe.
        audio_to_process = bytes(self._audio_buffer)
        self._audio_buffer.clear()

        transcript = await self._transcribe(audio_to_process)
        if not transcript:
            return None, None

        # Log the donor's speech.
        self._conversation.append({"role": "donor", "text": transcript})
        logger.info(
            "Donor %s said (%s): %s",
            self.donor_id, self.language, transcript,
        )

        # Check for intent.
        intent = self._extract_intent(transcript)

        if intent and not self._intent_resolved:
            self._intent_resolved = True
            return None, intent

        # If no clear intent, ask a follow-up.
        if not self._intent_resolved:
            followup_audio = await self._generate_followup()
            return followup_audio, None

        return None, None

    # ── Transcription ─────────────────────────────────────────────

    async def _transcribe(self, audio_bytes: bytes) -> Optional[str]:
        """Convert raw mu-law to WAV and call Sarvam STT."""
        try:
            bcp47 = get_bcp47_code(self.language)
            wav_bytes = create_wav_from_mulaw(audio_bytes)
            result = await transcribe_audio(wav_bytes, language=bcp47)
            return result.get("transcript", "").strip()
        except Exception as exc:
            logger.error(
                "STT failed for donor %s: %s", self.donor_id, exc
            )
            return None

    # ── Intent Extraction ─────────────────────────────────────────

    def _extract_intent(self, transcript: str) -> Optional[str]:
        """
        Check the transcript for acceptance or declination keywords.

        Returns 'accepted', 'declined', or None.
        """
        text_lower = transcript.lower()
        lang_key = self.language.lower()

        accept_words = _ACCEPT_KEYWORDS.get(lang_key, _ACCEPT_KEYWORDS["english"])
        decline_words = _DECLINE_KEYWORDS.get(lang_key, _DECLINE_KEYWORDS["english"])

        # Check decline first (if they say "no sorry I can't", decline wins).
        for keyword in decline_words:
            if keyword in text_lower:
                logger.info(
                    "Intent DECLINED detected for donor %s (keyword='%s')",
                    self.donor_id, keyword,
                )
                return "declined"

        for keyword in accept_words:
            if keyword in text_lower:
                logger.info(
                    "Intent ACCEPTED detected for donor %s (keyword='%s')",
                    self.donor_id, keyword,
                )
                return "accepted"

        return None

    # ── TTS Response Generation ───────────────────────────────────

    async def _generate_greeting(self) -> Optional[bytes]:
        """Generate the initial greeting in the donor's language."""
        greeting_en = (
            f"Hello {self.donor_name}, this is an urgent call from the "
            f"Blood Dispatch Network. Hospital {self.hospital_id} urgently "
            f"needs {self.blood_group} blood. You are a matched donor within "
            f"10 kilometers. Can you come to the hospital immediately?"
        )
        return await self._speak(greeting_en)

    async def _generate_followup(self) -> Optional[bytes]:
        """Generate a follow-up prompt asking for a clear answer."""
        followup_en = (
            "I understand. Could you please confirm — are you available "
            "to come to the hospital right now? Please say yes or no."
        )
        return await self._speak(followup_en)

    async def generate_closing_message(self, accepted: bool) -> Optional[bytes]:
        """Generate a closing message after intent is resolved."""
        if accepted:
            msg_en = (
                "Thank you so much! You are saving a life. "
                "You will receive directions to the hospital shortly. "
                "Please head there as soon as possible. Goodbye."
            )
        else:
            msg_en = (
                "Thank you for your time. We understand. "
                "Take care and goodbye."
            )
        return await self._speak(msg_en)

    async def _speak(self, text_en: str) -> Optional[bytes]:
        """Translate (if needed) and synthesize speech."""
        try:
            bcp47 = get_bcp47_code(self.language)

            # Translate from English to donor's language if needed.
            if self.language != "english":
                text = await translate_text(
                    text_en,
                    source_lang="en-IN",
                    target_lang=bcp47,
                )
            else:
                text = text_en

            # Log the AI's speech.
            self._conversation.append({"role": "ai", "text": text})

            # Synthesize audio.
            audio = await synthesize_speech(text, language=bcp47)
            if audio:
                return create_mulaw_from_wav(audio)
            return None

        except Exception as exc:
            logger.error(
                "TTS generation failed for donor %s: %s",
                self.donor_id, exc,
            )
            return None
