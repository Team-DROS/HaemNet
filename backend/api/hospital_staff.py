"""Staff accounts: the hospital's admins manage them, staff sign in with their own email and password."""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from backend.api.auth import (
    ROLE_HOSPITAL,
    create_access_token,
    get_current_hospital_admin,
    public_hospital,
)
from backend.api.dependencies import require_platform
from backend.services import hospital_staff
from backend.services.rate_limit import Limiter, enforce

router = APIRouter(tags=["hospital-staff"], dependencies=[Depends(require_platform)])

_staff_failures = Limiter("staff_login", max_events=10, window_seconds=15 * 60)
STAFF_TOKEN_HOURS = 24


class StaffCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: str
    role: str = "staff"
    password: str = Field(min_length=8, max_length=72)


class StaffLogin(BaseModel):
    hospital_id: str
    email: str
    password: str


@router.get("/api/hospitals/me/staff")
async def list_staff(hospital_id: str = Depends(get_current_hospital_admin)):
    return {"staff": await hospital_staff.list_staff(hospital_id)}


@router.post("/api/hospitals/me/staff")
async def add_staff(payload: StaffCreate, hospital_id: str = Depends(get_current_hospital_admin)):
    return await hospital_staff.add_staff(hospital_id, payload.name, payload.email, payload.role, payload.password)


@router.delete("/api/hospitals/me/staff/{staff_id}")
async def remove_staff(staff_id: str, hospital_id: str = Depends(get_current_hospital_admin)):
    await hospital_staff.remove_staff(hospital_id, staff_id)
    return {"removed": staff_id}


@router.post("/api/auth/staff-token")
async def staff_login(payload: StaffLogin):
    hospital_id = payload.hospital_id.strip().upper()
    email = payload.email.strip().lower()
    key = f"{hospital_id}:{email}"
    await enforce(_staff_failures, key, "Too many failed sign-in attempts. Try again in a few minutes.")
    hospital, member = await hospital_staff.authenticate(hospital_id, email, payload.password)
    await _staff_failures.reset(key)

    token = create_access_token(
        {"sub": hospital_id, "role": ROLE_HOSPITAL, "staff_id": member["id"], "staff_role": member["role"]},
        expires_delta=timedelta(hours=STAFF_TOKEN_HOURS),
    )
    user = public_hospital(hospital)
    user["staff"] = {"id": member["id"], "name": member["name"], "role": member["role"]}
    return {"access_token": token, "token_type": "bearer", "user": user}
