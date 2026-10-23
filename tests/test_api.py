from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_and_openapi():
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/openapi.json").status_code == 200


def test_create_and_idempotent_replay():
    key = "test-create-task-001"
    payload = {"title": "Write weekly report", "recurrence": {"frequency": "weekly", "interval": 1}}
    first = client.post("/v1/tasks", json=payload, headers={"Idempotency-Key": key})
    second = client.post("/v1/tasks", json=payload, headers={"Idempotency-Key": key})
    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["id"] == second.json()["id"]


def test_idempotency_conflict():
    key = "test-conflict-001"
    client.post("/v1/tasks", json={"title": "first task"}, headers={"Idempotency-Key": key})
    response = client.post("/v1/tasks", json={"title": "different task"}, headers={"Idempotency-Key": key})
    assert response.status_code == 409


def test_natural_language_fallback():
    response = client.post("/v1/tasks/from-text", json={"text": "Remind me to send report every Friday"})
    assert response.status_code == 201
    assert "report" in response.json()["title"].lower()
    assert response.json()["recurrence"]["frequency"] == "weekly"


def test_breakdown_creates_subtasks():
    response = client.post("/v1/tasks/breakdown", json={"text": "Launch a new website"})
    assert response.status_code == 201
    assert len(response.json()["subtasks"]) >= 3


def test_validation_error_contract():
    response = client.post("/v1/tasks", json={"title": "   "})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
