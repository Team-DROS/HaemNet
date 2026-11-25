"""
JWT authentication.

Two kinds of token share one signing key and are told apart by a `role`
claim:
  - hospital: issued by /api/auth/token (hospital ID + password)
  - donor:    issued by /api/donor/auth/register or /login (phone + password)
A donor token can never be used on hospital endpoints, and the reverse.
"""

import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer, OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel, Field

from backend.config import settings
from backend.db_services import (
    db_create_donor_password,
    db_create_hospital,
    db_get_donor_password_hash,
    db_get_hospital_by_id,
    get_donor_by_phone,
)
from backend.services import hospital_platform as hp
from backend.services import otp
from backend.services.passwords import get_password_hash, verify_password  # noqa: F401  (re-exported)
from backend.services.phone import normalise_phone
from backend.services.rate_limit import Limiter, enforce
from backend.services.turnstile import require_human

logger = logging.getLogger(__name__)

SECRET_KEY = settings.jwt_secret
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24  # 24 hours
DONOR_TOKEN_EXPIRE_DAYS = 30

ROLE_HOSPITAL = "hospital"
ROLE_DONOR = "donor"
ROLE_ADMIN = "admin"
# A short-lived proof that a phone number was verified by SMS. It is neither a donor nor a
# hospital token, so it cannot be used to call any other endpoint.
ROLE_PHONE_VERIFIED = "phone_verified"
PHONE_VERIFIED_MINUTES = 30

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/auth/token")
donor_bearer = HTTPBearer(auto_error=False)
router = APIRouter(prefix="/api/auth", tags=["auth"])
donor_router = APIRouter(prefix="/api/donor/auth", tags=["donor-auth"])

# Failed hospital sign-ins: 10 per ID per 15 minutes, then 429.
_login_failures = Limiter("hospital_login", max_events=10, window_seconds=15 * 60)


class HospitalRegister(BaseModel):
    # Optional: when omitted the server issues a unique ID. Clients used to
    # pick a random 3-digit ID themselves, which collided often.
    id: Optional[str] = None
    name: str
    location: str
    phone: str
    password: str
    # Verification details. Required together once the platform is available.
    official_email: Optional[str] = None
    contact_person: Optional[str] = None
    hfr_id: Optional[str] = None
    registration_number: Optional[str] = None
    blood_centre_licence: Optional[str] = None
    turnstile_token: Optional[str] = None


_PUBLIC_HOSPITAL_FIELDS = ("id", "name", "location", "phone", "status", "email_verified", "decision_reason")


def public_hospital(hospital) -> dict:
    """Hospital record safe to send to a client (never the password hash)."""
    data = dict(hospital)
    out = {key: data.get(key) for key in _PUBLIC_HOSPITAL_FIELDS}
    # Records created before verification existed count as approved.
    out["status"] = out["status"] or "approved"
    out["email_verified"] = True if out["email_verified"] is None else out["email_verified"]
    return out


async def _issue_hospital_id() -> str:
    for _ in range(20):
        candidate = f"HOSP-{secrets.randbelow(9000) + 1000}"
        if not await db_get_hospital_by_id(candidate):
            return candidate
    return f"HOSP-{secrets.token_hex(4).upper()}"


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def _decode(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.InvalidTokenError:
        return None


def hospital_from_token(token: str) -> Optional[str]:
    """Hospital ID from a hospital token, else None. Tokens issued before
    roles existed carry no role claim and are treated as hospital tokens."""
    payload = _decode(token) if token else None
    if not payload or payload.get("role", ROLE_HOSPITAL) != ROLE_HOSPITAL:
        return None
    return payload.get("sub") or None


def donor_from_token(token: str) -> Optional[str]:
    """Donor phone (E.164) from a donor token, else None."""
    payload = _decode(token) if token else None
    if not payload or payload.get("role") != ROLE_DONOR:
        return None
    return payload.get("sub") or None


def _unauthorized(detail: str = "Could not validate credentials") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_current_hospital(token: str = Depends(oauth2_scheme)) -> str:
    hospital_id = hospital_from_token(token)
    if hospital_id is None:
        raise _unauthorized()
    claims = _decode(token) or {}
    if claims.get("staff_id"):
        # A removed staff member loses access at once, not when the token expires.
        record = await hp.repo.get(hospital_id)
        member = next((m for m in (record or {}).get("staff", []) if m["id"] == claims["staff_id"]), None)
        if not member or not member.get("active", True):
            raise _unauthorized("This staff account was removed")
    return hospital_id


async def get_actor(token: str = Depends(oauth2_scheme)) -> str:
    """Who is acting: the staff member's ID, or "owner" for the hospital's own login."""
    claims = _decode(token) or {}
    return claims.get("staff_id") or "owner"


async def get_current_hospital_admin(token: str = Depends(oauth2_scheme)) -> str:
    """Hospital owner or a staff member with the admin role."""
    hospital_id = await get_current_hospital(token)
    claims = _decode(token) or {}
    if claims.get("staff_id") and claims.get("staff_role") != "admin":
        raise HTTPException(status_code=403, detail="Only hospital admins can manage staff")
    return hospital_id


def admin_from_token(token: str) -> Optional[str]:
    payload = _decode(token) if token else None
    if not payload or payload.get("role") != ROLE_ADMIN:
        return None
    return payload.get("sub") or None


async def get_current_admin(token: str = Depends(oauth2_scheme)) -> str:
    admin = admin_from_token(token)
    if admin is None:
        raise _unauthorized()
    return admin


async def get_current_donor(creds: Optional[HTTPAuthorizationCredentials] = Depends(donor_bearer)) -> str:
    phone = donor_from_token(creds.credentials) if creds else None
    if phone is None:
        raise _unauthorized("Sign in again to continue")
    return phone


@router.post("/register")
async def register_hospital(hospital: HospitalRegister, request: Request):
    await require_human(hospital.turnstile_token, request.client.host if request.client else None)
    profile = {}
    if hp.platform_available():
        email = (hospital.official_email or "").strip().lower()
        if not hp.valid_email(email):
            raise HTTPException(status_code=422, detail="Enter the hospital's official email address")
        contact_person = (hospital.contact_person or "").strip()
        if not contact_person:
            raise HTTPException(status_code=422, detail="Enter a contact person")
        if not ((hospital.hfr_id or "").strip() or (hospital.registration_number or "").strip()):
            raise HTTPException(status_code=422, detail="Enter your HFR ID or state registration number")
        profile = {
            "official_email": email,
            "contact_person": contact_person[:120],
            "hfr_id": (hospital.hfr_id or "").strip()[:60] or None,
            "registration_number": (hospital.registration_number or "").strip()[:60] or None,
            "blood_centre_licence": (hospital.blood_centre_licence or "").strip()[:60] or None,
        }
    hospital_id = (hospital.id or "").strip().upper() or await _issue_hospital_id()
    existing = await db_get_hospital_by_id(hospital_id)
    if existing:
        raise HTTPException(status_code=400, detail="Hospital ID already registered")

    hashed_password = get_password_hash(hospital.password)
    await db_create_hospital(
        id=hospital_id,
        name=hospital.name,
        location=hospital.location,
        phone=hospital.phone,
        password_hash=hashed_password,
    )
    if profile:
        await hp.register_pending(hospital_id, hospital.name, profile)
    return {
        "message": "Hospital registered successfully",
        "id": hospital_id,
        "status": "pending" if profile else "approved",
    }


@router.post("/token")
async def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends()):
    hospital_id = form_data.username.strip().upper()
    await enforce(_login_failures, hospital_id, "Too many failed sign-in attempts. Try again in a few minutes.")

    hospital = await db_get_hospital_by_id(hospital_id)
    if not hospital or not verify_password(form_data.password, hospital.get("password_hash", "")):
        raise _unauthorized("Incorrect username or password")
    await _login_failures.reset(hospital_id)

    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": hospital_id, "role": ROLE_HOSPITAL}, expires_delta=access_token_expires
    )
    # Previously the raw record was returned, which included the bcrypt
    # password hash and got stored in the browser.
    return {"access_token": access_token, "token_type": "bearer", "user": public_hospital(hospital)}


# ── Donor sign-in (phone + password) ──────────────────────────────
#
# A donor creates an account with the mobile number hospitals should call
# and a password, then signs in with the same pair. Passwords are stored as
# bcrypt hashes in `donor_logins`, apart from the donor profile. There is no
# SMS or email step: the number itself is not verified, which is noted in
# the donor app README. A forgotten password is reset by an admin with
# `python -m backend.tools.reset_donor_password <phone>`.

MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_BYTES = 72  # bcrypt ignores anything longer

# Failed donor sign-ins: 10 per number per 15 minutes, then 429.
_donor_failures = Limiter("donor_login", max_events=10, window_seconds=15 * 60)
# New accounts: 5 per number per hour (stops scripted squatting on numbers).
_donor_signups = Limiter("donor_signup", max_events=5, window_seconds=3600)
# Verification texts cost money: 3 per number and 10 per client address per hour.
_otp_by_phone = Limiter("otp_request_phone", max_events=3, window_seconds=3600)
_otp_by_ip = Limiter("otp_request_ip", max_events=10, window_seconds=3600)


class DonorCredentials(BaseModel):
    phone: str
    password: str
    # Proof from POST /otp/verify. Required to register when DONOR_OTP_REQUIRED is on.
    otp_token: Optional[str] = None


class OtpRequest(BaseModel):
    phone: str


class OtpVerify(BaseModel):
    phone: str
    code: str = Field(min_length=4, max_length=8)


def _donor_phone(raw: str) -> str:
    phone = normalise_phone(raw)
    if not phone:
        raise HTTPException(status_code=422, detail="Enter a valid 10-digit mobile number")
    return phone


def _check_new_password(password: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise HTTPException(status_code=422, detail=f"Use at least {MIN_PASSWORD_LENGTH} characters for the password")
    if len(password.encode("utf-8")) > MAX_PASSWORD_BYTES:
        raise HTTPException(status_code=422, detail="That password is too long (72 characters at most)")


async def _donor_session(phone: str) -> dict:
    token = create_access_token(
        {"sub": phone, "role": ROLE_DONOR}, expires_delta=timedelta(days=DONOR_TOKEN_EXPIRE_DAYS)
    )
    try:
        registered = bool(await get_donor_by_phone(phone))
    except Exception:
        registered = False
    return {"access_token": token, "token_type": "bearer", "phone": phone, "registered": registered}


def _phone_verified(otp_token: Optional[str], phone: str) -> bool:
    claims = _decode(otp_token) if otp_token else None
    return claims is not None and claims.get("role") == ROLE_PHONE_VERIFIED and claims.get("sub") == phone


@donor_router.get("/config")
async def donor_auth_config():
    """What the donor app needs to know before it shows the sign-up form."""
    return {"otp_required": settings.donor_otp_required}


@donor_router.post("/otp/request")
async def request_phone_code(payload: OtpRequest, request: Request):
    """Text a one-time code to the number. The answer is the same whether or not an account exists."""
    phone = _donor_phone(payload.phone)
    await enforce(
        _otp_by_ip, request.client.host if request.client else "unknown", "Too many requests. Try again later."
    )
    await enforce(_otp_by_phone, phone, "Too many codes requested for this number. Try again later.")
    await otp.send_code(phone)
    return {"sent": True, "expires_in": settings.otp_ttl_seconds}


@donor_router.post("/otp/verify")
async def verify_phone_code(payload: OtpVerify):
    """Exchange a correct code for a proof of phone ownership, used when registering."""
    phone = _donor_phone(payload.phone)
    if not await otp.check_code(phone, payload.code):
        raise HTTPException(status_code=400, detail="That code is wrong or has expired.")
    token = create_access_token(
        {"sub": phone, "role": ROLE_PHONE_VERIFIED}, expires_delta=timedelta(minutes=PHONE_VERIFIED_MINUTES)
    )
    return {"otp_token": token, "expires_in": PHONE_VERIFIED_MINUTES * 60}


@donor_router.post("/register")
async def register_donor_account(payload: DonorCredentials):
    """Create a donor account (phone + password) and sign it in."""
    phone = _donor_phone(payload.phone)
    _check_new_password(payload.password)
    if settings.donor_otp_required and not _phone_verified(payload.otp_token, phone):
        raise HTTPException(status_code=403, detail="Verify your phone number with the code we text you first.")
    await enforce(_donor_signups, phone, "Too many attempts. Try again later.")

    created = await db_create_donor_password(phone, get_password_hash(payload.password))
    if not created:
        raise HTTPException(status_code=409, detail="This number already has an account. Sign in instead.")
    logger.info("Donor account created for …%s", phone[-4:])
    return await _donor_session(phone)


@donor_router.post("/login")
async def login_donor(payload: DonorCredentials):
    """Exchange phone + password for a donor token (valid 30 days)."""
    phone = _donor_phone(payload.phone)
    await enforce(_donor_failures, phone, "Too many failed attempts. Try again in a few minutes.")

    stored = await db_get_donor_password_hash(phone)
    if not stored or not verify_password(payload.password, stored):
        raise HTTPException(status_code=401, detail="Wrong mobile number or password")
    await _donor_failures.reset(phone)
    return await _donor_session(phone)
