from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta
from typing import Any

from Bio import Entrez, Medline


def _extract_doi(entry: dict[str, Any]) -> str:
    aids = entry.get("AID", [])
    if isinstance(aids, str):
        aids = [aids]
    for aid in aids:
        s = str(aid or "").strip()
        if "[doi]" in s.lower():
            return s.split("[")[0].strip()

    lid = str(entry.get("LID", "") or "").strip()
    if lid and "[doi]" in lid.lower():
        return lid.split("[")[0].strip()
    return ""


def _build_pubmed_query(config: dict[str, Any]) -> str:
    journals = config.get("journals", [])
    days = int(config.get("date_range_days", 1))
    date_filter = f'("{(datetime.utcnow() - timedelta(days=days)).strftime("%Y/%m/%d")}"[Date - Publication] : "3000"[Date - Publication])'

    if not journals:
        return f"medical imaging AND {date_filter}"

    journal_expr = " OR ".join([f'"{j}"[Journal]' for j in journals])
    topic_expr = '(medical image OR MRI OR CT OR pathology OR ultrasound OR diffusion model OR generative)'
    return f"({journal_expr}) AND {topic_expr} AND {date_filter}"


def fetch_pubmed(config: dict[str, Any]) -> list[dict[str, Any]]:
    """抓取 PubMed 论文。"""
    email = os.getenv("PUBMED_EMAIL", "medpaper-flow@example.com")
    Entrez.email = email
    api_key = os.getenv("PUBMED_API_KEY", "").strip()
    if api_key:
        Entrez.api_key = api_key

    max_results = int(config.get("max_results", 80))
    query = _build_pubmed_query(config)
    papers: list[dict[str, Any]] = []

    try:
        with Entrez.esearch(db="pubmed", term=query, retmax=max_results, sort="pub date") as handle:
            record = Entrez.read(handle)
        ids = record.get("IdList", [])
        if not ids:
            return papers

        with Entrez.efetch(db="pubmed", id=",".join(ids), rettype="medline", retmode="text") as handle:
            entries = Medline.parse(handle)
            for entry in entries:
                pmid = entry.get("PMID")
                if not pmid:
                    continue

                title = (entry.get("TI") or "").strip()
                abstract = (entry.get("AB") or "").strip()
                authors = entry.get("AU", [])
                journal = entry.get("JT", "")
                published_date = (entry.get("DP", "")[:10] or datetime.utcnow().date().isoformat())
                if len(published_date) == 4:
                    published_date = f"{published_date}-01-01"

                papers.append(
                    {
                        "id": f"PMID:{pmid}",
                        "title": title,
                        "abstract": abstract,
                        "authors": authors,
                        "source": "pubmed",
                        "published_date": published_date,
                        "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                        "affiliation": journal,
                        "doi": _extract_doi(entry),
                    }
                )
    except Exception as exc:
        logging.exception("PubMed 抓取失败: %s", exc)

    return papers
