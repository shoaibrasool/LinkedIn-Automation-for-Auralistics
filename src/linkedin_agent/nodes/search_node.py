from tavily import TavilyClient

from linkedin_agent.config import get_tavily_api_key


def search_node(state: dict) -> dict:
    api_key = get_tavily_api_key()
    client = TavilyClient(api_key=api_key)
    response = client.search(
        query=state["topic"],
        search_depth="advanced",
        max_results=5,
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
    return {"search_results": "\n\n".join(snippets)}
