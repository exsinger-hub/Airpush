<div align="center">

# 📄 Airpush

[English](#english) | [中文](#中文)

</div>

---

<a id="english"></a>

# English

<div align="center">

## 📄 Airpush

**Hundreds of papers every day → auto-select top 3–12 → structured analysis + key figures → push to Notion / WeChat**

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://python.org)
[![LLM](https://img.shields.io/badge/LLM-OpenAI%20Compatible-412991?logo=openai&logoColor=white)]()
[![Notion](https://img.shields.io/badge/Notion-Integration-000000?logo=notion&logoColor=white)]()

*arXiv · PubMed · RSS · Conference → Semantic deduplication → Rule scoring → 3-stage LLM funnel → Daily digest*

</div>

## ✨ What it does

Airpush continuously scans research sources, filters and ranks papers, then delivers a daily summary with structured insights and key figures.

```
Scan 200–300 candidate papers daily
            ↓
Semantic dedup + rule-based scoring (local, seconds)
            ↓
LLM quick relevance filter (72B, keep 10–20)
            ↓
LLM deep structured analysis (~20 fields)
            ↓
PDF download → full-text analysis + figure extraction
            ↓
📊 Notion DB · 📝 Markdown daily report · 💬 WeChat/Webhook push
```

Built-in domain presets:

| Domain | Focus |
|------|-----------|
| 🏥 `medical` | Medical Imaging AI — diffusion, multimodal LLMs, reconstruction, super-resolution |
| ⚛️ `cqed_plasmonics` | Cavity QED & plasmonics — strong coupling, Purcell, nanophotonics |

## 🚀 Quick Start

### 1) Clone & install

```bash
git clone https://github.com/your-username/medpaper-flow.git
cd medpaper-flow
pip install -r requirements.txt
```

### 2) Configure

```bash
cp .env.example .env
```

Or edit per-domain config directly:

- `config/domains/medical/runtime.yaml`
- `config/domains/cqed_plasmonics/runtime.yaml`

Minimal runnable example:

```yaml
llm:
  api_key: "your-api-key"
  base_url: "http://localhost:8000/v1"
  quick_model: "your-model-name"
  deep_model: "your-model-name"

run:
  dry_run: true
```

### 3) Dry run

```bash
DRY_RUN=true python main.py
DOMAIN=medical DRY_RUN=true python main.py
```

### 4) Production run

```bash
python main.py
```

## ⚙️ Core Features

- **Multi-source ingestion**: arXiv, PubMed, RSS, conference sources.
- **Three-stage filtering**: semantic dedup, rule scoring, LLM relevance filter.
- **Deep structured extraction**: modality, task, architecture, innovation, limitations, reproducibility notes, etc.
- **Storage & delivery**: SQLite, Notion native blocks, WeChat ServerChan, generic webhook.
- **Weekly trends**: auto-generated architecture/modality trend report.

## 🖼️ Intelligent Figure Extraction

From downloaded PDFs, Airpush can automatically detect, rank, crop, host, and embed important figures into Notion, including bilingual captions.

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

## 🔧 Configuration Notes

Main runtime config:

- `config/domains/<domain>/runtime.yaml`

Environment variables can override YAML values at runtime.

---

<a id="中文"></a>

# 中文

<div align="center">

# 📄 Airpush

**每天数百篇论文 → 自动精选 3–12 篇 → 结构化分析 + 关键图表 → 推送到 Notion / 微信**

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://python.org)
[![LLM](https://img.shields.io/badge/LLM-OpenAI%20Compatible-412991?logo=openai&logoColor=white)]()
[![Notion](https://img.shields.io/badge/Notion-Integration-000000?logo=notion&logoColor=white)]()

*arXiv · PubMed · RSS · Conference → 语义去重 → 规则评分 → LLM 三级漏斗 → 日报推送*

</div>

## ✨ 它能做什么？

> 你只需每天收到一条消息，打开就是当日最值得读的论文——附带结构化分析、关键图表与中文图注，直接同步到 Notion 数据库。

```
每天扫描 200–300 篇候选论文
         ↓
  语义去重 + 规则评分（本地，秒级）
         ↓
  LLM 快速相关性过滤（72B，保留 10–20 篇）
         ↓
  LLM 深度结构化精析（72B，抽取 20 个字段）
         ↓
  PDF 下载 → 全文分析 + 图表智能提取
         ↓
  📊 Notion 数据库  ·  📝 Markdown 日报  ·  💬 微信/Webhook 推送
```

内置两个领域配置，克隆即用：

| 领域 | 关键词方向 |
|------|-----------|
| 🏥 `medical` | 医学影像 AI — 扩散模型、多模态 LLM、图像重建、超分辨率 |
| ⚛️ `cqed_plasmonics` | 腔量子电动力学 & 等离激元学 — 强耦合、Purcell、纳米光子 |

领域配置完全解耦，三个 YAML 文件即可接入任意研究方向。

## 🚀 快速开始

### 1. 克隆与安装

```bash
git clone https://github.com/your-username/medpaper-flow.git
cd medpaper-flow
pip install -r requirements.txt
```

### 2. 配置

复制配置模板并填写必要信息：

```bash
cp .env.example .env
```

或直接编辑对应域的一站式配置文件（推荐）：

```
config/domains/medical/runtime.yaml
config/domains/cqed_plasmonics/runtime.yaml
```

**最小可运行配置**（以 medical 域为例）：

```yaml
# config/domains/medical/runtime.yaml
llm:
  api_key: "your-api-key"       # OpenAI 兼容 key，本地 vLLM 填 EMPTY
  base_url: "http://localhost:8000/v1"
  quick_model: "your-model-name"
  deep_model: "your-model-name"

run:
  dry_run: true                  # 调试时设为 true，不推送不写库
```

> 环境变量优先级高于 YAML，支持通过 `DOMAIN=medical` 等方式覆盖任意配置项。

### 3. 干跑测试

```bash
# 仅生成 Markdown 报告，不写库不推送
DRY_RUN=true python main.py

# 指定领域
DOMAIN=medical DRY_RUN=true python main.py
```

### 4. 正式运行

```bash
python main.py
```

## ⚙️ 核心功能

- **📡 多源采集**：arXiv、PubMed、RSS、Conference。
- **🔬 三级漏斗过滤**：语义去重 + 规则评分 + LLM 快滤。
- **🧠 深度精析**：抽取约 20 个结构化字段。
- **💾 双层存储 + 多通道推送**：SQLite、Notion、微信/Webhook。
- **📈 自动周报**：架构/模态趋势统计。

## 🖼️ 图表智能提取

> 全自动从 PDF 中识别关键图表，上传 CDN，嵌入 Notion 页面，并附中文图注——无需任何手动操作。

在 `runtime.yaml` 中配置：

```yaml
llm:
  figure_hosting_enabled: true     # 主开关
  figure_selection_use_llm: true   # 使用 LLM 精选（false = 仅启发式）
  figure_max_images: 3             # 每篇论文最多上传图表数
  github_token: "${GITHUB_TOKEN}"   # 建议用环境变量注入，避免明文写入仓库
  github_user: "your-username"
  github_repo: "paper-figures"     # 用于托管图片的公开仓库
  github_branch: "main"
```

## 🔧 配置说明

所有配置集中在 `config/domains/<domain>/runtime.yaml`，环境变量可随时覆盖。
