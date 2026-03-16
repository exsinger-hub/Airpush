from __future__ import annotations

import asyncio
import json
import logging
import os
from contextlib import contextmanager
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

import yaml

from src.deduplicator import SemanticDeduplicator
from src.fetchers.arxiv_fetcher import fetch_arxiv
from src.fetchers.conference_fetcher import fetch_conference_papers
from src.fetchers.pubmed_fetcher import fetch_pubmed
from src.fetchers.rss_fetcher import fetch_rss
from src.llm_pipeline import LLMPipeline
from src.notifier import build_daily_message, build_daily_wechat_message, build_weekly_message, send_webhook
from src.pdf_downloader import PDFDownloader
from src.runtime_config import apply_runtime_env, load_runtime_yaml
from src.scorer import PaperScorer, select_scored_papers
from src.storage.notion_page_store import NotionPageStore
from src.storage.push_state_store import PushStateStore
from src.storage.notion_store import NotionStore
from src.storage.sqlite_store import SQLiteStore


def _current_domain() -> str:
    return (os.getenv("DOMAIN", "medical") or "medical").strip().lower()


def _is_physics_domain() -> bool:
    return _current_domain() in {"cqed_plasmonics", "physics", "quantum", "plasmonics", "cqed"}


def _brand_name() -> str:
    return "CQED/Plasmonics" if _is_physics_domain() else "医学AI"


def _domain_default_path(base_dir: str, filename: str = "") -> str:
    domain = _current_domain() or "medical"
    if filename:
        return str(Path(base_dir) / domain / filename)
    return str(Path(base_dir) / domain)


Path("logs").mkdir(exist_ok=True)
_log_file = os.getenv("LOG_FILE", "").strip() or str(Path("logs") / f"run-{_current_domain() or 'medical'}.log")
Path(_log_file).parent.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        RotatingFileHandler(_log_file, encoding="utf-8", maxBytes=5 * 1024 * 1024, backupCount=7),
        logging.StreamHandler(),
    ],
)


def send_alert(message: str) -> None:
    alert_url = os.getenv("ALERT_URL", "")
    if alert_url:
        send_webhook(f"⚠️ {message}", alert_url)


@contextmanager
def safe_stage(name: str):
    try:
        logging.info("▶ 开始 Stage: %s", name)
        yield
        logging.info("✅ 完成 Stage: %s", name)
    except Exception as exc:
        logging.exception("❌ Stage [%s] 失败: %s", name, exc)
        send_alert(f"{_brand_name()} 异常: [{name}] {str(exc)[:120]}")


def load_yaml(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _normalize_papers(papers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normed: list[dict[str, Any]] = []
    for paper in papers:
        if not isinstance(paper, dict):
            continue
        if not paper.get("title"):
            continue
        item = dict(paper)
        item.setdefault("abstract", "")
        item.setdefault("authors", [])
        item.setdefault("source", "unknown")
        item.setdefault("published_date", datetime.utcnow().date().isoformat())
        item.setdefault("url", "")
        item.setdefault("affiliation", "")
        normed.append(item)
    return normed


def load_import_bundle(bundle_file: str, pdf_root: str = "") -> tuple[list[dict[str, Any]], dict[str, Any]]:
    bundle_path = Path(bundle_file)
    if not bundle_path.exists():
        raise FileNotFoundError(f"导入抓取包不存在: {bundle_file}")

    payload = json.loads(bundle_path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        papers = payload
        meta: dict[str, Any] = {}
    elif isinstance(payload, dict):
        papers = payload.get("papers", [])
        meta = payload.get("meta", {}) if isinstance(payload.get("meta", {}), dict) else {}
    else:
        raise ValueError("导入抓取包格式非法：仅支持 papers 列表或包含 meta/papers 的 JSON 对象")

    if not isinstance(papers, list):
        raise ValueError("导入抓取包格式非法：papers 必须是列表")

    resolved_root = Path(pdf_root).expanduser() if pdf_root else bundle_path.parent
    normed = _normalize_papers(papers)
    for paper in normed:
        pdf_local_path = str(paper.get("pdf_local_path", "") or "").strip()
        if not pdf_local_path:
            continue
        candidate = Path(pdf_local_path).expanduser()
        if not candidate.is_absolute():
            candidate = resolved_root / candidate
        paper["pdf_local_path"] = str(candidate)
        if candidate.exists() and candidate.is_file():
            paper["pdf_downloaded"] = True
    return normed, meta


def fetch_all_sources(source_cfg: dict[str, Any]) -> list[dict[str, Any]]:
    papers: list[dict[str, Any]] = []
    papers.extend(fetch_arxiv(source_cfg.get("arxiv", {})))
    papers.extend(fetch_pubmed(source_cfg.get("pubmed", {})))
    papers.extend(fetch_rss(source_cfg.get("rss_feeds", [])))

    conf_cfg = source_cfg.get("conference", {})
    weekly_only = bool(conf_cfg.get("weekly_only", False))
    if (not weekly_only) or datetime.now().weekday() == 0:
        papers.extend(fetch_conference_papers(conf_cfg))
    else:
        logging.info("conference 抓取设为每周模式，今天跳过（weekday=%s）", datetime.now().weekday())
    return _normalize_papers(papers)


def write_markdown_report(top_papers: list[dict[str, Any]], total_scanned: int, out_dir: str = "reports") -> str:
    Path(out_dir).mkdir(exist_ok=True)
    path = Path(out_dir) / f"daily-{datetime.now().strftime('%Y-%m-%d')}.md"

    text = build_daily_message(top_papers, total_scanned=total_scanned)
    path.write_text(text, encoding="utf-8")
    return str(path)


def prioritize_figure_ready_papers(papers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def _priority(paper: dict[str, Any]) -> tuple[int, int, int, int]:
        figure_count = len(paper.get("figure_items", []) or [])
        has_figures = 1 if figure_count > 0 else 0
        has_pdf = 1 if bool(paper.get("pdf_downloaded", False)) else 0
        idea_score = int(paper.get("idea_score", 0) or 0)
        score = int(paper.get("score", 0) or 0)
        return has_figures, has_pdf, idea_score, score

    return sorted(papers, key=_priority, reverse=True)


def run_async(coro: Any) -> Any:
    try:
        return asyncio.run(coro)
    except RuntimeError:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()


def main() -> None:
    domain = (os.getenv("DOMAIN", "medical") or "medical").strip()
    domain_cfg_dir = Path("config") / "domains" / domain

    runtime_cfg_path = os.getenv("RUNTIME_CONFIG", "").strip()
    if not runtime_cfg_path:
        candidate_runtime = domain_cfg_dir / "runtime.yaml"
        runtime_cfg_path = str(candidate_runtime if candidate_runtime.exists() else Path("config/runtime.yaml"))

    sources_cfg_path = os.getenv("SOURCES_CONFIG", "").strip()
    if not sources_cfg_path:
        candidate_sources = domain_cfg_dir / "sources.yaml"
        sources_cfg_path = str(candidate_sources if candidate_sources.exists() else Path("config/sources.yaml"))

    scoring_cfg_path = os.getenv("SCORING_CONFIG", "").strip()
    if not scoring_cfg_path:
        candidate_scoring = domain_cfg_dir / "scoring_rules.yaml"
        scoring_cfg_path = str(candidate_scoring if candidate_scoring.exists() else Path("config/scoring_rules.yaml"))

    logging.info(
        "运行领域=%s | runtime=%s | sources=%s | scoring=%s",
        domain,
        runtime_cfg_path,
        sources_cfg_path,
        scoring_cfg_path,
    )

    runtime_cfg = load_runtime_yaml(runtime_cfg_path)
    apply_runtime_env(runtime_cfg)

    dry_run = str(os.getenv("DRY_RUN", "false")).lower() == "true"
    md_only = str(os.getenv("MD_ONLY", "false")).lower() == "true"
    reports_dir = os.getenv("REPORTS_DIR", _domain_default_path("reports"))
    score_threshold = int(os.getenv("SCORE_THRESHOLD", "30"))
    top_k = int(os.getenv("TOP_K", "5"))
    min_selected_papers = max(1, int(os.getenv("MIN_SELECTED_PAPERS", "3")))
    rule_score_fallback_enabled = str(os.getenv("RULE_SCORE_FALLBACK_ENABLED", "true")).lower() == "true"
    quick_filter_backfill_enabled = str(os.getenv("QUICK_FILTER_BACKFILL_ENABLED", "true")).lower() == "true"
    prefer_figure_ready_papers = str(os.getenv("PREFER_FIGURE_READY_PAPERS", "false")).lower() == "true"
    min_abstract_len = int(os.getenv("MIN_ABSTRACT_LEN", "50"))
    fulltext_enabled = str(os.getenv("FULLTEXT_ENABLED", "true")).lower() == "true"
    fulltext_top_k = max(1, int(os.getenv("FULLTEXT_TOP_K", str(top_k))))
    fulltext_min_chars = max(200, int(os.getenv("FULLTEXT_MIN_CHARS", "2000")))
    fulltext_content_key = os.getenv("FULLTEXT_CONTENT_KEY", "full_text_content").strip() or "full_text_content"
    pdf_download_enabled = str(os.getenv("PDF_DOWNLOAD_ENABLED", "true")).lower() == "true"
    pdf_download_top_k = max(1, int(os.getenv("PDF_DOWNLOAD_TOP_K", str(top_k))))
    pdf_download_dir = os.getenv("PDF_DOWNLOAD_DIR", _domain_default_path("data/pdfs")).strip() or _domain_default_path("data/pdfs")
    pdf_download_timeout = max(8, int(os.getenv("PDF_DOWNLOAD_TIMEOUT", "25")))
    md_push_state_file = os.getenv("MD_PUSH_STATE_FILE", str(Path("data") / f"pushed_ids_{domain}.txt"))
    sqlite_db_path = os.getenv("SQLITE_DB_PATH", str(Path("data") / f"papers-{domain}.db"))
    notion_page_replace = str(os.getenv("NOTION_PAGE_REPLACE", "false")).lower() == "true"
    notion_native_blocks = str(os.getenv("NOTION_NATIVE_BLOCKS", "true")).lower() == "true"
    notion_daily_page = str(os.getenv("NOTION_DAILY_PAGE", "false")).lower() == "true"
    notion_daily_reuse_existing = str(os.getenv("NOTION_DAILY_REUSE_EXISTING", "true")).lower() == "true"
    notion_daily_title_prefix = os.getenv("NOTION_DAILY_TITLE_PREFIX", "📰 ")
    notion_daily_title_suffix = os.getenv(
        "NOTION_DAILY_TITLE_SUFFIX",
        " CQED/Plasmonics 每日精选" if _is_physics_domain() else " 医学AI 每日精选",
    )
    source_cfg = load_yaml(sources_cfg_path).get("sources", {})
    import_bundle_file = os.getenv("IMPORT_PAPERS_FILE", "").strip()
    import_pdf_root = os.getenv("IMPORT_PDF_ROOT", "").strip()

    papers: list[dict[str, Any]] = []
    total_scanned = 0
    import_meta: dict[str, Any] = {}
    import_preprocessed = False
    import_pdf_prefetched = False

    if import_bundle_file:
        with safe_stage("导入抓取包"):
            papers, import_meta = load_import_bundle(import_bundle_file, import_pdf_root)
            import_preprocessed = bool(import_meta.get("preprocessed", False))
            import_pdf_prefetched = bool(import_meta.get("pdf_prefetched", False))
            total_scanned = int(import_meta.get("total_scanned", len(papers)) or len(papers))
            logging.info(
                "导入抓取包: file=%s papers=%s total_scanned=%s preprocessed=%s pdf_prefetched=%s",
                import_bundle_file,
                len(papers),
                total_scanned,
                import_preprocessed,
                import_pdf_prefetched,
            )
            papers = [p for p in papers if len((p.get("abstract") or "").strip()) > min_abstract_len]
            logging.info("导入包按摘要长度过滤后剩余 %s 篇", len(papers))
    else:
        with safe_stage("多源采集"):
            papers = fetch_all_sources(source_cfg)
            papers = [p for p in papers if len((p.get("abstract") or "").strip()) > min_abstract_len]
            total_scanned = len(papers)
            logging.info("采集到 %s 篇原始论文", total_scanned)

    if not import_preprocessed:
        with safe_stage("语义去重"):
            papers = SemanticDeduplicator(threshold=0.92).deduplicate(papers)

        with safe_stage("规则评分"):
            scorer = PaperScorer(scoring_cfg_path)
            scored: list[dict[str, Any]] = []
            all_ranked: list[dict[str, Any]] = []
            for p in papers:
                score, labels, core_ok = scorer.score(p)
                p["score"] = score
                p["labels"] = labels
                p["topic"] = scorer.assign_topic(p)
                p["core_ok"] = core_ok
                all_ranked.append(p)
                if core_ok and score > score_threshold:
                    scored.append(p)
            papers, fallback_used = select_scored_papers(
                all_ranked=all_ranked,
                scored=scored,
                min_selected_papers=min_selected_papers,
                fallback_enabled=rule_score_fallback_enabled,
            )
            if fallback_used:
                logging.warning(
                    "规则筛选结果为空，启用兜底策略：按分数保留 %s 篇（阈值=%s）",
                    len(papers),
                    score_threshold,
                )
            elif not papers:
                logging.warning(
                    "规则筛选结果为空，且已禁用兜底策略：阈值=%s，当前不保量",
                    score_threshold,
                )
            logging.info("规则过滤后剩余 %s 篇", len(papers))
    else:
        logging.info("导入包已预处理，跳过多源采集/语义去重/规则评分，当前候选=%s", len(papers))

    pipeline = LLMPipeline()

    with safe_stage("LLM 快速筛选"):
        pre_quick = list(papers)
        papers = pipeline.quick_filter(papers)
        if quick_filter_backfill_enabled and len(papers) < min_selected_papers and pre_quick:
            existing_ids = {
                str(p.get("id", "")).strip()
                for p in papers
                if str(p.get("id", "")).strip()
            }
            pre_quick.sort(key=lambda x: x.get("score", 0), reverse=True)
            needed = max(0, min_selected_papers - len(papers))
            supplements: list[dict[str, Any]] = []
            for cand in pre_quick:
                cid = str(cand.get("id", "")).strip()
                if cid and cid in existing_ids:
                    continue
                supplements.append(cand)
                if len(supplements) >= needed:
                    break

            papers.extend(supplements)
            for p in supplements:
                p["fallback_selected"] = True
                p["fallback_reason"] = "LLM快筛候选不足，按分数兜底补足"
            logging.warning(
                "LLM 快筛候选不足，启用兜底策略：补足后共 %s 篇",
                len(papers),
            )
        elif (not quick_filter_backfill_enabled) and len(papers) < min_selected_papers:
            logging.warning(
                "LLM 快筛候选不足，且已禁用补量策略：当前保留 %s 篇",
                len(papers),
            )
        logging.info("LLM 快筛后剩余 %s 篇", len(papers))

    with safe_stage("LLM 深度精析"):
        top_papers = pipeline.deep_extract(papers, top_k=top_k)
        top_papers.sort(
            key=lambda p: (
                int(p.get("idea_score", 0) or 0),
                int(p.get("score", 0) or 0),
            ),
            reverse=True,
        )

    if pdf_download_enabled and top_papers and not (import_bundle_file and import_pdf_prefetched):
        with safe_stage("已选论文 PDF 下载"):
            downloader = PDFDownloader(out_dir=pdf_download_dir, timeout=pdf_download_timeout)
            downloaded = downloader.download_batch(top_papers, top_k=min(pdf_download_top_k, len(top_papers)))

            mapped = {str(p.get("id", "")).strip(): p for p in downloaded if str(p.get("id", "")).strip()}
            merged_list: list[dict[str, Any]] = []
            for p in top_papers:
                pid = str(p.get("id", "")).strip()
                if pid and pid in mapped:
                    merged = {**p, **mapped[pid]}
                    if bool(merged.get("pdf_downloaded", False)):
                        merged["fulltext_status"] = "downloaded"
                        merged["analysis_notice"] = "✅ 全文分析"
                    elif bool(merged.get("manual_fulltext_required", False)):
                        merged["fulltext_status"] = "manual_required"
                        merged["analysis_notice"] = "⚠️ 仅摘要分析 (全文获取受阻)"
                    else:
                        merged["fulltext_status"] = "failed"
                        merged["analysis_notice"] = "⚠️ 仅摘要分析 (全文获取受阻)"
                    merged_list.append(merged)
                else:
                    merged_list.append({**p, "fulltext_status": "not_attempted", "analysis_notice": "⚠️ 仅摘要分析 (全文获取受阻)"})
            top_papers = merged_list

            ok = sum(1 for p in top_papers if bool(p.get("pdf_downloaded", False)))
            js_challenge = sum(1 for p in top_papers if str(p.get("pdf_failure_reason", "")) == "js_challenge")
            manual_required = sum(1 for p in top_papers if bool(p.get("manual_fulltext_required", False)))
            logging.info("PDF 下载完成：成功=%s / 尝试=%s", ok, min(pdf_download_top_k, len(top_papers)))
            if js_challenge or manual_required:
                logging.warning(
                    "全文降级：JS Challenge=%s，需手动全文=%s（其余论文自动回退摘要分析）",
                    js_challenge,
                    manual_required,
                )
    elif pdf_download_enabled and top_papers and import_bundle_file and import_pdf_prefetched:
        logging.info("导入抓取包已包含预抓取 PDF，跳过当前运行的 PDF 下载阶段")

    if fulltext_enabled and top_papers:
        with safe_stage("LLM 全文精读"):
            fulltext_candidates: list[dict[str, Any]] = []
            passthrough: list[dict[str, Any]] = []

            for p in top_papers:
                content = str(p.get(fulltext_content_key, "") or "").strip()
                if len(content) < fulltext_min_chars:
                    content = str(p.get("abstract", "") or "").strip()

                if len(content) >= fulltext_min_chars:
                    fulltext_candidates.append({**p, fulltext_content_key: content})
                else:
                    passthrough.append(p)

            if fulltext_candidates:
                analyzed = run_async(
                    pipeline.deep_analyze_fulltext_batch(
                        fulltext_candidates,
                        top_k=min(fulltext_top_k, len(fulltext_candidates)),
                        content_key=fulltext_content_key,
                    )
                )
                keep_ids = {str(p.get("id", "")).strip() for p in analyzed if str(p.get("id", "")).strip()}
                tail = [p for p in top_papers if str(p.get("id", "")).strip() not in keep_ids]
                top_papers = analyzed + tail
                logging.info("全文精读完成：候选=%s，实际精读=%s", len(fulltext_candidates), len(analyzed))
            else:
                logging.info("全文精读跳过：未发现长度>= %s 的正文内容", fulltext_min_chars)

            if passthrough:
                logging.info("全文精读旁路保留 %s 篇（正文不足）", len(passthrough))

        top_papers.sort(
            key=lambda p: (
                int(p.get("idea_score", 0) or 0),
                int(p.get("score", 0) or 0),
            ),
            reverse=True,
        )

    if prefer_figure_ready_papers and top_papers:
        before_top = [str(p.get("title", ""))[:80] for p in top_papers[:3]]
        top_papers = prioritize_figure_ready_papers(top_papers)
        after_top = [str(p.get("title", ""))[:80] for p in top_papers[:3]]
        figure_ready_count = sum(1 for p in top_papers if len(p.get("figure_items", []) or []) > 0)
        logging.info(
            "已按图片就绪优先级重排候选：figure_ready=%s before_top=%s after_top=%s",
            figure_ready_count,
            before_top,
            after_top,
        )

    store = None
    if not md_only:
        store = SQLiteStore(sqlite_db_path)
        with safe_stage("SQLite 存储"):
            for p in top_papers:
                store.upsert(p)

        notion_token = os.getenv("NOTION_TOKEN", "")
        notion_db_id = os.getenv("NOTION_DB_ID", "")
        if notion_token and notion_db_id:
            with safe_stage("Notion 同步"):
                notion = NotionStore(notion_token, notion_db_id)
                for p in top_papers:
                    notion.write(p)

    with safe_stage("Markdown 导出"):
        md_path = write_markdown_report(top_papers, total_scanned=total_scanned, out_dir=reports_dir)
        logging.info("Markdown 已导出: %s", md_path)

    notion_token = os.getenv("NOTION_TOKEN", "")
    notion_page_id = os.getenv("NOTION_PAGE_ID", "")
    if notion_token and notion_page_id:
        with safe_stage("Notion 页面同步"):
            page_store = NotionPageStore(notion_token, notion_page_id)
            if notion_daily_page and top_papers:
                daily_title = f"{notion_daily_title_prefix}{datetime.now().strftime('%Y-%m-%d')}{notion_daily_title_suffix}"
                page_store.use_daily_page(daily_title, reuse_existing=notion_daily_reuse_existing)
            elif notion_daily_page and not top_papers:
                logging.info("Notion 每日子页面已启用，但今日无入选论文，跳过创建子页面")
            if notion_native_blocks:
                page_store.sync_papers(top_papers, replace=notion_page_replace)
            else:
                md_text = Path(md_path).read_text(encoding="utf-8")
                page_store.sync_markdown(md_text, replace=notion_page_replace)

    with safe_stage("推送通知"):
        webhook_url = os.getenv("WEBHOOK_URL", "")
        if md_only:
            state = PushStateStore(md_push_state_file)
            to_push = []
            for p in top_papers:
                pid = str(p.get("id", "")).strip()
                if pid and not state.contains(pid):
                    to_push.append(p)
            if "sctapi.ftqq.com" in webhook_url:
                text = build_daily_wechat_message(to_push, total_scanned=total_scanned)
            else:
                text = build_daily_message(to_push, total_scanned=total_scanned)
            if not dry_run and to_push:
                send_webhook(text, webhook_url)
                state.add_many([str(p.get("id", "")).strip() for p in to_push if p.get("id")])
        else:
            if store is not None:
                unpushed_ids = {
                    str(p.get("id", "")).strip()
                    for p in store.get_unpushed()
                    if str(p.get("id", "")).strip()
                }
                to_push = [
                    p
                    for p in top_papers
                    if str(p.get("id", "")).strip() in unpushed_ids
                ]
            else:
                to_push = top_papers

            # 当日已全部推送过时，仍发送本次日报，保证微信内容与当次运行一致
            if not to_push:
                to_push = top_papers

            if "sctapi.ftqq.com" in webhook_url:
                text = build_daily_wechat_message(to_push, total_scanned=total_scanned)
            else:
                text = build_daily_message(to_push, total_scanned=total_scanned)
            if not dry_run and to_push:
                send_webhook(text, webhook_url)
                if store is not None:
                    store.mark_pushed([str(p.get("id", "")) for p in to_push if p.get("id")])
        logging.info("日报生成完成")

    if not md_only and store is not None and datetime.now().weekday() == 6:
        with safe_stage("每周趋势报告"):
            weekly = build_weekly_message(store.get_weekly_stats())
            if not dry_run:
                send_webhook(weekly, os.getenv("WEBHOOK_URL", ""))


if __name__ == "__main__":
    main()
