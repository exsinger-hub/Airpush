from __future__ import annotations

import json
import logging
from typing import Any

import requests

OLLAMA_BASE = "http://localhost:11434"

QUICK_FILTER_PROMPT = """判断论文是否属于以下任一方向：
A. 医学图像生成/合成/转换
B. 医学图像高分辨率重建/超分辨率/去噪
C. 医疗AI智能体/LLM临床应用

只输出 JSON: {\"relevant\": true/false, \"topic\": \"A|B|C|null\"}
标题: {title}
摘要: {snippet}
"""

TOPIC_MAP = {"A": "imaging", "B": "recon", "C": "agent"}


class LocalLLM:
    def __init__(self, model: str = "qwen2.5:7b"):
        self.model = model

    def is_available(self) -> bool:
        try:
            resp = requests.get(f"{OLLAMA_BASE}/api/tags", timeout=2)
            return resp.status_code < 400
        except Exception:
            return False

    @staticmethod
    def _safe_json(text: str) -> dict[str, Any]:
        try:
            return json.loads(text)
        except Exception:
            start = text.find("{")
            end = text.rfind("}")
            if start != -1 and end > start:
                try:
                    return json.loads(text[start : end + 1])
                except Exception:
                    pass
            return {}

    def quick_filter(self, papers: list[dict[str, Any]]) -> list[dict[str, Any]]:
        relevant: list[dict[str, Any]] = []
        for paper in papers:
            try:
                prompt = QUICK_FILTER_PROMPT.format(
                    title=paper.get("title", ""),
                    snippet=paper.get("abstract", "")[:180],
                )
                resp = requests.post(
                    f"{OLLAMA_BASE}/api/generate",
                    json={
                        "model": self.model,
                        "prompt": prompt,
                        "stream": False,
                        "options": {"temperature": 0, "num_predict": 40},
                    },
                    timeout=30,
                )
                resp.raise_for_status()
                text = (resp.json() or {}).get("response", "")
                result = self._safe_json(text)
                if bool(result.get("relevant", False)):
                    topic = TOPIC_MAP.get(str(result.get("topic", "")).strip(), "")
                    if topic:
                        paper["topic"] = topic
                    relevant.append(paper)
            except Exception as exc:
                logging.warning("Ollama 快筛失败，跳过本条: %s", exc)
        return relevant
