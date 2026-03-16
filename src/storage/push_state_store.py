from __future__ import annotations

from pathlib import Path


class PushStateStore:
    """md_only 模式下的轻量推送去重存储。"""

    def __init__(self, file_path: str = "data/pushed_ids.txt"):
        self.path = Path(file_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.write_text("", encoding="utf-8")

    def _load(self) -> set[str]:
        content = self.path.read_text(encoding="utf-8", errors="ignore")
        return {line.strip() for line in content.splitlines() if line.strip()}

    def contains(self, key: str) -> bool:
        if not key:
            return False
        return key in self._load()

    def add_many(self, keys: list[str]) -> None:
        new_keys = [k.strip() for k in keys if k and str(k).strip()]
        if not new_keys:
            return
        existing = self._load()
        merged = sorted(existing.union(new_keys))
        self.path.write_text("\n".join(merged) + "\n", encoding="utf-8")
