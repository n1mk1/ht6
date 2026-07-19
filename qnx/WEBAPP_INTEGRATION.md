# QNX to web application integration

## Boundary

The QNX device is an embedded measurement client. It has no MongoDB driver,
database identifier, Auth0 browser credential, or cloud AI dependency. Its only
external integration is the versioned backend HTTP API:

```text
POST /api/v1/qnx/sessions
Content-Type: application/json
X-Device-Key: <device credential>
```

The browser owns Auth0 login. QNX authenticates as a device through
`X-Device-Key`. For a production pairing flow, the web application should issue
a short-lived pairing code or opaque participant identifier for entry on the
device. Username matching is acceptable for this prototype but is identity
resolution, not secure participant authentication. Auth0 `sub` values stay in
the backend.

## Stable ingestion contract

QNX emits schema `3.0`. Breaking field or meaning changes require a new schema
version such as `3.1`; fields may not be silently redefined inside `3.0`.

Every payload includes:

- stable `device_id` and `session_id`, which do not change during retries;
- `task.type`, `task.version`, `task.difficulty`, and `task.hand`;
- deterministic scores, score version, raw-derived metrics, and warnings;
- a bounded trace for result visualization;
- relative artifact references rather than embedded images or full IMU files;
- AI image-quality and explanation outputs in separate fields from scores.

Hand was added as an optional field already supported by schema `3.0`; it does
not change the meaning of an existing field. The QNX dashboard now requires it
before a run starts. The web application must compare sessions only when type,
version, difficulty, and hand are compatible.

Unmeasurable values remain JSON `null` and receive a quality warning. QNX never
fabricates replacement metrics, and generated explanations cannot change a
score. Payloads contain no MongoDB IDs or database-specific object shapes.

## Idempotency and responses

The backend identity is the pair `(device_id, session_id)`. The immutable
payload content for that identity is replayed on every retry.

| Result | Device action |
|---|---|
| HTTP 200 or 201 | Mark sent; no retry |
| Network error, timeout, HTTP 429, or 5xx | Keep pending and retry with backoff |
| HTTP 401 | Move to terminal queue; fix device credentials and restart QNX |
| HTTP 409 | Move to terminal queue; inspect identity/payload conflict |
| HTTP 422 | Move to terminal queue; fix schema validation |
| Other HTTP response | Move to terminal queue for inspection |

Retry delays are 5, 10, 20, 40, 80, 160, then at most 300 seconds. Upload runs
in a background thread after local persistence, so network failure cannot block
capture, scoring, or session storage. On restart, QNX requeues each 401 failure
once so corrected device credentials can recover without creating a new session.
HTTP 409 and 422 payloads remain terminal because replaying unchanged content
cannot resolve those errors.

## On-device outbox

```text
~/steadyeye/outbox/
  pending/<device_id>__<session_id>.json
  sent/<device_id>__<session_id>.json
  failed/<device_id>__<session_id>.json
  state/<device_id>__<session_id>.json
  latest.json
```

Payload files are immutable. Retry counters, next-attempt timestamps, HTTP
status, and errors live in separate state files. `latest.json` is a convenience
pointer and is not the queue. The dashboard reads `GET /api/outbox/status` to
show local-only, queued, synced, or terminal-failure state.

## Pi configuration

Create `~/steadyeye/device.env` from `device.env.example`:

```bash
BACKEND_URL=http://<backend-lan-ip>:8000
BACKEND_RUNS_PATH=/api/v1/qnx/sessions
BACKEND_KEY=<device-key>
DEVICE_ID=qnx_pi_23
```

`device.env` is excluded from git and `rsync --delete`, while `make server`
loads it on every restart. Never add Auth0, MongoDB, or cloud-model credentials
to this file.

## Integration verification

Before merging the separate web application, verify:

1. First delivery returns 201 and an identical retry returns 200.
2. A temporary backend outage leaves the session in `pending/` and later sends
   the same device/session identity automatically.
3. Bad device keys and invalid payloads become visible terminal entries instead
   of retrying forever.
4. Runs with incompatible task or hand metadata are not compared.
5. Null measurements and quality warnings remain unchanged in storage and UI.
6. The backend resolves the entered participant identity without exposing an
   Auth0 subject or database ID to QNX.
