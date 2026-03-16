from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import arxiv


def fetch_arxiv(config: dict[str, Any]) -> list[dict[str, Any]]:
    """抓取近 N 天 arXiv 论文。"""
    query = config.get("query", "medical imaging")
    max_results = int(config.get("max_results", 50))
    lookback_days = int(config.get("date_range_days", 2))
    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)

    search = arxiv.Search(
        query=query,
        max_results=max_results,
        sort_by=arxiv.SortCriterion.SubmittedDate,
    )

    papers: list[dict[str, Any]] = []
    try:
        client = arxiv.Client(page_size=min(100, max_results), delay_seconds=2.5, num_retries=3)
        for result in client.results(search):
            published = result.published
            if published.tzinfo is None:
                published = published.replace(tzinfo=timezone.utc)
            if published < cutoff:
                continue

            papers.append(
                {
                    "id": result.get_short_id(),
                    "title": (result.title or "").strip(),
                    "abstract": (result.summary or "").strip().replace("\n", " "),
                    "authors": [a.name for a in result.authors],
                    "source": "arxiv",
                    "published_date": published.date().isoformat(),
                    "url": result.entry_id,
                    "affiliation": "",
                }
            )
    except Exception as exc:
        logging.exception("arXiv 抓取失败: %s", exc)

    return papers
