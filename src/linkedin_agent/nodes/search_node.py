from datetime import datetime, timezone

from linkedin_agent.config import get_tavily_api_key


def search_node(state: dict) -> dict:
    from tavily import TavilyClient

    api_key = get_tavily_api_key()
    client = TavilyClient(api_key=api_key)

    current_date = datetime.now(timezone.utc).strftime("%B %d, %Y")
    topic = state["topic"]
    hook = state.get("hook", "")
    premise = state.get("premise", "")

    # Build a richer query combining topic + hook + premise, with date for freshness
    query_parts = [topic]
    if hook:
        query_parts.append(hook)
    if premise:
        query_parts.append(premise)
    query_parts.append(current_date)
    query = " ".join(query_parts)

    # Search twice: once for the specific topic, once for broader trends
    all_snippets = []
    for search_query, results_count in [(query, 5), (f"latest news {topic}", 3)]:
        try:
            response = client.search(
                query=search_query,
                search_depth="advanced",
                max_results=results_count,
                include_answer=True,
            )
            if answer := response.get("answer"):
                all_snippets.append(f"Summary: {answer}")
            for result in response.get("results", []):
                content = result.get("content", "")
                url = result.get("url", "")
                if content:
                    all_snippets.append(f"[{url}]: {content}")
        except Exception:
            continue

    return {"search_results": "\n\n".join(all_snippets)}
