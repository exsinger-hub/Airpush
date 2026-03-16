<div align="center">

# 📄 Airpush

**每天数百篇论文 → 自动精选 3–12 篇 → 结构化分析 + 关键图表 → 推送到 Notion / 微信**

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://python.org)
[![LLM](https://img.shields.io/badge/LLM-OpenAI%20Compatible-412991?logo=openai&logoColor=white)]()
[![Notion](https://img.shields.io/badge/Notion-Integration-000000?logo=notion&logoColor=white)]()

*arXiv · PubMed · RSS · Conference → 语义去重 → 规则评分 → LLM 三级漏斗 → 日报推送*

</div>

---

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

---

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

---

## ⚙️ 核心功能

<table>
<tr>
<td width="50%">

**📡 多源采集**
- arXiv（类目 + 关键词查询）
- PubMed / NCBI E-utilities
- RSS Feed（Nature、IEEE 等）
- Conference（Semantic Scholar + OpenReview 回退）

</td>
<td width="50%">

**🔬 三级漏斗过滤**
- 语义去重：`all-MiniLM-L6-v2`，cosine ≥ 0.92
- 规则评分：机构白名单 + 关键词矩阵（YAML 热更新）
- LLM 快滤：仅返回 `{"relevant": true/false}`

</td>
</tr>
<tr>
<td>

**🧠 LLM 深度精析**

每篇论文抽取约 20 个结构化字段：

`模态` · `任务` · `架构` · `核心创新` · `临床价值`
`性能增益` · `局限性` · `机构` · `Idea 分` · `炒作指数`
`TL;DR` · `下一步实验` · `复现要点` · `消融缺口` …

</td>
<td>

**💾 双层存储 + 多通道推送**
- SQLite 主存储（域隔离，90 天自动清理）
- Notion 数据库 + 原生 Block 页面渲染
- 微信 Server Chan / 通用 Webhook
- 每周日自动生成架构/模态趋势周报

</td>
</tr>
</table>

---

## 🖼️ 图表智能提取

> 全自动从 PDF 中识别关键图表，上传 CDN，嵌入 Notion 页面，并附中文图注——无需任何手动操作。

### 工作原理

```
PDF（已下载）
    │
    ▼
PyMuPDF 逐页扫描（最多 80 页）
    │  ├─ 光栅图像区域检测（get_page_images）
    │  └─ 矢量绘图区域检测（get_drawings）
    │       去除过小（< 40×40 px）或全页背景
    ▼
空间聚合 → 合并相邻组件为完整图表区域
    │  锚定附近 Caption 文本（正则匹配 Figure / Fig.）
    ▼
候选打分（启发式）
    │  ✅ 加分：首页、有 Caption、含 pipeline/framework 等关键词
    │  ❌ 减分：Logo、作者署名、无文本信息
    ▼
LLM 精选（可选，Qwen2.5-72B）
    │  发送候选图的尺寸、页码、Caption、周围文本
    │  返回 {"selected_ids": [...]}，失败自动回退启发式
    ▼
高分辨率裁切渲染（PNG，目标长边 ≥ 1800 px）
    ▼
上传 GitHub 仓库 → jsDelivr CDN 加速 URL
    ▼
Notion 页面嵌入
    ├─ 🖼️ 原生 Image Block（CDN URL）
    ├─ 英文 Caption（斜体）
    └─ 🇨🇳 中文图注（LLM 翻译，自动匹配）
```

### 开启方式

在 `runtime.yaml` 中配置：

```yaml
llm:
  figure_hosting_enabled: true     # 主开关
  figure_selection_use_llm: true   # 使用 LLM 精选（false = 仅启发式）
  figure_max_images: 3             # 每篇论文最多上传图表数
  github_token: "ghp_..."          # GitHub PAT（需 repo Contents 写权限）
  github_user: "your-username"
  github_repo: "paper-figures"     # 用于托管图片的公开仓库
  github_branch: "main"
```

> **为什么用 GitHub + jsDelivr？**
> jsDelivr 对 GitHub 公开仓库提供免费全球 CDN，图片 URL 稳定可直接嵌入 Notion，无需额外存储服务。

---

## 🔧 配置说明

所有配置集中在 `config/domains/<domain>/runtime.yaml`，环境变量可随时覆盖。

### LLM 设置

| 配置项 | 推荐值 | 说明 |
|--------|--------|------|
| `llm.api_key` | `EMPTY`（本地 vLLM） | OpenAI 兼容 Key |
| `llm.base_url` | `http://localhost:8000/v1` | 推理服务地址 |
| `llm.quick_model` | `qwen-72b` | 快速过滤模型 |
| `llm.deep_model` | `qwen-72b` | 深度精析模型 |
| `llm.request_timeout_sec` | `240` | 单次请求超时（秒） |
| `llm.max_retries` | `3` | 失败重试次数 |
| `llm.deep_stage_max_seconds` | `900` | 深析阶段总耗时上限 |

### 运行参数

| 配置项 | 默认 | 说明 |
|--------|------|------|
| `run.top_k` | `5` | 深析 + 推送论文数量上限 |
| `run.score_threshold` | `30` | 进入 LLM 阶段的最低规则分 |
| `run.dry_run` | `false` | 调试模式，不写库不推送 |
| `run.md_only` | `false` | 仅导出 Markdown，跳过数据库 |
| `run.pdf_download_enabled` | `true` | 自动下载 PDF |
| `run.fulltext_enabled` | `true` | PDF 全文分析（含图表提取） |
| `run.notion_native_blocks` | `true` | Notion 原生 Block 渲染 |

### Notion 集成（可选）

1. 创建 Notion Integration，复制 Internal Integration Token
2. 新建数据库，Share → 邀请 Integration
3. 从 URL 复制数据库 ID（32 位）
4. 填入 `notion.token` 和 `notion.database_id`
5. 运行校验：`python scripts/notion_check.py`

数据库需包含属性：`Title`(title) · `Modality`(select) · `Task`(select) · `Architecture`(select) · `Score`(number) · `Tags`(multi_select) · `Innovation`(rich_text) · `Source`(url) · `Date`(date)
> 缺失列系统自动创建（加 `MPF_` 前缀）。

---

## 🤖 LLM 部署

本项目对接 **OpenAI 兼容 API**，不绑定特定模型或服务商。

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

远端部署时，本地建立 SSH 端口映射：

```bash
ssh -N -f -L 8000:localhost:8000 your-username@YOUR_SERVER_IP
```

或使用项目脚本（密码交互输入，不写入文件）：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/open_tunnel.ps1 `
    -Server "your-username@YOUR_SERVER_IP"
```

### 方案 B：云端 API

将 `llm.api_key` 和 `llm.base_url` 替换为 OpenAI / Together AI / DeepSeek 等服务配置即可。

### 方案 C：GitHub Actions 全自动

参考 `.github/workflows/daily_run.yml`，在仓库 Secrets 中配置：

| Secret | 说明 |
|--------|------|
| `OPENAI_API_KEY` | API Key |
| `NOTION_TOKEN` | Notion Token（可选） |
| `NOTION_DB_ID` | 数据库 ID（可选） |
| `WEBHOOK_URL` | 推送地址（可选） |
| `PUBMED_EMAIL` | PubMed 邮箱（推荐） |

---

## 📂 目录结构

```
medpaper-flow/
├── main.py                          # 主入口，编排所有 Stage
├── config/domains/
│   ├── medical/
│   │   ├── runtime.yaml             # LLM · Notion · 推送 · 运行参数
│   │   ├── sources.yaml             # arXiv · PubMed · RSS · 会议
│   │   └── scoring_rules.yaml       # 机构白名单 · 关键词评分规则
│   └── cqed_plasmonics/             # 同结构，物理领域配置
├── src/
│   ├── fetchers/                    # 各数据源采集器
│   ├── storage/                     # SQLite · Notion · 推送状态
│   ├── deduplicator.py              # 语义去重
│   ├── scorer.py                    # 规则评分
│   ├── llm_pipeline.py              # LLM 过滤 · 精析 · 图表提取
│   ├── pdf_downloader.py            # PDF 下载
│   └── notifier.py                  # 消息模板 · Webhook 推送
├── scripts/
│   ├── build_papers_bundle.py       # 离线预抓取 bundle
│   ├── run_daily_dual_domains.ps1   # Windows 双域定时运行
│   ├── open_tunnel.ps1              # SSH 端口映射
│   └── start_vllm_server.sh         # Linux vLLM 启动
├── reports/                         # Markdown 日报输出
└── .github/workflows/daily_run.yml  # GitHub Actions 定时任务
```

---

## 🔌 进阶用法

### Windows 定时任务

```powershell
# 注册每日 05:30 双域任务
powershell -ExecutionPolicy Bypass -File scripts/register_daily_dual_domains_task.ps1 `
    -TaskName MedPaperFlow-DualDaily -StartTime 05:30 -Force

# 立即执行一次（双域）
powershell -ExecutionPolicy Bypass -File scripts/run_daily_dual_domains.ps1 `
    -RemoteUser "your-username" `
    -RemoteHost "YOUR_SERVER_IP" `
    -RemotePython "/path/to/miniconda/envs/vllm/bin/python"
```

### Bundle 离线导入（本地抓取 + 远端 LLM）

适合本地网络访问 arXiv/PubMed 稳定、远端 GPU 服务器负责 LLM 精析的场景：

```bash
# 本地：预抓取打包
python scripts/build_papers_bundle.py --domain medical

# 远端：导入继续精析、同步、推送
IMPORT_PAPERS_FILE=/path/to/papers.json \
IMPORT_PDF_ROOT=/path/to/bundle \
LOCAL_PDF_ONLY=true python main.py
```

### 扩展新领域

在 `config/domains/` 下新建目录，复制现有三个 YAML 并修改内容，运行时指定 `DOMAIN=your_domain` 即可，**无需修改任何源码**。

### 运行测试

```bash
pip install -r requirements-dev.txt
pytest -q
```

---

## 🔒 安全须知

- **不要提交** Notion Token、API Key、OpenReview 账密到公开仓库
- **不要提交** 服务器 IP、SSH 用户名——通过脚本参数传入或写入本地 `.env`（已在 `.gitignore`）
- SSH 密码不会写入任何文件，隧道脚本连接时交互输入
- Notion 数据库需先在 Share 中授权 Integration，否则返回 403
- 72B 模型 + 模型缓存建议预留 **50GB+** 磁盘空间
- `data/`、`logs/`、`tmp/`、`transfer/` 均已加入 `.gitignore`

---

## 🤝 贡献指南

欢迎提交 Issue 和 Pull Request！

- **扩展领域**：在 `config/domains/` 下添加配置目录，无需改源码
- **新数据源**：在 `src/fetchers/` 实现 Fetcher，返回标准化 paper dict，在 `main.py` 注册
- **Bug 修复 / 功能改进**：请附复现步骤或测试用例

提交前请确保测试通过：

```bash
pytest -q
```

---

## 📜 许可证

本项目基于 [MIT License](LICENSE) 开源。
