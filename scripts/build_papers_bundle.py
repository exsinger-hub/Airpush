from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from main import fetch_all_sources, load_yaml
from src.deduplicator import SemanticDeduplicator
from src.pdf_downloader import PDFDownloader
from src.runtime_config import apply_runtime_env, load_runtime_yaml
from src.scorer import PaperScorer, select_scored_papers


def resolve_domain_config_paths(project_root: Path, domain: str) -> tuple[Path, Path, Path]:
    domain_cfg_dir = project_root / "config" / "domains" / domain
    runtime_cfg = Path(os.getenv("RUNTIME_CONFIG", "").strip() or domain_cfg_dir / "runtime.yaml")
    sources_cfg = Path(os.getenv("SOURCES_CONFIG", "").strip() or domain_cfg_dir / "sources.yaml")
    scoring_cfg = Path(os.getenv("SCORING_CONFIG", "").strip() or domain_cfg_dir / "scoring_rules.yaml")
    if not runtime_cfg.exists():
        runtime_cfg = project_root / "config" / "runtime.yaml"
    if not sources_cfg.exists():
        sources_cfg = project_root / "config" / "sources.yaml"
    if not scoring_cfg.exists():
        scoring_cfg = project_root / "config" / "scoring_rules.yaml"
    return runtime_cfg, sources_cfg, scoring_cfg


def score_candidate_papers(
    papers: list[dict[str, Any]],
    scoring_cfg_path: Path,
    min_selected_papers: int,
    score_threshold: int,
    fallback_enabled: bool,
) -> list[dict[str, Any]]:
    scorer = PaperScorer(str(scoring_cfg_path))
    scored: list[dict[str, Any]] = []
    all_ranked: list[dict[str, Any]] = []

    for paper in papers:
        score, labels, core_ok = scorer.score(paper)
        item = dict(paper)
        item["score"] = score
        item["labels"] = labels
        item["topic"] = scorer.assign_topic(item)
        item["core_ok"] = core_ok
        all_ranked.append(item)
        if core_ok and score > score_threshold:
            scored.append(item)

    selected, _ = select_scored_papers(
        all_ranked=all_ranked,
        scored=scored,
        min_selected_papers=min_selected_papers,
        fallback_enabled=fallback_enabled,
    )
    return selected


def copy_bundle_pdfs(bundle_dir: Path, papers: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    pdf_dir = bundle_dir / "pdfs"
    pdf_dir.mkdir(parents=True, exist_ok=True)
    copied = 0
    out: list[dict[str, Any]] = []

    for paper in papers:
        item = dict(paper)
        local_path = str(item.get("pdf_local_path", "") or "").strip()
        if local_path:
            src = Path(local_path)
            if src.exists() and src.is_file():
                dest_name = src.name
                dest = pdf_dir / dest_name
                if dest.exists() and dest.resolve() != src.resolve():
                    dest = pdf_dir / f"{str(item.get('id', 'paper')).strip()}_{src.name}"
                if not dest.exists():
                    shutil.copy2(src, dest)
                item["pdf_local_path"] = str(Path("pdfs") / dest.name)
                item["pdf_downloaded"] = True
                copied += 1
        out.append(item)

    return out, copied


def main() -> None:
    parser = argparse.ArgumentParser(description="本地抓取并打包 papers.json + PDFs，供远端导入")
    parser.add_argument("--domain", default=os.getenv("DOMAIN", "medical"), help="领域名，如 medical / cqed_plasmonics")
    parser.add_argument("--output-dir", default="", help="bundle 输出目录，默认 transfer/<domain>/<timestamp>")
    parser.add_argument("--pdf-top-k", type=int, default=0, help="本地预抓取 PDF 数量；0 表示对全部候选尝试下载")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    project_root = PROJECT_ROOT
    os.chdir(project_root)
    domain = (args.domain or "medical").strip()
    os.environ["DOMAIN"] = domain

    runtime_cfg_path, sources_cfg_path, scoring_cfg_path = resolve_domain_config_paths(project_root, domain)
    runtime_cfg = load_runtime_yaml(str(runtime_cfg_path))
    apply_runtime_env(runtime_cfg)

    top_k = int(os.getenv("TOP_K", "5"))
    min_selected_papers = max(1, int(os.getenv("MIN_SELECTED_PAPERS", "3")))
    rule_score_fallback_enabled = str(os.getenv("RULE_SCORE_FALLBACK_ENABLED", "true")).lower() == "true"
    min_abstract_len = int(os.getenv("MIN_ABSTRACT_LEN", "50"))
    score_threshold = int(os.getenv("SCORE_THRESHOLD", "30"))
    pdf_download_enabled = str(os.getenv("PDF_DOWNLOAD_ENABLED", "true")).lower() == "true"
    pdf_download_timeout = max(8, int(os.getenv("PDF_DOWNLOAD_TIMEOUT", "25")))
    pdf_download_dir = os.getenv("PDF_DOWNLOAD_DIR", f"data/pdfs/{domain}").strip() or f"data/pdfs/{domain}"

    source_cfg = load_yaml(str(sources_cfg_path)).get("sources", {})
    papers = fetch_all_sources(source_cfg)
    papers = [paper for paper in papers if len((paper.get("abstract") or "").strip()) > min_abstract_len]
    total_scanned = len(papers)
    logging.info("本地抓取完成：domain=%s total_scanned=%s", domain, total_scanned)

    papers = SemanticDeduplicator(threshold=0.92).deduplicate(papers)
    logging.info("语义去重后剩余 %s 篇", len(papers))

    papers = score_candidate_papers(
        papers,
        scoring_cfg_path=scoring_cfg_path,
        min_selected_papers=min_selected_papers,
        score_threshold=score_threshold,
        fallback_enabled=rule_score_fallback_enabled,
    )
    logging.info("规则评分后候选 %s 篇", len(papers))

    if pdf_download_enabled and papers:
        pdf_top_k = len(papers) if args.pdf_top_k <= 0 else min(len(papers), args.pdf_top_k)
        pdf_top_k = max(pdf_top_k, min(top_k, len(papers)))
        downloader = PDFDownloader(out_dir=pdf_download_dir, timeout=pdf_download_timeout)
        downloaded = downloader.download_batch(papers, top_k=pdf_top_k)
        mapped = {str(p.get("id", "")).strip(): p for p in downloaded if str(p.get("id", "")).strip()}
        merged: list[dict[str, Any]] = []
        for paper in papers:
            pid = str(paper.get("id", "")).strip()
            merged.append({**paper, **mapped.get(pid, {})})
        papers = merged
        ok = sum(1 for p in papers if bool(p.get("pdf_downloaded", False)))
        logging.info("本地 PDF 预抓取完成：成功=%s 尝试=%s", ok, pdf_top_k)

    bundle_dir = Path(args.output_dir).expanduser() if args.output_dir else project_root / "transfer" / domain / datetime.now().strftime("%Y%m%d-%H%M%S")
    bundle_dir.mkdir(parents=True, exist_ok=True)
    papers, copied = copy_bundle_pdfs(bundle_dir, papers)

    payload = {
        "meta": {
            "domain": domain,
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "total_scanned": total_scanned,
            "candidate_count": len(papers),
            "preprocessed": True,
            "pdf_prefetched": pdf_download_enabled,
            "local_pdf_only_recommended": True,
        },
        "papers": papers,
    }
    bundle_file = bundle_dir / "papers.json"
    bundle_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    logging.info("Bundle 已生成: %s", bundle_dir)
    logging.info("papers.json: %s", bundle_file)
    logging.info("随包 PDF 数量: %s", copied)


if __name__ == "__main__":
    main()