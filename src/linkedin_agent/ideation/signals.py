import time
import re
from datetime import datetime, timezone
from typing import Any

import requests
from bs4 import BeautifulSoup

from linkedin_agent.config import (
    get_github_token,
    get_github_topics,
    get_hits_per_source,
    get_min_github_stars,
    get_min_hn_points,
    get_min_reddit_comments,
    get_niche_keywords,
    get_reddit_subreddits,
)

Signal = dict[str, Any]
SignalField = tuple[str, str, str, int, str, str]  # platform, title, url, score, content, created_at


def _make_signal(
    platform: str, title: str, url: str, score: int, content: str, created_at: str
) -> Signal:
    return {
        "platform": platform,
        "title": title,
        "url": url,
        "score": score,
        "content": content,
        "created_at": created_at,
    }


# ---------------------------------------------------------------------------
# Reddit — HTML scraping of old.reddit.com (no OAuth required)
# ---------------------------------------------------------------------------

_BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
}


def _parse_comment_count(text: str) -> int:
    match = re.search(r"(\d+)", text or "0")
    return int(match.group(1)) if match else 0


def _fetch_with_backoff(url: str, headers: dict, max_retries: int = 3) -> requests.Response | None:
    for attempt in range(max_retries):
        try:
            resp = requests.get(url, headers=headers, timeout=15)
            if resp.status_code == 200:
                return resp
            if resp.status_code == 429:
                time.sleep(2.0 * (attempt + 1))
                continue
            if resp.status_code == 403:
                time.sleep(3.0)
                continue
        except requests.RequestException:
            time.sleep(2.0 * (attempt + 1))
            continue
    return None


def scrape_reddit() -> list[Signal]:
    subreddits = get_reddit_subreddits()
    if not subreddits:
        return []

    min_comments = get_min_reddit_comments()
    hits = get_hits_per_source()
    signals: list[Signal] = []

    for sub_name in subreddits:
        url = f"https://old.reddit.com/r/{sub_name}/hot/"
        resp = _fetch_with_backoff(url, _BROWSER_HEADERS)
        if resp is None:
            continue

        soup = BeautifulSoup(resp.text, "lxml")
        things = soup.find_all("div", class_="thing")

        for thing in things:
            if "stickied" in thing.get("class", []):
                continue

            title_el = thing.find("a", class_="title")
            if not title_el:
                continue

            title = title_el.text.strip()
            permalink = thing.get("data-permalink", "")
            score = int(thing.get("data-score", 0))
            comments_text = thing.find("a", class_="comments")
            comments = _parse_comment_count(
                comments_text.text.strip() if comments_text else "0"
            )

            if comments < min_comments:
                continue

            signals.append(
                _make_signal(
                    platform="reddit",
                    title=title,
                    url=f"https://old.reddit.com{permalink}",
                    score=score,
                    content=title,
                    created_at=datetime.now(timezone.utc).isoformat(),
                )
            )

            if len(signals) >= hits:
                break

        time.sleep(3.0)

    return signals


# ---------------------------------------------------------------------------
# Hacker News — Algolia Search API (no auth)
# ---------------------------------------------------------------------------

def scrape_hackernews(trending_keywords: str = "") -> list[Signal]:
    keywords = get_niche_keywords()
    min_points = get_min_hn_points()
    hits = get_hits_per_source()

    # Use trending keywords if available, otherwise fall back to static
    if trending_keywords.strip():
        search_terms = [k.strip() for k in trending_keywords.split(",") if k.strip()][:3]
    else:
        search_terms = [keywords.split(",")[0].strip()]

    thirty_days_ago = int(time.time()) - 30 * 86400
    signals: list[Signal] = []

    url = "https://hn.algolia.com/api/v1/search_by_date"
    for term in search_terms:
        params = {
            "query": term,
            "tags": "story",
            "numericFilters": f"points>{min_points},created_at_i>{thirty_days_ago}",
            "hitsPerPage": min(hits, 20),
        }
        try:
            resp = requests.get(url, params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            for hit in data.get("hits", []):
                signals.append(
                    _make_signal(
                        platform="hackernews",
                        title=hit.get("title", ""),
                        url=hit.get("url") or f"https://news.ycombinator.com/item?id={hit.get('objectID', '')}",
                        score=hit.get("points", 0),
                        content=hit.get("story_text", "")[:500] or "",
                        created_at=hit.get("created_at", ""),
                    )
                )
        except requests.RequestException:
            continue

    return signals


# ---------------------------------------------------------------------------
# GitHub — Search Repositories API
# ---------------------------------------------------------------------------

def scrape_github(trending_keywords: str = "") -> list[Signal]:
    topics = get_github_topics()
    hits = get_hits_per_source()
    token = get_github_token()
    signals: list[Signal] = []

    headers = {"Accept": "application/vnd.github.v3+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    # Query 1: Trending repos created this week (fresh repos, any topic)
    one_week_ago = (datetime.now(timezone.utc) - __import__("datetime").timedelta(days=7)).strftime("%Y-%m-%d")
    trending_query = f"created:>={one_week_ago} stars:>50"
    params = {"q": trending_query, "sort": "stars", "order": "desc", "per_page": min(hits, 10)}
    try:
        resp = requests.get(
            "https://api.github.com/search/repositories",
            headers=headers,
            params=params,
            timeout=15,
        )
        if resp.status_code != 403:
            resp.raise_for_status()
            data = resp.json()
            for item in data.get("items", []):
                signals.append(
                    _make_signal(
                        platform="github",
                        title=item.get("full_name", ""),
                        url=item.get("html_url", ""),
                        score=item.get("stargazers_count", 0),
                        content=item.get("description", "") or "",
                        created_at=item.get("created_at", ""),
                    )
                )
    except requests.RequestException:
        pass

    # Query 2: Topic-based search (broadened topics)
    broad_topics = topics + ["developer-tools", "startup", "security", "database", "frontend", "api"]
    for topic in broad_topics[:3]:
        query = f"topic:{topic} stars:>50"
        params = {"q": query, "sort": "stars", "order": "desc", "per_page": min(hits, 10)}
        try:
            resp = requests.get(
                "https://api.github.com/search/repositories",
                headers=headers,
                params=params,
                timeout=15,
            )
            if resp.status_code == 403:
                continue
            resp.raise_for_status()
            data = resp.json()
            for item in data.get("items", []):
                signals.append(
                    _make_signal(
                        platform="github",
                        title=item.get("full_name", ""),
                        url=item.get("html_url", ""),
                        score=item.get("stargazers_count", 0),
                        content=item.get("description", "") or "",
                        created_at=item.get("created_at", ""),
                    )
                )
        except requests.RequestException:
            continue

    return signals


# ---------------------------------------------------------------------------
# Aggregator
# ---------------------------------------------------------------------------

def gather_signals(trending_keywords: str = "") -> list[Signal]:
    reddit_signals = scrape_reddit()
    hn_signals = scrape_hackernews(trending_keywords=trending_keywords)
    github_signals = scrape_github(trending_keywords=trending_keywords)
    return reddit_signals + hn_signals + github_signals


def extract_keywords_from_signals(signals: list[Signal]) -> str:
    """Extract novel keywords from collected signals for broader discovery.

    Pulls key terms from signal titles and content to feed back
    into the trend discovery loop.
    """
    import re as _re
    all_text = " ".join(
        s.get("title", "") + " " + (s.get("content", "") or "")
        for s in signals
    )
    # Find capitalized multi-word phrases (likely project/tool names)
    phrases = _re.findall(r"([A-Z][a-z]+(?:\s+[A-Z]?[a-z0-9]+){0,3})", all_text)
    stop_words = {
        "this", "that", "what", "with", "from", "they", "have", "been",
        "trend", "news", "topic", "week", "today", "just", "about",
        "will", "your", "more", "some", "them", "than", "into", "data",
        "using", "based", "also", "first", "would", "could",
    }
    seen: set[str] = set()
    result: list[str] = []
    for p in phrases:
        clean = p.strip().rstrip(".,!?:;")
        if len(clean) < 4 or clean.lower() in stop_words or clean.lower() in seen:
            continue
        seen.add(clean.lower())
        result.append(clean)
    return ", ".join(result[:15])


def format_signals_for_prompt(signals: list[Signal]) -> str:
    lines = []
    for s in signals:
        lines.append(f"[{s['platform']}] {s['title']} (score: {s['score']})")
        if s["url"]:
            lines.append(f"  URL: {s['url']}")
        if s["content"]:
            lines.append(f"  Content: {s['content'][:300]}")
        lines.append("")
    return "\n".join(lines)
