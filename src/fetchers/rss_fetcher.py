from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import feedparser


def fetch_rss(config: list[dict[str, str]]) -> list[dict[str, Any]]:
    """抓取 RSS 源。"""
    papers: list[dict[str, Any]] = []

    for feed in config or []:
        url = feed.get("url", "")
        name = feed.get("name", "rss")
        topic = feed.get("topic", "General")
        if not url:
            continue

        try:
            parsed = feedparser.parse(url)
            for item in parsed.entries[:30]:
                entry_id = item.get("id") or item.get("link") or f"{name}-{item.get('title', '')}"
                published = item.get("published", "") or item.get("updated", "")
                published_date = datetime.utcnow().date().isoformat()
                if published:
                    try:
                        published_date = datetime(*item.published_parsed[:6]).date().isoformat()
                    except Exception:
                        pass

                summary = item.get("summary", "")
                title = item.get("title", "").strip()

                papers.append(
                    {
                        "id": f"RSS:{entry_id}",
                        "title": title,
                        "abstract": summary,
                        "authors": [],
                        "source": "rss",
                        "topic": topic,
                        "published_date": published_date,
                        "url": item.get("link", ""),
                        "affiliation": name,
                    }
                )
        except Exception as exc:
            logging.exception("RSS 抓取失败 (%s): %s", name, exc)

    return papers
