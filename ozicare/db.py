"""
Mongo access. One client per process, created lazily so importing a module
never opens a connection (the LiveKit worker forks, and a client created before
the fork is not safe to use after it).
"""

from __future__ import annotations

import secrets
from datetime import datetime, timezone

from pymongo import ASCENDING, DESCENDING, AsyncMongoClient
from pymongo.asynchronous.database import AsyncDatabase

from .config import settings

_client: AsyncMongoClient | None = None


def db() -> AsyncDatabase:
    global _client
    if _client is None:
        _client = AsyncMongoClient(settings.mongo.uri, tz_aware=True, serverSelectionTimeoutMS=8000)
    return _client[settings.mongo.db]


async def close() -> None:
    global _client
    if _client is not None:
        await _client.close()
        _client = None


def now() -> datetime:
    return datetime.now(timezone.utc)


def new_id(prefix: str) -> str:
    """Short readable ids: staff read case numbers aloud to each other."""
    return f"{prefix}-{secrets.token_hex(3).upper()}"


async def ensure_indexes() -> None:
    d = db()
    await d.patients.create_index("phone_e164", unique=True)
    await d.cases.create_index([("status", ASCENDING), ("next_action_at", ASCENDING)])
    await d.cases.create_index([("patient_id", ASCENDING), ("created_at", DESCENDING)])
    await d.messages.create_index([("case_id", ASCENDING), ("created_at", ASCENDING)])
    await d.messages.create_index("provider_message_id", sparse=True)
    await d.events.create_index([("case_id", ASCENDING), ("created_at", ASCENDING)])
    await d.staff_users.create_index("email", unique=True)
    await d.calls.create_index("keys")
