from unittest.mock import patch

from fastapi.testclient import TestClient

from linkedin_agent.api import app

client = TestClient(app)


def test_root():
    r = client.get("/")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "healthy"


def test_generate_mocked():
    with (
        patch("linkedin_agent.api.build_graph") as mock_build,
    ):
        mock_graph = mock_build.return_value
        mock_graph.invoke.return_value = {"draft": "This is a test draft."}

        r = client.post("/generate", json={"topic": "test topic"})
        assert r.status_code == 200
        data = r.json()
        assert data["topic"] == "test topic"
        assert data["draft"] == "This is a test draft."


def test_generate_missing_topic():
    r = client.post("/generate", json={})
    assert r.status_code == 422


def test_generate_no_draft():
    with (
        patch("linkedin_agent.api.build_graph") as mock_build,
    ):
        mock_graph = mock_build.return_value
        mock_graph.invoke.return_value = {"draft": None}

        r = client.post("/generate", json={"topic": "test"})
        assert r.status_code == 500
