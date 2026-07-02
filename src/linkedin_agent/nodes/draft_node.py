from langchain_core.messages import HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI

from linkedin_agent.config import get_gemini_api_key
from linkedin_agent.prompts.system_prompt import SYSTEM_PROMPT


def draft_node(state: dict) -> dict:
    llm = ChatGoogleGenerativeAI(
        model="gemini-2.5-flash",
        api_key=get_gemini_api_key(),
        temperature=0.9,
    )
    messages = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(
            content=f"TOPIC: {state['topic']}\n\nSEARCH CONTEXT:\n{state['search_results']}"
        ),
    ]
    response = llm.invoke(messages)
    return {"draft": response.content}
