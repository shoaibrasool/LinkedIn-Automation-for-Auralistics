"""Tests for the Human Review Queue (Phase 8) endpoints."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from linkedin_agent.api import app

client = TestClient(app)


def _mock_supabase_find(return_value: list | None = None):
    if return_value is None:
        return_value = [
            {
                "id": 1,
                "topic": "Test Topic",
                "content_pillar": "build_in_public",
                "draft_content": "This is a test draft for LinkedIn.",
                "authenticity_passed": True,
                "authenticity_feedback": "",
                "flagged_for_manual": False,
                "status": "ready_for_review",
                "created_at": "2026-07-07T12:00:00+00:00",
                "reviewed_at": None,
            }
        ]
    return return_value


@patch("linkedin_agent.api.SupabaseClient")
def test_get_ready_drafts(mock_supabase):
    instance = mock_supabase.return_value
    instance.find.return_value = _mock_supabase_find()

    resp = client.get("/api/drafts/ready")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["id"] == 1
    assert data[0]["status"] == "ready_for_review"
    instance.find.assert_called_once_with(
        "drafts",
        filter={"status": "ready_for_review"},
        sort=[("created_at", -1)],
        limit=50,
    )


@patch("linkedin_agent.api.SupabaseClient")
def test_get_ready_drafts_empty(mock_supabase):
    instance = mock_supabase.return_value
    instance.find.return_value = []

    resp = client.get("/api/drafts/ready")
    assert resp.status_code == 200
    assert resp.json() == []


@patch("linkedin_agent.api.SupabaseClient")
def test_approve_draft(mock_supabase):
    instance = mock_supabase.return_value
    instance.update_one.return_value = 1

    resp = client.post("/api/drafts/1/approve")
    assert resp.status_code == 200
    assert resp.json() == {"status": "approved"}

    args, kwargs = instance.update_one.call_args
    table = args[0]
    filter_dict = args[1]
    update_dict = args[2]
    assert table == "drafts"
    assert filter_dict == {"id": 1}
    assert update_dict["status"] == "approved"
    assert "reviewed_at" in update_dict


@patch("linkedin_agent.api.SupabaseClient")
def test_approve_draft_not_found(mock_supabase):
    instance = mock_supabase.return_value
    instance.update_one.return_value = 0

    resp = client.post("/api/drafts/999/approve")
    assert resp.status_code == 404


@patch("linkedin_agent.api.SupabaseClient")
def test_edit_draft(mock_supabase):
    instance = mock_supabase.return_value
    instance.update_one.return_value = 1

    new_content = "This is the edited draft content."
    resp = client.post("/api/drafts/1/edit", json={"content": new_content})
    assert resp.status_code == 200
    assert resp.json() == {"status": "edited"}

    args, kwargs = instance.update_one.call_args
    table = args[0]
    filter_dict = args[1]
    update_dict = args[2]
    assert table == "drafts"
    assert filter_dict == {"id": 1}
    assert update_dict["status"] == "edited"
    assert update_dict["draft_content"] == new_content
    assert "reviewed_at" in update_dict


@patch("linkedin_agent.api.SupabaseClient")
def test_edit_draft_not_found(mock_supabase):
    instance = mock_supabase.return_value
    instance.update_one.return_value = 0

    resp = client.post("/api/drafts/999/edit", json={"content": "any"})
    assert resp.status_code == 404


@patch("linkedin_agent.api.SupabaseClient")
def test_reject_draft(mock_supabase):
    instance = mock_supabase.return_value
    instance.update_one.return_value = 1

    resp = client.post("/api/drafts/1/reject")
    assert resp.status_code == 200
    assert resp.json() == {"status": "rejected"}

    args, kwargs = instance.update_one.call_args
    table = args[0]
    filter_dict = args[1]
    update_dict = args[2]
    assert table == "drafts"
    assert filter_dict == {"id": 1}
    assert update_dict["status"] == "rejected"
    assert "reviewed_at" in update_dict


@patch("linkedin_agent.api.SupabaseClient")
def test_reject_draft_not_found(mock_supabase):
    instance = mock_supabase.return_value
    instance.update_one.return_value = 0

    resp = client.post("/api/drafts/999/reject")
    assert resp.status_code == 404


def test_review_page_redirects_to_spa():
    resp = client.get("/review", follow_redirects=False)
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "text/html; charset=utf-8"
    assert "/#review" in resp.text


def test_stats_page_redirects_to_spa():
    resp = client.get("/stats", follow_redirects=False)
    assert resp.status_code == 200
    assert "/#stats" in resp.text


@patch("linkedin_agent.api.build_graph")
def test_generate_persists_draft(mock_build_graph, tmp_path):
    from linkedin_agent.api import GenerateRequest

    mock_graph = MagicMock()
    mock_build_graph.return_value = mock_graph
    mock_graph.invoke.return_value = {
        "draft": "Generated draft content here.",
        "authenticity_result": {"passed": True, "feedback": ""},
        "flagged_for_manual": False,
    }

    with patch("linkedin_agent.api.SupabaseClient") as mock_supabase:
        instance = mock_supabase.return_value
        instance.insert_one.return_value = "42"

        resp = client.post(
            "/generate",
            json={"topic": "Test Topic", "content_pillar": "technical_teardown"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["draft_id"] == "42"
    assert data["draft"] == "Generated draft content here."
    assert data["authenticity_passed"] is True

    # Verify it was saved to drafts table
    args, kwargs = instance.insert_one.call_args
    table = args[0]
    doc = args[1]
    assert table == "drafts"
    assert doc["topic"] == "Test Topic"
    assert doc["content_pillar"] == "technical_teardown"
    assert doc["draft_content"] == "Generated draft content here."
    assert doc["status"] == "ready_for_review"
    assert doc["authenticity_passed"] is True
