# MedPaper-Flow

> 多领域学术论文自动化监测与精析流水线

**MedPaper-Flow** 是一个可配置的学术论文日报系统。它接入 arXiv、PubMed、RSS 等多个数据源，通过语义去重、规则评分、LLM 三级漏斗过滤，将每天数百篇候选论文压缩为 3-12 篇高价值精选，并自动生成结构化分析报告，推送至 Notion 与微信/Webhook 通知。

内置两个领域配置，开箱即用：
- **medical** — 医学影像 AI（扩散模型、多模态 LLM、图像重建、超分辨率等）
- **cqed_plasmonics** — 腔量子电动力学与等离激元学（强耦合、Purcell 效应、纳米光子器件等）

领域配置完全解耦，可按同样方式扩展至任意研究方向。

---

## 目录

- [功能特性](#功能特性)
- [工作流程](#工作流程)
- [快速开始](#快速开始)
- [配置说明](#配置说明)
- [LLM 部署](#llm-部署)
- [输出示例](#输出示例)
- [目录结构](#目录结构)
- [进阶用法](#进阶用法)
- [安全须知](#安全须知)
- [贡献指南](#贡献指南)
- [许可证](#许可证)

---

## 功能特性

| 模块 | 说明 |
|------|------|
| **多源采集** | arXiv、PubMed、RSS Feed、Conference（Semantic Scholar + OpenReview 回退） |
| **语义去重** | `all-MiniLM-L6-v2` embedding 余弦相似度（阈值 0.92），标题归一化兜底 |
| **规则评分** | 机构白名单、关键词矩阵、惩罚词，YAML 驱动，可热更新 |
| **LLM 快速过滤** | 仅返回 `{"relevant": true/false}`，高效压缩候选集 |
| **LLM 深度精析** | 抽取约 20 个结构化字段：场景、任务、架构、创新点、临床价值、性能、局限等 |
| **PDF 全文分析** | 自动下载 PDF，支持 WebVPN / curl_cffi / Playwright 多重回退 |
| **双层存储** | SQLite 主存储 + Notion 展示层（原生 Block 渲染或 Markdown 追加） |
| **多通道推送** | 微信 Server Chan、通用 Webhook、每周日自动发送趋势周报 |
| **容错隔离** | Stage 级异常隔离，关键阶段失败自动触发告警 Webhook |
| **双域并行** | medical 与 cqed_plasmonics 使用独立 DB / 报告目录 / 推送状态 |

---

## 工作流程

```
多源采集（arXiv / PubMed / RSS / Conference）
      │
      ▼
语义去重（all-MiniLM-L6-v2，cosine ≥ 0.92）
      │
      ▼
规则评分（机构白名单 + 关键词矩阵，YAML 配置）
      │
      ▼
LLM 快速过滤（72B，relevant/idea_worthy JSON 判定）
      │
      ▼
LLM 深度精析（72B，~20 个结构化字段）
      │
      ▼
PDF 下载 + 全文分析（top-k 篇，可选）
      │
      ▼
SQLite 存储  ──►  Notion 同步  ──►  Markdown 日报
                                         │
                                         ▼
                                    Webhook 推送（微信 / 通用）
                                    （每周日额外生成趋势周报）
```

---

## 快速开始

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

# 指定域
DOMAIN=medical DRY_RUN=true python main.py
DOMAIN=cqed_plasmonics DRY_RUN=true python main.py
```

### 4. 正式运行

```bash
python main.py
```

---

## 配置说明

### 核心配置项

每个域在 `config/domains/<domain>/runtime.yaml` 中独立配置：

#### LLM 设置

| 配置项 | 说明 | 推荐值 |
|--------|------|--------|
| `llm.api_key` | OpenAI 兼容 API Key | 本地 vLLM 填 `EMPTY` |
| `llm.base_url` | 推理服务地址 | `http://localhost:8000/v1` |
| `llm.quick_model` | 快速过滤模型名 | `qwen-72b` |
| `llm.deep_model` | 深度精析模型名 | `qwen-72b` |
| `llm.disable_local_quick` | 禁用 Ollama 本地回退 | 使用远程 72B 时设 `true` |
| `llm.request_timeout_sec` | 单次请求超时（秒） | `240` |
| `llm.max_retries` | LLM 请求重试次数 | `3` |
| `llm.deep_stage_max_seconds` | 深析阶段总耗时上限 | `900` |

#### Notion 推送（可选）

| 配置项 | 说明 |
|--------|------|
| `notion.token` | Internal Integration Token |
| `notion.database_id` | 目标数据库 ID（32 位） |
| `notion.page_id` | 目标页面 ID（追加 Markdown 模式） |

Notion 数据库需包含以下属性（系统自动创建缺失列并加 `MPF_` 前缀）：

| 属性名 | 类型 |
|--------|------|
| `Title` | title |
| `Modality` | select |
| `Task` | select |
| `Architecture` | select |
| `Score` | number |
| `Tags` | multi_select |
| `Innovation` | rich_text |
| `Source` | url |
| `Date` | date |

#### 通知推送（可选）

| 配置项 | 说明 |
|--------|------|
| `notify.webhook_url` | 微信 Server Chan URL 或通用 Webhook 地址 |
| `notify.alert_url` | 流水线异常告警接收地址 |

#### 运行参数

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `run.dry_run` | `false` | 不推送、不写库 |
| `run.md_only` | `false` | 仅导出 Markdown |
| `run.top_k` | `5` | 深析论文最大数量 |
| `run.score_threshold` | `30` | 进入 LLM 阶段的最低规则分 |
| `run.min_selected_papers` | `3` | 最低保底论文数（回退策略） |
| `run.disable_semantic_dedup` | `false` | 关闭语义去重（加速调试） |
| `run.pdf_download_enabled` | `true` | 是否下载 PDF |
| `run.fulltext_enabled` | `true` | 是否进行全文分析 |
| `run.notion_native_blocks` | `true` | Notion 原生 Block 渲染 |

### 数据源配置

在 `config/domains/<domain>/sources.yaml` 中配置 arXiv 类目、PubMed 期刊列表、RSS 源、会议列表。

### 评分规则配置

在 `config/domains/<domain>/scoring_rules.yaml` 中配置：
- 机构白名单（+30 分）
- `bonus_keywords`：正则 + 分值
- `penalty_keywords`：惩罚词 -15 分
- `topic_mapping`：子话题分类规则

---

## LLM 部署

本项目对接 **OpenAI 兼容 API**，不绑定特定模型或服务。推荐配置：

### 方案 A：本地 / 远端 vLLM（Qwen2.5-72B，推荐）

**硬件参考：** 4 × NVIDIA RTX 4090（或等效 96GB+ 显存）

```bash
# 服务端启动（Linux）
CUDA_VISIBLE_DEVICES=0,1,2,3 python -m vllm.entrypoints.openai.api_server \
    --model Qwen/Qwen2.5-72B-Instruct-AWQ \
    --served-model-name qwen-72b \
    --tensor-parallel-size 4 \
    --max-model-len 32768 \
    --port 8000
```

远端部署时，在本地建立 SSH 端口映射：

```bash
ssh -N -f -L 8000:localhost:8000 your-username@YOUR_SERVER_IP
```

或使用项目脚本（首次连接会交互输入密码，密码不会写入任何文件）：

```powershell
# 将 your-username@YOUR_SERVER_IP 替换为你的实际服务器地址
powershell -ExecutionPolicy Bypass -File scripts/open_tunnel.ps1 `
    -Server "your-username@YOUR_SERVER_IP"
```

然后将 `runtime.yaml` 中 `llm.base_url` 设为 `http://localhost:8000/v1`。

### 方案 B：云端 API（OpenAI / Together AI / 其他）

将 `llm.api_key` 和 `llm.base_url` 替换为对应服务的配置即可。

### 方案 C：GitHub Actions（轻量云端模型）

参考 `.github/workflows/daily_run.yml`，配置 Secrets 后每天自动运行：

| Secret | 说明 |
|--------|------|
| `OPENAI_API_KEY` | API Key |
| `NOTION_TOKEN` | Notion 集成 Token（可选） |
| `NOTION_DB_ID` | Notion 数据库 ID（可选） |
| `WEBHOOK_URL` | 推送 Webhook（可选） |
| `ALERT_URL` | 告警 Webhook（可选） |
| `PUBMED_EMAIL` | PubMed E-utilities 邮箱（推荐） |

---

## 输出示例

### Markdown 日报（`reports/<domain>/daily-YYYY-MM-DD.md`）

```markdown
# 医学AI 每日精选
*📅 2026-03-16 | 🔍 扫描: 287 | 🌟 入选: 5*

---

### 🥇 Top 1: Photon-Counting CT for Quantitative Assessment
**🏷️ 标签:** 顶会/顶刊, 开源
**📊 评分:** 78/100 | **💡 Idea分:** 8/10 | **💬 炒作指数:** 3/10

* **来源**: pubmed | **日期**: 2026-03-15
* **模态/任务**: CT → Quantitative Assessment
* **核心创新**: 首次...
...
```

### Notion 数据库

每篇论文生成一条结构化记录，支持按模态、任务、评分筛选和排序。

---

## 目录结构

```
medpaper-flow/
├── main.py                        # 主入口，编排所有 Stage
├── requirements.txt
├── .env.example                   # 环境变量模板
├── config/
│   └── domains/
│       ├── medical/
│       │   ├── runtime.yaml       # 运行参数、LLM、Notion、Webhook 配置
│       │   ├── sources.yaml       # 数据源（arXiv / PubMed / RSS / 会议）
│       │   └── scoring_rules.yaml # 评分规则
│       └── cqed_plasmonics/       # 同上，物理领域配置
├── src/
│   ├── fetchers/
│   │   ├── arxiv_fetcher.py
│   │   ├── pubmed_fetcher.py
│   │   ├── rss_fetcher.py
│   │   ├── conference_fetcher.py
│   │   └── vpn_downloader.py      # WebVPN / curl_cffi PDF 下载
│   ├── storage/
│   │   ├── sqlite_store.py
│   │   ├── notion_store.py
│   │   ├── notion_page_store.py
│   │   └── push_state_store.py
│   ├── deduplicator.py
│   ├── scorer.py
│   ├── llm_pipeline.py
│   ├── pdf_downloader.py
│   ├── notifier.py
│   ├── runtime_config.py
│   └── local_llm.py               # Ollama 本地 LLM 回退
├── scripts/
│   ├── build_papers_bundle.py     # 本地预抓取，生成离线 bundle
│   ├── run_medpaper_flow.ps1      # Windows 单域运行
│   ├── run_daily_dual_domains.ps1 # Windows 双域顺序运行
│   ├── register_daily_dual_domains_task.ps1
│   ├── open_tunnel.ps1            # SSH 端口映射
│   ├── check_vllm.ps1
│   ├── start_vllm_server.sh       # Linux vLLM 启动
│   └── notion_check.py            # Notion 字段校验
├── data/                          # SQLite DB + PDF 缓存（git ignore）
├── reports/                       # Markdown 日报输出
├── logs/                          # 运行日志
└── .github/workflows/
    └── daily_run.yml              # GitHub Actions 每日定时任务
```

---

## 进阶用法

### Windows 定时任务

```powershell
# 注册每日 05:30 双域定时任务
powershell -ExecutionPolicy Bypass -File scripts/register_daily_dual_domains_task.ps1 `
    -TaskName MedPaperFlow-DualDaily -StartTime 05:30 -Force

# 立即执行一次双域流程（需指定远端服务器信息）
powershell -ExecutionPolicy Bypass -File scripts/run_daily_dual_domains.ps1 `
    -RemoteUser "your-username" `
    -RemoteHost "YOUR_SERVER_IP" `
    -RemotePython "/path/to/your/miniconda/envs/vllm/bin/python"

# 干跑模式
powershell -ExecutionPolicy Bypass -File scripts/run_daily_dual_domains.ps1 `
    -RemoteUser "your-username" `
    -RemoteHost "YOUR_SERVER_IP" `
    -RemotePython "/path/to/your/miniconda/envs/vllm/bin/python" `
    -DryRun
```

### Bundle 离线导入模式

适合「本地抓取 + 远端 LLM 精析」的弱网场景：

```bash
# Step 1: 本地预抓取并打包
python scripts/build_papers_bundle.py --domain medical

# Step 2: 在远端导入继续精析、推送
IMPORT_PAPERS_FILE=/path/to/transfer/medical/<timestamp>/papers.json \
IMPORT_PDF_ROOT=/path/to/transfer/medical/<timestamp> \
LOCAL_PDF_ONLY=true python main.py
```

或使用一键脚本传输并触发远端执行（需指定远端服务器信息）：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/run_remote_bundle_flow.ps1 `
    -Domain medical `
    -RemoteUser "your-username" `
    -RemoteHost "YOUR_SERVER_IP" `
    -RemotePython "/path/to/your/miniconda/envs/vllm/bin/python"
```

### 扩展新领域

1. 在 `config/domains/` 下新建一个域目录，复制现有的三个 YAML 文件并修改。
2. 运行时指定域：`DOMAIN=your_domain python main.py`

### 运行测试

```bash
pip install -r requirements-dev.txt
pytest -q
```

---

## 安全须知

- **不要**将 Notion Token（`ntn_...`）、API Key、OpenReview 账密提交到公开仓库。
- **不要**将服务器 IP、SSH 用户名、远端路径硬编码进脚本后提交，统一通过参数传入或写入本地 `.env` 文件（已加入 `.gitignore`）。
- **不要**在脚本中明文保存 SSH 密码，隧道脚本会在连接时交互提示。
- Notion 数据库/页面必须先在 Share 设置中授权对应 Integration，否则会返回 403。
- 72B 模型含模型缓存建议预留 **50GB+** 磁盘空间。
- 建议通过 `.gitignore` 排除 `data/`、`logs/`、`tmp/`、`transfer/` 目录，避免推送敏感内容或大文件。

---

## 贡献指南

欢迎提交 Issue 和 Pull Request！

- **新领域配置**：无需修改核心代码，只需在 `config/domains/` 下添加配置目录。
- **新数据源**：在 `src/fetchers/` 下实现一个新 Fetcher，返回标准化 paper dict，并在 `main.py` 中注册。
- **Bug 修复 / 功能改进**：请附上复现步骤或测试用例。

提交前请确保通过现有测试：

```bash
pytest -q
```

---

## 许可证

本项目基于 [MIT License](LICENSE) 开源。
