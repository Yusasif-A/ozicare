"""
Staff authentication and role checks.

Email + password, bcrypt-hashed, JWT bearer tokens. Roles, lowest to highest:
viewer (read only) < navigator (works cases) < clinician (also takes urgent
escalations) < admin (manages staff, exports audit).
"""

from __future__ import annotations

import logging
import secrets
from datetime import timedelta
from typing import Annotated

import bcrypt
import jwt
from fastapi import Depends, Header, HTTPException

from .config import settings
from .db import db, new_id, now

logger = logging.getLogger("ozicare.auth")

ROLES = ("viewer", "navigator", "clinician", "admin")
TOKEN_HOURS = 12


def hash_password(pw: str) -> str:
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()


def check_password(pw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(pw.encode(), hashed.encode())
    except ValueError:
        return False


def issue_token(user: dict) -> str:
    if not settings.app.jwt_secret:
        raise HTTPException(503, "JWT_SECRET is not set")
    payload = {"sub": user["_id"], "role": user["role"], "exp": now() + timedelta(hours=TOKEN_HOURS)}
    return jwt.encode(payload, settings.app.jwt_secret, algorithm="HS256")


def public_user(u: dict) -> dict:
    return {"id": u["_id"], "name": u["name"], "email": u["email"], "role": u["role"], "active": u.get("active", True)}


async def current_user(authorization: Annotated[str | None, Header()] = None) -> dict:
    if not settings.app.jwt_secret:
        raise HTTPException(503, "JWT_SECRET is not set; refusing all staff requests")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "not signed in")
    try:
        data = jwt.decode(authorization[7:], settings.app.jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(401, "session expired, sign in again") from None
    user = await db().staff_users.find_one({"_id": data["sub"]})
    if not user or user.get("active") is False:
        raise HTTPException(401, "account disabled")
    return user


def require(min_role: str):
    """Dependency: the signed-in user must be at least `min_role`."""

    async def dep(user: Annotated[dict, Depends(current_user)]) -> dict:
        if ROLES.index(user["role"]) < ROLES.index(min_role):
            raise HTTPException(403, f"needs {min_role} role")
        return user

    return dep


async def seed_staff() -> None:
    """
    First run only: an admin from env, plus a navigator and a clinician so the
    owner rules have someone to assign to. Demo passwords are printed once.
    """
    if await db().staff_users.count_documents({}) > 0:
        return
    admin_pw = settings.app.admin_password or secrets.token_urlsafe(9)
    demo_pw = settings.app.admin_password or admin_pw
    people = [
        ("Admin", settings.app.admin_email, "admin", admin_pw),
        ("Amina Navigator", "navigator@ozicare.demo", "navigator", demo_pw),
        ("Dr. Yusuf Clinician", "clinician@ozicare.demo", "clinician", demo_pw),
    ]
    for name, email, role, pw in people:
        await db().staff_users.insert_one(
            {"_id": new_id("ST"), "name": name, "email": email.lower(), "role": role, "password_hash": hash_password(pw), "active": True, "created_at": now()}
        )
    if not settings.app.admin_password:
        logger.warning("Seeded staff with generated password %s — set ADMIN_PASSWORD to choose one", admin_pw)
    logger.info("Seeded staff: %s", ", ".join(p[1] for p in people))
