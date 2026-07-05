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

def scrape_hackernews() -> list[Signal]:
    keywords = get_niche_keywords()
    min_points = get_min_hn_points()
    hits = get_hits_per_source()

    thirty_days_ago = int(time.time()) - 30 * 86400
    signals: list[Signal] = []

    url = "https://hn.algolia.com/api/v1/search_by_date"
    params = {
        "query": keywords.split(",")[0].strip(),
        "tags": "story",
        "numericFilters": f"points>{min_points},created_at_i>{thirty_days_ago}",
        "hitsPerPage": min(hits, 50),
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
        pass

    return signals


# ---------------------------------------------------------------------------
# GitHub — Search Repositories API
# ---------------------------------------------------------------------------

def scrape_github() -> list[Signal]:
    topics = get_github_topics()
    if not topics:
        return []

    min_stars = get_min_github_stars()
    hits = get_hits_per_source()
    token = get_github_token()
    signals: list[Signal] = []

    headers = {"Accept": "application/vnd.github.v3+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    for topic in topics[:3]:
        query = f"topic:{topic} stars:>{min_stars}"
        params = {"q": query, "sort": "stars", "order": "desc", "per_page": min(hits, 20)}
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

def gather_signals() -> list[Signal]:
    reddit_signals = scrape_reddit()
    hn_signals = scrape_hackernews()
    github_signals = scrape_github()
    return reddit_signals + hn_signals + github_signals


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
