"""The telephony interface: provider selection and a swapped-in provider driving the pipeline."""

from types import SimpleNamespace

import pytest

from backend.config import settings
from backend.orchestration import graph
from backend.services import telephony, twilio_service


@pytest.fixture(autouse=True)
def fresh_provider(monkeypatch):
    monkeypatch.setattr(telephony, "_instance", None)
    monkeypatch.setattr(settings, "telephony_provider", "twilio")


def test_twilio_is_the_default_provider():
    assert telephony.get_telephony().name == "twilio"
    assert telephony.get_telephony() is telephony.get_telephony()  # created once


def test_an_unknown_provider_fails_loudly_and_names_the_choices(monkeypatch):
    monkeypatch.setattr(settings, "telephony_provider", "carrier-pigeon")
    with pytest.raises(ValueError, match="available: twilio"):
        telephony.get_telephony()


@pytest.mark.asyncio
async def test_twilio_provider_returns_the_call_sid_and_forwards_sms(monkeypatch):
    sent = []

    async def fake_call(donor, dispatch_id, callback_url):
        return {"sid": "CA123"}

    async def fake_sms(phone, message):
        sent.append((phone, message))

    monkeypatch.setattr(twilio_service, "initiate_call", fake_call)
    monkeypatch.setattr(twilio_service, "send_sms", fake_sms)
    provider = telephony.get_telephony()
    assert await provider.start_call(SimpleNamespace(), "dp-1", "cb") == "CA123"
    await provider.send_sms("+919000000001", "hello")
    assert sent == [("+919000000001", "hello")]


@pytest.mark.asyncio
async def test_twilio_provider_returns_none_when_no_sid_comes_back(monkeypatch):
    async def fake_call(donor, dispatch_id, callback_url):
        return {}

    monkeypatch.setattr(twilio_service, "initiate_call", fake_call)
    assert await telephony.get_telephony().start_call(SimpleNamespace(), "dp-1", "cb") is None


@pytest.mark.asyncio
async def test_the_pipeline_works_with_any_provider(monkeypatch):
    """A different provider is registered and selected; the pipeline neither knows nor cares."""
    registered, placed = [], []

    class OtherProvider:
        name = "other"

        async def start_call(self, donor, dispatch_id, callback_url):
            placed.append(dispatch_id)
            return "OTHER-1"

        async def send_sms(self, phone, message): ...

        async def close(self): ...

    class Store:
        async def register_call(self, call_id, dispatch_id, donor_id):
            registered.append((call_id, dispatch_id, donor_id))

    async def no_wait():
        return None

    monkeypatch.setitem(telephony._PROVIDERS, "other", OtherProvider)
    monkeypatch.setattr(settings, "telephony_provider", "other")
    monkeypatch.setattr(graph, "wait_for_slot", no_wait)
    monkeypatch.setattr(graph, "dispatch_store", Store())
    await graph._initiate_single_call(SimpleNamespace(), "dp-1", "d1", "cb")
    assert placed == ["dp-1"] and registered == [("OTHER-1", "dp-1", "d1")]
