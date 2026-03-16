from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any

import requests
from dateutil import parser as date_parser
from tenacity import retry, stop_after_attempt, wait_exponential


class NotionStore:
    def __init__(self, token: str, database_id: str):
        self.database_id = self._normalize_id(database_id)
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Notion-Version": "2022-06-28",
            "Content-Type": "application/json",
        }
        self.title_property = "Title"
        self.prop_map = {
            "modality": "Modality",
            "task": "Task",
            "architecture": "Architecture",
            "score": "Score",
            "tags": "Tags",
            "innovation": "Innovation",
            "source": "Source",
            "date": "Date",
        }
        self._sync_schema()

    def _sync_schema(self) -> None:
        """读取数据库结构，并自动补齐非 title 字段。"""
        resp = requests.get(
            f"https://api.notion.com/v1/databases/{self.database_id}",
            headers=self.headers,
            timeout=30,
        )
        if resp.status_code >= 400:
            logging.error(
                "Notion 读取数据库失败 status=%s db_id=%s body=%s",
                resp.status_code,
                self.database_id,
                resp.text[:500],
            )
            resp.raise_for_status()

        data = resp.json()
        props: dict[str, Any] = data.get("properties", {})

        # 自动识别 title 列名（可能是 Name 而非 Title）
        for name, conf in props.items():
            if conf.get("type") == "title":
                self.title_property = name
                break

        # 目标字段定义：逻辑名 -> (首选字段名, 期望类型, schema)
        definitions: dict[str, tuple[str, str, dict[str, Any]]] = {
            "modality": ("Modality", "select", {"select": {}}),
            "task": ("Task", "select", {"select": {}}),
            "architecture": ("Architecture", "select", {"select": {}}),
            "score": ("Score", "number", {"number": {}}),
            "tags": ("Tags", "multi_select", {"multi_select": {}}),
            "innovation": ("Innovation", "rich_text", {"rich_text": {}}),
            "source": ("Source", "url", {"url": {}}),
            "date": ("Date", "date", {"date": {}}),
        }

        patch_properties: dict[str, Any] = {}
        for logical, (preferred, expected_type, schema) in definitions.items():
            # 优先使用同名且类型匹配字段
            if preferred in props and props[preferred].get("type") == expected_type:
                self.prop_map[logical] = preferred
                continue

            # 其次使用已存在的 MPF_ 备份字段
            fallback = f"MPF_{preferred}"
            if fallback in props and props[fallback].get("type") == expected_type:
                self.prop_map[logical] = fallback
                continue

            # 否则创建 MPF_ 字段，避免与已有错误类型字段冲突
            patch_properties[fallback] = schema
            self.prop_map[logical] = fallback

        if patch_properties:
            patch_resp = requests.patch(
                f"https://api.notion.com/v1/databases/{self.database_id}",
                headers=self.headers,
                json={"properties": patch_properties},
                timeout=30,
            )
            if patch_resp.status_code >= 400:
                logging.error(
                    "Notion 补字段失败 status=%s db_id=%s body=%s",
                    patch_resp.status_code,
                    self.database_id,
                    patch_resp.text[:500],
                )
                patch_resp.raise_for_status()
            logging.info("Notion 已自动补齐字段: %s", ", ".join(patch_properties.keys()))

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
    def _normalize_date(value: Any) -> str:
        s = str(value or "").strip()
        if not s:
            return datetime.utcnow().date().isoformat()

        # 已是 ISO 日期
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
            return s

        # 处理像 "2026 Mar 6" / "2026" / 其他常见格式
        try:
            dt = date_parser.parse(s, fuzzy=True, default=datetime.utcnow())
            return dt.date().isoformat()
        except Exception:
            pass

        year_match = re.fullmatch(r"\d{4}", s)
        if year_match:
            return f"{s}-01-01"

        return datetime.utcnow().date().isoformat()

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10), reraise=True)
    def write(self, paper: dict[str, Any]) -> None:
        payload = {
            "parent": {"database_id": self.database_id},
            "properties": {
                self.title_property: {"title": [{"text": {"content": paper.get("title", "Untitled")[:2000]}}]},
                self.prop_map["modality"]: {"select": {"name": (paper.get("modality") or "Unknown")[:100]}},
                self.prop_map["task"]: {"select": {"name": (paper.get("task") or "Unknown")[:100]}},
                self.prop_map["architecture"]: {"select": {"name": (paper.get("architecture") or "Unknown")[:100]}},
                self.prop_map["score"]: {"number": int(paper.get("score", 0))},
                self.prop_map["tags"]: {"multi_select": [{"name": str(l)[:100]} for l in paper.get("labels", [])[:20]]},
                self.prop_map["innovation"]: {"rich_text": [{"text": {"content": (paper.get("innovation_core") or "")[:2000]}}]},
                self.prop_map["source"]: {"url": paper.get("url", "") or None},
                self.prop_map["date"]: {"date": {"start": self._normalize_date(paper.get("published_date"))}},
            },
        }

        resp = requests.post("https://api.notion.com/v1/pages", headers=self.headers, json=payload, timeout=30)
        if resp.status_code >= 400:
            logging.error(
                "Notion 写入失败 status=%s db_id=%s body=%s",
                resp.status_code,
                self.database_id,
                resp.text[:500],
            )
        resp.raise_for_status()
