from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml


def load_runtime_yaml(path: str = "config/runtime.yaml") -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        return {}
    with p.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data if isinstance(data, dict) else {}


def apply_runtime_env(runtime_cfg: dict[str, Any]) -> None:
    """将 runtime.yaml 中配置写入环境变量（仅在变量未设置时生效）。"""
    llm = runtime_cfg.get("llm", {}) if isinstance(runtime_cfg.get("llm", {}), dict) else {}
    notion = runtime_cfg.get("notion", {}) if isinstance(runtime_cfg.get("notion", {}), dict) else {}
    notify = runtime_cfg.get("notify", {}) if isinstance(runtime_cfg.get("notify", {}), dict) else {}
    pubmed = runtime_cfg.get("pubmed", {}) if isinstance(runtime_cfg.get("pubmed", {}), dict) else {}
    elsevier = runtime_cfg.get("elsevier", {}) if isinstance(runtime_cfg.get("elsevier", {}), dict) else {}
    openreview = runtime_cfg.get("openreview", {}) if isinstance(runtime_cfg.get("openreview", {}), dict) else {}
    webvpn = runtime_cfg.get("webvpn", {}) if isinstance(runtime_cfg.get("webvpn", {}), dict) else {}
    run = runtime_cfg.get("run", {}) if isinstance(runtime_cfg.get("run", {}), dict) else {}

    mapping = {
        "OPENAI_API_KEY": llm.get("api_key"),
        "OPENAI_BASE_URL": llm.get("base_url"),
        "LLM_QUICK_MODEL": llm.get("quick_model"),
        "LLM_DEEP_MODEL": llm.get("deep_model"),
        "LLM_FULLTEXT_MODEL": llm.get("fulltext_model"),
        "LLM_LOCAL_MODEL": llm.get("local_model"),
        "DISABLE_LOCAL_QUICK": llm.get("disable_local_quick"),
        "LLM_REQUEST_TIMEOUT": llm.get("request_timeout_sec"),
        "LLM_MAX_RETRIES": llm.get("max_retries"),
        "LLM_CIRCUIT_BREAKER_FAILS": llm.get("circuit_breaker_fails"),
        "LLM_MAX_INPUT_TOKENS": llm.get("max_input_tokens"),
        "LLM_TEMPERATURE": llm.get("temperature"),
        "LLM_TOP_P": llm.get("top_p"),
        "LLM_PRESENCE_PENALTY": llm.get("presence_penalty"),
        "LLM_DEEP_STAGE_MAX_SECONDS": llm.get("deep_stage_max_seconds"),
        "LLM_FULLTEXT_MAX_TOKENS": llm.get("fulltext_max_tokens"),
        "LLM_DEEP_EXTRACT_MAX_TOKENS": llm.get("deep_extract_max_tokens"),
        "LLM_ABSTRACT_TRANSLATE_MAX_TOKENS": llm.get("abstract_translate_max_tokens"),
        "LLM_FULLTEXT_CONCURRENCY": llm.get("fulltext_concurrency"),
        "FIGURE_HOSTING_ENABLED": llm.get("figure_hosting_enabled"),
        "FIGURE_SELECTION_USE_LLM": llm.get("figure_selection_use_llm"),
        "FIGURE_SELECTION_TIMEOUT": llm.get("figure_selection_timeout_sec"),
        "FIGURE_SELECTION_TOTAL_BUDGET": llm.get("figure_selection_total_budget_sec"),
        "FIGURE_SELECTION_ATTEMPTS": llm.get("figure_selection_attempts"),
        "FIGURE_MAX_IMAGES": llm.get("figure_max_images"),
        "FIGURE_SCAN_PAGES": llm.get("figure_scan_pages"),
        "FIGURE_CANDIDATE_LIMIT": llm.get("figure_candidate_limit"),
        "FIGURE_LLM_CANDIDATE_CAP": llm.get("figure_llm_candidate_cap"),
        "GITHUB_TOKEN": llm.get("github_token"),
        "GITHUB_USER": llm.get("github_user"),
        "GITHUB_REPO": llm.get("github_repo"),
        "GITHUB_BRANCH": llm.get("github_branch"),
        "GITHUB_UPLOAD_TIMEOUT": llm.get("github_upload_timeout"),
        "ENABLE_PDF_ROUTING": llm.get("enable_pdf_routing"),
        "PREFER_PDF_FULLTEXT": llm.get("prefer_pdf_fulltext"),
        "PDF_FETCH_TIMEOUT": llm.get("pdf_fetch_timeout_sec"),
        "FULLTEXT_WORD_MIN": llm.get("fulltext_word_min"),
        "FULLTEXT_WORD_MAX": llm.get("fulltext_word_max"),
        "NOTION_TOKEN": notion.get("token"),
        "NOTION_DB_ID": notion.get("database_id"),
        "NOTION_PAGE_ID": notion.get("page_id"),
        "WEBHOOK_URL": notify.get("webhook_url"),
        "ALERT_URL": notify.get("alert_url"),
        "PUBMED_EMAIL": pubmed.get("email"),
        "PUBMED_API_KEY": pubmed.get("api_key"),
        "ELSEVIER_API_KEY": elsevier.get("api_key"),
        "OPENREVIEW_USERNAME": openreview.get("username"),
        "OPENREVIEW_PASSWORD": openreview.get("password"),
        "OPENREVIEW_ACCESS_TOKEN": openreview.get("access_token"),
        "OPENREVIEW_USE_AUTH": openreview.get("use_auth"),
        "WEBVPN_ENABLED": webvpn.get("enabled"),
        "WEBVPN_BASE_URL": webvpn.get("base_url"),
        "WEBVPN_PREFIX": webvpn.get("prefix"),
        "WEBVPN_TICKET": webvpn.get("ticket"),
        "WEBVPN_TICKET_COOKIE_NAME": webvpn.get("ticket_cookie_name"),
        "WEBVPN_ROUTE": webvpn.get("route"),
        "WEBVPN_EXTRA_COOKIES": webvpn.get("extra_cookies"),
        "WEBVPN_COOKIE_HEADER": webvpn.get("cookie_header"),
        "WEBVPN_REFERER": webvpn.get("referer"),
        "WEBVPN_USER_AGENT": webvpn.get("user_agent"),
        "WEBVPN_ACCEPT": webvpn.get("accept"),
        "WEBVPN_SEC_FETCH_DEST": webvpn.get("sec_fetch_dest"),
        "WEBVPN_SEC_FETCH_MODE": webvpn.get("sec_fetch_mode"),
        "WEBVPN_SEC_FETCH_SITE": webvpn.get("sec_fetch_site"),
        "WEBVPN_USE_CURL_CFFI": webvpn.get("use_curl_cffi"),
        "WEBVPN_CURL_IMPERSONATE": webvpn.get("curl_impersonate"),
        "WEBVPN_USTC_ENCRYPT_HOST": webvpn.get("ustc_encrypt_host"),
        "WEBVPN_USTC_CIPHER_KEY": webvpn.get("ustc_cipher_key"),
        "WEBVPN_PLAYWRIGHT_FALLBACK": webvpn.get("playwright_fallback"),
        "WEBVPN_PLAYWRIGHT_HEADLESS": webvpn.get("playwright_headless"),
        "WEBVPN_PLAYWRIGHT_TIMEOUT_MS": webvpn.get("playwright_timeout_ms"),
        "WEBVPN_PROBE_URL": webvpn.get("probe_url"),
        "WEBVPN_TIMEOUT": webvpn.get("timeout_sec"),
        "DRY_RUN": run.get("dry_run"),
        "DISABLE_SEMANTIC_DEDUP": run.get("disable_semantic_dedup"),
        "MD_ONLY": run.get("md_only"),
        "REPORTS_DIR": run.get("reports_dir"),
        "TOP_K": run.get("top_k"),
        "SCORE_THRESHOLD": run.get("score_threshold"),
        "MIN_SELECTED_PAPERS": run.get("min_selected_papers"),
        "RULE_SCORE_FALLBACK_ENABLED": run.get("rule_score_fallback_enabled"),
        "QUICK_FILTER_BACKFILL_ENABLED": run.get("quick_filter_backfill_enabled"),
        "PREFER_FIGURE_READY_PAPERS": run.get("prefer_figure_ready_papers"),
        "MIN_ABSTRACT_LEN": run.get("min_abstract_len"),
        "FULLTEXT_ENABLED": run.get("fulltext_enabled"),
        "FULLTEXT_TOP_K": run.get("fulltext_top_k"),
        "FULLTEXT_MIN_CHARS": run.get("fulltext_min_chars"),
        "FULLTEXT_CONTENT_KEY": run.get("fulltext_content_key"),
        "PDF_DOWNLOAD_ENABLED": run.get("pdf_download_enabled"),
        "PDF_DOWNLOAD_TOP_K": run.get("pdf_download_top_k"),
        "PDF_DOWNLOAD_DIR": run.get("pdf_download_dir"),
        "PDF_DOWNLOAD_TIMEOUT": run.get("pdf_download_timeout"),
        "SQLITE_DB_PATH": run.get("sqlite_db_path"),
        "MD_PUSH_STATE_FILE": run.get("md_push_state_file"),
        "NOTION_PAGE_REPLACE": run.get("notion_page_replace"),
        "NOTION_NATIVE_BLOCKS": run.get("notion_native_blocks"),
        "NOTION_DAILY_PAGE": run.get("notion_daily_page"),
        "NOTION_DAILY_REUSE_EXISTING": run.get("notion_daily_reuse_existing"),
        "NOTION_DAILY_TITLE_PREFIX": run.get("notion_daily_title_prefix"),
        "NOTION_DAILY_TITLE_SUFFIX": run.get("notion_daily_title_suffix"),
        "CONFERENCE_WEEKLY_ONLY": run.get("conference_weekly_only"),
    }

    for key, value in mapping.items():
        if value is None:
            continue
        if key in os.environ and str(os.environ.get(key, "")).strip() != "":
            continue
        os.environ[key] = str(value).strip()
