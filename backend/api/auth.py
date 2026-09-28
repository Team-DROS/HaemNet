"""
JWT authentication.

Two kinds of token share one signing key and are told apart by a `role`
claim:
  - hospital: issued by /api/auth/token (hospital ID + password)
  - donor:    issued by /api/donor/auth/verify (phone + emailed code)
A donor token can never be used on hospital endpoints, and the reverse.
"""

import logging
import jwt
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer, OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel
import bcrypt
from backend.config import settings
from backend.db_services import (
    db_create_hospital,
    db_get_hospital_by_id,
    db_get_login_email,
    db_set_login_email,
    get_donor_by_phone,
)
from backend.services import otp
from backend.services.email_service import EmailError, mask_email, send_sign_in_code
from backend.services.rate_limit import SlidingWindowLimiter

logger = logging.getLogger(__name__)

SECRET_KEY = settings.jwt_secret
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 # 24 hours
DONOR_TOKEN_EXPIRE_DAYS = 30

ROLE_HOSPITAL = "hospital"
ROLE_DONOR = "donor"

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/auth/token")
donor_bearer = HTTPBearer(auto_error=False)
router = APIRouter(prefix="/api/auth", tags=["auth"])
donor_router = APIRouter(prefix="/api/donor/auth", tags=["donor-auth"])

# Failed hospital sign-ins: 10 per ID per 15 minutes, then 429.
_login_failures = SlidingWindowLimiter(max_events=10, window_seconds=15 * 60)

class HospitalRegister(BaseModel):
    # Optional: when omitted the server issues a unique ID. Clients used to
    # pick a random 3-digit ID themselves, which collided often.
    id: Optional[str] = None
    name: str
    location: str
    phone: str
    password: str


_PUBLIC_HOSPITAL_FIELDS = ("id", "name", "location", "phone")


def public_hospital(hospital) -> dict:
    """Hospital record safe to send to a client (never the password hash)."""
    data = dict(hospital)
    return {key: data.get(key) for key in _PUBLIC_HOSPITAL_FIELDS}


async def _issue_hospital_id() -> str:
    for _ in range(20):
        candidate = f"HOSP-{secrets.randbelow(9000) + 1000}"
        if not await db_get_hospital_by_id(candidate):
            return candidate
    return f"HOSP-{secrets.token_hex(4).upper()}"

def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))
    except Exception:
        return False

def get_password_hash(password: str) -> str:
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

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
    return hospital_id


async def get_current_donor(creds: Optional[HTTPAuthorizationCredentials] = Depends(donor_bearer)) -> str:
    phone = donor_from_token(creds.credentials) if creds else None
    if phone is None:
        raise _unauthorized("Sign in again to continue")
    return phone

@router.post("/register")
async def register_hospital(hospital: HospitalRegister):
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
        password_hash=hashed_password
    )
    return {"message": "Hospital registered successfully", "id": hospital_id}

@router.post("/token")
async def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends()):
    hospital_id = form_data.username.strip().upper()
    if not _login_failures.allowed(hospital_id):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many failed sign-in attempts. Try again in a few minutes.",
            headers={"Retry-After": str(_login_failures.retry_after(hospital_id))},
        )

    hospital = await db_get_hospital_by_id(hospital_id)
    if not hospital or not verify_password(form_data.password, hospital.get("password_hash", "")):
        _login_failures.hit(hospital_id)
        raise _unauthorized("Incorrect username or password")
    _login_failures.reset(hospital_id)

    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": hospital_id, "role": ROLE_HOSPITAL}, expires_delta=access_token_expires
    )
    # Previously the raw record was returned, which included the bcrypt
    # password hash and got stored in the browser.
    return {"access_token": access_token, "token_type": "bearer", "user": public_hospital(hospital)}


# ── Donor sign-in (phone + emailed code) ──────────────────────────
#
# The donor gives the mobile number hospitals should call and an email
# address. A 6-digit code is emailed; entering it issues a donor token for
# that phone. The first successful sign-in binds the email to the phone, and
# later sign-ins for that phone only work with the same email, so knowing
# someone's number is not enough to take over their donor profile.
# (SMS codes were dropped: the Twilio trial could not deliver to Indian
# numbers. Twilio is still used for the AI voice calls.)

class OtpRequest(BaseModel):
    phone: str
    email: str


class OtpVerify(BaseModel):
    phone: str
    email: str
    code: str


def _normalise_pair(phone_raw: str, email_raw: str) -> tuple:
    phone = otp.normalise_phone(phone_raw)
    if not phone:
        raise HTTPException(status_code=422, detail="Enter a valid mobile number")
    email = otp.normalise_email(email_raw)
    if not email:
        raise HTTPException(status_code=422, detail="Enter a valid email address")
    return phone, email


_WRONG_EMAIL = ("This number is already linked to a different email address. "
                "Use that email, or ask the HaemNet team to reset it.")


@donor_router.post("/request")
async def request_donor_code(payload: OtpRequest):
    """Email a 6-digit sign-in code for this phone and email pairing."""
    phone, email = _normalise_pair(payload.phone, payload.email)

    if not settings.email_configured and settings.app_env.lower() != "development":
        raise HTTPException(status_code=503, detail="Email sign-in is not configured")

    bound = await db_get_login_email(phone)
    if bound and bound != email:
        raise HTTPException(status_code=409, detail=_WRONG_EMAIL)

    try:
        otp.check_email_quota(email)
        code = otp.issue_code(otp.login_key(phone, email))
    except otp.OtpError as exc:
        raise HTTPException(status_code=429, detail=str(exc), headers={"Retry-After": str(exc.retry_after)})

    response = {
        "status": "sent",
        "phone": phone,
        "email": mask_email(email),
        "expires_in": otp.CODE_TTL_SECONDS,
    }
    if settings.email_configured:
        try:
            await send_sign_in_code(email, code, otp.CODE_TTL_SECONDS // 60)
        except EmailError as exc:
            logger.error("Could not email sign-in code to %s: %s", mask_email(email), exc)
            raise HTTPException(status_code=502, detail="Could not send the code email. Try again shortly.")
    else:
        # Development only (checked above): no email provider, so hand the
        # code back so the app can be tested end to end.
        logger.warning("Email not configured; returning dev sign-in code for %s", phone)
        response["dev_code"] = code
    return response


@donor_router.post("/verify")
async def verify_donor_code(payload: OtpVerify):
    """Exchange a correct code for a donor token (valid 30 days)."""
    phone, email = _normalise_pair(payload.phone, payload.email)
    if not otp.verify_code(otp.login_key(phone, email), payload.code):
        raise HTTPException(status_code=401, detail="That code is incorrect or has expired")

    bound = await db_get_login_email(phone)
    if bound and bound != email:  # bound by someone else between request and verify
        raise HTTPException(status_code=409, detail=_WRONG_EMAIL)
    if not bound:
        await db_set_login_email(phone, email)

    token = create_access_token(
        {"sub": phone, "role": ROLE_DONOR}, expires_delta=timedelta(days=DONOR_TOKEN_EXPIRE_DAYS)
    )
    try:
        registered = bool(await get_donor_by_phone(phone))
    except Exception:
        registered = False
    return {
        "access_token": token,
        "token_type": "bearer",
        "phone": phone,
        "email": mask_email(email),
        "registered": registered,
    }
