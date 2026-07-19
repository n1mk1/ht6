from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException

from .comparisons import POLICY_VERSION, compare_sessions
from .db import Database
from .freesolo import AnalysisResult, FreeSoloAdapter
from .schemas import QnxSessionPayload, UserResolve, UserUpdate


def now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def json_text(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), sort_keys=True)


def json_value(value: str | None, fallback: Any = None) -> Any:
    if value is None:
        return fallback
    return json.loads(value)


class PraxisService:
    def __init__(self, database: Database, adapter: FreeSoloAdapter):
        self.database = database
        self.adapter = adapter

    def ingest(
        self, payload: QnxSessionPayload, original_payload: dict[str, Any]
    ) -> tuple[dict[str, Any], bool]:
        original = original_payload
        original_json = json_text(original)
        payload_hash = hashlib.sha256(original_json.encode()).hexdigest()
        received_at = now_iso()
        with self.database.transaction() as connection:
            existing = connection.execute(
                "SELECT id, payload_sha256 FROM sessions WHERE session_id=? AND device_id=?",
                (payload.session_id, payload.device_id),
            ).fetchone()
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
                return self._session_by_pk(connection, existing["id"]), False

            user_id = self._upsert_user(connection, payload.username, received_at)
            task_dict = original["task"]
            task_id = self._upsert_task(connection, task_dict, received_at)
            metrics = payload.metrics.model_dump(mode="json", exclude_none=False)
            quality = payload.quality.model_dump(mode="json", exclude_none=False)
            scores = payload.scores.model_dump(mode="json", exclude_none=False)
            timing = payload.timing.model_dump(mode="json", exclude_none=False)
            trace = payload.trace.model_dump(mode="json", exclude_none=False)
            cursor = connection.execute(
                """
                INSERT INTO sessions (
                    session_id, device_id, user_id, task_id, schema_version, created_at,
                    started_at, duration_ms, accuracy_score, stability_score, accuracy_band,
                    stability_band, score_version, coverage_pct, completion_time_seconds,
                    mean_dev_mm, max_dev_mm, rms_dev_mm, tremor_rms_deg_s, gyro_rms_deg_s,
                    peak_angular_velocity_deg_s, calibration_valid, quality_warnings_json,
                    task_json, timing_json, scores_json, metrics_json, quality_json, trace_json,
                    percentiles_json, explanation_json, score_definitions_json, artifacts_json,
                    original_payload_json, payload_sha256, received_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    payload.session_id,
                    payload.device_id,
                    user_id,
                    task_id,
                    payload.schema_version,
                    payload.created_at.isoformat().replace("+00:00", "Z"),
                    timing.get("started_at"),
                    timing.get("duration_ms"),
                    scores.get("accuracy"),
                    scores.get("stability"),
                    scores.get("accuracy_band"),
                    scores.get("stability_band"),
                    scores.get("version"),
                    metrics.get("coverage_pct"),
                    metrics.get("completion_time_seconds"),
                    metrics.get("mean_dev_mm"),
                    metrics.get("max_dev_mm"),
                    metrics.get("rms_dev_mm"),
                    metrics.get("tremor_rms_deg_s"),
                    metrics.get("gyro_rms_deg_s"),
                    metrics.get("peak_angular_velocity_deg_s"),
                    None
                    if quality.get("calibration_valid") is None
                    else int(quality["calibration_valid"]),
                    json_text(quality.get("warnings", [])),
                    json_text(task_dict),
                    json_text(timing),
                    json_text(scores),
                    json_text(metrics),
                    json_text(quality),
                    json_text(trace),
                    json_text(original.get("percentiles"))
                    if original.get("percentiles") is not None
                    else None,
                    json_text(original.get("explanation"))
                    if original.get("explanation") is not None
                    else None,
                    json_text(original.get("score_definitions"))
                    if original.get("score_definitions") is not None
                    else None,
                    json_text(original.get("artifacts"))
                    if original.get("artifacts") is not None
                    else None,
                    original_json,
                    payload_hash,
                    received_at,
                ),
            )
            session_pk = cursor.lastrowid
            current = self._session_by_pk(connection, session_pk)
            reference_row = connection.execute(
                """
                SELECT s.id FROM sessions s
                WHERE s.user_id=? AND s.task_id=? AND s.id<>?
                ORDER BY s.created_at DESC, s.id DESC LIMIT 1
                """,
                (user_id, task_id, session_pk),
            ).fetchone()
            reference = (
                self._session_by_pk(connection, reference_row["id"]) if reference_row else None
            )
            if reference:
                result = compare_sessions(reference, current)
                connection.execute(
                    """
                    INSERT INTO deterministic_comparisons
                    (reference_session_pk,current_session_pk,policy_version,compatibility_status,result_json,created_at)
                    VALUES (?,?,?,?,?,?)
                    """,
                    (
                        reference["id"],
                        session_pk,
                        POLICY_VERSION,
                        "compatible" if result["compatible"] else "incompatible",
                        json_text(result),
                        received_at,
                    ),
                )
            connection.execute(
                """
                INSERT INTO model_results
                (session_pk,reference_session_pk,status,adapter,created_at,updated_at)
                VALUES (?,?,?,?,?,?)
                """,
                (
                    session_pk,
                    reference["id"] if reference else None,
                    "pending",
                    "freesolo_http",
                    received_at,
                    received_at,
                ),
            )

        return self.get_session(payload.device_id, payload.session_id), True

    def analyze_session(self, session_pk: int) -> None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT reference_session_pk FROM model_results WHERE session_pk=?",
                (session_pk,),
            ).fetchone()
            if not row:
                return
            current = self._session_by_pk(connection, session_pk)
            reference = (
                self._session_by_pk(connection, row["reference_session_pk"])
                if row["reference_session_pk"] is not None
                else None
            )
        self._save_analysis(session_pk, self.adapter.analyze(reference, current))

    def list_users(self) -> list[dict[str, Any]]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT u.*, COUNT(s.id) session_count, MAX(s.created_at) latest_session_at
                FROM users u LEFT JOIN sessions s ON s.user_id=u.id
                GROUP BY u.id ORDER BY COALESCE(MAX(s.created_at), u.created_at) DESC
                """
            ).fetchall()
            return [dict(row) for row in rows]

    def resolve_user(self, request: UserResolve) -> tuple[dict[str, Any], bool]:
        timestamp = now_iso()
        with self.database.transaction() as connection:
            existing = connection.execute(
                "SELECT id FROM users WHERE username=?", (request.username,)
            ).fetchone()
            if existing:
                user_id = existing["id"]
                created = False
            else:
                user_id = self._upsert_user(connection, request.username, timestamp)
                created = True
        return self.get_user(user_id), created

    def get_user(self, user_id: int) -> dict[str, Any]:
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT u.*, COUNT(s.id) session_count, MAX(s.created_at) latest_session_at
                FROM users u LEFT JOIN sessions s ON s.user_id=u.id
                WHERE u.id=? GROUP BY u.id
                """,
                (user_id,),
            ).fetchone()
            if not row:
                raise HTTPException(404, detail={"code": "user_not_found"})
            return dict(row)

    def update_user(self, user_id: int, update: UserUpdate) -> dict[str, Any]:
        fields = update.model_dump(exclude_unset=True)
        if not fields:
            return self.get_user(user_id)
        fields["updated_at"] = now_iso()
        assignments = ", ".join(f"{name}=?" for name in fields)
        with self.database.transaction() as connection:
            cursor = connection.execute(
                f"UPDATE users SET {assignments} WHERE id=?",  # noqa: S608
                (*fields.values(), user_id),
            )
            if cursor.rowcount == 0:
                raise HTTPException(404, detail={"code": "user_not_found"})
        return self.get_user(user_id)

    def list_sessions(
        self, user_id: int, limit: int = 100, offset: int = 0
    ) -> list[dict[str, Any]]:
        self.get_user(user_id)
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT s.id FROM sessions s WHERE s.user_id=?
                ORDER BY s.created_at DESC, s.id DESC LIMIT ? OFFSET ?
                """,
                (user_id, limit, offset),
            ).fetchall()
            return [self._session_by_pk(connection, row["id"], compact=True) for row in rows]

    def latest(self, user_id: int) -> dict[str, Any]:
        sessions = self.list_sessions(user_id, 1)
        if not sessions:
            raise HTTPException(404, detail={"code": "session_not_found"})
        return self.get_session(sessions[0]["device_id"], sessions[0]["session_id"])

    def get_session(self, device_id: str, session_id: str) -> dict[str, Any]:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT id FROM sessions WHERE device_id=? AND session_id=?",
                (device_id, session_id),
            ).fetchone()
            if not row:
                raise HTTPException(404, detail={"code": "session_not_found"})
            return self._session_by_pk(connection, row["id"])

    def trends(self, user_id: int, limit: int = 50) -> dict[str, Any]:
        sessions = list(reversed(self.list_sessions(user_id, limit)))
        series = []
        for session in sessions:
            series.append(
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
            )
        return {"user_id": user_id, "series": series}

    def compare(
        self,
        reference_device: str,
        reference_session: str,
        current_device: str,
        current_session: str,
    ) -> dict[str, Any]:
        reference = self.get_session(reference_device, reference_session)
        current = self.get_session(current_device, current_session)
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

    def baseline_comparison(
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
            self.get_session(current_device, current_session)
            if current_device and current_session
            else self.latest(user_id)
        )
        if current["user"]["id"] != user_id:
            raise HTTPException(422, detail={"code": "different_users"})
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT id FROM sessions
                WHERE user_id=? AND task_id=(SELECT task_id FROM sessions WHERE id=?)
                  AND id<>? AND created_at<=?
                ORDER BY created_at ASC, id ASC LIMIT 1
                """,
                (user_id, current["id"], current["id"], current["created_at"]),
            ).fetchone()
            if not row:
                raise HTTPException(404, detail={"code": "compatible_baseline_not_found"})
            baseline = self._session_by_pk(connection, row["id"])
        result = compare_sessions(baseline, current)
        return {
            "baseline": baseline,
            "current": current,
            "deterministic_comparison": result,
            "model_prediction": current.get("model_result"),
        }

    def _save_analysis(self, session_pk: int, result: AnalysisResult) -> None:
        with self.database.transaction() as connection:
            connection.execute(
                """
                UPDATE model_results SET status=?,adapter=?,model_version=?,regression_score=?,
                regression_flag=?,confidence=?,overall_pattern=?,result_json=?,error_code=?,
                error_detail=?,updated_at=? WHERE session_pk=?
                """,
                (
                    result.status,
                    result.adapter,
                    result.model_version,
                    result.regression_score,
                    None if result.regression_flag is None else int(result.regression_flag),
                    result.confidence,
                    result.overall_pattern,
                    json_text(result.result) if result.result is not None else None,
                    result.error_code,
                    result.error_detail,
                    now_iso(),
                    session_pk,
                ),
            )

    def _upsert_user(self, connection: sqlite3.Connection, username: str, timestamp: str) -> int:
        connection.execute(
            "INSERT OR IGNORE INTO users(username,created_at,updated_at) VALUES (?,?,?)",
            (username, timestamp, timestamp),
        )
        return connection.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()[
            "id"
        ]

    def _upsert_task(
        self, connection: sqlite3.Connection, task: dict[str, Any], timestamp: str
    ) -> int:
        difficulty = str(task.get("difficulty", "") if task.get("difficulty") is not None else "")
        hand = str(task.get("hand", task.get("dominant_hand", "")) or "")
        connection.execute(
            """
            INSERT OR IGNORE INTO tasks
            (task_type,task_version,difficulty_key,hand_key,metadata_json,created_at)
            VALUES (?,?,?,?,?,?)
            """,
            (task["type"], task["version"], difficulty, hand, json_text(task), timestamp),
        )
        return connection.execute(
            "SELECT id FROM tasks WHERE task_type=? AND task_version=? "
            "AND difficulty_key=? AND hand_key=?",
            (task["type"], task["version"], difficulty, hand),
        ).fetchone()["id"]

    def _session_by_pk(
        self, connection: sqlite3.Connection, session_pk: int, compact: bool = False
    ) -> dict[str, Any]:
        row = connection.execute(
            """
            SELECT s.*, u.username, u.display_name, t.task_type, t.task_version,
                   mr.status model_status, mr.adapter model_adapter, mr.model_version,
                   mr.regression_score, mr.regression_flag, mr.confidence,
                   mr.overall_pattern, mr.result_json model_result_json,
                   mr.error_code model_error_code, mr.error_detail model_error_detail,
                   dc.result_json comparison_json
            FROM sessions s
            JOIN users u ON u.id=s.user_id
            JOIN tasks t ON t.id=s.task_id
            LEFT JOIN model_results mr ON mr.session_pk=s.id
            LEFT JOIN deterministic_comparisons dc ON dc.current_session_pk=s.id
                AND dc.policy_version=?
            WHERE s.id=?
            """,
            (POLICY_VERSION, session_pk),
        ).fetchone()
        if not row:
            raise HTTPException(404, detail={"code": "session_not_found"})
        output = {
            "id": row["id"],
            "session_id": row["session_id"],
            "device_id": row["device_id"],
            "schema_version": row["schema_version"],
            "created_at": row["created_at"],
            "received_at": row["received_at"],
            "user": {
                "id": row["user_id"],
                "username": row["username"],
                "display_name": row["display_name"],
            },
            "task": json_value(row["task_json"], {}),
            "timing": json_value(row["timing_json"], {}),
            "scores": json_value(row["scores_json"], {}),
            "metrics": json_value(row["metrics_json"], {}),
            "quality": json_value(row["quality_json"], {}),
            "model_result": self._model_result(row),
            "deterministic_comparison": json_value(row["comparison_json"]),
        }
        if not compact:
            output.update(
                trace=json_value(row["trace_json"], {}),
                percentiles=json_value(row["percentiles_json"]),
                explanation=json_value(row["explanation_json"]),
                score_definitions=json_value(row["score_definitions_json"]),
                artifacts=json_value(row["artifacts_json"]),
                original_payload=json_value(row["original_payload_json"], {}),
            )
        return output

    @staticmethod
    def _model_result(row: sqlite3.Row) -> dict[str, Any] | None:
        if row["model_status"] is None:
            return None
        return {
            "status": row["model_status"],
            "adapter": row["model_adapter"],
            "model_version": row["model_version"],
            "regression_score": row["regression_score"],
            "regression_flag": None
            if row["regression_flag"] is None
            else bool(row["regression_flag"]),
            "confidence": row["confidence"],
            "overall_pattern": row["overall_pattern"],
            "result": json_value(row["model_result_json"]),
            "error_code": row["model_error_code"],
            "error_detail": row["model_error_detail"],
        }
