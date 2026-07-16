from datetime import datetime, timezone

from linkedin_agent.gemini_fallback import create_gemini_llm
from linkedin_agent.prompts.system_prompt import SYSTEM_PROMPT


def draft_node(state: dict, **kwargs) -> dict:
    from langchain_core.messages import HumanMessage, SystemMessage

    progress_callback = kwargs.get("progress_callback")
    retry_count = state.get("retry_count", 0)

    if retry_count > 0:
        msg = f"Rewriting draft (attempt {retry_count + 1})..."
    else:
        msg = "Generating draft with Gemini..."
    if progress_callback:
        progress_callback("drafting", msg, 40)

    llm = create_gemini_llm()

    current_date = datetime.now(timezone.utc).strftime("%B %d, %Y")

    feedback = state.get("authenticity_feedback", "")
    feedback_section = (
        f"\n\n## REVISION FEEDBACK (previous draft was rejected — fix these issues)\n\n{feedback}\n\n"
        f"Rewrite the post. Address every point above. Do NOT repeat the same mistakes."
        if feedback
        else ""
    )

    hook_section = f"\nSUGGESTED HOOK: {state['hook']}" if state.get('hook') else ""
    premise_section = f"\nPOST DIRECTION: {state['premise']}" if state.get('premise') else ""

    messages = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(
            content=(
                f"CURRENT DATE: {current_date}\n\n"
                f"TOPIC: {state['topic']}"
                f"{hook_section}{premise_section}\n\n"
                f"SEARCH CONTEXT:\n{state['search_results']}"
                f"{feedback_section}"
            )
        ),
    ]
    response = llm.invoke(messages)
    content = response.content
    if isinstance(content, list):
        content = "".join(
            part.get("text", "") for part in content if isinstance(part, dict)
        )

    if progress_callback:
        progress_callback("draft_done", "Draft generated", 55)

    return {"draft": content}
