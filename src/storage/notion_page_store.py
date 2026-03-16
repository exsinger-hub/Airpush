from __future__ import annotations

import logging
import json
import os
import re
import ast
from datetime import datetime
from typing import Any

import requests


class NotionPageStore:
    def __init__(self, token: str, page_id: str):
        self.parent_page_id = self._normalize_id(page_id)
        self.page_id = self.parent_page_id
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Notion-Version": "2022-06-28",
            "Content-Type": "application/json",
        }

    def _append_blocks(self, blocks: list[dict[str, Any]]) -> None:
        if not blocks:
            return
        for i in range(0, len(blocks), 100):
            payload = {"children": blocks[i : i + 100]}
            resp = requests.patch(
                f"https://api.notion.com/v1/blocks/{self.page_id}/children",
                headers=self.headers,
                json=payload,
                timeout=30,
            )
            resp.raise_for_status()

    def _find_child_page_by_title(self, title: str) -> str:
        cursor: str | None = None
        target = (title or "").strip()
        if not target:
            return ""

        while True:
            url = f"https://api.notion.com/v1/blocks/{self.parent_page_id}/children?page_size=100"
            if cursor:
                url += f"&start_cursor={cursor}"
            resp = requests.get(url, headers=self.headers, timeout=30)
            resp.raise_for_status()
            data = resp.json()

            for item in data.get("results", []):
                if str(item.get("type", "")) != "child_page":
                    continue
                child_title = str(item.get("child_page", {}).get("title", "")).strip()
                if child_title == target and item.get("id"):
                    return str(item["id"])

            if not data.get("has_more"):
                break
            cursor = data.get("next_cursor")
            if not cursor:
                break

        return ""

    def use_daily_page(self, title: str, reuse_existing: bool = True, icon: str = "📰") -> str:
        page_title = (title or "").strip()
        if not page_title:
            page_title = datetime.now().strftime("%Y-%m-%d")

        if reuse_existing:
            existing = self._find_child_page_by_title(page_title)
            if existing:
                self.page_id = self._normalize_id(existing)
                logging.info("Notion 复用当日子页面: %s (%s)", page_title, self.page_id)
                return self.page_id

        payload = {
            "parent": {"page_id": self.parent_page_id},
            "icon": {"type": "emoji", "emoji": icon or "📰"},
            "properties": {
                "title": {
                    "title": [
                        {
                            "type": "text",
                            "text": {"content": page_title[:2000]},
                        }
                    ]
                }
            },
        }
        resp = requests.post("https://api.notion.com/v1/pages", headers=self.headers, json=payload, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        new_page_id = self._normalize_id(str(data.get("id", "")))
        if new_page_id:
            self.page_id = new_page_id
            logging.info("Notion 已创建当日子页面: %s (%s)", page_title, self.page_id)
        return self.page_id

    @staticmethod
    def _normalize_id(raw_id: str) -> str:
        value = (raw_id or "").strip()
        match = re.search(r"([0-9a-fA-F]{32})", value)
        if match:
            hex32 = match.group(1)
            return f"{hex32[:8]}-{hex32[8:12]}-{hex32[12:16]}-{hex32[16:20]}-{hex32[20:32]}"
        hex32 = re.sub(r"[^0-9a-fA-F]", "", value)
        if len(hex32) == 32:
            return f"{hex32[:8]}-{hex32[8:12]}-{hex32[12:16]}-{hex32[16:20]}-{hex32[20:32]}"
        return value

    @staticmethod
    def _plain_text(text: str) -> dict[str, Any]:
        return {"type": "text", "text": {"content": text[:2000]}}

    @staticmethod
    def _annot_text(text: str, *, bold: bool = False, code: bool = False, italic: bool = False) -> dict[str, Any]:
        return {
            "type": "text",
            "text": {"content": text[:2000]},
            "annotations": {
                "bold": bold,
                "italic": italic,
                "strikethrough": False,
                "underline": False,
                "code": code,
                "color": "default",
            },
        }

    @staticmethod
    def _link_text(text: str, url: str) -> dict[str, Any]:
        return {
            "type": "text",
            "text": {
                "content": text[:2000],
                "link": {"url": url},
            },
        }

    @classmethod
    def _split_text(cls, text: str) -> list[dict[str, Any]]:
        """将长文本拆分为多个 rich_text 元素（Notion API 单元素上限 2000 字符）。"""
        if not text:
            return [cls._plain_text("")]
        return [cls._plain_text(text[i : i + 1900]) for i in range(0, len(text), 1900)]

    @classmethod
    def _to_rich_text(cls, text: str) -> list[dict[str, Any]]:
        # 支持最常见的内联语法：链接 [x](url)、粗体 **x**、代码 `x`、斜体 *x*
        pattern = re.compile(r"(\[([^\]]+)\]\((https?://[^)]+)\)|\*\*([^*]+)\*\*|`([^`]+)`|\*([^*]+)\*)")
        rich: list[dict[str, Any]] = []
        pos = 0

        for m in pattern.finditer(text):
            if m.start() > pos:
                plain = text[pos : m.start()]
                if plain:
                    rich.append(cls._plain_text(plain))

            if m.group(2) and m.group(3):
                rich.append(cls._link_text(m.group(2), m.group(3)))
            elif m.group(4):
                rich.append(cls._annot_text(m.group(4), bold=True))
            elif m.group(5):
                rich.append(cls._annot_text(m.group(5), code=True))
            elif m.group(6):
                rich.append(cls._annot_text(m.group(6), italic=True))

            pos = m.end()

        if pos < len(text):
            tail = text[pos:]
            if tail:
                rich.append(cls._plain_text(tail))

        return rich or [cls._plain_text(text)]

    @classmethod
    def _to_blocks(cls, markdown_text: str) -> list[dict[str, Any]]:
        blocks: list[dict[str, Any]] = []
        for raw in markdown_text.splitlines():
            line = raw.strip()
            if not line:
                continue

            if line in {"---", "***", "___"}:
                blocks.append({"object": "block", "type": "divider", "divider": {}})
                continue

            if line.startswith("# "):
                blocks.append(
                    {
                        "object": "block",
                        "type": "heading_1",
                        "heading_1": {"rich_text": cls._to_rich_text(line[2:])},
                    }
                )
            elif line.startswith("## "):
                blocks.append(
                    {
                        "object": "block",
                        "type": "heading_2",
                        "heading_2": {"rich_text": cls._to_rich_text(line[3:])},
                    }
                )
            elif line.startswith("### "):
                blocks.append(
                    {
                        "object": "block",
                        "type": "heading_3",
                        "heading_3": {"rich_text": cls._to_rich_text(line[4:])},
                    }
                )
            elif line.startswith("- ") or line.startswith("* "):
                blocks.append(
                    {
                        "object": "block",
                        "type": "bulleted_list_item",
                        "bulleted_list_item": {
                            "rich_text": cls._to_rich_text(line[2:])
                        },
                    }
                )
            elif re.match(r"^\d+\.\s+", line):
                content = re.sub(r"^\d+\.\s+", "", line)
                blocks.append(
                    {
                        "object": "block",
                        "type": "numbered_list_item",
                        "numbered_list_item": {"rich_text": cls._to_rich_text(content)},
                    }
                )
            elif line.startswith("> "):
                blocks.append(
                    {
                        "object": "block",
                        "type": "quote",
                        "quote": {"rich_text": cls._to_rich_text(line[2:])},
                    }
                )
            else:
                blocks.append(
                    {
                        "object": "block",
                        "type": "paragraph",
                        "paragraph": {"rich_text": cls._to_rich_text(line)},
                    }
                )
        return blocks

    @classmethod
    def _paper_to_blocks(cls, paper: dict[str, Any], rank: int) -> list[dict[str, Any]]:
        def _safe_text(v: Any, default: str = "未提及") -> str:
            s = str(v or "").strip()
            if not s:
                return default
            if s.lower() in {"unknown", "none", "null", "n/a"}:
                return default
            return s

        def _format_struct(v: Any) -> str:
            if v is None:
                return "未提及"

            if isinstance(v, str):
                s = v.strip()
                if not s:
                    return "未提及"
                if s.lower() in {"unknown", "none", "null", "n/a", "未提及"}:
                    return "未提及"

                if s.startswith("[") or s.startswith("{"):
                    parsed: Any | None = None
                    try:
                        parsed = json.loads(s)
                    except Exception:
                        try:
                            parsed = ast.literal_eval(s)
                        except Exception:
                            parsed = None
                    if parsed is not None:
                        return _format_struct(parsed)
                return s

            if isinstance(v, list):
                if not v:
                    return "未提及"
                lines: list[str] = []
                for idx, item in enumerate(v, start=1):
                    if isinstance(item, dict):
                        parts: list[str] = []
                        for k, val in item.items():
                            fv = _format_struct(val)
                            if fv == "未提及":
                                continue
                            parts.append(f"{k}: {fv.replace(chr(10), '；')}")
                        lines.append(f"{idx}. " + ("；".join(parts) if parts else "未提及"))
                    else:
                        lines.append(f"{idx}. {_format_struct(item)}")
                return "\n".join(lines) if lines else "未提及"

            if isinstance(v, dict):
                if not v:
                    return "未提及"
                parts: list[str] = []
                for k, val in v.items():
                    fv = _format_struct(val)
                    if fv == "未提及":
                        continue
                    parts.append(f"{k}: {fv.replace(chr(10), '；')}")
                return "；".join(parts) if parts else "未提及"

            s = str(v).strip()
            return s if s else "未提及"

        def _paragraph_blocks(text: str) -> list[dict[str, Any]]:
            content = _safe_text(text)
            if content == "未提及":
                return [
                    {
                        "object": "block",
                        "type": "paragraph",
                        "paragraph": {"rich_text": [cls._plain_text("未提及")]},
                    }
                ]

            blocks: list[dict[str, Any]] = []
            for i in range(0, len(content), 1800):
                chunk = content[i : i + 1800]
                blocks.append(
                    {
                        "object": "block",
                        "type": "paragraph",
                        "paragraph": {"rich_text": [cls._plain_text(chunk)]},
                    }
                )
            return blocks

        title = str(paper.get("title", "未命名论文"))
        paper_url = str(paper.get("url", "") or paper.get("pdf_url", "")).strip()
        source = str(paper.get("source", "unknown"))
        date = str(paper.get("published_date", "未知"))
        pushed_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        domain = os.getenv("DOMAIN", "").strip().lower()
        is_physics = domain in {"cqed_plasmonics", "physics", "quantum", "plasmonics", "cqed"}

        analysis_tldr = _format_struct(paper.get("tldr", "未提及"))
        task_modality = _format_struct(paper.get("task_modality", "未提及"))
        arch_innovation = _format_struct(paper.get("architecture_innovation", paper.get("innovation_core", "未提及")))
        baselines = _format_struct(paper.get("baselines", "未提及"))
        physical_system = _format_struct(paper.get("physical_system", task_modality))
        core_mechanism = _format_struct(paper.get("core_mechanism", arch_innovation))
        experimental_setup = _format_struct(paper.get("experimental_setup", baselines))
        key_results = _format_struct(paper.get("key_results", paper.get("performance_gain", "未提及")))
        error_and_decoherence = _format_struct(paper.get("error_and_decoherence", paper.get("ablation_gap", "未提及")))
        future_impact = _format_struct(
            paper.get("future_impact")
            or paper.get("engineering_value")
            or paper.get("application_value")
            or paper.get("clinical_compliance", "未提及")
        )
        value_focus = (
            str(paper.get("engineering_value", "")).strip()
            or str(paper.get("application_value", "")).strip()
            or str(paper.get("clinical_compliance", paper.get("clinical_problem", "未提及")))
        )
        critique = _format_struct(paper.get("reviewer_critique", paper.get("limitations", "未提及")))
        idea_takeaway = _format_struct(paper.get("idea_takeaway", "未提及"))
        repro_recipe = _format_struct(paper.get("repro_recipe", "未提及"))
        next_experiment = _format_struct(paper.get("next_experiment", "未提及"))
        ablation_gap = _format_struct(paper.get("ablation_gap", "未提及"))
        method_pipeline = _format_struct(paper.get("method_pipeline", "未提及"))
        experimental_protocol = _format_struct(paper.get("experimental_protocol", "未提及"))
        quantitative_results = _format_struct(
            paper.get("quantitative_results", paper.get("key_results", paper.get("performance_gain", "未提及")))
        )
        failure_boundary = _format_struct(paper.get("failure_boundary", "未提及"))
        reproducibility_checklist = _format_struct(paper.get("reproducibility_checklist", "未提及"))
        evidence_map = _format_struct(paper.get("evidence_map", "未提及"))
        idea_score = str(paper.get("idea_score", "未提及"))
        score = str(paper.get("score", "未提及"))
        evidence_anchor = str(paper.get("evidence_anchor", "未提及"))
        clinical_problem = _format_struct(paper.get("clinical_problem", "未提及"))
        innovation_core = _format_struct(paper.get("innovation_core", "未提及"))
        performance_gain = _format_struct(paper.get("performance_gain", paper.get("key_results", "未提及")))
        route = str(paper.get("analysis_route", "abstract")).strip().lower()
        route_text = "全文" if route == "fulltext" else "摘要"
        detail_mode = str(os.getenv("NOTION_DETAIL_MODE", "rich_when_fulltext")).strip().lower()
        rich_fulltext = route == "fulltext" and detail_mode in {"rich_when_fulltext", "rich", "fulltext_rich"}
        analysis_notice = str(paper.get("analysis_notice", "⚠️ 仅摘要分析 (全文获取受阻)"))
        abstract_en = _safe_text(paper.get("abstract", ""))
        abstract_zh = _safe_text(
            paper.get("abstract_zh")
            or paper.get("abstract_cn")
            or paper.get("translated_abstract")
            or paper.get("abstract_translation"),
            default="未提及",
        )
        figure_items_raw = paper.get("figure_items", [])
        figure_items: list[dict[str, str]] = []
        if isinstance(figure_items_raw, str):
            try:
                parsed = json.loads(figure_items_raw)
                figure_items_raw = parsed if isinstance(parsed, list) else []
            except Exception:
                figure_items_raw = []
        if isinstance(figure_items_raw, list):
            for idx, item in enumerate(figure_items_raw, start=1):
                if isinstance(item, dict):
                    figure_url = str(item.get("url", "") or "").strip()
                    caption = _format_struct(item.get("caption", f"图{idx}"))
                    if figure_url:
                        figure_items.append({"url": figure_url, "caption": caption})

        figure_urls_raw = paper.get("figure_urls", [])
        if isinstance(figure_urls_raw, str):
            try:
                parsed = json.loads(figure_urls_raw)
                figure_urls = parsed if isinstance(parsed, list) else []
            except Exception:
                figure_urls = [figure_urls_raw] if figure_urls_raw.strip() else []
        elif isinstance(figure_urls_raw, list):
            figure_urls = [str(u).strip() for u in figure_urls_raw if str(u).strip()]
        else:
            figure_urls = []
        if not figure_items and figure_urls:
            figure_items = [{"url": u, "caption": f"图{idx}：论文关键图表"} for idx, u in enumerate(figure_urls[:6], start=1)]

        # 图注中文翻译：从 paper dict 提取 LLM 翻译结果
        _captions_zh_raw = paper.get("figure_captions_zh", {})
        if isinstance(_captions_zh_raw, str):
            try:
                _captions_zh_raw = json.loads(_captions_zh_raw)
            except Exception:
                _captions_zh_raw = {}
        figure_captions_zh: dict[str, str] = _captions_zh_raw if isinstance(_captions_zh_raw, dict) else {}

        fulltext_status_raw = str(paper.get("fulltext_status", "")).strip().lower()
        if fulltext_status_raw == "downloaded":
            fulltext_status = "已下载全文"
        elif fulltext_status_raw == "manual_required" or bool(paper.get("manual_fulltext_required", False)):
            fulltext_status = "⚠️ 需手动获取全文（当前为摘要降级）"
        elif fulltext_status_raw == "failed":
            fulltext_status = "下载失败（当前为摘要降级）"
        else:
            fulltext_status = "未尝试/不需要"

        def bullet(label: str, content: str, icon: str = "") -> dict[str, Any]:
            prefix = f"{icon} {label}: " if icon else f"{label}: "
            rich: list[dict[str, Any]] = [cls._annot_text(prefix, bold=True)]
            rich.extend(cls._split_text(content if content else "未提及"))
            return {
                "object": "block",
                "type": "bulleted_list_item",
                "bulleted_list_item": {"rich_text": rich},
            }

        heading_text = f"🥇 Top {rank}: {title}" if rank == 1 else f"📄 Top {rank}: {title}"
        heading_rt = [cls._link_text(heading_text, paper_url)] if paper_url else [cls._plain_text(heading_text)]

        value_label = "实验与工程价值" if is_physics else "临床与工程价值"
        value_icon = "⚙️" if is_physics else "🏥"

        blocks = [
            {
                "object": "block",
                "type": "heading_2",
                "heading_2": {"rich_text": heading_rt},
            },
            {
                "object": "block",
                "type": "quote",
                "quote": {
                    "rich_text": [
                        cls._plain_text(
                            f"🔗 来源: {source} | 📅 论文日期: {date} | 🕒 推送时间: {pushed_time} | 🧭 路径: {route_text} | 📊 评分: {score}/100"
                        ),
                    ]
                },
            },
            {"object": "block", "type": "divider", "divider": {}},
            {
                "object": "block",
                "type": "heading_3",
                "heading_3": {"rich_text": [cls._plain_text("📝 一句话 TL;DR")]},
            },
            {
                "object": "block",
                "type": "paragraph",
                "paragraph": {"rich_text": [cls._annot_text(analysis_tldr, italic=True)]},
            },
            {
                "object": "block",
                "type": "heading_3",
                "heading_3": {"rich_text": [cls._plain_text("📄 摘要（原文）")]},
            },
        ]

        blocks.extend(_paragraph_blocks(abstract_en))
        blocks.extend(
            [
                {
                    "object": "block",
                    "type": "heading_3",
                    "heading_3": {"rich_text": [cls._plain_text("🌐 摘要翻译（中文）")]},
                },
            ]
        )
        blocks.extend(_paragraph_blocks(abstract_zh))

        if figure_items:
            blocks.append(
                {
                    "object": "block",
                    "type": "heading_3",
                    "heading_3": {"rich_text": [cls._plain_text("🖼️ 关键图表（自动提取）")]},
                }
            )
            for item in figure_items[:6]:
                blocks.append(
                    {
                        "object": "block",
                        "type": "image",
                        "image": {"type": "external", "external": {"url": item["url"]}},
                    }
                )
                caption_text = _format_struct(item.get("caption", "图注缺失"))
                # 尝试匹配中文图注：从 "Figure N: ..." 提取 key
                fig_key_match = re.match(r"(Fig(?:ure)?\s*\.?\s*\d+)", caption_text, re.IGNORECASE)
                caption_zh = ""
                if fig_key_match:
                    raw_key = fig_key_match.group(1).strip()
                    norm_key = re.sub(r"(?i)fig(?:ure)?\s*\.?\s*(\d+)", r"Figure \1", raw_key)
                    caption_zh = figure_captions_zh.get(norm_key, "")
                # 英文图注
                for i in range(0, len(caption_text), 1800):
                    chunk = caption_text[i : i + 1800]
                    blocks.append(
                        {
                            "object": "block",
                            "type": "paragraph",
                            "paragraph": {
                                "rich_text": [cls._annot_text(chunk or "图注缺失", italic=True)]
                            },
                        }
                    )
                # 中文图注（若有）
                if caption_zh and caption_zh.strip():
                    for i in range(0, len(caption_zh), 1800):
                        chunk = caption_zh[i : i + 1800]
                        blocks.append(
                            {
                                "object": "block",
                                "type": "paragraph",
                                "paragraph": {
                                    "rich_text": [
                                        cls._annot_text("🇨🇳 ", bold=True),
                                        cls._plain_text(chunk),
                                    ]
                                },
                            }
                        )

        if is_physics:
            blocks.extend(
                [
                    {
                        "object": "block",
                        "type": "heading_3",
                        "heading_3": {"rich_text": [cls._plain_text("⚛️ 核心物理图像")]},
                    },
                    bullet("核心物理系统", physical_system, "🧭"),
                    bullet("核心物理机制", core_mechanism, "🌀"),
                    bullet("核心创新", innovation_core, "💡"),
                    bullet("关键指标", performance_gain, "📊"),
                    bullet("关键实验装置", experimental_setup, "🔬"),
                    bullet("关键结果与极限", key_results, "📈"),
                    bullet("误差与退相干", error_and_decoherence, "🧯"),
                    bullet("下一步影响", future_impact, "🚀"),
                    bullet("可复用Idea", idea_takeaway, "🪄"),
                    bullet("最小复现路径", repro_recipe, "🔁"),
                    bullet("下一步实验", next_experiment, "🧪"),
                    bullet("全文状态", fulltext_status, "📄"),
                    bullet("分析标记", analysis_notice, "🚦"),
                    bullet("证据锚点", evidence_anchor, "📌"),
                    {
                        "object": "block",
                        "type": "callout",
                        "callout": {
                            "icon": {"type": "emoji", "emoji": "🧐"},
                            "color": "gray_background",
                            "rich_text": [
                                cls._annot_text(f"Idea分: {idea_score} / 10 | ", bold=True),
                                cls._annot_text("审稿人点评: ", bold=True),
                                *cls._split_text(critique),
                            ],
                        },
                    },
                    {"object": "block", "type": "divider", "divider": {}},
                ]
            )
            if rich_fulltext:
                blocks.extend(
                    [
                        {
                            "object": "block",
                            "type": "heading_3",
                            "heading_3": {"rich_text": [cls._plain_text("📚 全文深度拆解（物理）")]},
                        },
                        bullet("方法/实验流程", method_pipeline, "🧩"),
                        bullet("实验协议细节", experimental_protocol, "🧪"),
                        bullet("结果-证据映射", evidence_map, "🗺️"),
                        bullet("失败案例与边界", failure_boundary, "🧱"),
                        bullet("复现清单", reproducibility_checklist, "✅"),
                        {"object": "block", "type": "divider", "divider": {}},
                    ]
                )
        else:
            blocks.extend(
                [
                    {
                        "object": "block",
                        "type": "heading_3",
                        "heading_3": {"rich_text": [cls._plain_text("🛠️ 核心技术拆解")]},
                    },
                    bullet("临床痛点", clinical_problem, "🩺"),
                    bullet("核心创新", innovation_core, "💡"),
                    bullet("性能提升", performance_gain, "📊"),
                    bullet("场景与模态", task_modality, "🎯"),
                    bullet("架构创新", arch_innovation, "🧠"),
                    bullet("基线与对比", baselines, "📈"),
                    bullet(value_label, value_focus, value_icon),
                    bullet("缺失消融", ablation_gap, "🧷"),
                    bullet("证据锚点", evidence_anchor, "📌"),
                    bullet("可复用Idea", idea_takeaway, "🪄"),
                    bullet("最小复现路径", repro_recipe, "🔁"),
                    bullet("下一步实验", next_experiment, "🧪"),
                    bullet("全文状态", fulltext_status, "📄"),
                    bullet("分析标记", analysis_notice, "🚦"),
                    {
                        "object": "block",
                        "type": "callout",
                        "callout": {
                            "icon": {"type": "emoji", "emoji": "🧐"},
                            "color": "gray_background",
                            "rich_text": [
                                cls._annot_text(f"Idea分: {idea_score} / 10 | ", bold=True),
                                cls._annot_text("审稿人点评: ", bold=True),
                                *cls._split_text(critique),
                            ],
                        },
                    },
                    {"object": "block", "type": "divider", "divider": {}},
                ]
            )
            if rich_fulltext:
                blocks.extend(
                    [
                        {
                            "object": "block",
                            "type": "heading_3",
                            "heading_3": {"rich_text": [cls._plain_text("📚 全文深度拆解")]}},
                        bullet("方法流程分解", method_pipeline, "🧩"),
                        bullet("实验协议细节", experimental_protocol, "🧪"),
                        bullet("关键定量结果", quantitative_results, "📐"),
                        bullet("结果-证据映射", evidence_map, "🗺️"),
                        bullet("失败案例与边界", failure_boundary, "🧱"),
                        bullet("复现清单", reproducibility_checklist, "✅"),
                        {"object": "block", "type": "divider", "divider": {}},
                    ]
                )

        return blocks

    def append_papers(self, papers: list[dict[str, Any]]) -> None:
        blocks: list[dict[str, Any]] = []
        for idx, p in enumerate(papers, start=1):
            blocks.extend(self._paper_to_blocks(p, idx))
        self._append_blocks(blocks)

    def append_markdown(self, markdown_text: str) -> None:
        blocks = self._to_blocks(markdown_text)
        self._append_blocks(blocks)

    def _list_children_ids(self) -> list[str]:
        ids: list[str] = []
        cursor: str | None = None
        while True:
            url = f"https://api.notion.com/v1/blocks/{self.page_id}/children?page_size=100"
            if cursor:
                url += f"&start_cursor={cursor}"
            resp = requests.get(url, headers=self.headers, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            for item in data.get("results", []):
                bid = item.get("id")
                if bid:
                    ids.append(bid)
            if not data.get("has_more"):
                break
            cursor = data.get("next_cursor")
            if not cursor:
                break
        return ids

    def clear_page(self) -> None:
        for bid in self._list_children_ids():
            resp = requests.delete(f"https://api.notion.com/v1/blocks/{bid}", headers=self.headers, timeout=30)
            resp.raise_for_status()

    def sync_markdown(self, markdown_text: str, replace: bool = True) -> None:
        if replace:
            self.clear_page()
        self.append_markdown(markdown_text)

    def sync_papers(self, papers: list[dict[str, Any]], replace: bool = True) -> None:
        if replace:
            self.clear_page()
        self.append_papers(papers)
