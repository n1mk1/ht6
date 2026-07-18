from dataclasses import dataclass
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

from bson import ObjectId
from fastapi.testclient import TestClient

from atlas_gemini_api.config import Settings
from atlas_gemini_api.dependencies import get_gemini_client, get_notes_collection, require_user
from atlas_gemini_api.main import create_app

TEST_USER = {"sub": "auth0|test-user", "scope": "openid profile"}


def make_test_app():
    settings = Settings(
        _env_file=None,
        app_env="test",
        frontend_origins="http://localhost:3000",
        mongodb_uri=None,
        auth0_domain=None,
        auth0_audience=None,
        gemini_api_key=None,
    )
    return create_app(settings)


def test_health_describes_unconfigured_integrations() -> None:
    app = make_test_app()
    with TestClient(app) as client:
        response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["integrations"] == {
        "auth0": False,
        "mongodb": False,
        "gemini": False,
    }


def test_protected_route_fails_closed_without_auth0() -> None:
    app = make_test_app()
    with TestClient(app) as client:
        response = client.get("/api/me")

    assert response.status_code == 503
    assert "Auth0 is not configured" in response.json()["detail"]


class FakeCursor:
    def __init__(self, documents: list[dict[str, Any]]) -> None:
        self.documents = documents

    def sort(self, _field: str, _direction: int) -> "FakeCursor":
        self.documents.sort(key=lambda item: item["created_at"], reverse=True)
        return self

    def limit(self, count: int) -> "FakeCursor":
        self.documents = self.documents[:count]
        return self

    async def to_list(self, length: int) -> list[dict[str, Any]]:
        return self.documents[:length]


@dataclass
class DeleteResult:
    deleted_count: int


class FakeCollection:
    def __init__(self) -> None:
        self.documents: list[dict[str, Any]] = []

    async def insert_one(self, document: dict[str, Any]) -> Any:
        inserted_id = ObjectId()
        self.documents.append({**document, "_id": inserted_id})
        return SimpleNamespace(inserted_id=inserted_id)

    def find(self, query: dict[str, Any]) -> FakeCursor:
        return FakeCursor(
            [item.copy() for item in self.documents if item["owner_sub"] == query["owner_sub"]]
        )

    async def delete_one(self, query: dict[str, Any]) -> DeleteResult:
        before = len(self.documents)
        self.documents = [
            item
            for item in self.documents
            if not (item["_id"] == query["_id"] and item["owner_sub"] == query["owner_sub"])
        ]
        return DeleteResult(deleted_count=before - len(self.documents))


async def fake_user() -> dict[str, Any]:
    return TEST_USER


def test_note_crud_is_scoped_to_the_authenticated_user() -> None:
    app = make_test_app()
    collection = FakeCollection()
    app.dependency_overrides[require_user] = fake_user
    app.dependency_overrides[get_notes_collection] = lambda: collection

    with TestClient(app) as client:
        created = client.post("/api/notes", json={"title": "Ship it", "content": "Run the checks"})
        listed = client.get("/api/notes")
        deleted = client.delete(f"/api/notes/{created.json()['id']}")

    assert created.status_code == 201
    assert datetime.fromisoformat(created.json()["created_at"]).tzinfo == UTC
    assert [note["title"] for note in listed.json()] == ["Ship it"]
    assert deleted.status_code == 204


class FakeInteractions:
    async def create(self, **_kwargs: Any) -> Any:
        return SimpleNamespace(output_text="A concise Gemini response.")


class FakeGemini:
    def __init__(self) -> None:
        self.aio = SimpleNamespace(interactions=FakeInteractions())


def test_gemini_route_returns_the_model_response() -> None:
    app = make_test_app()
    app.dependency_overrides[require_user] = fake_user
    app.dependency_overrides[get_gemini_client] = lambda: FakeGemini()

    with TestClient(app) as client:
        response = client.post("/api/ai/generate", json={"prompt": "Give me a launch checklist"})

    assert response.status_code == 200
    assert response.json() == {"text": "A concise Gemini response.", "model": "gemini-3.5-flash"}
