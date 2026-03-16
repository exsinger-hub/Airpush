from __future__ import annotations

import re
from typing import Any

import yaml


class PaperScorer:
    def __init__(self, config_path: str = "config/scoring_rules.yaml"):
        with open(config_path, "r", encoding="utf-8") as f:
            self.rules = yaml.safe_load(f)

    @staticmethod
    def _contains(text: str, terms: list[str]) -> bool:
        t = text.lower()
        return any(term.lower() in t for term in terms)

    @staticmethod
    def _contains_all(text: str, terms: list[str]) -> bool:
        t = text.lower()
        return all(term.lower() in t for term in terms)

    @staticmethod
    def _contains_phrase(text: str, phrase: str) -> bool:
        normalized_text = text.lower()
        normalized_phrase = str(phrase or "").strip().lower()
        if not normalized_phrase:
            return False
        pattern = rf"(?<![a-z0-9]){re.escape(normalized_phrase)}(?![a-z0-9])"
        return re.search(pattern, normalized_text) is not None

    @staticmethod
    def _match_legacy_expr(text: str, expr: str) -> bool:
        """支持 legacy 语法: 'a AND (b OR c)'。"""
        import re

        t = text.lower()
        s = expr.strip()
        if not s:
            return False

        # 先处理括号中的 OR 组
        pattern = re.compile(r"\(([^()]+)\)", re.IGNORECASE)
        while True:
            m = pattern.search(s)
            if not m:
                break
            group = m.group(1)
            ok = any(part.strip().lower() in t for part in re.split(r"\bOR\b", group, flags=re.IGNORECASE))
            s = s[: m.start()] + (" __TRUE__ " if ok else " __FALSE__ ") + s[m.end() :]

        and_parts = [p.strip() for p in re.split(r"\bAND\b", s, flags=re.IGNORECASE) if p.strip()]
        for part in and_parts:
            or_parts = [x.strip() for x in re.split(r"\bOR\b", part, flags=re.IGNORECASE) if x.strip()]
            if not or_parts:
                continue
            matched = False
            for token in or_parts:
                if token == "__TRUE__":
                    matched = True
                    break
                if token == "__FALSE__":
                    continue
                if token.lower() in t:
                    matched = True
                    break
            if not matched:
                return False
        return True

    def _match_core(self, text: str) -> bool:
        core_rules = self.rules.get("core_rules", [])
        for rule in core_rules:
            if not isinstance(rule, dict):
                continue
            any_terms = rule.get("any", [])
            all_terms = rule.get("all", [])

            any_ok = True if not any_terms else self._contains(text, any_terms)
            all_ok = True if not all_terms else self._contains_all(text, all_terms)
            if any_ok and all_ok:
                return True

        # 兼容 legacy core_keywords 字段与 AND/OR 表达式
        legacy = self.rules.get("core_keywords", [])
        for item in legacy:
            if isinstance(item, str) and self._match_legacy_expr(text, item):
                return True

        # 若未配置任何 core 规则，默认放行
        return not core_rules and not legacy

    def score(self, paper: dict[str, Any]) -> tuple[int, list[str], bool]:
        score = 0
        labels: list[str] = []

        text = " ".join(
            [
                paper.get("title", ""),
                paper.get("abstract", ""),
                paper.get("affiliation", ""),
                " ".join(paper.get("authors", [])),
            ]
        )

        core_ok = self._match_core(text)

        for inst in self.rules.get("top_institutions", []):
            if self._contains_phrase(text, str(inst)):
                score += 30
                labels.append(f"顶级机构({inst})")
                break

        for rule in self.rules.get("bonus_keywords", []):
            pattern = rule.get("pattern")
            if pattern and re.search(pattern, text, re.IGNORECASE):
                score += int(rule.get("score", 0))
                labels.append(rule.get("label", "加分"))

        title_lower = paper.get("title", "").lower()
        for kw in self.rules.get("penalty_keywords", []):
            if kw.lower() in title_lower:
                score -= 15
                labels.append(f"降权({kw})")

        return score, labels, core_ok

    def assign_topic(self, paper: dict[str, Any]) -> str:
        existing = str(paper.get("topic", "")).strip()
        if existing and existing.lower() not in {"general", "unknown", "none"}:
            return existing

        text = " ".join([paper.get("title", ""), paper.get("abstract", "")]).lower()
        mapping = self.rules.get("topic_mapping", {})
        if isinstance(mapping, dict):
            for topic, keywords in mapping.items():
                if not isinstance(keywords, list):
                    continue
                if any(str(kw).lower() in text for kw in keywords):
                    return str(topic)
        return "General"


def select_scored_papers(
    all_ranked: list[dict[str, Any]],
    scored: list[dict[str, Any]],
    min_selected_papers: int,
    fallback_enabled: bool,
    fallback_reason: str = "规则阈值未命中，按分数兜底入选",
) -> tuple[list[dict[str, Any]], bool]:
    scored.sort(key=lambda x: x.get("score", 0), reverse=True)
    all_ranked.sort(key=lambda x: x.get("score", 0), reverse=True)
    if scored:
        return scored, False

    if not fallback_enabled:
        return [], False

    fallback_pool = [p for p in all_ranked if bool(p.get("core_ok", False))] or all_ranked
    selected = fallback_pool[: max(1, min_selected_papers)]
    for paper in selected:
        paper["fallback_selected"] = True
        paper["fallback_reason"] = fallback_reason
    return selected, True
