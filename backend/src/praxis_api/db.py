from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorClientSession, AsyncIOMotorDatabase
from pymongo import ReturnDocument


class Database:
    """Async MongoDB Atlas connection: client lifecycle, indexes, transactions,
    and the counters collection used to hand out stable integer ids so the
    REST API's `id` fields keep the same shape they had under SQLite."""

    def __init__(
        self,
        uri: str,
        name: str,
        client_factory: Callable[[str], Any] = AsyncIOMotorClient,
        supports_transactions: bool = True,
    ):
        self.uri = uri
        self.name = name
        self._client_factory = client_factory
        self.supports_transactions = supports_transactions
        self._client: Any | None = None

    def connect(self) -> None:
        self._client = self._client_factory(self.uri)

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    @property
    def db(self) -> AsyncIOMotorDatabase:
        if self._client is None:
            raise RuntimeError("MongoDB client is not initialized")
        return self._client[self.name]

    async def ensure_indexes(self) -> None:
        await self.db.users.create_index("username_lower", unique=True)
        await self.db.tasks.create_index(
            [("task_type", 1), ("task_version", 1), ("difficulty_key", 1), ("hand_key", 1)],
            unique=True,
        )
        await self.db.sessions.create_index([("session_id", 1), ("device_id", 1)], unique=True)
        await self.db.sessions.create_index([("user_id", 1), ("created_at", -1)])
        await self.db.sessions.create_index([("task_id", 1), ("created_at", -1)])

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[AsyncIOMotorClientSession | None]:
        """Yield a session with an active transaction on a real Atlas replica
        set. Test doubles that don't support sessions (e.g. mongomock) yield
        None; callers pass session=None through to Motor calls in that case,
        which is a valid no-op session."""
        if not self.supports_transactions:
            yield None
            return
        async with await self._client.start_session() as session, session.start_transaction():
            yield session

    async def next_id(self, counter: str, session: AsyncIOMotorClientSession | None = None) -> int:
        doc = await self.db.counters.find_one_and_update(
            {"_id": counter},
            {"$inc": {"seq": 1}},
            upsert=True,
            return_document=ReturnDocument.AFTER,
            session=session,
        )
        return doc["seq"]
