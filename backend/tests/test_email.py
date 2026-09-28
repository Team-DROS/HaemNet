"""Email delivery for donor sign-in codes (no network: Brevo is mocked)."""

import json

import httpx
import pytest

from backend.services import email_service


@pytest.fixture
def brevo(monkeypatch):
    monkeypatch.setattr(email_service.settings, "brevo_api_key", "xkeysib-test")
    monkeypatch.setattr(email_service.settings, "email_from", "noreply@example.com")
    seen = {}

    def reply(status):
        def handler(request: httpx.Request) -> httpx.Response:
            seen["url"] = str(request.url)
            seen["key"] = request.headers.get("api-key")
            seen["body"] = json.loads(request.content)
            return httpx.Response(status, json={"messageId": "<1@x>"} if status < 300 else {"message": "bad"})
        monkeypatch.setattr(email_service, "_client", httpx.AsyncClient(transport=httpx.MockTransport(handler)))

    return seen, reply


async def test_code_email_goes_to_brevo_with_the_code(brevo):
    seen, reply = brevo
    reply(201)
    await email_service.send_sign_in_code("donor@example.com", "123456", 5)
    assert seen["url"] == email_service.BREVO_URL
    assert seen["key"] == "xkeysib-test"
    assert seen["body"]["to"] == [{"email": "donor@example.com"}]
    assert seen["body"]["sender"]["email"] == "noreply@example.com"
    assert "123456" in seen["body"]["subject"] and "123456" in seen["body"]["textContent"]


async def test_brevo_rejection_raises_email_error(brevo):
    _, reply = brevo
    reply(401)
    with pytest.raises(email_service.EmailError):
        await email_service.send_sign_in_code("donor@example.com", "123456", 5)


def test_mask_email():
    assert email_service.mask_email("umas@gmail.com") == "u***@gmail.com"
    assert email_service.mask_email("broken") == "***"
