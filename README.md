<div align="center">

# 📄 Airpush

**From hundreds of papers to a daily top list — automatically.**

Automated research scouting pipeline for labs and R&D teams.<br/>
Fetch, deduplicate, score, deeply analyze, and push key papers to Notion / WeChat.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://python.org)
[![LLM](https://img.shields.io/badge/LLM-OpenAI%20Compatible-412991?logo=openai&logoColor=white)]()
[![Notion](https://img.shields.io/badge/Notion-Integration-000000?logo=notion&logoColor=white)]()

`arXiv · PubMed · RSS · Conference → Semantic Dedup → Rule Scoring → 3-Stage LLM Funnel → Daily Digest`

**English | [简体中文](#简体中文)**

</div>

---

## What is Airpush?

Airpush is an automated paper intelligence workflow that turns a noisy daily paper stream into a compact, high-value digest.

Assign a domain config, run the pipeline, and receive:

- top-ranked papers with structured summaries,
- key figure extraction from PDFs,
- Notion-ready entries and markdown reports,
- optional WeChat / webhook notifications.

No manual triage, no repetitive filtering, and no copy-pasting paper notes.

---

## Features

- **Multi-source ingestion**
  - arXiv category + query based crawling
  - PubMed (NCBI E-utilities)
  - RSS feeds (Nature, IEEE, etc.)
  - Conference sources (Semantic Scholar with OpenReview fallback)

- **Three-stage filtering funnel**
  - semantic dedup (`all-MiniLM-L6-v2`, cosine threshold)
  - rule-based scoring (institution whitelist + keyword matrix)
  - fast LLM relevance gate (`{"relevant": true/false}`)

- **Deep structured analysis**
  - extracts ~20 research fields (task, modality, architecture, novelty, gains, limitations, reproducibility hints, etc.)

- **Storage + delivery**
  - SQLite local persistence (domain isolation)
  - Notion database + native block rendering
  - markdown daily report export
  - WeChat ServerChan / generic webhook push

- **Figure intelligence from PDF**
  - detect candidate figures automatically
  - rank/select, crop, host via GitHub + jsDelivr
  - embed to Notion with EN/CN caption support

---

## Built-in Domains

| Domain | Focus |
|---|---|
| `medical` | Medical imaging AI (diffusion, multimodal LLM, reconstruction, super-resolution) |
| `cqed_plasmonics` | Cavity QED & plasmonics (strong coupling, Purcell, nanophotonics) |

Domain logic is decoupled through YAML. You can add new research directions by extending config files.

---

## Quick Install

```bash
# Replace with your fork or the actual repository URL
git clone https://github.com/your-username/medpaper-flow.git
cd medpaper-flow
pip install -r requirements.txt
```

---

## Getting Started

### 1) Configure runtime

```bash
cp .env.example .env
```

Edit one of:

- `config/domains/medical/runtime.yaml`
- `config/domains/cqed_plasmonics/runtime.yaml`

Minimal example:

```yaml
llm:
  api_key: "your-api-key"         # use EMPTY for local vLLM if applicable
  base_url: "http://localhost:8000/v1"
  quick_model: "your-model-name"
  deep_model: "your-model-name"

run:
  dry_run: true
```

### 2) Dry run

```bash
DRY_RUN=true python main.py
DOMAIN=medical DRY_RUN=true python main.py
```

### 3) Production run

```bash
python main.py
```

---

## Figure Extraction (Optional)

Enable in `runtime.yaml`:

```yaml
llm:
  figure_hosting_enabled: true
  figure_selection_use_llm: true
  figure_max_images: 3
  github_token: "${GITHUB_TOKEN}"
  github_user: "your-username"
  github_repo: "paper-figures"
  github_branch: "main"
```

> Security tip: keep secrets (API keys/tokens/webhooks) in environment variables instead of committing plaintext values.

---

## Architecture (Pipeline)

```text
Candidate Papers (arXiv / PubMed / RSS / Conference)
                    ↓
         Semantic Dedup + Rule Scoring
                    ↓
          LLM Quick Relevance Filter
                    ↓
        LLM Deep Structured Extraction
                    ↓
      PDF Download + Fulltext/Figure Analysis
                    ↓
  SQLite / Notion / Markdown / WeChat / Webhook
```

---

## Configuration

Primary config path:

- `config/domains/<domain>/runtime.yaml`

Environment variables can override YAML values at runtime (for example via `DOMAIN=medical`).

---

## Development

Run pipeline entrypoint:

```bash
python main.py
```

Core modules are under `src/`:

- fetchers: `src/fetchers/`
- ranking/filtering: `src/scorer.py`, `src/deduplicator.py`
- LLM pipeline: `src/llm_pipeline.py`
- persistence/push: `src/storage/`, `src/notifier.py`

---

## License

MIT. See [LICENSE](LICENSE).

---

<a id="简体中文"></a>

## 简体中文

<div align="center">

# 📄 Airpush

**每天数百篇论文，自动筛出最值得读的少量论文。**

面向科研团队 / 实验室的自动化论文情报管线。<br/>
自动采集、去重、评分、深度分析，并推送到 Notion / 微信。

`arXiv · PubMed · RSS · Conference → 语义去重 → 规则评分 → LLM 三级漏斗 → 每日精选`

[English](#what-is-airpush) | **简体中文**

</div>

### Airpush 是什么？

Airpush 用于把“高噪声论文流”变成“低噪声高价值日报”。

配置好领域后，一次运行即可得到：

- 入选论文的结构化解读；
- PDF 关键图表提取；
- Notion 数据库同步与 Markdown 日报；
- 可选微信 / Webhook 通知。

### 核心能力

- **多源采集**：arXiv、PubMed、RSS、会议源。
- **三级过滤**：语义去重 + 规则评分 + LLM 快速相关性判断。
- **深度精析**：抽取约 20 个结构化字段（任务、模态、架构、创新、局限等）。
- **存储与推送**：SQLite、Notion 原生 Block、微信 ServerChan、Webhook。
- **图表智能提取**：自动识别候选图，裁切上传并嵌入 Notion（支持中英文图注）。

### 内置领域

| 领域 | 方向 |
|---|---|
| `medical` | 医学影像 AI：扩散、多模态 LLM、重建、超分辨率 |
| `cqed_plasmonics` | 腔量子电动力学与等离激元：强耦合、Purcell、纳米光子 |

### 快速开始

```bash
git clone https://github.com/your-username/medpaper-flow.git
cd medpaper-flow
pip install -r requirements.txt
cp .env.example .env
DRY_RUN=true python main.py
```

### 配置文件

- 主配置：`config/domains/<domain>/runtime.yaml`
- 支持通过环境变量覆盖（例如 `DOMAIN=medical`）

### 图表功能开关（可选）

```yaml
llm:
  figure_hosting_enabled: true
  figure_selection_use_llm: true
  figure_max_images: 3
```

### 开发入口

```bash
python main.py
```

许可证：MIT（见 `LICENSE`）。
