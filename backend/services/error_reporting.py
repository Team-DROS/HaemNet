"""Best-effort error reporting.

Reporting an error must never cause another one: a failing reporter would abort the
very error handling (or call cleanup) it was called from.
"""

from __future__ import annotations

import logging

import sentry_sdk

logger = logging.getLogger(__name__)


def report_exception(exc: BaseException) -> None:
    """Send `exc` to Sentry when it is configured; never raises."""
    try:
        sentry_sdk.capture_exception(exc)
    except Exception:
        logger.debug("Could not report %s to Sentry", type(exc).__name__, exc_info=True)
