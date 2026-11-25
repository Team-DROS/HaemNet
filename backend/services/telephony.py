"""Telephony behind one interface, so the provider can change without touching the call pipeline.

The dispatch pipeline and the notification fallbacks only ever call `get_telephony()`. To add a
provider (for example Exotel or Plivo for an Indian caller ID), write a class with these three
methods, register it in `_PROVIDERS` and set TELEPHONY_PROVIDER. Note that incoming webhooks are
verified per provider: `services/twilio_signature.py` covers Twilio, a new provider needs its own check.
"""

from __future__ import annotations

from typing import Protocol

from backend.config import settings
from backend.schemas.models import DonorNode
from backend.services import twilio_service


class TelephonyProvider(Protocol):
    name: str

    async def start_call(self, donor: DonorNode, dispatch_id: str, callback_url: str) -> str | None:
        """Place an outbound call to the donor. Returns the provider's call ID, if it gave one."""
        ...

    async def send_sms(self, phone: str, message: str) -> None:
        """Send a text message."""
        ...

    async def close(self) -> None:
        """Release network resources at shutdown."""
        ...


class TwilioProvider:
    name = "twilio"

    async def start_call(self, donor: DonorNode, dispatch_id: str, callback_url: str) -> str | None:
        result = await twilio_service.initiate_call(donor, dispatch_id, callback_url)
        return result.get("sid") or None

    async def send_sms(self, phone: str, message: str) -> None:
        await twilio_service.send_sms(phone, message)

    async def close(self) -> None:
        await twilio_service.close()


_PROVIDERS: dict[str, type[TelephonyProvider]] = {"twilio": TwilioProvider}
_instance: TelephonyProvider | None = None


def get_telephony() -> TelephonyProvider:
    """The configured provider, created on first use."""
    global _instance
    if _instance is None or _instance.name != settings.telephony_provider:
        try:
            _instance = _PROVIDERS[settings.telephony_provider]()
        except KeyError as exc:
            raise ValueError(
                f"Unknown TELEPHONY_PROVIDER {settings.telephony_provider!r}; available: {', '.join(_PROVIDERS)}"
            ) from exc
    return _instance


def available_providers() -> tuple[str, ...]:
    return tuple(_PROVIDERS)
