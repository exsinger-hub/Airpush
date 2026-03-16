from __future__ import annotations

import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.llm_pipeline import LLMPipeline
from src.runtime_config import apply_runtime_env, load_runtime_yaml
from src.storage.notion_page_store import NotionPageStore


def _current_domain() -> str:
    return (os.getenv("DOMAIN", "medical") or "medical").strip().lower()


def _daily_title_suffix(domain: str) -> str:
    return " CQED/Plasmonics 每日精选" if domain in {"cqed_plasmonics", "physics", "quantum", "plasmonics", "cqed"} else " 医学AI 每日精选"


def _daily_report_path(domain: str) -> Path:
    return PROJECT_ROOT / "reports" / domain / f"daily-{datetime.now().strftime('%Y-%m-%d')}.md"


def _extract_entries(markdown_text: str) -> list[dict[str, str]]:
    pattern = re.compile(r"### .*?: \[(?P<title>.+?)\]\((?P<url>https?://[^)]+)\)")
    entries: list[dict[str, str]] = []
    for match in pattern.finditer(markdown_text):
        entries.append({"title": match.group("title").strip(), "url": match.group("url").strip()})
    return entries


def _find_pdf_for_entry(pdf_dir: Path, entry: dict[str, str]) -> Path | None:
    url = entry.get("url", "")
    arxiv_match = re.search(r"/(\d{4}\.\d{4,5}v\d+)", url)
    if arxiv_match:
        arxiv_id = arxiv_match.group(1)
        for file in pdf_dir.glob("*.pdf"):
            if arxiv_id in file.name:
                return file
    title_tokens = [tok.lower() for tok in re.findall(r"[A-Za-z0-9]+", entry.get("title", ""))[:4]]
    for file in pdf_dir.glob("*.pdf"):
        name = file.stem.lower()
        if all(tok in name for tok in title_tokens if tok):
            return file
    return None


def _image_blocks(paper: dict[str, Any]) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = [
        {
            "object": "block",
            "type": "heading_3",
            "heading_3": {"rich_text": [NotionPageStore._plain_text(f"🖼️ {paper['title']}")]},
        }
    ]
    for item in paper.get("figure_items", []):
        blocks.append(
            {
                "object": "block",
                "type": "image",
                "image": {"type": "external", "external": {"url": item["url"]}},
            }
        )
        blocks.append(
            {
                "object": "block",
                "type": "paragraph",
                "paragraph": {"rich_text": [NotionPageStore._annot_text(item.get("caption", "图注缺失"), italic=True)]},
            }
        )
    return blocks


def main() -> None:
    domain = _current_domain()
    print(f"domain={domain}", flush=True)
    runtime_cfg = load_runtime_yaml(str(PROJECT_ROOT / "config" / "domains" / domain / "runtime.yaml"))
    apply_runtime_env(runtime_cfg)

    report_path = _daily_report_path(domain)
    if not report_path.exists():
        raise FileNotFoundError(f"daily report not found: {report_path}")
    print(f"report={report_path}", flush=True)

    report_text = report_path.read_text(encoding="utf-8")
    entries = _extract_entries(report_text)
    if not entries:
        raise RuntimeError("no report entries found")

    pdf_dir = PROJECT_ROOT / "data" / "pdfs" / domain
    pipeline = LLMPipeline()
    print(f"pdf_dir={pdf_dir}", flush=True)
    notion_token = os.getenv("NOTION_TOKEN", "")
    notion_page_id = os.getenv("NOTION_PAGE_ID", "")
    if not notion_token or not notion_page_id:
        raise RuntimeError("missing notion config")

    page_store = NotionPageStore(notion_token, notion_page_id)
    daily_title = f"📰 {datetime.now().strftime('%Y-%m-%d')}{_daily_title_suffix(domain)}"
    print(f"daily_title={daily_title}", flush=True)
    page_store.use_daily_page(daily_title, reuse_existing=True)
    print("daily_page_ready", flush=True)

    appended = 0
    for entry in entries[:3]:
        print(f"processing={entry['title']}", flush=True)
        pdf_path = _find_pdf_for_entry(pdf_dir, entry)
        if not pdf_path or not pdf_path.exists():
            print(f"skip_no_pdf: {entry['title']}")
            continue
        print(f"pdf={pdf_path.name}", flush=True)
        with pdf_path.open("rb") as f:
            pdf_bytes = f.read()
        figure_items = pipeline._extract_and_upload_figures_github(pdf_bytes, entry, max_images=2)
        if not figure_items:
            print(f"skip_no_figure: {entry['title']}")
            continue
        print(f"figure_items={len(figure_items)}", flush=True)
        page_store._append_blocks(_image_blocks({"title": entry['title'], "figure_items": figure_items}))
        appended += len(figure_items)
        print(f"appended: {entry['title']} count={len(figure_items)}")

    print(f"appended_total={appended}")


if __name__ == "__main__":
    main()
