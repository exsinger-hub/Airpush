from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Any

import requests
from dateutil import parser as date_parser

DAILY_TEMPLATE = """# {title}

*📅 {date} | 🔍 扫描: {total_scanned} | 🌟 入选: {top_count}*
---

{papers}
"""

PAPER_TEMPLATE = """### {medal} Top {rank}: [{title}]({url})

**🏷️ 标签:** {labels}
**📊 评分:** {score}/100 | **💡 Idea分:** {idea_score}/10 | **🧭 分析路径:** {analysis_route} | **🔥 炒作指数:** {hype_stars}

* **📰 来源**: {source} | **📅 日期**: {published_date}
* **🏥 场景/任务**: {modality} · {task}
* **🧠 算法架构**: {architecture}
* **🎯 核心创新**: {innovation_core}
* **🪄 可复用Idea**: {idea_takeaway}
* **🧪 下一步实验**: {next_experiment}
* **🔁 最小复现路径**: {repro_recipe}
* **📄 全文状态**: {fulltext_status}
* **🚦 分析标记**: {analysis_notice}
* **🧷 证据锚点**: {evidence_anchor}
* **💡 临床价值**: {clinical_problem}
* **📈 关键提升**: {performance_gain}
* **⚠️ 主要局限**: {limitations}
* **🧷 缺失消融**: {ablation_gap}
* **🏢 研发机构**: {institution}

---
"""

PHYSICS_PAPER_TEMPLATE = """### {medal} Top {rank}: [{title}]({url})

**🏷️ 标签:** {labels}
**📊 评分:** {score}/100 | **💡 Idea分:** {idea_score}/10 | **🧭 分析路径:** {analysis_route} | **🔥 炒作指数:** {hype_stars}

* **📰 来源**: {source} | **📅 日期**: {published_date}
* **⚛️ 核心物理系统**: {physical_system}
* **🌀 核心物理机制**: {core_mechanism}
* **🔬 关键实验装置**: {experimental_setup}
* **📈 关键结果与极限**: {key_results}
* **🧯 误差与退相干**: {error_and_decoherence}
* **🚀 下一步影响**: {future_impact}
* **🪄 可复用Idea**: {idea_takeaway}
* **🧪 下一步实验**: {next_experiment}
* **🔁 最小复现路径**: {repro_recipe}
* **📄 全文状态**: {fulltext_status}
* **🚦 分析标记**: {analysis_notice}
* **🧷 证据锚点**: {evidence_anchor}
* **⚠️ 主要局限**: {limitations}
* **🏢 研发机构**: {institution}

---
"""

WEEKLY_TEMPLATE = """{title} {week}

技术架构热度:
{architecture_ranking}

模态热度:
{modality_ranking}
"""


def _current_domain() -> str:
    return (os.getenv("DOMAIN", "") or "").strip().lower()


def _is_physics_domain() -> bool:
    return _current_domain() in {"cqed_plasmonics", "physics", "quantum", "plasmonics", "cqed"}


def _daily_title() -> str:
    return "📢 CQED/Plasmonics 每日精选" if _is_physics_domain() else "📢 医学AI 每日精选"


def _weekly_title() -> str:
    return "📊 本周 CQED/Plasmonics 趋势报告" if _is_physics_domain() else "📊 本周医学AI趋势报告"


def _notify_brand() -> str:
    return "CQED/Plasmonics 通知" if _is_physics_domain() else "医学AI 通知"


def _rank_text(items: dict[str, int]) -> str:
    if not items:
        return "暂无数据"
    lines = []
    for idx, (k, v) in enumerate(items.items(), start=1):
        lines.append(f"{idx}. {k}: {v}")
    return "\n".join(lines)


def build_daily_message(papers: list[dict[str, Any]], total_scanned: int) -> str:
    def _safe(v: Any, default: str = "未提及") -> str:
        text = str(v or "").strip()
        if not text:
            return default
        if text.lower() in {"unknown", "none", "n/a", "null"}:
            return default
        return text

    def _normalize_date_text(v: Any) -> str:
        s = _safe(v, default="")
        if not s:
            return datetime.now().strftime("%Y-%m-%d")
        try:
            return date_parser.parse(s, fuzzy=True).date().isoformat()
        except Exception:
            return s

    def _medal(rank: int) -> str:
        return "🥇" if rank == 1 else ("🥈" if rank == 2 else ("🥉" if rank == 3 else "📄"))

    entries = []
    is_physics = _is_physics_domain()
    for i, p in enumerate(papers[:3], start=1):
        raw_labels = p.get("labels", [])
        if isinstance(raw_labels, str):
            try:
                import json

                raw_labels = json.loads(raw_labels)
            except Exception:
                raw_labels = [raw_labels]
        labels_list = [str(l).strip() for l in list(raw_labels)[:4] if str(l).strip()]
        topic = _safe(p.get("topic", "General"), default="General")
        if topic and topic not in labels_list:
            labels_list.append(topic)
        labels = " | ".join([f"`{l}`" for l in labels_list]) if labels_list else "`General`"
        score = int(p.get("score", 0) or 0)
        idea_score = int(p.get("idea_score", 0) or 0)
        hype = int(p.get("hype_score", 0) or 0)
        hype_stars = ("🌟" * max(1, min(5, hype))) if hype > 0 else "⚪"
        url = _safe(p.get("url", ""), default="#")
        route_raw = _safe(p.get("analysis_route", "abstract"), default="abstract").lower()
        analysis_route = "全文" if route_raw == "fulltext" else "摘要"
        ft_status_raw = str(p.get("fulltext_status", "")).strip().lower()
        if ft_status_raw == "downloaded":
            ft_status = "已下载全文"
        elif ft_status_raw == "manual_required" or bool(p.get("manual_fulltext_required", False)):
            ft_status = "⚠️ 需手动获取全文（已自动降级摘要）"
        elif ft_status_raw == "failed":
            ft_status = "下载失败（已自动降级摘要）"
        else:
            ft_status = "未尝试/不需要"
        analysis_notice = _safe(p.get("analysis_notice", "⚠️ 仅摘要分析 (全文获取受阻)"))
        if is_physics:
            entries.append(
                PHYSICS_PAPER_TEMPLATE.format(
                    rank=i,
                    medal=_medal(i),
                    labels=labels,
                    title=_safe(p.get("title", ""), default="未命名论文"),
                    source=_safe(p.get("source", "")),
                    published_date=_normalize_date_text(p.get("published_date", "")),
                    physical_system=_safe(p.get("physical_system", p.get("task_modality", ""))),
                    core_mechanism=_safe(p.get("core_mechanism", p.get("architecture_innovation", ""))),
                    experimental_setup=_safe(p.get("experimental_setup", p.get("baselines", ""))),
                    key_results=_safe(p.get("key_results", p.get("performance_gain", ""))),
                    error_and_decoherence=_safe(p.get("error_and_decoherence", p.get("ablation_gap", ""))),
                    future_impact=_safe(p.get("future_impact", p.get("clinical_compliance", ""))),
                    institution=_safe(p.get("institution", "")),
                    idea_takeaway=_safe(p.get("idea_takeaway", "")),
                    next_experiment=_safe(p.get("next_experiment", "")),
                    repro_recipe=_safe(p.get("repro_recipe", "")),
                    fulltext_status=ft_status,
                    analysis_notice=analysis_notice,
                    evidence_anchor=_safe(p.get("evidence_anchor", "")),
                    limitations=_safe(p.get("reviewer_critique", p.get("limitations", ""))),
                    score=max(0, min(100, score)),
                    idea_score=max(1, min(10, idea_score)) if idea_score else 1,
                    analysis_route=analysis_route,
                    hype_stars=hype_stars,
                    url=url,
                )
            )
        else:
            entries.append(
                PAPER_TEMPLATE.format(
                    rank=i,
                    medal=_medal(i),
                    labels=labels,
                    title=_safe(p.get("title", ""), default="未命名论文"),
                    source=_safe(p.get("source", "")),
                    published_date=_normalize_date_text(p.get("published_date", "")),
                    modality=_safe(p.get("modality", "")),
                    task=_safe(p.get("task", "")),
                    architecture=_safe(p.get("architecture", "")),
                    institution=_safe(p.get("institution", "")),
                    innovation_core=_safe(p.get("innovation_core", "")),
                    idea_takeaway=_safe(p.get("idea_takeaway", "")),
                    next_experiment=_safe(p.get("next_experiment", "")),
                    repro_recipe=_safe(p.get("repro_recipe", "")),
                    fulltext_status=ft_status,
                    analysis_notice=analysis_notice,
                    evidence_anchor=_safe(p.get("evidence_anchor", "")),
                    clinical_problem=_safe(p.get("clinical_problem", "")),
                    performance_gain=_safe(p.get("performance_gain", "")),
                    limitations=_safe(p.get("limitations", "")),
                    ablation_gap=_safe(p.get("ablation_gap", "")),
                    score=max(0, min(100, score)),
                    idea_score=max(1, min(10, idea_score)) if idea_score else 1,
                    analysis_route=analysis_route,
                    hype_stars=hype_stars,
                    url=url,
                )
            )

    return DAILY_TEMPLATE.format(
        title=_daily_title(),
        date=datetime.now().strftime("%Y-%m-%d"),
        total_scanned=total_scanned,
        top_count=min(3, len(papers)),
        papers="\n".join(entries) if entries else "今日无高价值候选",
    )


def build_weekly_message(stats: dict[str, dict[str, int]]) -> str:
    return WEEKLY_TEMPLATE.format(
        title=_weekly_title(),
        week=datetime.now().strftime("%Y-W%W"),
        architecture_ranking=_rank_text(stats.get("architecture", {})),
        modality_ranking=_rank_text(stats.get("modality", {})),
    )


def build_daily_wechat_message(papers: list[dict[str, Any]], total_scanned: int) -> str:
    def _safe(v: Any, default: str = "未提及") -> str:
        text = str(v or "").strip()
        if not text:
            return default
        if text.lower() in {"unknown", "none", "n/a", "null"}:
            return default
        return text

    def _normalize_date_text(v: Any) -> str:
        s = _safe(v, default="")
        if not s:
            return datetime.now().strftime("%Y-%m-%d")
        try:
            return date_parser.parse(s, fuzzy=True).date().isoformat()
        except Exception:
            return s

    def _medal(rank: int) -> str:
        return "🥇" if rank == 1 else ("🥈" if rank == 2 else ("🥉" if rank == 3 else "📄"))

    lines: list[str] = []
    is_physics = _is_physics_domain()
    today = datetime.now().strftime("%Y-%m-%d")
    lines.append(f"{_daily_title()} {today}")
    lines.append(f"扫描 {total_scanned} 篇，入选 {min(3, len(papers))} 篇")
    lines.append("")

    if not papers:
        lines.append("今日无高价值候选")
        return "\n".join(lines)

    for i, p in enumerate(papers[:3], start=1):
        title = _safe(p.get("title", ""), default="未命名论文")
        url = _safe(p.get("url", ""), default="#")
        score = int(p.get("score", 0) or 0)
        idea_score = int(p.get("idea_score", 0) or 0)
        route_raw = _safe(p.get("analysis_route", "abstract"), default="abstract").lower()
        analysis_route = "全文" if route_raw == "fulltext" else "摘要"

        fulltext_status_raw = str(p.get("fulltext_status", "")).strip().lower()
        if fulltext_status_raw == "downloaded":
            fulltext_status = "已下载全文"
        elif fulltext_status_raw == "manual_required" or bool(p.get("manual_fulltext_required", False)):
            fulltext_status = "需手动获取全文（当前为摘要降级）"
        elif fulltext_status_raw == "failed":
            fulltext_status = "下载失败（当前为摘要降级）"
        else:
            fulltext_status = "未尝试/不需要"

        lines.append(f"### {_medal(i)} Top {i}: [{title}]({url})")
        lines.append(
            f"- 来源：{_safe(p.get('source', ''))}｜日期：{_normalize_date_text(p.get('published_date', ''))}｜评分：{max(0, min(100, score))}/100｜Idea：{max(1, min(10, idea_score)) if idea_score else 1}/10｜路径：{analysis_route}"
        )
        lines.append(f"- TL;DR：{_safe(p.get('tldr', p.get('innovation_core', '')))}")
        task_modality = _safe(
            p.get(
                "task_modality",
                f"{_safe(p.get('modality', ''))} · {_safe(p.get('task', ''))}",
            )
        )
        if is_physics:
            lines.append(f"- 核心物理系统：{_safe(p.get('physical_system', task_modality))}")
            lines.append(f"- 核心物理机制：{_safe(p.get('core_mechanism', p.get('architecture_innovation', '')))}")
            lines.append(f"- 关键实验装置：{_safe(p.get('experimental_setup', p.get('baselines', '')))}")
            lines.append(f"- 关键结果与极限：{_safe(p.get('key_results', p.get('performance_gain', '')))}")
            lines.append(f"- 误差与退相干：{_safe(p.get('error_and_decoherence', p.get('ablation_gap', '')))}")
            lines.append(f"- 下一步影响：{_safe(p.get('future_impact', p.get('clinical_compliance', '')))}")
        else:
            lines.append(f"- 场景与任务：{task_modality}")
            lines.append(f"- 架构创新：{_safe(p.get('architecture_innovation', p.get('architecture', '')))}")
        lines.append(f"- 可复用Idea：{_safe(p.get('idea_takeaway', ''))}")
        lines.append(f"- 下一步实验：{_safe(p.get('next_experiment', ''))}")
        lines.append(f"- 最小复现路径：{_safe(p.get('repro_recipe', ''))}")
        lines.append(f"- 全文状态：{fulltext_status}")
        lines.append(f"- 分析标记：{_safe(p.get('analysis_notice', '⚠️ 仅摘要分析 (全文获取受阻)'))}")
        lines.append(f"- 证据锚点：{_safe(p.get('evidence_anchor', ''))}")
        if not is_physics:
            lines.append(f"- 临床与工程价值：{_safe(p.get('clinical_compliance', p.get('clinical_problem', '')))}")
            lines.append(f"- 基线与提升：{_safe(p.get('baselines', p.get('performance_gain', '')))}")
        lines.append(f"- 主要局限：{_safe(p.get('reviewer_critique', p.get('limitations', '')))}")
        if not is_physics:
            lines.append(f"- 缺失消融：{_safe(p.get('ablation_gap', ''))}")
        lines.append("")

    return "\n".join(lines).strip()


def send_webhook(text: str, webhook_url: str) -> None:
    if not webhook_url:
        return
    try:
        if "sctapi.ftqq.com" in webhook_url:
            lines = [ln for ln in text.splitlines()]
            title = (lines[0].strip() if lines else _notify_brand())[:100]
            desp = "\n".join(lines[1:]).strip() if len(lines) > 1 else text
            resp = requests.post(webhook_url, data={"title": title, "desp": desp}, timeout=20)
            resp.raise_for_status()
            try:
                payload = resp.json()
            except Exception as exc:
                raise RuntimeError(f"Server酱返回非JSON响应: {(resp.text or '')[:200]}") from exc
            code = payload.get("code")
            if code not in {0, "0", None}:
                raise RuntimeError(f"Server酱推送失败 code={code} message={payload.get('message') or payload.get('msg')}")
            logging.info("Webhook 推送成功: serverchan title=%s code=%s", title, code)
        else:
            resp = requests.post(webhook_url, json={"text": text}, timeout=20)
            resp.raise_for_status()
            logging.info("Webhook 推送成功: status=%s url=%s", resp.status_code, webhook_url[:120])
    except Exception as exc:
        logging.exception("Webhook 推送失败: %s", exc)
        raise


def send_weekly_report_msg(
    stats: dict[str, dict[str, int]],
    webhook_url: str,
) -> None:
    message = build_weekly_message(stats)
    send_webhook(message, webhook_url)
