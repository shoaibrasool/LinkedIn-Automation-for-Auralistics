import json
import logging

from linkedin_agent.banned_phrases import BANNED_PHRASES, MAX_AUTHENTICITY_RETRIES
from linkedin_agent.gemini_fallback import create_gemini_llm
from linkedin_agent.prompts.authenticity_prompt import AUTHENTICITY_SYSTEM_PROMPT

logger = logging.getLogger(__name__)


def _scan_banned_phrases(draft: str) -> list[str]:
    found: list[str] = []
    draft_lower = draft.lower()
    for phrase in BANNED_PHRASES:
        if phrase.lower() in draft_lower:
            found.append(phrase)
    return found


def _llm_check(draft: str) -> dict:
    from langchain_core.messages import HumanMessage, SystemMessage

    llm = create_gemini_llm()
    messages = [
        SystemMessage(content=AUTHENTICITY_SYSTEM_PROMPT),
        HumanMessage(content=f"Evaluate this LinkedIn draft:\n\n---\n{draft}\n---"),
    ]
    response = llm.invoke(messages)
    raw = response.content
    if isinstance(raw, list):
        raw = "".join(
            part.get("text", "") for part in raw if isinstance(part, dict)
        )
    raw = raw.strip()

    if raw.startswith("```"):
        raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()

    try:
        result = json.loads(raw)
        result.setdefault("banned_phrases_found", [])
        result.setdefault("has_concrete_detail", False)
        result.setdefault("concrete_detail_feedback", "")
        result.setdefault("sentence_rhythm_ok", False)
        result.setdefault("sentence_rhythm_feedback", "")
        result.setdefault("feedback", "")
        result.setdefault("passed", False)
        return result
    except (json.JSONDecodeError, ValueError):
        logger.warning("Failed to parse authenticity LLM response, defaulting to fail")
        return {
            "passed": False,
            "banned_phrases_found": [],
            "has_concrete_detail": False,
            "concrete_detail_feedback": "LLM response was unparseable",
            "sentence_rhythm_ok": False,
            "sentence_rhythm_feedback": "LLM response was unparseable",
            "feedback": "Authenticity check failed — LLM response could not be parsed.",
        }


def authenticity_node(state: dict, **kwargs) -> dict:
    progress_callback = kwargs.get("progress_callback")
    if progress_callback:
        progress_callback("authenticity", "Running authenticity check...", 65)

    draft = state.get("draft", "")
    if isinstance(draft, list):
        draft = "".join(
            part.get("text", "") for part in draft if isinstance(part, dict)
        )
    if not draft:
        result = {
            "passed": False,
            "banned_phrases_found": [],
            "has_concrete_detail": False,
            "concrete_detail_feedback": "No draft content to evaluate",
            "sentence_rhythm_ok": False,
            "sentence_rhythm_feedback": "No draft content to evaluate",
            "feedback": "Draft is empty.",
        }
        if progress_callback:
            progress_callback("authenticity_fail", "Authenticity check failed — empty draft", 70)
        return {
            "authenticity_result": result,
            "authenticity_feedback": result["feedback"],
        }

    config_phrases = _scan_banned_phrases(draft)
    if config_phrases and progress_callback:
        progress_callback("authenticity_scan", f"Found {len(config_phrases)} banned phrases", 68)

    result = _llm_check(draft)

    merged_phrases = list(dict.fromkeys(config_phrases + result.get("banned_phrases_found", [])))
    if merged_phrases:
        result["banned_phrases_found"] = merged_phrases

    if config_phrases and result.get("passed", False):
        result["passed"] = False
        phrase_list = "; ".join(config_phrases[:3])
        extra = f" Config scan found: {phrase_list}."
        if result["feedback"]:
            result["feedback"] += extra
        else:
            result["feedback"] = extra.strip()

    passed = result.get("passed", False)
    retry_count = state.get("retry_count", 0)
    feedback_text = result.get("feedback", "")

    if not passed:
        retry_count += 1

    flagged_for_manual = not passed and retry_count >= MAX_AUTHENTICITY_RETRIES

    if progress_callback:
        if passed:
            progress_callback("authenticity_pass", "Authenticity check passed", 80)
        elif flagged_for_manual:
            progress_callback("authenticity_flag", "Flagged for manual review", 75)
        else:
            progress_callback("authenticity_retry", f"Authenticity failed — retry {retry_count}/{MAX_AUTHENTICITY_RETRIES}", 70)

    return {
        "authenticity_result": result,
        "authenticity_feedback": feedback_text if not passed else "",
        "retry_count": retry_count,
        "flagged_for_manual": flagged_for_manual,
    }
