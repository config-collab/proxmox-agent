"""
Reddit community integration — search r/Proxmox for relevant Q&A without auto-executing.
Uses Pushshift/Reddit API to find community wisdom on Proxmox topics.

This is READ-ONLY and TRANSPARENT:
- User sees the exact Reddit threads and upvote counts
- No autonomous action based on Reddit replies
- Community knowledge enriches the RAG — user still decides what to do
- Timestamps shown so users know if advice is recent/stale
"""
import json
import urllib.request
import urllib.parse
import time
from typing import Optional


REDDIT_API = "https://api.reddit.com"
SUBREDDIT = "Proxmox"
USER_AGENT = "proxmox-agent/1.0 (asking community questions; not a bot)"


def search(keyword: str, top_k: int = 5, sort: str = "relevance", time_filter: str = "year") -> list[dict]:
    """
    Search r/Proxmox for threads matching keyword.

    sort: "relevance" | "hot" | "top" | "new"
    time_filter: "hour" | "day" | "week" | "month" | "year" | "all"

    Returns list of {id, title, url, author, score, comments, created, body_preview}
    """
    params = {
        "q": f"subreddit:{SUBREDDIT} {keyword}",
        "sort": sort,
        "t": time_filter,
        "limit": min(top_k * 2, 50),
        "type": "link,comment",
    }

    url = f"{REDDIT_API}/search?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
    except Exception as exc:
        return [{"id": "error", "title": f"Reddit search failed", "url": "", "author": "", "score": 0, "comments": 0, "created": "", "body_preview": str(exc)}]

    results = []
    seen_ids = set()

    for item in data.get("data", {}).get("children", []):
        post = item.get("data", {})
        post_id = post.get("id", "")
        if post_id in seen_ids:
            continue
        seen_ids.add(post_id)

        title = post.get("title", "")
        if not title:
            continue

        url = f"https://reddit.com{post.get('permalink', '')}"
        author = post.get("author", "[deleted]")
        score = post.get("score", 0)
        comments = post.get("num_comments", 0)
        created = post.get("created_utc", 0)
        body = post.get("selftext", post.get("title", ""))[:400]

        # Convert unix timestamp to date
        import datetime
        date_str = datetime.datetime.utcfromtimestamp(created).strftime("%Y-%m-%d")

        results.append({
            "id":            post_id,
            "title":         title,
            "url":           url,
            "author":        author,
            "score":         score,
            "comments":      comments,
            "created":       date_str,
            "body_preview":  body,
        })

        if len(results) >= top_k:
            break

    return results


def search_formatted(keyword: str, top_k: int = 5) -> str:
    """Format Reddit search results for LLM consumption."""
    results = search(keyword, top_k)

    if not results or results[0].get("id") == "error":
        return f"Could not search r/Proxmox: {results[0].get('body_preview', 'unknown error')}"

    lines = [f"r/Proxmox community discussions on '{keyword}' (recent {top_k} results):"]
    for r in results:
        score_str = f"↑{r['score']}" if r['score'] > 0 else f"↓{abs(r['score'])}"
        lines.append(
            f"\n**{r['title']}** (by u/{r['author']}, {score_str} | {r['comments']} comments | {r['created']})"
        )
        lines.append(f"  {r['body_preview'][:200]}…")
        lines.append(f"  Link: {r['url']}")

    lines.append("\n---\n*Community knowledge enriches decisions. Always verify with official docs before critical changes.*")
    return "\n".join(lines)


def get_trending(top_k: int = 10) -> list[dict]:
    """Get trending Proxmox topics (top posts from last week)."""
    return search("", top_k=top_k, sort="top", time_filter="week")


def search_formatted_trending(top_k: int = 10) -> str:
    """Format trending r/Proxmox posts."""
    results = get_trending(top_k)
    if not results or results[0].get("id") == "error":
        return "Could not fetch trending Proxmox discussions"

    lines = ["**Trending on r/Proxmox (top posts this week):**"]
    for r in results:
        lines.append(f"↑{r['score']} | **{r['title']}**")
        lines.append(f"  {r['comments']} comments • {r['created']}")

    return "\n".join(lines)
