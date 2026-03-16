from __future__ import annotations

import logging
import os
from typing import Any

import numpy as np


class SemanticDeduplicator:
    """基于语义向量的去重。"""

    def __init__(self, threshold: float = 0.92, model_name: str = "all-MiniLM-L6-v2"):
        self.threshold = threshold
        self.model = None
        if str(os.getenv("DISABLE_SEMANTIC_DEDUP", "false")).lower() == "true":
            logging.info("已禁用语义去重模型，使用规则去重模式")
            return
        try:
            from sentence_transformers import SentenceTransformer

            self.model = SentenceTransformer(model_name)
        except Exception as exc:
            logging.warning("语义模型加载失败，降级到规则去重: %s", exc)

    @staticmethod
    def _preferred(p1: dict[str, Any], p2: dict[str, Any]) -> dict[str, Any]:
        rank = {"pubmed": 3, "rss": 2, "arxiv": 1}
        return p1 if rank.get(p1.get("source", ""), 0) >= rank.get(p2.get("source", ""), 0) else p2

    def deduplicate(self, papers: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not papers:
            return []

        if self.model is None:
            # 降级：标题归一化去重 + 来源优先级保留
            normalized_map: dict[str, dict[str, Any]] = {}
            for p in papers:
                title = (p.get("title", "") or "").lower().strip()
                norm = "".join(ch for ch in title if ch.isalnum() or ch.isspace())
                norm = " ".join(norm.split())
                if not norm:
                    norm = p.get("id", "")
                if norm in normalized_map:
                    normalized_map[norm] = self._preferred(normalized_map[norm], p)
                else:
                    normalized_map[norm] = p
            deduped = list(normalized_map.values())
            logging.info("规则去重(降级): %s -> %s", len(papers), len(deduped))
            return deduped

        texts = [f"{p.get('title', '')}. {p.get('abstract', '')}".strip() for p in papers]
        embeddings = self.model.encode(texts, batch_size=32, normalize_embeddings=True)

        keep_indices: list[int] = []
        dropped: set[int] = set()

        for i in range(len(papers)):
            if i in dropped:
                continue
            keep_indices.append(i)
            for j in range(i + 1, len(papers)):
                if j in dropped:
                    continue
                cos_sim = float(np.dot(embeddings[i], embeddings[j]))
                if cos_sim >= self.threshold:
                    chosen = self._preferred(papers[keep_indices[-1]], papers[j])
                    if chosen is papers[j]:
                        keep_indices[-1] = j
                    dropped.add(j)

        deduped = [papers[idx] for idx in keep_indices]
        logging.info("语义去重: %s -> %s", len(papers), len(deduped))
        return deduped
