from linkedin_agent.gemini_fallback import create_gemini_llm
from linkedin_agent.prompts.system_prompt import SYSTEM_PROMPT


def draft_node(state: dict) -> dict:
    from langchain_core.messages import HumanMessage, SystemMessage

    llm = create_gemini_llm()

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
    return {"draft": content}
