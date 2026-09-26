"""
Check that every service HaemNet depends on is configured and reachable.

Run it locally before a deploy, and again from the deployed environment
(Render shell) to prove the live keys work:

    python -m backend.tools.check_config

It exits 0 when everything the current APP_ENV needs is working, and 1
otherwise. Secrets are never printed: only the last four characters of an
identifier appear, so the output is safe to paste into a chat or an issue.
"""

from __future__ import annotations

import asyncio
import sys
from typing import List, Tuple

import httpx

from backend.config import settings

OK, WARN, FAIL = "ok", "warn", "fail"
Result = Tuple[str, str, str]  # (state, check name, detail)


def _tail(value: str, keep: int = 4) -> str:
    value = value or ""
    return f"…{value[-keep:]}" if len(value) > keep else "(not set)"


async def check_database() -> Result:
    name = f"Database ({settings.db_backend})"
    try:
        from backend.db_services import db_health, ensure_indexes

        health = await db_health()
        if health["status"] != "connected":
            return FAIL, name, health["status"]
        await ensure_indexes()
        return OK, name, "connected, indexes ready"
    except Exception as exc:  # noqa: BLE001 - the point of the check
        return FAIL, name, str(exc)


async def check_twilio() -> List[Result]:
    if not (settings.twilio_account_sid and settings.twilio_auth_token):
        return [(WARN, "Twilio", "not configured: AI voice calls and SMS sign-in codes are disabled")]

    results: List[Result] = []
    auth = (settings.twilio_account_sid, settings.twilio_auth_token)
    base = "https://api.twilio.com/2010-04-01"
    async with httpx.AsyncClient(timeout=20, auth=auth) as client:
        try:
            resp = await client.get(f"{base}/Accounts/{settings.twilio_account_sid}.json")
            if resp.status_code == 401:
                return [(FAIL, "Twilio credentials", "rejected (check the SID and auth token)")]
            resp.raise_for_status()
            account = resp.json()
            results.append((OK, "Twilio credentials",
                            f"{account.get('friendly_name', 'account')} [{account.get('type', '?')}], "
                            f"status {account.get('status')}, SID {_tail(settings.twilio_account_sid)}"))
        except Exception as exc:  # noqa: BLE001
            return [(FAIL, "Twilio credentials", str(exc))]

        if not settings.twilio_phone_number:
            results.append((FAIL, "Twilio number", "TWILIO_PHONE_NUMBER is empty"))
            return results
        try:
            resp = await client.get(
                f"{base}/Accounts/{settings.twilio_account_sid}/IncomingPhoneNumbers.json",
                params={"PhoneNumber": settings.twilio_phone_number},
            )
            resp.raise_for_status()
            numbers = resp.json().get("incoming_phone_numbers", [])
            if not numbers:
                results.append((FAIL, "Twilio number",
                                f"{settings.twilio_phone_number} is not on this account"))
            else:
                caps = numbers[0].get("capabilities", {})
                missing = [c for c in ("voice", "sms") if not caps.get(c)]
                state = WARN if missing else OK
                detail = f"{numbers[0].get('phone_number')} voice={caps.get('voice')} sms={caps.get('sms')}"
                if missing:
                    detail += f" — missing {', '.join(missing)}; that part will not work"
                results.append((state, "Twilio number", detail))
        except Exception as exc:  # noqa: BLE001
            results.append((FAIL, "Twilio number", str(exc)))
    return results


async def check_sarvam() -> Result:
    if not settings.sarvam_api_key:
        return WARN, "Sarvam AI", "not configured: the voice pipeline cannot speak or transcribe"
    try:
        from backend.services.sarvam_service import synthesize_speech

        audio = await synthesize_speech("Hello from HaemNet.", language="en-IN")
        if not audio:
            return WARN, "Sarvam AI", "key accepted but no audio came back"
        return OK, "Sarvam AI", f"text to speech works ({len(audio)} bytes), key {_tail(settings.sarvam_api_key)}"
    except httpx.HTTPStatusError as exc:
        return FAIL, "Sarvam AI", f"HTTP {exc.response.status_code}: {exc.response.text[:120]}"
    except Exception as exc:  # noqa: BLE001
        return FAIL, "Sarvam AI", str(exc)


async def check_geocoding() -> Result:
    try:
        from backend.services.geocoding import geocode_address

        coords = await geocode_address("Greams Road, Chennai")
        if not coords:
            return WARN, "Geocoding", "no result for a known address (hospital registration may fail)"
        return OK, "Geocoding", f"Greams Road, Chennai -> {coords[0]:.4f}, {coords[1]:.4f}"
    except Exception as exc:  # noqa: BLE001
        return WARN, "Geocoding", str(exc)


def check_app_settings() -> List[Result]:
    results: List[Result] = []
    production = settings.app_env.lower() in {"production", "staging"}

    if len(settings.jwt_secret) < 32:
        results.append(((FAIL if production else WARN), "JWT secret",
                        f"only {len(settings.jwt_secret)} characters; use 32 or more"))
    else:
        results.append((OK, "JWT secret", f"{len(settings.jwt_secret)} characters"))

    if production and settings.server_base_url.startswith("http://"):
        results.append((FAIL, "SERVER_BASE_URL",
                        "must be https in production: Twilio callbacks and audio streaming need it"))
    else:
        results.append((OK, "SERVER_BASE_URL", settings.server_base_url))

    insecure = [o for o in settings.cors_origins if o.startswith("http://") and "localhost" not in o]
    if production and any(o == "*" for o in settings.cors_origins):
        results.append((FAIL, "CORS origins", "wildcard origin in production"))
    elif insecure:
        results.append((WARN, "CORS origins", f"non-https origins: {', '.join(insecure)}"))
    else:
        results.append((OK, "CORS origins", ", ".join(settings.cors_origins) or "(none set)"))

    return results


async def main() -> int:
    print(f"HaemNet configuration check (APP_ENV={settings.app_env}, DB_BACKEND={settings.db_backend})\n")
    results: List[Result] = []
    results.extend(check_app_settings())
    results.append(await check_database())
    results.extend(await check_twilio())
    results.append(await check_sarvam())
    results.append(await check_geocoding())

    symbols = {OK: "PASS", WARN: "WARN", FAIL: "FAIL"}
    for state, name, detail in results:
        print(f"[{symbols[state]}] {name}: {detail}")

    try:
        from backend.db_services import close

        await close()
    except Exception:  # noqa: BLE001 - shutdown is best effort
        pass

    failures = [r for r in results if r[0] == FAIL]
    warnings = [r for r in results if r[0] == WARN]
    print(f"\n{len(results) - len(failures) - len(warnings)} passed, {len(warnings)} warnings, {len(failures)} failed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
