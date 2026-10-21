"""Consent and audio regressions. No phone calls or provider requests."""

import audioop
import json
from unittest.mock import AsyncMock

import httpx
import pytest

from backend.services import ai_voice_pipeline, voice_intent, voice_pipeline
from backend.services.voice_intent import IntentResult


def result(intent, confirmation=False):
    return IntentResult(intent=intent, explicit_consent=intent == "accepted",
                        confirmation_answer=confirmation)


@pytest.fixture
def session(monkeypatch):
    s = ai_voice_pipeline.AIVoiceSession(
        call_sid="test", dispatch_id="test", donor_id="test", donor_name="Test",
    )
    s._speak = AsyncMock(return_value=b"question")
    s._greeting_sent = True
    return s


async def test_accept_requires_a_separate_answer_after_playback(session, monkeypatch):
    classify = AsyncMock(side_effect=[result("accepted"), result("accepted", True)])
    monkeypatch.setattr(ai_voice_pipeline, "interpret_response", classify)
    assert await session.process_transcript("Yes, I will come") == (b"question", None)
    mark = session.playback_started()
    assert await session.process_transcript("yes") == (None, None)
    session.playback_finished("wrong-mark")
    assert await session.process_transcript("yes") == (None, None)
    session.playback_finished(mark)
    assert await session.process_transcript("Yes, I confirm") == (None, "accepted")
    assert await session.process_transcript("again") == (None, None)
    assert classify.await_count == 2


async def test_confirmation_no_cancels_initial_yes(session, monkeypatch):
    monkeypatch.setattr(ai_voice_pipeline, "interpret_response",
                        AsyncMock(side_effect=[result("accepted"), result("declined")]))
    await session.process_transcript("yes")
    session.playback_finished(session.playback_started())
    assert await session.process_transcript("No, I cannot donate") == (None, "declined")


async def test_uncertain_confirmation_never_uses_previous_yes(session, monkeypatch):
    monkeypatch.setattr(ai_voice_pipeline, "interpret_response",
                        AsyncMock(side_effect=[result("accepted"), result("unclear")]))
    await session.process_transcript("yes")
    session.playback_finished(session.playback_started())
    assert await session.process_transcript("maybe") == (b"question", None)
    assert not session._intent_resolved
    assert not session._confirmation_played


async def test_cannot_accept_when_confirmation_audio_fails(session, monkeypatch):
    monkeypatch.setattr(ai_voice_pipeline, "interpret_response", AsyncMock(return_value=result("accepted")))
    session._speak.return_value = None
    assert await session.process_transcript("yes") == (None, "unconfirmed")


async def test_repeated_unknown_ends_without_decision(session, monkeypatch):
    monkeypatch.setattr(ai_voice_pipeline, "interpret_response", AsyncMock(return_value=result("unclear")))
    for _ in range(2):
        assert await session.process_transcript("unclear") == (b"question", None)
    assert await session.process_transcript("unclear") == (None, "unconfirmed")


async def test_waits_for_silence_and_discards_playback_audio(session, monkeypatch):
    session._transcribe = AsyncMock(return_value="no")
    monkeypatch.setattr(ai_voice_pipeline, "interpret_response", AsyncMock(return_value=result("declined")))
    speech = audioop.lin2ulaw(b"\x10\x27" * 160, 2)
    silence = b"\xff" * 160
    mark = session.playback_started()
    for _ in range(60):
        await session.handle_audio_chunk(speech)
    session._transcribe.assert_not_awaited()
    session.playback_finished(mark)
    for _ in range(10):
        assert await session.handle_audio_chunk(speech) == (None, None)
    for _ in range(49):
        assert await session.handle_audio_chunk(silence) == (None, None)
    assert await session.handle_audio_chunk(silence) == (None, "declined")


async def test_truncated_speech_and_silence_cannot_accept(session):
    session._transcribe = AsyncMock()
    assert await session.handle_audio_chunk(b"\xff" * session.IDLE_BYTES) == (None, "unconfirmed")
    session._transcribe.assert_not_awaited()


async def test_continuous_speech_is_not_classified_when_cut_off(session):
    session._transcribe = AsyncMock()
    speech = audioop.lin2ulaw(b"\x10\x27" * 160, 2)
    for _ in range(599):
        assert await session.handle_audio_chunk(speech) == (None, None)
    assert await session.handle_audio_chunk(speech) == (b"question", None)
    session._transcribe.assert_not_awaited()


@pytest.mark.parametrize("final_intent", ["accepted", "declined"])
def test_twilio_persists_only_the_confirmed_outcome(client, store, monkeypatch, final_intent):
    import base64
    from backend.api import callbacks
    from backend.config import settings
    from backend.tests.conftest import donor
    store.add("voice-test", donors=[donor("donor-test", "+919000000001")])
    monkeypatch.setattr(callbacks, "dispatch_store", store)
    monkeypatch.setattr(settings, "voice_intent_mode", "ai")
    monkeypatch.setattr(ai_voice_pipeline.AIVoiceSession, "_speak", AsyncMock(return_value=b"audio"))
    monkeypatch.setattr(ai_voice_pipeline.AIVoiceSession, "_transcribe",
                        AsyncMock(side_effect=["Yes, I will donate", "The final answer"]))
    monkeypatch.setattr(ai_voice_pipeline, "interpret_response", AsyncMock(side_effect=[
        result("accepted"), result(final_intent, final_intent == "accepted"),
    ]))
    route = AsyncMock(return_value=False)
    monkeypatch.setattr(callbacks, "_route_accepted_donor", route)
    monkeypatch.setattr(callbacks.manager, "broadcast", AsyncMock())
    speech = audioop.lin2ulaw(b"\x10\x27" * 160, 2)
    def speak(ws):
        for frame in [speech] * 10 + [b"\xff" * 160] * 50:
            ws.send_json({"event": "media", "media": {"track": "inbound",
                "payload": base64.b64encode(frame).decode()}})
    def acknowledge(ws):
        assert ws.receive_json()["event"] == "media"
        mark = ws.receive_json()
        ws.send_json({"event": "mark", "mark": mark["mark"]})
    with client.websocket_connect("/ws/twilio/audio-stream") as ws:
        ws.send_json({"event": "start", "start": {"streamSid": "stream-test", "callSid": "call-test",
            "customParameters": {"dispatch_id": "voice-test", "donor_id": "donor-test"}}})
        acknowledge(ws)
        speak(ws)
        # The first yes produces a question, never acceptance or directions.
        assert ws.receive_json()["event"] == "media"
        confirmation_mark = ws.receive_json()
        assert store.dispatches["voice-test"]["donors"]["donor-test"]["status"] == "ringing"
        route.assert_not_awaited()
        ws.send_json({"event": "mark", "mark": confirmation_mark["mark"]})
        speak(ws)
        acknowledge(ws)
    assert store.dispatches["voice-test"]["donors"]["donor-test"]["status"] == final_intent
    assert route.await_count == (1 if final_intent == "accepted" else 0)


@pytest.mark.parametrize("content,finish", [
    ('{"intent":"accepted","explicit_consent":false,"confirmation_answer":true}', "stop"),
    ('{"intent":"accepted","explicit_consent":"true","confirmation_answer":true}', "stop"),
    ('{"intent":"accepted","explicit_consent":true,"confirmation_answer":true}', "length"),
    ('not JSON', "stop"),
])
async def test_provider_output_validation(monkeypatch, content, finish):
    client = AsyncMock()
    client.post.return_value = httpx.Response(200, request=httpx.Request("POST", "https://example.invalid"),
        json={"choices": [{"finish_reason": finish, "message": {"content": content}}]})
    monkeypatch.setattr(voice_intent, "_get_client", AsyncMock(return_value=client))
    assert (await voice_intent.interpret_response("no", [], False)).intent == "unclear"


async def test_timeout_never_falls_back_to_keywords(monkeypatch):
    client = AsyncMock()
    client.post.side_effect = httpx.ReadTimeout("test")
    monkeypatch.setattr(voice_intent, "_get_client", AsyncMock(return_value=client))
    assert (await voice_intent.interpret_response("okay", [], False)).intent == "unclear"


def test_rollback_selects_original_class(monkeypatch):
    from backend.config import settings
    args = dict(call_sid="t", dispatch_id="t", donor_id="t", donor_name="Test")
    monkeypatch.setattr(settings, "voice_intent_mode", "legacy")
    assert type(voice_pipeline.create_voice_session(**args)) is voice_pipeline.VoiceSession
    monkeypatch.setattr(settings, "voice_intent_mode", "ai")
    assert isinstance(voice_pipeline.create_voice_session(**args), ai_voice_pipeline.AIVoiceSession)
