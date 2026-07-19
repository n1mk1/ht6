"""Host-side tests for the QNX immutable session outbox."""
import json
import os
import sys
import tempfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

from server import server  # noqa: E402

FAIL = 0


def check(condition, message):
    global FAIL
    if not condition:
        print(f"  FAIL: {message}")
        FAIL += 1


class OutboxSandbox:
    def __enter__(self):
        self.temp = tempfile.TemporaryDirectory()
        self.saved = {name: getattr(server, name) for name in (
            "OUTBOX", "OUTBOX_PENDING", "OUTBOX_SENT", "OUTBOX_FAILED",
            "OUTBOX_STATE", "BACKEND_URL", "BACKEND_RUNS_PATH")}
        server.OUTBOX = self.temp.name
        server.OUTBOX_PENDING = os.path.join(self.temp.name, "pending")
        server.OUTBOX_SENT = os.path.join(self.temp.name, "sent")
        server.OUTBOX_FAILED = os.path.join(self.temp.name, "failed")
        server.OUTBOX_STATE = os.path.join(self.temp.name, "state")
        for folder in (server.OUTBOX_PENDING, server.OUTBOX_SENT,
                       server.OUTBOX_FAILED, server.OUTBOX_STATE):
            os.makedirs(folder)
        server.BACKEND_URL = ""
        server.BACKEND_RUNS_PATH = "/api/v1/qnx/sessions"
        return self

    def __exit__(self, *_args):
        for name, value in self.saved.items():
            setattr(server, name, value)
        self.temp.cleanup()


def payload(session_id="session_test"):
    return {"schema_version": "3.0", "device_id": "qnx_pi_23",
            "session_id": session_id, "task": {"type": "path_tracing",
            "version": "mat_v1", "difficulty": 1, "hand": "right"}}


def test_policy_and_backoff():
    check(server.BACKEND_RUNS_PATH.startswith("/api/v1/"),
          "default ingestion endpoint is versioned v1")
    check(server._upload_policy(200) == "success", "200 is success")
    check(server._upload_policy(201) == "success", "201 is success")
    for status in (401, 409, 422):
        check(server._upload_policy(status) == "terminal",
              f"{status} is terminal")
    for status in (429, 500, 503):
        check(server._upload_policy(status) == "retry", f"{status} retries")
    check(server._upload_policy(None, network_error=True) == "retry",
          "network failure retries")
    check([server._backoff_seconds(i) for i in range(1, 9)] ==
          [5, 10, 20, 40, 80, 160, 300, 300], "backoff is bounded")


def test_payload_is_immutable():
    with OutboxSandbox():
        original = payload()
        status = server.enqueue_session(original)
        check(status["queued"] is True, "new payload is queued")
        key = server._queue_key(original)
        path = os.path.join(server.OUTBOX_PENDING, key + ".json")
        changed = payload()
        changed["task"]["hand"] = "left"
        server.enqueue_session(changed)
        with open(path) as source:
            stored = json.load(source)
        check(stored == original, "same identity cannot overwrite queued payload")


def test_retry_success_and_terminal():
    with OutboxSandbox():
        server.BACKEND_URL = "http://backend.test"
        first = payload("session_retry")
        server.enqueue_session(first)
        calls = []
        original_upload = server._upload_payload
        try:
            server._upload_payload = lambda item: (calls.append(item) or (503, "http_503"))
            server.process_outbox_once(now=100)
            key = server._queue_key(first)
            state = server._outbox_state(key)
            check(state["attempts"] == 1 and state["next_attempt_at"] == 105,
                  "retry records attempt and next time")
            server.process_outbox_once(now=104)
            check(len(calls) == 1, "backoff prevents early retry")
            server._upload_payload = lambda _item: (201, None)
            server.process_outbox_once(now=105)
            check(os.path.exists(os.path.join(server.OUTBOX_SENT, key + ".json")),
                  "201 moves immutable payload to sent")

            auth = payload("session_auth")
            server.enqueue_session(auth)
            server._upload_payload = lambda _item: (401, "http_401")
            server.process_outbox_once(now=106)
            auth_key = server._queue_key(auth)
            check(os.path.exists(os.path.join(
                server.OUTBOX_FAILED, auth_key + ".json")),
                "401 moves payload to terminal queue")
            check(server.requeue_auth_failures() == 1,
                  "server restart requeues an auth failure once")
            check(os.path.exists(os.path.join(
                server.OUTBOX_PENDING, auth_key + ".json")),
                "requeued auth payload returns to pending")
            server._upload_payload = lambda _item: (200, None)
            server.process_outbox_once(now=107)
            check(os.path.exists(os.path.join(
                server.OUTBOX_SENT, auth_key + ".json")),
                "requeued auth payload can succeed after remediation")

            rejected = payload("session_rejected")
            server.enqueue_session(rejected)
            server._upload_payload = lambda _item: (422, "http_422")
            server.process_outbox_once(now=200)
            rejected_key = server._queue_key(rejected)
            check(os.path.exists(os.path.join(
                server.OUTBOX_FAILED, rejected_key + ".json")),
                "422 moves payload to terminal queue")
        finally:
            server._upload_payload = original_upload


def test_imu_evidence_gate():
    one = [{"t": 1, "gx": 2.0, "gy": 0.0, "gz": 0.0}]
    metrics = server.imu_stability(one)
    check(metrics["gyro_rms_deg_s"] == 2.0,
          "insufficient IMU still preserves raw gyro RMS")
    check(metrics["tremor_rms_deg_s"] is None,
          "one IMU sample cannot produce tremor")
    check(server.praxis_score.stability_score(metrics["tremor_rms_deg_s"]) is None,
          "one IMU sample cannot produce a stability score")

    enough = [{"t": i * 10_000_000, "gx": 2.0, "gy": 0.0, "gz": 0.0}
              for i in range(101)]
    check(server.imu_evidence(enough)["sufficient"] is True,
          "one second of 100 Hz IMU evidence is sufficient")
    check(server.imu_stability(enough)["tremor_rms_deg_s"] == 0.0,
          "sufficient steady IMU evidence can produce zero tremor")


def test_compute_metrics_quality_gates():
    with tempfile.TemporaryDirectory() as directory:
        score_path = os.path.join(directory, "score.json")
        with open(score_path, "w") as target:
            json.dump({"ok": True, "frame": [100, 100], "coverage_pct": 20.0,
                       "n_ref_slices": 10, "n_scored_slices": 2,
                       "reference": [[0, 10], [20, 10]],
                       "red": [[0, 10], [20, 10]], "mean_dev_px": 0.0}, target)
        with open(os.path.join(directory, "imu.jsonl"), "w") as target:
            target.write(json.dumps({"t": 1, "valid": True, "gx": 2.0,
                                     "gy": 0.0, "gz": 0.0}) + "\n")
        old_calibration = server.S["imu_cal"]
        try:
            server.S["imu_cal"] = {"ok": True}
            metrics, quality = server.compute_metrics(directory, 0, 1_000_000_000)
        finally:
            server.S["imu_cal"] = old_calibration
        check(metrics["mean_dev_mm"] == 0.0,
              "low coverage preserves raw deviation")
        check(metrics["accuracy_score"] is None,
              "low coverage produces null accuracy")
        check(metrics["gyro_rms_deg_s"] == 2.0,
              "insufficient IMU preserves raw gyro metric")
        check(metrics["tremor_rms_deg_s"] is None and
              metrics["stability_score"] is None,
              "insufficient IMU produces null tremor and stability")
        check("insufficient_trace_coverage" in quality["warnings"],
              "low coverage warning is emitted")
        check("insufficient_imu_evidence" in quality["warnings"],
              "insufficient IMU warning is emitted")


if __name__ == "__main__":
    print("running outbox tests...")
    test_policy_and_backoff()
    test_payload_is_immutable()
    test_retry_success_and_terminal()
    test_imu_evidence_gate()
    test_compute_metrics_quality_gates()
    if FAIL == 0:
        print("ALL TESTS PASSED")
    else:
        print(f"{FAIL} CHECK(S) FAILED")
    sys.exit(1 if FAIL else 0)
