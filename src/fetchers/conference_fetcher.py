from __future__ import annotations

import logging
import os
import time
from datetime import datetime
from typing import Any, cast

import feedparser
import requests


DEFAULT_VENUES = [
    "NeurIPS",
    "ICLR",
    "CVPR",
    "ECCV",
    "ICCV",
    "AAAI",
    "MICCAI",
    "MIDL",
    "ACM MM",
]

DEFAULT_TOPIC_QUERIES = {
    "agent": "medical AI agent LLM clinical autonomous diagnosis",
    "imaging": "medical image generation synthesis diffusion GAN",
    "recon": "medical image super resolution reconstruction MRI CT denoising",
}

DEFAULT_TOPIC_KEYWORDS = {
    "agent": ["agent", "llm", "clinical", "diagnosis", "medical ai"],
    "imaging": ["medical image", "synthesis", "generation", "diffusion", "gan"],
    "recon": ["super resolution", "reconstruction", "denoising", "restoration", "mri", "ct"],
}

DEFAULT_RELAXED_MEDICAL_KEYWORDS = [
    "medical",
    "clinical",
    "mri",
    "ct",
    "ultrasound",
    "radiology",
    "image",
]

DEFAULT_OPENREVIEW_INVITATIONS = {
    "agent": [
        "ICLR.cc/2025/Conference/-/Submission",
        "NeurIPS.cc/2025/Conference/-/Submission",
        "AAAI.org/AAAI/2025/Conference/-/Submission",
    ],
    "imaging": [
        "MICCAI.org/2025/Conference/-/Submission",
        "MIDL.io/2025/Conference/-/Submission",
        "CVPR.cc/2025/Conference/-/Submission",
    ],
    "recon": [
        "MICCAI.org/2025/Conference/-/Submission",
        "MIDL.io/2025/Conference/-/Submission",
        "ICCV.cc/2025/Conference/-/Submission",
    ],
}


def _extract_or_value(content: dict[str, Any], key: str, default: Any) -> Any:
    v = content.get(key, default)
    if isinstance(v, dict) and "value" in v:
        return v.get("value", default)
    return v if v is not None else default


def _fallback_openreview_api(
    topic: str,
    limit: int,
    invitations_map: dict[str, list[str]],
    keywords_map: dict[str, list[str]],
    username: str,
    password: str,
) -> list[dict[str, Any]]:
    try:
        import openreview
    except Exception:
        return []

    kwargs: dict[str, Any] = {"baseurl": "https://api2.openreview.net"}
    if username and password:
        kwargs["username"] = username
        kwargs["password"] = password

    api_mod: Any = getattr(openreview, "api", openreview)
    client: Any = api_mod.OpenReviewClient(**kwargs)
    invitations = invitations_map.get(topic, [])
    keywords = [k.lower() for k in keywords_map.get(topic, [])]

    items: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    def _append_note(note: Any, affiliation: str) -> None:
        content = getattr(note, "content", {}) or {}
        title = str(_extract_or_value(content, "title", "") or "").strip()
        abstract = str(_extract_or_value(content, "abstract", "") or "").strip()
        text = f"{title} {abstract}".lower()
        if keywords and not any(k in text for k in keywords):
            return

        authors = _extract_or_value(content, "authors", [])
        if not isinstance(authors, list):
            authors = []

        note_id = getattr(note, "id", "") or f"{affiliation}:{title[:30]}"
        if note_id in seen_ids:
            return

        pdf = str(_extract_or_value(content, "pdf", "") or "")
        if pdf and pdf.startswith("/"):
            url = f"https://openreview.net{pdf}"
        else:
            url = f"https://openreview.net/forum?id={note_id}"

        items.append(
            {
                "id": f"ORAPI:{note_id}",
                "title": title,
                "abstract": abstract,
                "authors": [str(a) for a in authors if a],
                "source": "conference:openreview-api",
                "topic": topic,
                "published_date": datetime.utcnow().date().isoformat(),
                "url": url,
                "affiliation": affiliation,
            }
        )
        seen_ids.add(note_id)

    for invitation in invitations:
        try:
            notes = client.get_all_notes(invitation=invitation)
        except Exception as exc:
            logging.warning("OpenReview API 抓取失败 invitation=%s: %s", invitation, exc)
            continue
        for note in notes:
            _append_note(note, invitation)
            if len(items) >= limit:
                return items

    # invitation 未命中时，使用 search_notes 兜底
    if len(items) < limit:
        search_terms: list[str] = []
        if keywords:
            search_terms.extend([str(k) for k in keywords[:4]])
        if topic == "agent":
            search_terms.extend(["medical llm", "clinical agent"])
        elif topic == "imaging":
            search_terms.extend(["medical imaging", "image synthesis"])
        elif topic == "recon":
            search_terms.extend(["super resolution", "image reconstruction"])

        for term in search_terms:
            term = term.strip()
            if not term:
                continue
            try:
                notes = cast(list[Any], client.search_notes(term=term, content="all", limit=20))
            except Exception as exc:
                logging.warning("OpenReview API 搜索失败 term=%s: %s", term, exc)
                continue
            for note in notes:
                _append_note(note, f"search:{term}")
                if len(items) >= limit:
                    return items

    return items


def _fallback_openreview(topic: str, limit: int, url: str, keywords_map: dict[str, list[str]]) -> list[dict[str, Any]]:
    parsed = feedparser.parse(url)
    strict_items: list[dict[str, Any]] = []
    relaxed_items: list[dict[str, Any]] = []
    backup_items: list[dict[str, Any]] = []
    keywords = [k.lower() for k in keywords_map.get(topic, [])]
    relaxed_keywords = DEFAULT_RELAXED_MEDICAL_KEYWORDS

    def _build_item(entry: Any, title: str, summary: str) -> dict[str, Any]:
        link = entry.get("link") or ""
        entry_id = entry.get("id") or link or title
        published_date = datetime.utcnow().date().isoformat()
        if getattr(entry, "published_parsed", None):
            try:
                published_date = datetime(*entry.published_parsed[:6]).date().isoformat()
            except Exception:
                pass
        return {
            "id": f"OR:{entry_id}",
            "title": title,
            "abstract": summary,
            "authors": [],
            "source": "conference:openreview",
            "topic": topic,
            "published_date": published_date,
            "url": link,
            "affiliation": "OpenReview",
        }

    for entry in parsed.entries[:200]:
        title = str(entry.get("title") or "").strip()
        summary = str(entry.get("summary") or "").strip()
        if not title:
            continue
        text = f"{title} {summary}".lower()
        item = _build_item(entry, title, summary)

        if keywords and any(k in text for k in keywords):
            strict_items.append(item)
        elif any(k in text for k in relaxed_keywords):
            relaxed_items.append(item)
        elif len(summary) >= 80:
            backup_items.append(item)

        if len(strict_items) >= limit:
            return strict_items[:limit]

    items = strict_items + relaxed_items + backup_items
    seen_ids: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for it in items:
        pid = str(it.get("id", ""))
        if not pid or pid in seen_ids:
            continue
        deduped.append(it)
        seen_ids.add(pid)
        if len(deduped) >= limit:
            break

    return deduped


def fetch_conference_papers(config: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    cfg = config or {}
    if cfg.get("enabled", True) is False:
        return []

    base_url = "https://api.semanticscholar.org/graph/v1/paper/search"
    fields = "paperId,title,abstract,authors,year,venue,externalIds"
    limit = int(cfg.get("max_results_per_topic", 20))
    venues = cfg.get("venues", DEFAULT_VENUES)
    topic_queries = cfg.get("topic_queries", DEFAULT_TOPIC_QUERIES)
    fallback_openreview_url = str(cfg.get("fallback_openreview_url", "https://openreview.net/rss")).strip()
    fallback_keywords = cfg.get("fallback_topic_keywords", DEFAULT_TOPIC_KEYWORDS)
    openreview_api_enabled = bool(cfg.get("openreview_api_enabled", True))
    openreview_invitations = cfg.get("openreview_invitations", DEFAULT_OPENREVIEW_INVITATIONS)
    or_use_auth = str(os.getenv("OPENREVIEW_USE_AUTH", "false")).lower() == "true"
    or_username = os.getenv("OPENREVIEW_USERNAME", "").strip() if or_use_auth else ""
    or_password = os.getenv("OPENREVIEW_PASSWORD", "").strip() if or_use_auth else ""

    papers: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    for topic, query in topic_queries.items():
        need_fallback = False
        try:
            resp = requests.get(
                base_url,
                params={
                    "query": query,
                    "fields": fields,
                    "limit": limit,
                    "publicationTypes": "JournalArticle,Conference",
                },
                timeout=20,
            )
            resp.raise_for_status()
            data = resp.json().get("data", [])
            if not data:
                need_fallback = True

            for item in data:
                venue = (item.get("venue") or "").strip()
                if venue and not any(v.lower() in venue.lower() for v in venues):
                    continue

                external_ids = item.get("externalIds", {}) or {}
                pid = external_ids.get("ArXiv") or external_ids.get("DOI") or item.get("paperId")
                if not pid:
                    continue

                if external_ids.get("ArXiv"):
                    url = f"https://arxiv.org/abs/{external_ids['ArXiv']}"
                else:
                    url = f"https://www.semanticscholar.org/paper/{item.get('paperId', '')}"

                record = (
                    {
                        "id": f"SS:{pid}",
                        "title": (item.get("title") or "").strip(),
                        "abstract": (item.get("abstract") or "").strip(),
                        "authors": [a.get("name", "") for a in item.get("authors", []) if a.get("name")],
                        "source": f"conference:{venue}" if venue else "conference",
                        "topic": str(topic),
                        "published_date": str(item.get("year") or datetime.utcnow().date().isoformat()),
                        "url": url,
                        "affiliation": venue,
                    }
                )
                if record["id"] in seen_ids:
                    continue
                papers.append(record)
                seen_ids.add(record["id"])
            time.sleep(1.0)
        except Exception as exc:
            logging.warning("Conference 抓取失败 topic=%s: %s", topic, exc)
            need_fallback = True

        if need_fallback:
            if openreview_api_enabled:
                try:
                    api_items = _fallback_openreview_api(
                        topic,
                        limit=limit,
                        invitations_map=openreview_invitations,
                        keywords_map=fallback_keywords,
                        username=or_username,
                        password=or_password,
                    )
                    for item in api_items:
                        if item["id"] in seen_ids:
                            continue
                        papers.append(item)
                        seen_ids.add(item["id"])
                    if api_items:
                        logging.info("Conference fallback 生效 topic=%s source=openreview-api count=%s", topic, len(api_items))
                        need_fallback = False
                except Exception as exc:
                    logging.warning("Conference OpenReview API fallback 失败 topic=%s: %s", topic, exc)

        if need_fallback:
            try:
                fallback_items = _fallback_openreview(topic, limit=limit, url=fallback_openreview_url, keywords_map=fallback_keywords)
                for item in fallback_items:
                    if item["id"] in seen_ids:
                        continue
                    papers.append(item)
                    seen_ids.add(item["id"])
                if fallback_items:
                    logging.info("Conference fallback 生效 topic=%s source=openreview count=%s", topic, len(fallback_items))
            except Exception as exc:
                logging.warning("Conference fallback 失败 topic=%s: %s", topic, exc)

    return papers
