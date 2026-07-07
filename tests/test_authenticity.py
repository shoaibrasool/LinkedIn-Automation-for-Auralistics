from unittest.mock import patch

import pytest

from linkedin_agent.banned_phrases import BANNED_PHRASES
from linkedin_agent.nodes.authenticity_node import (
    _scan_banned_phrases,
    authenticity_node,
)

# ---------------------------------------------------------------------------
# Generic / cliché test posts — should ALL fail
# ---------------------------------------------------------------------------

CLICHE_POST_1 = (
    "In today's fast-paced world, leveraging AI is a game-changer for businesses. "
    "Let's dive into how you can unlock the power of automation to revolutionize your workflow. "
    "The key takeaway is that seamless integration of cutting-edge technology drives transformative results. "
    "I'm excited to announce that we've embraced this paradigm shift and it's been a game changer for our team."
)

CLICHE_POST_2 = (
    "Have you ever wondered about the future of AI? It's no secret that we're in the midst of a digital transformation. "
    "Thought leadership in this space requires thinking outside the box and moving the needle. "
    "At the end of the day, it's about harnessing the power of artificial intelligence to drive actionable insights. "
    "Let's be honest — we all need to embrace AI to stay ahead."
)

CLICHE_POST_3 = (
    "In this day and age, the importance of best-in-class solutions cannot be overstated. "
    "Our results-driven approach has a proven track record of delivering world-class outcomes. "
    "I wanted to take a moment to share some lessons learned on our journey. "
    "The beauty of this transformative technology is that it's truly a paradigm shift for the industry."
)

# ---------------------------------------------------------------------------
# Good / authentic test posts — should PASS
# ---------------------------------------------------------------------------

GOOD_POST_1 = (
    "We spent 3 weeks migrating from OpenAI to BGE embeddings after hitting rate limits on the $0.13/1K tokens tier.\n\n"
    "Not because BGE is better. Because our RAG pipeline was calling the API 400 times per query.\n\n"
    "We were spending $12/day on a demo.\n\n"
    "Switched to BGE-M3 running on a T4 GPU. Cost dropped to $0.40/day. Latency went from 800ms to 1.2s.\n\n"
    "Worth the tradeoff for a prototype.\n\n"
    "What's your most expensive API call? I'll start: ours was embedding a 200-page legal doc every time someone asked a question."
)

GOOD_POST_2 = (
    "A client asked us to build an AI chatbot last month.\n\n"
    "I said no.\n\n"
    "Not because we couldn't. Because their knowledge base was 47 outdated Notion pages with conflicting info.\n\n"
    "We spent 3 weeks cleaning data before writing a line of code. Wrote 12 canonical answers for the top 80% of tickets.\n\n"
    "The chatbot works now because we fixed the input before obsessing over the output.\n\n"
    "When was the last time you audited what your AI actually consumes?"
)

GOOD_POST_3 = (
    "I spent 2 months building a feature nobody asked for.\n\n"
    "Beautiful charts. Real-time updates. Interactive filters.\n\n"
    "The client wanted a CSV export button that works consistently.\n\n"
    "We stripped 80% of the UI and delivered 2 weeks early. Client was thrilled.\n\n"
    "What feature did you over-engineer while the simple thing sat undone?"
)


class TestScanBannedPhrases:
    def test_detects_cliche_openers(self):
        found = _scan_banned_phrases(CLICHE_POST_1)
        assert "in today's fast-paced world" in found
        assert "let's dive into" in found or "let's dive in" in found

    def test_detects_multiple_banned_phrases(self):
        found = _scan_banned_phrases(CLICHE_POST_1)
        assert len(found) >= 4

    def test_no_false_positives_on_clean_text(self):
        found = _scan_banned_phrases(GOOD_POST_1)
        assert len(found) == 0

    def test_case_insensitive_matching(self):
        found = _scan_banned_phrases("IN TODAY'S FAST-PACED WORLD")
        assert len(found) == 1

    def test_partial_phrase_boundaries(self):
        found = _scan_banned_phrases("We need to think about our ROI here.")
        assert any("ROI" in p.upper() for p in found)


class TestAuthenticityNode:
    def test_empty_draft_returns_fail(self):
        result = authenticity_node({
            "draft": "",
            "retry_count": 0,
        })
        assert result["authenticity_result"]["passed"] is False

    def test_missing_draft_returns_fail(self):
        result = authenticity_node({
            "retry_count": 0,
        })
        assert result["authenticity_result"]["passed"] is False

    def test_increments_retry_count_on_fail(self, mocker):
        mock_llm = mocker.patch(
            "langchain_google_genai.ChatGoogleGenerativeAI"
        )
        instance = mock_llm.return_value
        instance.invoke.return_value.content = (
            '{"passed": false, "banned_phrases_found": ["game-changer"], '
            '"has_concrete_detail": false, "concrete_detail_feedback": "no detail", '
            '"sentence_rhythm_ok": false, "sentence_rhythm_feedback": "monotone", '
            '"feedback": "starts with cliche."}'
        )

        result = authenticity_node({
            "draft": "This is a game-changer for our team.",
            "retry_count": 0,
        })
        assert result["retry_count"] == 1
        assert result["authenticity_feedback"] != ""

    def test_flagged_after_two_failures(self, mocker):
        mock_llm = mocker.patch(
            "langchain_google_genai.ChatGoogleGenerativeAI"
        )
        instance = mock_llm.return_value
        instance.invoke.return_value.content = (
            '{"passed": false, "banned_phrases_found": ["game-changer"], '
            '"has_concrete_detail": false, "concrete_detail_feedback": "no detail", '
            '"sentence_rhythm_ok": false, "sentence_rhythm_feedback": "monotone", '
            '"feedback": "starts with cliche."}'
        )

        result = authenticity_node({
            "draft": "This is a game-changer.",
            "retry_count": 1,
        })
        assert result["retry_count"] == 2
        assert result["flagged_for_manual"] is True

    def test_does_not_flag_on_pass(self, mocker):
        mock_llm = mocker.patch(
            "langchain_google_genai.ChatGoogleGenerativeAI"
        )
        instance = mock_llm.return_value
        instance.invoke.return_value.content = (
            '{"passed": true, "banned_phrases_found": [], '
            '"has_concrete_detail": true, "concrete_detail_feedback": "mentions T4 GPU", '
            '"sentence_rhythm_ok": true, "sentence_rhythm_feedback": "varied and natural", '
            '"feedback": "authentic voice, concrete detail, good rhythm."}'
        )

        result = authenticity_node({
            "draft": "We spent 3 weeks migrating to BGE.",
            "retry_count": 0,
        })
        assert result["authenticity_result"]["passed"] is True
        assert result["authenticity_feedback"] == ""
        assert result["flagged_for_manual"] is False

    def test_config_scan_overrides_llm_pass(self, mocker):
        mock_llm = mocker.patch(
            "langchain_google_genai.ChatGoogleGenerativeAI"
        )
        instance = mock_llm.return_value
        instance.invoke.return_value.content = (
            '{"passed": true, "banned_phrases_found": [], '
            '"has_concrete_detail": true, "concrete_detail_feedback": "ok", '
            '"sentence_rhythm_ok": true, "sentence_rhythm_feedback": "fine", '
            '"feedback": "looks good."}'
        )

        result = authenticity_node({
            "draft": "This is a game-changer for our workflow.",
            "retry_count": 0,
        })
        assert result["authenticity_result"]["passed"] is False
        assert "game-changer" in str(result["authenticity_result"]["banned_phrases_found"])


class TestAuthenticityEdgeCases:
    def test_banned_phrases_list_is_populated(self):
        assert len(BANNED_PHRASES) > 20

    def test_all_banned_phrases_are_strings(self):
        for phrase in BANNED_PHRASES:
            assert isinstance(phrase, str)
            assert len(phrase) > 0


class TestGraphIntegration:
    def test_route_after_authenticity_returns_end_on_pass(self):
        from linkedin_agent.graph import route_after_authenticity

        state = {
            "topic": "test",
            "search_results": "",
            "draft": "a draft",
            "authenticity_result": {
                "passed": True,
                "feedback": "looks good",
            },
            "retry_count": 0,
            "flagged_for_manual": False,
            "authenticity_feedback": "",
        }
        assert route_after_authenticity(state) == "end"

    def test_route_after_authenticity_returns_draft_on_fail(self):
        from linkedin_agent.graph import route_after_authenticity

        state = {
            "topic": "test",
            "search_results": "",
            "draft": "a draft",
            "authenticity_result": {
                "passed": False,
                "feedback": "banned phrases found",
            },
            "retry_count": 1,
            "flagged_for_manual": False,
            "authenticity_feedback": "fix this",
        }
        assert route_after_authenticity(state) == "draft"

    def test_route_after_authenticity_returns_end_when_flagged(self):
        from linkedin_agent.graph import route_after_authenticity

        state = {
            "topic": "test",
            "search_results": "",
            "draft": "a draft",
            "authenticity_result": {
                "passed": False,
                "feedback": "banned phrases found",
            },
            "retry_count": 2,
            "flagged_for_manual": True,
            "authenticity_feedback": "fix this",
        }
        assert route_after_authenticity(state) == "end"

    def test_graph_nodes_include_authenticity(self):
        from linkedin_agent.graph import build_graph

        graph = build_graph()
        nodes = list(graph.nodes.keys())
        assert "search" in nodes
        assert "draft" in nodes
        assert "authenticity" in nodes

    def test_graph_state_type(self):
        from linkedin_agent.graph import GraphState

        state: GraphState = {
            "topic": "test",
            "search_results": "",
            "draft": None,
            "authenticity_result": None,
            "retry_count": 0,
            "flagged_for_manual": False,
            "authenticity_feedback": "",
        }
        assert state["retry_count"] == 0
        assert state["flagged_for_manual"] is False
        assert state["authenticity_feedback"] == ""

    def test_draft_node_includes_feedback_on_retry(self, mocker):
        mock_llm = mocker.patch(
            "langchain_google_genai.ChatGoogleGenerativeAI"
        )
        instance = mock_llm.return_value
        instance.invoke.return_value.content = "Rewritten draft."

        from linkedin_agent.nodes.draft_node import draft_node

        result = draft_node({
            "topic": "test topic",
            "search_results": "test search results",
            "authenticity_feedback": "Banned phrase 'game-changer' found. Add a concrete detail.",
        })
        assert result["draft"] == "Rewritten draft."

        call_args = instance.invoke.call_args[0][0]
        human_msg = [m for m in call_args if m.type == "human"][0]
        assert "REVISION FEEDBACK" in human_msg.content
        assert "game-changer" in human_msg.content

    def test_draft_node_no_feedback_on_first_try(self, mocker):
        mock_llm = mocker.patch(
            "langchain_google_genai.ChatGoogleGenerativeAI"
        )
        instance = mock_llm.return_value
        instance.invoke.return_value.content = "First draft."

        from linkedin_agent.nodes.draft_node import draft_node

        result = draft_node({
            "topic": "test topic",
            "search_results": "test search results",
            "authenticity_feedback": "",
        })
        call_args = instance.invoke.call_args[0][0]
        human_msg = [m for m in call_args if m.type == "human"][0]
        assert "REVISION FEEDBACK" not in human_msg.content


class TestAuthenticityDefOfDone:
    def test_cliche_post_1_is_flagged(self, mocker):
        mock_llm = mocker.patch(
            "langchain_google_genai.ChatGoogleGenerativeAI"
        )
        instance = mock_llm.return_value
        instance.invoke.return_value.content = (
            '{"passed": false, "banned_phrases_found": ["in today\'s fast-paced world", "game-changer", "let\'s dive into", "unlock the power of"], '
            '"has_concrete_detail": false, "concrete_detail_feedback": "no numbers, no tools, no real decisions", '
            '"sentence_rhythm_ok": false, "sentence_rhythm_feedback": "all sentences are medium length, no variation", '
            '"feedback": "Opens with worn-out cliche. No concrete detail anywhere. Sentences are uniform length."}'
        )

        result = authenticity_node({
            "draft": CLICHE_POST_1,
            "retry_count": 0,
        })
        assert result["authenticity_result"]["passed"] is False
        assert len(result["authenticity_result"]["banned_phrases_found"]) >= 2

    def test_cliche_post_2_is_flagged(self, mocker):
        mock_llm = mocker.patch(
            "langchain_google_genai.ChatGoogleGenerativeAI"
        )
        instance = mock_llm.return_value
        instance.invoke.return_value.content = (
            '{"passed": false, "banned_phrases_found": ["have you ever wondered", "thought leadership", "think outside the box"], '
            '"has_concrete_detail": false, "concrete_detail_feedback": "pure abstraction, no specifics", '
            '"sentence_rhythm_ok": false, "sentence_rhythm_feedback": "same structure repeating", '
            '"feedback": "Opens with rhetorical question. Every sentence is generic."}'
        )

        result = authenticity_node({
            "draft": CLICHE_POST_2,
            "retry_count": 0,
        })
        assert result["authenticity_result"]["passed"] is False

    def test_cliche_post_3_is_flagged(self, mocker):
        mock_llm = mocker.patch(
            "langchain_google_genai.ChatGoogleGenerativeAI"
        )
        instance = mock_llm.return_value
        instance.invoke.return_value.content = (
            '{"passed": false, "banned_phrases_found": ["in this day and age", "best-in-class", "proven track record"], '
            '"has_concrete_detail": false, "concrete_detail_feedback": "no specifics", '
            '"sentence_rhythm_ok": false, "sentence_rhythm_feedback": "monotone", '
            '"feedback": "Every sentence is a generic claim."}'
        )

        result = authenticity_node({
            "draft": CLICHE_POST_3,
            "retry_count": 0,
        })
        assert result["authenticity_result"]["passed"] is False

    def test_good_post_1_passes(self, mocker):
        mock_llm = mocker.patch(
            "langchain_google_genai.ChatGoogleGenerativeAI"
        )
        instance = mock_llm.return_value
        instance.invoke.return_value.content = (
            '{"passed": true, "banned_phrases_found": [], '
            '"has_concrete_detail": true, "concrete_detail_feedback": "mentions 3 weeks, BGE, OpenAI, $0.13/1K tokens, 400 calls, $12/day, T4 GPU, $0.40/day", '
            '"sentence_rhythm_ok": true, "sentence_rhythm_feedback": "short punchy lines mixed with longer explanatory sentences", '
            '"feedback": "Opens with a specific timeline and tool name. Every claim has a number. Rhythm varies naturally."}'
        )

        result = authenticity_node({
            "draft": GOOD_POST_1,
            "retry_count": 0,
        })
        assert result["authenticity_result"]["passed"] is True

    def test_good_post_2_passes(self, mocker):
        mock_llm = mocker.patch(
            "langchain_google_genai.ChatGoogleGenerativeAI"
        )
        instance = mock_llm.return_value
        instance.invoke.return_value.content = (
            '{"passed": true, "banned_phrases_found": [], '
            '"has_concrete_detail": true, "concrete_detail_feedback": "mentions 47 Notion pages, 12 canonical answers, 80%", '
            '"sentence_rhythm_ok": true, "sentence_rhythm_feedback": "short sentences create tension, longer ones explain", '
            '"feedback": "Personal story anchored in specific numbers. Opens with tension."}'
        )

        result = authenticity_node({
            "draft": GOOD_POST_2,
            "retry_count": 0,
        })
        assert result["authenticity_result"]["passed"] is True

    def test_good_post_3_passes(self, mocker):
        mock_llm = mocker.patch(
            "langchain_google_genai.ChatGoogleGenerativeAI"
        )
        instance = mock_llm.return_value
        instance.invoke.return_value.content = (
            '{"passed": true, "banned_phrases_found": [], '
            '"has_concrete_detail": true, "concrete_detail_feedback": "mentions 2 months, CSV export, 80% UI reduction, 2 weeks early", '
            '"sentence_rhythm_ok": true, "sentence_rhythm_feedback": "short standalone lines contrast with longer detail sentences", '
            '"feedback": "Specific failure story. Concrete numbers throughout. Natural rhythm."}'
        )

        result = authenticity_node({
            "draft": GOOD_POST_3,
            "retry_count": 0,
        })
        assert result["authenticity_result"]["passed"] is True


class TestApiIntegration:
    def test_generate_response_has_authenticity_fields(self):
        from linkedin_agent.api import GenerateResponse

        resp = GenerateResponse(
            draft_id="1",
            draft="test draft",
            authenticity_passed=True,
            flagged_for_manual=False,
            authenticity_feedback="looks good",
        )
        assert resp.draft == "test draft"
        assert resp.authenticity_passed is True
        assert resp.flagged_for_manual is False
        assert resp.authenticity_feedback == "looks good"

    def test_generate_response_defaults_to_false_on_flag(self):
        from linkedin_agent.api import GenerateResponse

        resp = GenerateResponse(
            draft_id="1",
            draft="bad draft",
            authenticity_passed=False,
            flagged_for_manual=True,
            authenticity_feedback="Banned phrase found.",
        )
        assert resp.flagged_for_manual is True
        assert resp.authenticity_passed is False

    @pytest.mark.skip(reason="Requires real API keys — module-level graph build at import time prevents mocking")
    def test_generate_endpoint_returns_authenticity(self, mocker):
        mocker.patch(
            "linkedin_agent.nodes.search_node.TavilyClient"
        )
        mocker.patch(
            "langchain_google_genai.ChatGoogleGenerativeAI"
        )
        mocker.patch(
            "langchain_google_genai.ChatGoogleGenerativeAI"
        )

        from linkedin_agent.api import app
        from fastapi.testclient import TestClient

        client = TestClient(app)
        response = client.post("/generate", json={"topic": "test topic"})
        assert response.status_code == 200
        data = response.json()
        assert "draft" in data
        assert "authenticity_passed" in data
        assert "flagged_for_manual" in data
        assert "authenticity_feedback" in data

    def test_health_still_works(self):
        from linkedin_agent.api import app
        from fastapi.testclient import TestClient

        client = TestClient(app)
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
