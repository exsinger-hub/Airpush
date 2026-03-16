from __future__ import annotations

import json
import os
import sqlite3
from typing import Any


class SQLiteStore:
    def __init__(self, db_path: str = "data/papers.db"):
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.conn = sqlite3.connect(db_path)
        self._init_schema()

    def _init_schema(self) -> None:
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS papers (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                abstract TEXT,
                authors TEXT,
                source TEXT,
                published_date TEXT,
                score INTEGER DEFAULT 0,
                labels TEXT,
                topic TEXT,
                modality TEXT,
                task TEXT,
                architecture TEXT,
                institution TEXT,
                innovation_core TEXT,
                clinical_problem TEXT,
                performance_gain TEXT,
                limitations TEXT,
                readability_score INTEGER,
                hype_score INTEGER,
                url TEXT,
                pushed_at TEXT DEFAULT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        self._ensure_columns()
        self.conn.commit()

    def _ensure_columns(self) -> None:
        cur = self.conn.execute("PRAGMA table_info(papers)")
        existing = {row[1] for row in cur.fetchall()}
        required = {
            "topic": "TEXT",
            "institution": "TEXT",
            "performance_gain": "TEXT",
            "limitations": "TEXT",
            "readability_score": "INTEGER",
            "pushed_at": "TEXT",
        }
        for col, col_type in required.items():
            if col not in existing:
                self.conn.execute(f"ALTER TABLE papers ADD COLUMN {col} {col_type}")

    def upsert(self, paper: dict[str, Any]) -> None:
        self.conn.execute(
            """
            INSERT INTO papers
            (id, title, abstract, authors, source, published_date,
             score, labels, topic, modality, task, architecture,
             institution, innovation_core, clinical_problem, performance_gain,
             limitations, readability_score, hype_score, url)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                title=excluded.title,
                abstract=excluded.abstract,
                authors=excluded.authors,
                source=excluded.source,
                published_date=excluded.published_date,
                score=excluded.score,
                labels=excluded.labels,
                topic=excluded.topic,
                modality=excluded.modality,
                task=excluded.task,
                architecture=excluded.architecture,
                institution=excluded.institution,
                innovation_core=excluded.innovation_core,
                clinical_problem=excluded.clinical_problem,
                performance_gain=excluded.performance_gain,
                limitations=excluded.limitations,
                readability_score=excluded.readability_score,
                hype_score=excluded.hype_score,
                url=excluded.url
            """,
            (
                paper.get("id"),
                paper.get("title"),
                paper.get("abstract"),
                json.dumps(paper.get("authors", []), ensure_ascii=False),
                paper.get("source"),
                paper.get("published_date"),
                int(paper.get("score", 0)),
                json.dumps(paper.get("labels", []), ensure_ascii=False),
                paper.get("topic", "General"),
                paper.get("modality"),
                paper.get("task"),
                paper.get("architecture"),
                paper.get("institution"),
                paper.get("innovation_core"),
                paper.get("clinical_problem"),
                paper.get("performance_gain"),
                paper.get("limitations"),
                int(paper.get("readability_score", 0)) if paper.get("readability_score") is not None else None,
                int(paper.get("hype_score", 0)) if paper.get("hype_score") is not None else None,
                paper.get("url"),
            ),
        )
        self.conn.commit()

    def get_unpushed(self) -> list[dict[str, Any]]:
        cur = self.conn.execute(
            """
            SELECT * FROM papers
            WHERE pushed_at IS NULL
            ORDER BY score DESC, created_at DESC
            """
        )
        columns = [d[0] for d in cur.description]
        rows = [dict(zip(columns, row)) for row in cur.fetchall()]
        for row in rows:
            for field in ("authors", "labels"):
                value = row.get(field)
                if isinstance(value, str) and value:
                    try:
                        row[field] = json.loads(value)
                    except Exception:
                        pass
        return rows

    def mark_pushed(self, paper_ids: list[str]) -> None:
        if not paper_ids:
            return
        placeholders = ",".join(["?"] * len(paper_ids))
        self.conn.execute(
            f"""
            UPDATE papers
            SET pushed_at = CURRENT_TIMESTAMP
            WHERE id IN ({placeholders})
            """,
            paper_ids,
        )
        self.conn.commit()

    def get_weekly_stats(self) -> dict[str, dict[str, int]]:
        stats: dict[str, dict[str, int]] = {"architecture": {}, "modality": {}, "topic": {}}

        cursor1 = self.conn.execute(
            """
            SELECT COALESCE(architecture, 'Unknown'), COUNT(*)
            FROM papers
            WHERE created_at >= date('now', '-7 day')
            GROUP BY COALESCE(architecture, 'Unknown')
            ORDER BY COUNT(*) DESC
            """
        )
        stats["architecture"] = {k: v for k, v in cursor1.fetchall()}

        cursor2 = self.conn.execute(
            """
            SELECT COALESCE(modality, 'Unknown'), COUNT(*)
            FROM papers
            WHERE created_at >= date('now', '-7 day')
            GROUP BY COALESCE(modality, 'Unknown')
            ORDER BY COUNT(*) DESC
            """
        )
        stats["modality"] = {k: v for k, v in cursor2.fetchall()}

        cursor3 = self.conn.execute(
            """
            SELECT COALESCE(topic, 'General'), COUNT(*)
            FROM papers
            WHERE created_at >= date('now', '-7 day')
            GROUP BY COALESCE(topic, 'General')
            ORDER BY COUNT(*) DESC
            """
        )
        stats["topic"] = {k: v for k, v in cursor3.fetchall()}

        return stats
