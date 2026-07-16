from linkedin_agent.config import get_gemini_api_key
from linkedin_agent.prompts.system_prompt import SYSTEM_PROMPT


def draft_node(state: dict) -> dict:
    from langchain_core.messages import HumanMessage, SystemMessage
    from langchain_google_genai import ChatGoogleGenerativeAI

    llm = ChatGoogleGenerativeAI(
        model="gemini-3.5-flash",
        api_key=get_gemini_api_key(),
        timeout=30,
    )

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
