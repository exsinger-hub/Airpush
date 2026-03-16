from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import requests
import yaml

REQUIRED_FIELDS = {
    "Modality": "select",
    "Task": "select",
    "Architecture": "select",
    "Score": "number",
    "Tags": "multi_select",
    "Innovation": "rich_text",
    "Source": "url",
    "Date": "date",
}


def main() -> int:
    token = os.getenv("NOTION_TOKEN", "").strip()
    db_id = os.getenv("NOTION_DB_ID", "").strip()

    cfg_path = Path("config/runtime.yaml")
    if cfg_path.exists():
        with cfg_path.open("r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        notion = cfg.get("notion", {}) if isinstance(cfg.get("notion", {}), dict) else {}
        token = token or str(notion.get("token", "")).strip()
        db_id = db_id or str(notion.get("database_id", "")).strip()

    if not token or not db_id:
        print("缺少环境变量：NOTION_TOKEN 或 NOTION_DB_ID")
        return 1

    hex32 = re.sub(r"[^0-9a-fA-F]", "", db_id)
    if len(hex32) == 32:
        db_id = f"{hex32[:8]}-{hex32[8:12]}-{hex32[12:16]}-{hex32[16:20]}-{hex32[20:32]}"

    headers = {
        "Authorization": f"Bearer {token}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json",
    }

    resp = requests.get(f"https://api.notion.com/v1/databases/{db_id}", headers=headers, timeout=30)
    if resp.status_code >= 400:
        print(f"访问数据库失败: {resp.status_code} {resp.text[:300]}")
        # 常见误配置：传入 page_id 而非 database_id
        page_resp = requests.get(f"https://api.notion.com/v1/pages/{db_id}", headers=headers, timeout=30)
        if page_resp.status_code == 200:
            print("检测到该 ID 是 page，不是 database。请打开数据库本体页面复制 database_id。")
        return 2

    data = resp.json()
    props = data.get("properties", {})
    title_fields = [name for name, conf in props.items() if conf.get("type") == "title"]

    missing: list[str] = []
    mismatch: list[str] = []

    for name, expected_type in REQUIRED_FIELDS.items():
        preferred = props.get(name)
        fallback = props.get(f"MPF_{name}")

        if preferred and preferred.get("type") == expected_type:
            continue
        if fallback and fallback.get("type") == expected_type:
            continue

        if not preferred and not fallback:
            missing.append(name)
            continue

        preferred_type = preferred.get("type") if preferred else "无"
        fallback_type = fallback.get("type") if fallback else "无"
        mismatch.append(
            f"{name}: 期望 {expected_type}, 实际 {preferred_type} (fallback MPF_{name}: {fallback_type})"
        )

    print("Notion 连接成功")
    print(f"数据库标题: {data.get('title', [])}")
    if title_fields:
        print("Title 列:", ", ".join(title_fields))
    else:
        print("未检测到 title 列，请在 Notion 数据库保留至少一个 title 属性")

    if missing:
        print("缺少字段:", ", ".join(missing))
    if mismatch:
        print("字段类型不匹配:")
        for item in mismatch:
            print("-", item)

    if title_fields and not missing and not mismatch:
        print("字段校验通过，可直接运行主流程。")
        return 0

    return 3


if __name__ == "__main__":
    sys.exit(main())
