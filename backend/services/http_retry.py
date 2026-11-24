"""Bounded retries for calls to Twilio and Sarvam.

Only retries what is safe:
  * connection errors (the request never reached the provider) always;
  * timeouts and dropped connections only when `idempotent=True` (speech and
    translation calls), never for starting a phone call, which could ring a donor twice;
  * throttling and server errors listed in `retry_statuses`, honouring Retry-After (capped).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Iterable

import httpx

logger = logging.getLogger(__name__)

_sleep = asyncio.sleep  # replaced in tests
MAX_RETRY_AFTER = 5.0


async def post_with_retry(
    client: httpx.AsyncClient, url: str, *, retry_statuses: Iterable[int] = (), idempotent: bool = False,
    attempts: int = 3, base_delay: float = 0.4, **kwargs,
) -> httpx.Response:
    retry_statuses = set(retry_statuses)
    for attempt in range(1, attempts + 1):
        last = attempt == attempts
        try:
            response = await client.post(url, **kwargs)
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            if last:
                raise
            logger.warning("POST %s connection failed (%s); retry %d", url, type(exc).__name__, attempt)
        except (httpx.ReadTimeout, httpx.WriteTimeout, httpx.RemoteProtocolError, httpx.ReadError) as exc:
            if last or not idempotent:
                raise
            logger.warning("POST %s timed out (%s); retry %d", url, type(exc).__name__, attempt)
        else:
            if response.status_code not in retry_statuses or last:
                return response
            logger.warning("POST %s returned %d; retry %d", url, response.status_code, attempt)
            try:
                delay = min(float(response.headers.get("Retry-After", "")), MAX_RETRY_AFTER)
            except ValueError:
                delay = base_delay * 2 ** (attempt - 1)
            await _sleep(delay)
            continue
        await _sleep(base_delay * 2 ** (attempt - 1))
    raise RuntimeError("unreachable")  # pragma: no cover
