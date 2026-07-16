from datetime import datetime, timezone

from linkedin_agent.config import get_tavily_api_key


def search_node(state: dict, **kwargs) -> dict:
    from tavily import TavilyClient

    progress_callback = kwargs.get("progress_callback")
    if progress_callback:
        progress_callback("search", "Searching the web for context...", 15)

    api_key = get_tavily_api_key()
    client = TavilyClient(api_key=api_key)

    current_date = datetime.now(timezone.utc).strftime("%B %d, %Y")
    topic = state["topic"]
    hook = state.get("hook", "")
    premise = state.get("premise", "")

    query_parts = [topic]
    if hook:
        query_parts.append(hook)
    if premise:
        query_parts.append(premise)
    query_parts.append(current_date)
    query = " ".join(query_parts)

    try:
        response = client.search(
            query=query,
            search_depth="advanced",
            max_results=6,
            include_answer=True,
        )
        snippets = []
        if answer := response.get("answer"):
            snippets.append(f"Summary: {answer}")
        for result in response.get("results", []):
            content = result.get("content", "")
            url = result.get("url", "")
            if content:
                snippets.append(f"[{url}]: {content}")
    except Exception:
        snippets = ["No search results found."]

    if progress_callback:
        progress_callback("search_done", "Web search complete", 25)

    return {"search_results": "\n\n".join(snippets)}
