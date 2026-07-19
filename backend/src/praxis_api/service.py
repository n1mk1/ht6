from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException
from motor.motor_asyncio import AsyncIOMotorClientSession
from pymongo.errors import DuplicateKeyError

from .comparisons import compare_sessions
from .db import Database
from .freesolo import AnalysisResult, FreeSoloAdapter
from .schemas import QnxSessionPayload, UserResolve, UserUpdate

MODEL_RESULT_FIELDS = (
    "status",
    "adapter",
    "model_version",
    "regression_score",
    "regression_flag",
    "confidence",
    "overall_pattern",
    "result",
    "error_code",
    "error_detail",
)


def now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def json_text(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), sort_keys=True)


class PraxisService:
    def __init__(self, database: Database, adapter: FreeSoloAdapter):
        self.database = database
        self.adapter = adapter

    @property
    def db(self):
        return self.database.db

    # -- ingestion ---------------------------------------------------------

    async def ingest(
        self, payload: QnxSessionPayload, original_payload: dict[str, Any]
    ) -> tuple[dict[str, Any], bool]:
        original = original_payload
        payload_hash = hashlib.sha256(json_text(original).encode()).hexdigest()
        received_at = now_iso()

        existing = await self.db.sessions.find_one(
            {"session_id": payload.session_id, "device_id": payload.device_id}
        )
        if existing:
            if existing["payload_sha256"] != payload_hash:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "session_identity_conflict",
                        "message": (
                            "session_id and device_id already identify a different payload"
                        ),
                        "retryable": False,
                    },
                )
            return await self._hydrate_session(existing), False

        task_dict = original["task"]
        metrics = payload.metrics.model_dump(mode="json", exclude_none=False)
        quality = payload.quality.model_dump(mode="json", exclude_none=False)
        scores = payload.scores.model_dump(mode="json", exclude_none=False)
        timing = payload.timing.model_dump(mode="json", exclude_none=False)
        trace = payload.trace.model_dump(mode="json", exclude_none=False)

        async with self.database.transaction() as db_session:
            user_id = await self._upsert_user(payload.username, received_at, db_session)
            task_id = await self._upsert_task(task_dict, received_at, db_session)
            session_pk = await self.database.next_id("sessions", db_session)

            doc: dict[str, Any] = {
                "_id": session_pk,
                "session_id": payload.session_id,
                "device_id": payload.device_id,
                "user_id": user_id,
                "task_id": task_id,
                "schema_version": payload.schema_version,
                "created_at": payload.created_at.isoformat().replace("+00:00", "Z"),
                "received_at": received_at,
                "task": task_dict,
                "timing": timing,
                "scores": scores,
                "metrics": metrics,
                "quality": quality,
                "trace": trace,
                "percentiles": original.get("percentiles"),
                "explanation": original.get("explanation"),
                "score_definitions": original.get("score_definitions"),
                "artifacts": original.get("artifacts"),
                "original_payload": original,
                "payload_sha256": payload_hash,
                "model_result": None,
                "deterministic_comparison": None,
            }

            reference_docs = await (
                self.db.sessions.find(
                    {"user_id": user_id, "task_id": task_id, "_id": {"$ne": session_pk}},
                    session=db_session,
                )
                .sort([("created_at", -1), ("_id", -1)])
                .limit(1)
                .to_list(1)
            )
            reference_doc = reference_docs[0] if reference_docs else None
            if reference_doc is not None:
                doc["deterministic_comparison"] = compare_sessions(reference_doc, doc)

            doc["model_result"] = {
                "status": "pending",
                "adapter": "freesolo_http_v2",
                "model_version": None,
                "regression_score": None,
                "regression_flag": None,
                "confidence": None,
                "overall_pattern": None,
                "result": None,
                "error_code": None,
                "error_detail": None,
                "reference_session_pk": reference_doc["_id"] if reference_doc else None,
                "updated_at": received_at,
            }

            await self.db.sessions.insert_one(doc, session=db_session)

        return await self._hydrate_session(doc), True

    async def analyze_session(self, session_pk: int) -> None:
        doc = await self.db.sessions.find_one({"_id": session_pk})
        if not doc or doc.get("model_result") is None:
            return
        reference_pk = doc["model_result"].get("reference_session_pk")
        reference_doc = (
            await self.db.sessions.find_one({"_id": reference_pk})
            if reference_pk is not None
            else None
        )
        current = await self._adapter_input(doc)
        reference = await self._adapter_input(reference_doc) if reference_doc else None
        await self._save_analysis(session_pk, self.adapter.analyze(reference, current))

    async def _adapter_input(self, session_doc: dict[str, Any]) -> dict[str, Any]:
        user = await self.db.users.find_one({"_id": session_doc["user_id"]})
        return {
            "session_id": session_doc["session_id"],
            "username": user["username"] if user else None,
            "created_at": session_doc["created_at"],
            "task": session_doc["task"],
            "metrics": session_doc["metrics"],
            "quality": session_doc["quality"],
        }

    async def _save_analysis(self, session_pk: int, result: AnalysisResult) -> None:
        await self.db.sessions.update_one(
            {"_id": session_pk},
            {
                "$set": {
                    "model_result.status": result.status,
                    "model_result.adapter": result.adapter,
                    "model_result.model_version": result.model_version,
                    "model_result.regression_score": result.regression_score,
                    "model_result.regression_flag": result.regression_flag,
                    "model_result.confidence": result.confidence,
                    "model_result.overall_pattern": result.overall_pattern,
                    "model_result.result": result.result,
                    "model_result.error_code": result.error_code,
                    "model_result.error_detail": result.error_detail,
                    "model_result.updated_at": now_iso(),
                }
            },
        )

    # -- users ---------------------------------------------------------------

    async def list_users(self) -> list[dict[str, Any]]:
        stats: dict[int, dict[str, Any]] = {}
        async for row in self.db.sessions.aggregate(
            [
                {
                    "$group": {
                        "_id": "$user_id",
                        "session_count": {"$sum": 1},
                        "latest_session_at": {"$max": "$created_at"},
                    }
                }
            ]
        ):
            stats[row["_id"]] = row
        users = await self.db.users.find().to_list(None)
        output = [self._user_out(user, stats.get(user["_id"])) for user in users]
        output.sort(key=lambda user: user["latest_session_at"] or user["created_at"], reverse=True)
        return output

    async def resolve_user(self, request: UserResolve) -> tuple[dict[str, Any], bool]:
        existing = await self.db.users.find_one({"username_lower": request.username.lower()})
        if existing:
            return await self.get_user(existing["_id"]), False
        user_id = await self._upsert_user(request.username, now_iso())
        return await self.get_user(user_id), True

    async def get_user(self, user_id: int) -> dict[str, Any]:
        user = await self.db.users.find_one({"_id": user_id})
        if not user:
            raise HTTPException(404, detail={"code": "user_not_found"})
        stats = await self.db.sessions.aggregate(
            [
                {"$match": {"user_id": user_id}},
                {
                    "$group": {
                        "_id": "$user_id",
                        "session_count": {"$sum": 1},
                        "latest_session_at": {"$max": "$created_at"},
                    }
                },
            ]
        ).to_list(1)
        return self._user_out(user, stats[0] if stats else None)

    async def update_user(self, user_id: int, update: UserUpdate) -> dict[str, Any]:
        fields = update.model_dump(exclude_unset=True)
        if not fields:
            return await self.get_user(user_id)
        fields["updated_at"] = now_iso()
        result = await self.db.users.update_one({"_id": user_id}, {"$set": fields})
        if result.matched_count == 0:
            raise HTTPException(404, detail={"code": "user_not_found"})
        return await self.get_user(user_id)

    # -- sessions --------------------------------------------------------------

    async def list_sessions(
        self, user_id: int, limit: int = 100, offset: int = 0
    ) -> list[dict[str, Any]]:
        await self.get_user(user_id)
        docs = await (
            self.db.sessions.find({"user_id": user_id})
            .sort([("created_at", -1), ("_id", -1)])
            .skip(offset)
            .limit(limit)
            .to_list(limit)
        )
        return [await self._hydrate_session(doc, compact=True) for doc in docs]

    async def latest(self, user_id: int) -> dict[str, Any]:
        sessions = await self.list_sessions(user_id, 1)
        if not sessions:
            raise HTTPException(404, detail={"code": "session_not_found"})
        return await self.get_session(sessions[0]["device_id"], sessions[0]["session_id"])

    async def get_session(self, device_id: str, session_id: str) -> dict[str, Any]:
        doc = await self.db.sessions.find_one({"device_id": device_id, "session_id": session_id})
        if doc is None:
            raise HTTPException(404, detail={"code": "session_not_found"})
        return await self._hydrate_session(doc)

    async def trends(self, user_id: int, limit: int = 50) -> dict[str, Any]:
        sessions = list(reversed(await self.list_sessions(user_id, limit)))
        series = [
            {
                "session_id": session["session_id"],
                "device_id": session["device_id"],
                "created_at": session["created_at"],
                "task": session["task"],
                "accuracy": session["scores"].get("accuracy"),
                "stability": session["scores"].get("stability"),
                "completion_time_seconds": session["metrics"].get("completion_time_seconds"),
                "coverage_pct": session["metrics"].get("coverage_pct"),
            }
            for session in sessions
        ]
        return {"user_id": user_id, "series": series}

    async def compare(
        self,
        reference_device: str,
        reference_session: str,
        current_device: str,
        current_session: str,
    ) -> dict[str, Any]:
        reference = await self.get_session(reference_device, reference_session)
        current = await self.get_session(current_device, current_session)
        if reference["user"]["id"] != current["user"]["id"]:
            raise HTTPException(422, detail={"code": "different_users"})
        result = compare_sessions(reference, current)
        if not result["compatible"]:
            raise HTTPException(422, detail={"code": "incompatible_sessions", **result})
        return {
            "reference": reference,
            "current": current,
            "deterministic_comparison": result,
            "model_prediction": current.get("model_result"),
        }

    async def baseline_comparison(
        self,
        user_id: int,
        current_device: str | None = None,
        current_session: str | None = None,
    ) -> dict[str, Any]:
        if bool(current_device) != bool(current_session):
            raise HTTPException(
                422,
                detail={
                    "code": "incomplete_current_session_identity",
                    "message": "current_device_id and current_session_id must be provided together",
                },
            )
        current = (
            await self.get_session(current_device, current_session)
            if current_device and current_session
            else await self.latest(user_id)
        )
        if current["user"]["id"] != user_id:
            raise HTTPException(422, detail={"code": "different_users"})
        current_doc = await self.db.sessions.find_one({"_id": current["id"]})
        baseline_docs = await (
            self.db.sessions.find(
                {
                    "user_id": user_id,
                    "task_id": current_doc["task_id"],
                    "_id": {"$ne": current["id"]},
                    "created_at": {"$lte": current["created_at"]},
                }
            )
            .sort([("created_at", 1), ("_id", 1)])
            .limit(1)
            .to_list(1)
        )
        if not baseline_docs:
            raise HTTPException(404, detail={"code": "compatible_baseline_not_found"})
        baseline = await self._hydrate_session(baseline_docs[0])
        result = compare_sessions(baseline, current)
        return {
            "baseline": baseline,
            "current": current,
            "deterministic_comparison": result,
            "model_prediction": current.get("model_result"),
        }

    # -- internal helpers --------------------------------------------------

    async def _upsert_user(
        self, username: str, timestamp: str, session: AsyncIOMotorClientSession | None = None
    ) -> int:
        username_lower = username.lower()
        existing = await self.db.users.find_one({"username_lower": username_lower}, session=session)
        if existing:
            return existing["_id"]
        user_id = await self.database.next_id("users", session)
        doc = {
            "_id": user_id,
            "username": username,
            "username_lower": username_lower,
            "display_name": None,
            "notes": None,
            "created_at": timestamp,
            "updated_at": timestamp,
        }
        try:
            await self.db.users.insert_one(doc, session=session)
        except DuplicateKeyError:
            existing = await self.db.users.find_one(
                {"username_lower": username_lower}, session=session
            )
            return existing["_id"]
        return user_id

    async def _upsert_task(
        self, task: dict[str, Any], timestamp: str, session: AsyncIOMotorClientSession | None = None
    ) -> int:
        difficulty = str(task.get("difficulty", "") if task.get("difficulty") is not None else "")
        hand = str(task.get("hand", task.get("dominant_hand", "")) or "")
        key = {
            "task_type": task["type"],
            "task_version": task["version"],
            "difficulty_key": difficulty,
            "hand_key": hand,
        }
        existing = await self.db.tasks.find_one(key, session=session)
        if existing:
            return existing["_id"]
        task_id = await self.database.next_id("tasks", session)
        doc = {"_id": task_id, **key, "metadata": task, "created_at": timestamp}
        try:
            await self.db.tasks.insert_one(doc, session=session)
        except DuplicateKeyError:
            existing = await self.db.tasks.find_one(key, session=session)
            return existing["_id"]
        return task_id

    async def _hydrate_session(self, doc: dict[str, Any], compact: bool = False) -> dict[str, Any]:
        user = await self.db.users.find_one({"_id": doc["user_id"]})
        output = {
            "id": doc["_id"],
            "session_id": doc["session_id"],
            "device_id": doc["device_id"],
            "schema_version": doc["schema_version"],
            "created_at": doc["created_at"],
            "received_at": doc["received_at"],
            "user": {
                "id": user["_id"],
                "username": user["username"],
                "display_name": user.get("display_name"),
            }
            if user
            else None,
            "task": doc["task"],
            "timing": doc["timing"],
            "scores": doc["scores"],
            "metrics": doc["metrics"],
            "quality": doc["quality"],
            "model_result": self._model_result_out(doc.get("model_result")),
            "deterministic_comparison": doc.get("deterministic_comparison"),
        }
        if not compact:
            output.update(
                trace=doc["trace"],
                percentiles=doc.get("percentiles"),
                explanation=doc.get("explanation"),
                score_definitions=doc.get("score_definitions"),
                artifacts=doc.get("artifacts"),
                original_payload=doc["original_payload"],
            )
        return output

    @staticmethod
    def _model_result_out(model_result: dict[str, Any] | None) -> dict[str, Any] | None:
        if model_result is None:
            return None
        return {field: model_result.get(field) for field in MODEL_RESULT_FIELDS}

    @staticmethod
    def _user_out(user: dict[str, Any], stats: dict[str, Any] | None) -> dict[str, Any]:
        return {
            "id": user["_id"],
            "username": user["username"],
            "display_name": user.get("display_name"),
            "notes": user.get("notes"),
            "created_at": user["created_at"],
            "updated_at": user["updated_at"],
            "session_count": stats["session_count"] if stats else 0,
            "latest_session_at": stats["latest_session_at"] if stats else None,
        }
