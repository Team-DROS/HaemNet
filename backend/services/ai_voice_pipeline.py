"""Opt-in voice session. The original VoiceSession remains the rollback path."""

import audioop
import logging

from backend.services.voice_intent import interpret_response
from backend.services.voice_pipeline import VoiceSession

logger = logging.getLogger(__name__)


class AIVoiceSession(VoiceSession):
    # Twilio inbound audio is 8-bit mu-law, 8000 bytes per second.
    SILENCE_BYTES = 8000  # one second after speech
    MAX_TURN_BYTES = 12 * 8000
    IDLE_BYTES = 20 * 8000
    SPEECH_RMS = 350

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.confirming = False
        self._confirmation_played = False
        self._pending_mark = None
        self._mark_number = 0
        self._speech_started = False
        self._silence_bytes = 0
        self._idle_bytes = 0
        self._attempts = 0
        self._pre_roll = bytearray()

    def playback_started(self) -> str:
        self._mark_number += 1
        self._pending_mark = f"voice-{self._mark_number}"
        self._reset_audio()
        return self._pending_mark

    def playback_finished(self, name: str) -> None:
        if name == self._pending_mark:
            self._pending_mark = None
            self._reset_audio()
            if self.confirming:
                self._confirmation_played = True

    def _reset_audio(self):
        self._audio_buffer.clear()
        self._pre_roll.clear()
        self._speech_started = False
        self._silence_bytes = 0
        self._idle_bytes = 0

    async def handle_audio_chunk(self, audio_bytes):
        if self._intent_resolved:
            return None, None
        if not self._greeting_sent:
            self._greeting_sent = True
            audio = await self._generate_greeting()
            return (audio, None) if audio else (None, "unconfirmed")
        # Do not interpret queued audio captured during agent playback.
        if self._pending_mark or not audio_bytes:
            return None, None
        pcm = audioop.ulaw2lin(audio_bytes, 2)
        speaking = audioop.rms(pcm, 2) >= self.SPEECH_RMS
        if not self._speech_started:
            self._pre_roll.extend(audio_bytes)
            self._pre_roll = self._pre_roll[-1600:]
            if not speaking:
                self._idle_bytes += len(audio_bytes)
                if self._idle_bytes >= self.IDLE_BYTES:
                    self._intent_resolved = True
                    return None, "unconfirmed"
                return None, None
            self._speech_started = True
            self._audio_buffer.extend(self._pre_roll)
        else:
            self._audio_buffer.extend(audio_bytes)
        self._silence_bytes = 0 if speaking else self._silence_bytes + len(audio_bytes)
        if len(self._audio_buffer) >= self.MAX_TURN_BYTES:
            # A truncated utterance must never be interpreted as consent.
            self._reset_audio()
            return await self._retry()
        if self._silence_bytes < self.SILENCE_BYTES:
            return None, None
        audio = bytes(self._audio_buffer)
        self._reset_audio()
        transcript = await self._transcribe(audio)
        if not transcript:
            return await self._retry()
        return await self.process_transcript(transcript)

    async def process_transcript(self, transcript):
        """A separate turn can confirm only after the confirmation was played."""
        if self._intent_resolved or self._pending_mark:
            return None, None
        result = await interpret_response(transcript, self._conversation, self.confirming)
        self._conversation.append({"role": "donor", "text": transcript[:2000]})
        logger.info("AI voice decision=%s confirming=%s", result.intent, self.confirming)
        if result.intent == "declined":
            self._intent_resolved = True
            return None, "declined"
        if result.intent == "accepted" and result.explicit_consent:
            if self.confirming and self._confirmation_played and result.confirmation_answer:
                self._intent_resolved = True
                return None, "accepted"
            if not self.confirming:
                self.confirming = True
                audio = await self._speak(
                    "Just to confirm: do you agree to come to the hospital now to donate blood? "
                    "Please answer yes to confirm, or no to decline."
                )
                return (audio, None) if audio else (None, "unconfirmed")
        return await self._retry()

    async def _retry(self):
        self._attempts += 1
        if self._attempts >= 3:
            self._intent_resolved = True
            return None, "unconfirmed"
        if self.confirming:
            # Previous evidence never substitutes for answering again.
            self._confirmation_played = False
        audio = await self._speak(
            "I could not confirm your answer. Do you agree to come to the hospital "
            "now to donate blood? Please say yes or no."
        )
        return (audio, None) if audio else (None, "unconfirmed")
