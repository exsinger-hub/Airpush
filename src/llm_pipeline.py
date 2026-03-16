from __future__ import annotations

import asyncio
import base64
import importlib
import json
import logging
import os
from pathlib import Path
import re
import time
import uuid
from io import BytesIO
from typing import Any
from urllib.parse import urljoin

import requests
from openai import AsyncOpenAI, OpenAI
from openai.types.chat import ChatCompletionUserMessageParam
from src.local_llm import LocalLLM

QUICK_FILTER_PROMPT = """
你在做"医学影像论文找idea"。请判断是否值得作为"可落地研究想法"进入下一轮。
仅输出 JSON：
{{
    "relevant": true/false,
    "idea_worthy": true/false,
    "topic": "imaging|recon|agent|none",
    "reason": "一句话理由",
    "idea_hint": "一个有逻辑有依据的想法钩子"
}}

判定标准：
1) 必须与医学影像生成/重建/多模态/临床智能体相关；
2) 必须有可执行创新点（新损失/新训练策略/新数据构造/新评测协议/新工程技巧其一）；
3) 纯概念描述、泛泛应用或信息不足则 idea_worthy=false。

标题：{title}
摘要：{abstract_snippet}
"""

PHYSICS_QUICK_FILTER_PROMPT = """
你在做"量子/凝聚态/CQED/等离激元论文找idea"。请判断是否值得作为"可落地研究想法"进入下一轮。
仅输出 JSON：
{{
    "relevant": true/false,
    "idea_worthy": true/false,
    "topic": "cqed|plasmonics|quantum|materials|none",
    "reason": "一句话理由",
    "idea_hint": "一个有逻辑有依据的想法钩子"
}}

判定标准：
1) 必须与腔量子电动力学、等离激元、纳米光子学、量子器件、量子材料或相关实验/理论机制直接相关；
2) 必须有可执行创新点（新结构、新耦合机制、新测量方案、新制备工艺、新参数区间、新理论框架其一）；
3) 纯现象罗列、泛泛综述、工程信息不足或无法转化为后续研究方案则 idea_worthy=false。

标题：{title}
摘要：{abstract_snippet}
"""

DEEP_EXTRACT_PROMPT = """
你是资深医学图像AI专家。提取以下摘要的结构化信息，只输出JSON。
每个文本字段至少写 2 句话，包含具体方法名/技术名词/数值，禁止一句话敷衍。

输出格式:
{{
    "abstract_zh": "摘要完整中文翻译（尽量逐句忠实，不要省略，未知则填未提及）",
    "tldr": "一句话概括核心痛点、方法与效果，含具体指标提升数值（未知则填未提及）",
    "task_modality": "具体模态与任务（如 3D MRI 脑肿瘤分割 / CT-MRI 跨模态合成 / 病理 WSI 分类，未知则填未提及）",
    "architecture_innovation": "架构创新细节：提出了什么新模块/新机制？具体设计是什么？至少 2 句（未知则填未提及）",
    "baselines": "核心对比基线方法名称列表（未知则填未提及）",
    "clinical_compliance": "临床价值或合规讨论：解决了什么临床场景的实际问题？（未知则填未提及）",
    "reviewer_critique": "审稿人视角局限性点评：至少指出 2 个不足（未知则填未提及）",
    "idea_takeaway": "可复用研究策略清单（给出3条，每条包含：思路->实施要点->预期收益）",
    "repro_recipe": "最小可复现实验路径（3步内，含具体框架/数据要求，未知则填未提及）",
    "next_experiment": "你建议的下一步实验（可执行，含具体方向和预期验证点，未知则填未提及）",
    "ablation_gap": "最关键但缺失的消融实验是什么？如果做了会验证什么假设？（未知则填未提及）",
    "idea_score": 1-10,
    "implementation_effort": 1-5,
    "modality": "MRI|CT|US|PET|Pathology|X-Ray|Multi|未提及",
    "task": "Generation|Translation|Reconstruction|Segmentation-aided|Super-Resolution|未提及",
    "architecture": "Diffusion|GAN|Transformer|Mamba|LLM|VAE|Hybrid|Multi-Agent|未提及",
    "institution": "第一作者主要机构简称（未知则填未提及）",
    "innovation_core": "核心创新点：提出了什么新方法？与现有工作的本质区别是什么？至少 2 句含具体模块名（未知则填未提及）",
    "clinical_problem": "解决的临床痛点：现有方案的具体不足是什么？新方法如何改善？至少 2 句（未知则填未提及）",
    "performance_gain": "关键指标提升：具体数据集上哪些指标提升了多少？列出数值（如 Dice +2.3%, AUC 0.95->0.97）（未知则填未提及）",
    "limitations": "作者承认的主要局限：至少列出 2 点（未知则填未提及）",
    "readability_score": 1-5,
    "hype_score": 1-5
}}

注意：
1) 禁止输出 Unknown/null/N/A，缺失信息统一填"未提及"。
2) 允许结合标题、作者、来源、机构线索综合判断，不要只看摘要一句话。
3) 如果当前仅有摘要而无全文，请将无法确认的实验细节写为"需查阅原文确认"。
4) 每个字段要有信息密度，让读者不看原文也能快速抓住关键点。

标题: {title}
作者: {authors}
来源: {source}
机构线索: {affiliation}
摘要: {abstract}
"""

FULLTEXT_IDEA_PROMPT = """
你是严苛的医学影像顶会审稿人（MICCAI/CVPR/MIA 视角）。
请基于论文正文信息输出"可执行 idea 情报"，仅输出 JSON。

输出格式:
{{
    "abstract_zh": "摘要完整中文翻译（尽量逐句忠实，不要省略，未知则填未提及）",
    "tldr": "一句话概括核心方法与收益（未知填未提及）",
    "task_modality": "任务+模态（未知填未提及）",
    "architecture_innovation": "具体结构/损失/训练机制改动（未知填未提及）",
    "baselines": "关键数据集与对比基线（未知填未提及）",
    "clinical_compliance": "临床价值或合规线索（未知填未提及）",
    "reviewer_critique": "审稿人毒舌点评（主要短板/风险，未知填未提及）",
    "idea_takeaway": "可复用研究策略清单（给出3条，每条包含：思路→实施要点→预期收益）",
    "repro_recipe": "最小可复现实验路径（3步内，未知填未提及）",
    "next_experiment": "下一步最该做的实验（未知填未提及）",
    "ablation_gap": "最关键但缺失的消融（未知填未提及）",
    "evidence_anchor": "2-3个可定位证据锚点（章节/表格/指标），未知填未提及",
    "idea_score": 1-10,
    "implementation_effort": 1-5,
    "modality": "MRI|CT|US|PET|Pathology|X-Ray|Multi|未提及",
    "task": "Generation|Translation|Reconstruction|Segmentation-aided|Super-Resolution|未提及",
    "architecture": "Diffusion|GAN|Transformer|Mamba|LLM|VAE|Hybrid|Multi-Agent|未提及",
    "institution": "第一作者主要机构简称（未知填未提及）",
    "innovation_core": "核心创新（未知填未提及）",
    "clinical_problem": "解决的临床痛点（未知填未提及）",
    "performance_gain": "关键指标提升（必须含数值或写未提及）",
    "limitations": "作者承认或你识别的主要局限（未知填未提及）",
    "readability_score": 1-5,
    "hype_score": 1-5
}}

要求：
1) 禁止输出 Unknown/null/N/A，缺失统一填"未提及"；
2) 优先引用正文中的方法、实验、消融证据，不要空泛总结；
3) 如果正文信息不充分，明确写"未提及"。

标题: {title}
作者: {authors}
来源: {source}
机构线索: {affiliation}
正文（已截断）:
{full_text}
"""

FULLTEXT_REVIEW_PROMPT = """
你是一个严苛的 MICCAI / CVPR / MIA 资深审稿人。
请阅读以下医学影像领域论文的正文/核心段落，并提取最硬核信息。
必须且只能返回合法 JSON，不要输出 Markdown、代码块或额外解释。

【论文标题】: {title}
【论文正文内容】:
{full_text_content}

请严格输出如下 JSON 结构（每个字段至少 2-4 句话，包含具体方法名/模块名/数值，禁止一句话带过）：
{{
    "tldr": "一句话概括：方法、痛点、核心收益（含具体指标提升数值）。",
    "clinical_problem": "该论文解决的临床痛点是什么？现有方案的具体不足在哪里？至少写 2-3 句。",
    "innovation_core": "核心创新点拆解：提出了什么新方法/新架构/新策略？与已有工作的本质区别是什么？至少写 3 句，需包含具体模块名称和技术细节。",
    "performance_gain": "关键指标提升：在哪些数据集上，哪些指标提升了多少？列出具体数值对比（如 Dice +2.3%, PSNR +1.5dB）。若有多个数据集/任务，逐一列出。",
    "modality_task": "具体模态与任务（如 3D MRI 脑肿瘤分割 / CT-MRI 跨模态合成 / 病理 WSI 分类）。",
    "the_magic": "核心机制深度拆解（至少 3-5 句）：1) 网络整体架构是什么？ 2) 关键模块的设计细节（输入输出维度/注意力类型/损失函数公式） 3) 训练策略的特殊设计（数据增强/课程学习/多阶段训练）。",
    "experiment_assets": "明确列出：1) 所有使用的数据集名称及规模 2) 所有对比基线方法名称 3) 评测指标列表。",
    "method_pipeline": "方法流程分步拆解（至少 4-6 步）：从输入数据预处理到最终输出，每步写清楚输入/操作/输出，含训练和推理两条路径的差异。",
    "experimental_protocol": "实验协议完整细节：数据划分方式/交叉验证/超参数设置（学习率/batch size/optimizer）/训练硬件/训练时长/评测协议。",
    "quantitative_results": "关键定量结果表格化描述：逐数据集、逐指标写出本方法 vs 最强基线的具体数值和提升幅度。若有置信区间或统计检验也需列出。",
    "ablation_study": "消融实验核心结论（至少 2-3 条）：每个被消融的组件对性能的影响数值。若文中无消融实验，写'文中未包含消融实验细节'。",
    "failure_boundary": "失败案例与适用边界：在哪些场景/数据/条件下性能下降？鲁棒性测试结果如何？已知局限是什么？",
    "reproducibility_checklist": "可复现性清单：是否开源代码（附链接）/数据集是否公开/是否固定随机种子/完整训练时长/依赖版本号。",
    "evidence_map": "结论到证据映射：每个核心结论由哪张图/哪个表/哪个章节支撑？格式如 '结论X -> Table Y / Figure Z / Section W'。",
    "steal_value": "可迁移到其他任务的可复用设计：1) 哪个模块可以即插即用？ 2) 哪个训练技巧可以借鉴？ 3) 预期在什么场景下有收益？每条写 1-2 句。",
    "hype_check": "毒舌审稿点评（至少 3 句）：真实创新度几成？有多少是已有工作的简单组合？实验设计是否充分？主要局限和潜在风险是什么？",
    "figure_captions_zh": {{"Figure N": "对应图注的完整中文翻译（仅翻译正文中实际出现的 Figure/Fig 图注，key 格式为 'Figure 1'/'Figure 2' 等，value 为完整中文翻译；无图注则填 {{}}）"}},
    "idea_score": 1-10,
    "implementation_effort": 1-5
}}

要求：
1) 禁止输出 Unknown/null/N/A，缺失统一写"未提及"；
2) 如果正文信息不足，明确写"未提及"；
3) 优先给可执行细节，不要泛化陈述；
4) 每个文本字段至少写 2 句完整的话，包含具体名词和数值，禁止空泛描述；
5) 拆解要让读者不看原文也能抓住核心技术要点和关键结果。
"""

ABSTRACT_TRANSLATE_PROMPT = """
请将下面论文摘要完整翻译成中文。
要求：
1) 忠实原文，不要省略关键实验设置、指标、数值和结论；
2) 不要添加原文没有的内容；
3) 仅输出翻译后的中文正文，不要输出解释或前后缀。

摘要原文：
{abstract}
"""

PHYSICS_DEEP_EXTRACT_PROMPT = """
你是一个极其严谨的物理学（量子物理/凝聚态物理）顶级期刊资深审稿人。
请阅读以下论文信息并提取核心物理图像，只输出 JSON。
每个文本字段至少写 2 句话，包含具体参数/数值/系统名，禁止一句话敷衍。

输出格式:
{{
    "abstract_zh": "摘要完整中文翻译（尽量逐句忠实，不要省略，未知填未提及）",
    "tldr": "一句话概括：研究了什么系统，观测/实现了什么突破，含具体数值（未知填未提及）",
    "physical_system": "核心物理系统：具体材料/器件/腔体结构是什么？工作温度/频率/尺度范围？至少 2 句（未知填未提及）",
    "core_mechanism": "核心物理机制：涉及哪些物理效应/耦合关系？与已有工作的本质区别？至少 2-3 句含具体机制名（未知填未提及）",
    "experimental_setup": "关键实验装置与技术：具体仪器/平台/测量手段/技术参数，纯理论填纯理论推导（至少 2 句）",
    "key_results": "核心观测数据与极限（至少列出 3 个具体数值或指标：如 Q 因子、耦合强度 g、保真度、温度极限等）",
    "error_and_decoherence": "误差与退相干：主要来源是什么？量化分析（量级/百分比）？如何抑制？至少 2 句（未知填未提及）",
    "future_impact": "研究推进逻辑（至少3点）：1)对哪个领域有何影响；2)需要满足什么触发条件；3)关键风险/挑战是什么",
    "reviewer_critique": "审稿人点评：至少指出 2 个主要短板、苛刻条件或过强假设（未知填未提及）",
    "idea_takeaway": "可复用研究策略清单（给出3条，每条包含：思路->实施要点->预期收益）",
    "repro_recipe": "最小复现实验路径（3步内，含具体装置/材料要求，未知填未提及）",
    "next_experiment": "下一步最值得做的实验：具体说明目标/方法/预期结果（未知填未提及）",
    "evidence_anchor": "2-3个证据锚点（图号/表号/章节，格式如 Figure 2 / Table 1 / Section 3，未知填未提及）",
    "idea_score": 1-10,
    "implementation_effort": 1-5,
    "institution": "主要机构简称（未知填未提及）",
    "innovation_core": "核心创新：提出了什么新方法/新结构/新现象？与已有工作的本质区别？至少 2 句（未知填未提及）",
    "performance_gain": "关键指标提升：具体数值对比（如 Q 从 X 提升到 Y，保真度 +Z%），至少列 2 个数值（未知填未提及）",
    "limitations": "主要局限：至少列出 2 点（未知填未提及）",
    "readability_score": 1-5,
    "hype_score": 1-5
}}

要求：
1) 只能返回合法 JSON；
2) 禁止输出 Unknown/null/N/A，缺失统一填"未提及"；
3) 无法确认处写"需查阅原文确认"；
4) 每个字段要有信息密度，让读者不看原文也能快速抓住核心物理图像。

标题: {title}
作者: {authors}
来源: {source}
机构线索: {affiliation}
摘要: {abstract}
"""

PHYSICS_FULLTEXT_IDEA_PROMPT = """
你是顶级量子物理/凝聚态物理审稿人。
请基于论文正文输出结构化评审 JSON。
每个文本字段至少写 2 句话，包含具体参数/数值/系统名，禁止一句话敷衍。

输出格式:
{{
    "abstract_zh": "摘要完整中文翻译（尽量逐句忠实，未知填未提及）",
    "tldr": "一句话概括核心系统、机制与结果（含具体数值）",
    "physical_system": "核心物理系统（至少 2 句）：具体材料/器件/腔体结构？工作温度/频率/尺度？",
    "core_mechanism": "关键物理机制或理论框架（至少 2-3 句）：涉及哪些物理效应/耦合关系？关键参数方程？",
    "experimental_setup": "关键实验装置/操控手段（至少 2 句）：纯理论填纯理论推导",
    "key_results": "核心测量结果与极限（至少列 3 个具体数值/指标）",
    "error_and_decoherence": "误差与退相干：主要来源？各项量级？抑制手段？（至少 2 句）",
    "future_impact": "研究推进逻辑（至少 3 点）：1)影响对象；2)触发条件；3)关键风险",
    "reviewer_critique": "主要局限与审稿意见（至少指出 2 个短板）",
    "idea_takeaway": "可复用研究策略清单（给出 3 条，每条：思路->实施要点->预期收益）",
    "repro_recipe": "最小复现实验路径（3步内，含具体装置/材料要求）",
    "next_experiment": "建议下一步实验（含具体目标/方法/预期结果）",
    "evidence_anchor": "2-3 个证据锚点（图号/表号/章节，格式如 Figure 2 / Table 1）",
    "idea_score": 1-10,
    "implementation_effort": 1-5,
    "institution": "主要机构简称（未知填未提及）",
    "innovation_core": "核心创新（至少 2 句）：提出了什么新方法/新结构/新现象？与已有工作本质区别？",
    "performance_gain": "关键指标提升（至少 2 个具体数值对比）",
    "limitations": "主要局限（至少列 2 点）",
    "readability_score": 1-5,
    "hype_score": 1-5
}}

要求：
1) 只能返回合法 JSON；
2) 缺失统一"未提及"；
3) 强调物理可验证结论，避免空泛描述；
4) 每个字段至少 2 句话，包含具体名词和数值。

标题: {title}
作者: {authors}
来源: {source}
机构线索: {affiliation}
正文（已截断）:
{full_text}
"""

PHYSICS_FULLTEXT_REVIEW_PROMPT = """
你是 PRL/Nature Physics 视角的严格审稿人。
请阅读论文正文，提取最核心的物理信息，只输出 JSON。
每个字段至少写 2-4 句话，包含具体参数/数值/系统名/效应名，禁止一句话带过。

【论文标题】: {title}
【论文正文内容】:
{full_text_content}

请严格输出如下 JSON（每个文本字段至少 2 句完整的话，包含具体数值和术语）：
{{
    "tldr": "一句话概括：系统+机制+核心发现（含具体数值）",
    "innovation_core": "核心创新点（至少 3 句）：提出了什么新机制/新结构/新现象？与已有工作本质区别？具体涉及哪些物理效应或器件设计？",
    "performance_gain": "关键指标提升（至少列出 3 个具体数值对比）：Q 因子、耦合强度 g、保真度、温度极限、线宽等具体数值与已有工作对比",
    "physical_system": "核心物理系统（至少 2 句）：具体材料/器件结构/腔体类型是什么？工作温度/波长/频率/尺度是多少？",
    "core_mechanism": "核心物理机制（至少 3 句）：涉及哪些物理效应/耦合关系/量子效应？关键参数方程？与已有理论的区别？",
    "experimental_setup": "关键实验装置与操控（至少 2 句）：具体仪器/平台/激光参数/低温系统/测量手段，纯理论填纯理论推导",
    "method_pipeline": "方法或实验流程分步拆解（至少 4-5 步）：从样品制备/初态制备到测量读出，每步写清楚操作和关键参数",
    "experimental_protocol": "实验协议完整细节：样品规格/工作点参数/测量流程/校准方法/数据处理步骤",
    "key_results": "关键观测结果（至少列 3 个具体数值/极限）：主曲线特征值、信噪比、对比度、极限参数等",
    "error_and_decoherence": "误差与退相干（至少 2 句）：主要来源是什么？各项贡献量级？采取了哪些抑制手段？",
    "failure_boundary": "失败案例与参数边界（至少 2 句）：在哪些条件下性能下降？适用范围的上下限？",
    "reproducibility_checklist": "复现清单：装置参数/样品条件/测量窗口/数据处理流程/开源状态",
    "evidence_map": "结论到证据映射：每个核心结论由哪张图/哪个表/哪个章节支撑，格式如 '结论X -> Figure Y / Table Z'",
    "future_impact": "研究推进逻辑（至少 3 点）：1)对哪个领域有何影响；2)需满足什么触发条件；3)关键风险/挑战",
    "idea_takeaway": "可复用研究策略（给出 3 条，每条格式：思路->实施要点->预期收益）",
    "reviewer_critique": "审稿人毒舌点评（至少 3 句）：真实创新度、实验条件苛刻程度、过强假设、主要弱点",
    "figure_captions_zh": {{"Figure N": "对应图注的完整中文翻译（key 格式为 'Figure 1'/'Figure 2' 等；无图注则填 {{}}）"}},
    "idea_score": 1-10,
    "implementation_effort": 1-5
}}

要求：
1) 仅返回合法 JSON；
2) 缺失写"未提及"；
3) 不要写医学AI术语（如消融、基线）；
4) 每个字段至少写 2 句完整的话，包含具体名词和数值，禁止空泛描述；
5) 拆解要让读者不看原文也能抓住核心物理图像和关键实验结果。
"""

FIGURE_SELECTION_PROMPT = """
你是论文图表甄选助手。请从候选 figure 区域中选出最值得放入 Notion 的图（最多 {max_images} 张）。
优先级：
1) 方法总览图/系统示意图；
2) 核心实验结果图（主曲线、关键对比）；
3) 机制解释图。

排除：Logo、纯装饰图、页眉页脚、作者照片、重复图、分辨率低图、无信息图。
优先参考每张图自带的 caption / nearby_text，不要凭空猜图意。
候选区域可能包含多张子图，它们已经按版面布局聚合成同一个 figure 区域。

论文标题：{title}
论文摘要：{abstract}

候选图（JSON）：
{candidates_json}

仅输出 JSON：
{{
    "selected_ids": [候选id数组，按优先级排序]
}}
"""


class LLMPipeline:
    def __init__(self):
        self.domain = (os.getenv("DOMAIN", "medical") or "medical").strip().lower()
        self.is_physics_domain = self.domain in {"cqed_plasmonics", "physics", "quantum", "plasmonics", "cqed"}
        base_url = os.getenv("OPENAI_BASE_URL", "").strip() or None
        api_key = os.getenv("OPENAI_API_KEY", "").strip() or None
        self.client = OpenAI(base_url=base_url, api_key=api_key)
        self.async_client = AsyncOpenAI(base_url=base_url, api_key=api_key)
        self.quick_model = os.getenv("LLM_QUICK_MODEL", "gpt-4o-mini")
        self.deep_model = os.getenv("LLM_DEEP_MODEL", "gpt-4o")
        self.fulltext_model = os.getenv("LLM_FULLTEXT_MODEL", os.getenv("LLM_DEEP_MODEL", "gpt-4o"))
        self.request_timeout = int(os.getenv("LLM_REQUEST_TIMEOUT", "180"))
        self.max_retries = max(0, int(os.getenv("LLM_MAX_RETRIES", "2")))
        self.circuit_breaker_fails = max(1, int(os.getenv("LLM_CIRCUIT_BREAKER_FAILS", "2")))
        self.deep_stage_max_seconds = max(30, int(os.getenv("LLM_DEEP_STAGE_MAX_SECONDS", "300")))
        self.fulltext_max_tokens = int(os.getenv("LLM_FULLTEXT_MAX_TOKENS", "3200"))
        self.deep_extract_max_tokens = int(os.getenv("LLM_DEEP_EXTRACT_MAX_TOKENS", "8192"))
        self.abstract_translate_max_tokens = int(os.getenv("LLM_ABSTRACT_TRANSLATE_MAX_TOKENS", "4096"))
        self.max_input_tokens = max(2000, int(os.getenv("LLM_MAX_INPUT_TOKENS", "24000")))
        self.temperature = float(os.getenv("LLM_TEMPERATURE", "0.3"))
        self.top_p = float(os.getenv("LLM_TOP_P", "0.85"))
        self.presence_penalty = float(os.getenv("LLM_PRESENCE_PENALTY", "0.2"))
        self.fulltext_concurrency = max(1, int(os.getenv("LLM_FULLTEXT_CONCURRENCY", "2")))
        self.fulltext_semaphore = asyncio.Semaphore(self.fulltext_concurrency)
        self.enable_pdf_routing = str(os.getenv("ENABLE_PDF_ROUTING", "true")).lower() == "true"
        self.prefer_pdf_fulltext = str(os.getenv("PREFER_PDF_FULLTEXT", "true")).lower() == "true"
        self.local_pdf_only = str(os.getenv("LOCAL_PDF_ONLY", "false")).lower() == "true"
        self.pdf_fetch_timeout = max(5, int(os.getenv("PDF_FETCH_TIMEOUT", "20")))
        self.fulltext_word_min = max(200, int(os.getenv("FULLTEXT_WORD_MIN", "300")))
        self.fulltext_word_max = max(self.fulltext_word_min, int(os.getenv("FULLTEXT_WORD_MAX", "22000")))
        self.enable_figure_hosting = str(os.getenv("FIGURE_HOSTING_ENABLED", "false")).lower() == "true"
        self.use_llm_for_figure_selection = str(os.getenv("FIGURE_SELECTION_USE_LLM", "true")).lower() == "true"
        self.figure_max_images = max(1, int(os.getenv("FIGURE_MAX_IMAGES", "3")))
        self.figure_scan_pages = max(10, int(os.getenv("FIGURE_SCAN_PAGES", "80")))
        self.figure_candidate_limit = max(6, int(os.getenv("FIGURE_CANDIDATE_LIMIT", "24")))
        self.figure_selection_timeout = max(10, int(os.getenv("FIGURE_SELECTION_TIMEOUT", "45")))
        self.figure_selection_total_budget = max(
            self.figure_selection_timeout,
            int(os.getenv("FIGURE_SELECTION_TOTAL_BUDGET", "90")),
        )
        self.figure_selection_attempts = max(1, int(os.getenv("FIGURE_SELECTION_ATTEMPTS", "3")))
        self.figure_llm_candidate_cap = max(
            self.figure_max_images + 1,
            int(os.getenv("FIGURE_LLM_CANDIDATE_CAP", "8")),
        )
        self.github_token = str(os.getenv("GITHUB_TOKEN", "")).strip()
        self.github_user = str(os.getenv("GITHUB_USER", "")).strip()
        self.github_repo = str(os.getenv("GITHUB_REPO", "")).strip()
        self.github_branch = str(os.getenv("GITHUB_BRANCH", "main")).strip() or "main"
        self.github_timeout = max(8, int(os.getenv("GITHUB_UPLOAD_TIMEOUT", "20")))
        self.local_llm = LocalLLM(os.getenv("LLM_LOCAL_MODEL", "qwen2.5:7b"))
        disable_local_quick = str(os.getenv("DISABLE_LOCAL_QUICK", "false")).lower() == "true"
        self.use_local_quick = (not disable_local_quick) and self.local_llm.is_available()
        if self.use_local_quick:
            logging.info("LLM 快筛使用本地模型: %s", os.getenv("LLM_LOCAL_MODEL", "qwen2.5:7b"))
        else:
            logging.info("LLM 快筛使用云端模型: %s", self.quick_model)

    @staticmethod
    def _extract_first_json_object(text: str) -> dict[str, Any]:
        cleaned = LLMPipeline._strip_llm_wrappers(str(text or "")).replace("\ufeff", "").strip()
        if not cleaned:
            return {}

        try:
            parsed = json.loads(cleaned)
            if isinstance(parsed, dict):
                return parsed
            if isinstance(parsed, list) and len(parsed) == 1 and isinstance(parsed[0], dict):
                return parsed[0]
        except Exception:
            pass

        decoder = json.JSONDecoder()
        for index, char in enumerate(cleaned):
            if char not in "[{":
                continue
            try:
                parsed, _ = decoder.raw_decode(cleaned[index:])
            except Exception:
                continue
            if isinstance(parsed, dict):
                return parsed
            if isinstance(parsed, list) and len(parsed) == 1 and isinstance(parsed[0], dict):
                return parsed[0]
        return {}

    def _safe_json(self, text: str, log_fail: bool = True) -> dict[str, Any]:
        parsed = self._extract_first_json_object(text)
        if parsed:
            return parsed
        if log_fail:
            logging.warning("LLM JSON 解析失败，内容: %s", str(text or "")[:300])
        return {}

    @staticmethod
    def _strip_llm_wrappers(text: str) -> str:
        cleaned = str(text or "").strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", cleaned)
            cleaned = re.sub(r"\s*```$", "", cleaned).strip()
        cleaned = re.sub(r"^(markdown|md|json|text)\s*[:：]?\s*\n", "", cleaned, flags=re.IGNORECASE).strip()
        return cleaned

    @staticmethod
    def _unwrap_text_payload(value: Any) -> str:
        if isinstance(value, str):
            return LLMPipeline._strip_llm_wrappers(value)
        if isinstance(value, dict):
            for key in (
                "@/content",
                "@/value",
                "content",
                "value",
                "text",
                "result",
                "translation",
                "translated",
                "abstract_zh",
                "摘要",
            ):
                inner = value.get(key)
                if inner is None:
                    continue
                unwrapped = LLMPipeline._unwrap_text_payload(inner)
                if unwrapped:
                    return unwrapped
            string_values = [LLMPipeline._unwrap_text_payload(v) for v in value.values()]
            string_values = [item for item in string_values if item]
            if len(string_values) == 1:
                return string_values[0]
            return ""
        if isinstance(value, list):
            parts = [LLMPipeline._unwrap_text_payload(item) for item in value]
            parts = [item for item in parts if item]
            if len(parts) == 1:
                return parts[0]
            return "\n".join(parts).strip()
        return ""

    @staticmethod
    def _summarize_plain_text(text: str, limit: int = 120) -> str:
        cleaned = re.sub(r"\s+", " ", str(text or "")).strip(" \n\r\t\"'{}[]")
        if not cleaned:
            return "未提及"
        sentence = re.split(r"(?<=[。！？!?;；.])\s*", cleaned, maxsplit=1)[0].strip()
        if not sentence:
            sentence = cleaned
        return sentence[:limit].strip() or "未提及"

    @staticmethod
    def _sanitize_abstract_translation(text: str) -> str:
        raw = LLMPipeline._strip_llm_wrappers(str(text or "")).replace("\ufeff", "").strip()
        if not raw:
            return "未提及"

        candidates: list[str] = [raw]
        marker_patterns = [
            r"仅输出翻译后的中文正文如下\s*[:：]",
            r"翻译后的中文正文如下\s*[:：]",
            r"中文正文如下\s*[:：]",
            r"输出如下\s*[:：]",
        ]
        for pattern in marker_patterns:
            for match in re.finditer(pattern, raw, flags=re.IGNORECASE):
                candidates.append(raw[match.end() :].strip())

        quoted_candidates = re.findall(r'"([^"\n]{20,})"', raw)
        candidates.extend(quoted_candidates)

        if raw.startswith("{") and "}" in raw:
            candidates.append(raw[1 : raw.rfind("}")].strip())

        noise_markers = [
            "请注意",
            "根据要求",
            "再次强调",
            "实际翻译应",
            "实际的翻译应",
            "仅输出翻译后的中文正文",
            "不包括任何额外说明",
            "不要输出解释或前后缀",
        ]

        def _clean_candidate(candidate: str) -> str:
            value = LLMPipeline._strip_llm_wrappers(str(candidate or "")).replace("\ufeff", "").strip()
            if not value:
                return ""
            value = re.sub(
                r'^\s*(?:摘要(?:完整中文翻译)?|abstract_zh|translation|translated|中文正文)\s*[:：]\s*',
                "",
                value,
                flags=re.IGNORECASE,
            )
            value = re.sub(
                r'^\{?\s*"?(?:摘要|abstract_zh|translation|translated|content|result)"?\s*:\s*"?',
                "",
                value,
                flags=re.IGNORECASE,
            )
            cut_positions = [value.find(marker) for marker in noise_markers if value.find(marker) > 0]
            if cut_positions:
                value = value[: min(cut_positions)]
            value = re.sub(r"\s+", " ", value).strip(" \n\r\t\"'{}[]")
            return value

        def _score_candidate(candidate: str) -> int:
            if not candidate or candidate.lower() in {"unknown", "none", "null", "n/a"}:
                return -1
            chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", candidate))
            noise_hits = sum(candidate.count(marker) for marker in noise_markers)
            return chinese_chars * 10 + min(len(candidate), 2000) - noise_hits * 500

        normalized_candidates: list[str] = []
        for candidate in candidates:
            cleaned = _clean_candidate(candidate)
            if cleaned:
                normalized_candidates.append(cleaned)

        if not normalized_candidates:
            return "未提及"

        best = max(normalized_candidates, key=_score_candidate)
        return best if _score_candidate(best) >= 0 else "未提及"

    def _coerce_extraction_from_text(self, text: str) -> dict[str, Any]:
        cleaned = self._strip_llm_wrappers(text)
        compact = re.sub(r"\s+", " ", cleaned).strip(" \n\r\t\"'{}[]")
        if not compact:
            return {}

        def _pick(patterns: list[str]) -> str:
            for pattern in patterns:
                match = re.search(pattern, cleaned, flags=re.IGNORECASE | re.DOTALL)
                if match:
                    value = re.sub(r"\s+", " ", match.group(1)).strip(" \n\r\t\"'{}[]")
                    if value:
                        return value
            return ""

        common = {
            "abstract_zh": _pick([
                r'"abstract_zh"\s*:\s*"(.*?)"',
                r"摘要(?:完整中文翻译)?\s*[:：]\s*(.+?)(?:\n\S|$)",
            ]),
            "tldr": _pick([
                r'"tldr"\s*:\s*"(.*?)"',
                r"(?:tldr|一句话概括|核心概括)\s*[:：]\s*(.+?)(?:\n\S|$)",
            ]),
            "idea_takeaway": _pick([
                r'"idea_takeaway"\s*:\s*"(.*?)"',
                r"(?:idea[_ ]?takeaway|可复用研究策略清单)\s*[:：]\s*(.+?)(?:\n\S|$)",
            ]),
            "reviewer_critique": _pick([
                r'"reviewer_critique"\s*:\s*"(.*?)"',
                r"(?:reviewer[_ ]?critique|审稿人点评)\s*[:：]\s*(.+?)(?:\n\S|$)",
            ]),
            "innovation_core": _pick([
                r'"innovation_core"\s*:\s*"(.*?)"',
                r"(?:innovation[_ ]?core|核心创新)\s*[:：]\s*(.+?)(?:\n\S|$)",
            ]),
            "performance_gain": _pick([
                r'"performance_gain"\s*:\s*"(.*?)"',
                r"(?:performance[_ ]?gain|关键指标提升|关键结果)\s*[:：]\s*(.+?)(?:\n\S|$)",
            ]),
            "limitations": _pick([
                r'"limitations"\s*:\s*"(.*?)"',
                r"(?:limitations|主要局限)\s*[:：]\s*(.+?)(?:\n\S|$)",
            ]),
        }

        if self.is_physics_domain:
            common.update(
                {
                    "physical_system": _pick([
                        r'"physical_system"\s*:\s*"(.*?)"',
                        r"(?:physical[_ ]?system|核心物理系统)\s*[:：]\s*(.+?)(?:\n\S|$)",
                    ]),
                    "core_mechanism": _pick([
                        r'"core_mechanism"\s*:\s*"(.*?)"',
                        r"(?:core[_ ]?mechanism|核心物理机制)\s*[:：]\s*(.+?)(?:\n\S|$)",
                    ]),
                    "experimental_setup": _pick([
                        r'"experimental_setup"\s*:\s*"(.*?)"',
                        r"(?:experimental[_ ]?setup|关键实验装置与技术)\s*[:：]\s*(.+?)(?:\n\S|$)",
                    ]),
                    "key_results": _pick([
                        r'"key_results"\s*:\s*"(.*?)"',
                        r"(?:key[_ ]?results|核心观测数据与极限)\s*[:：]\s*(.+?)(?:\n\S|$)",
                    ]),
                    "future_impact": _pick([
                        r'"future_impact"\s*:\s*"(.*?)"',
                        r"(?:future[_ ]?impact|研究推进逻辑)\s*[:：]\s*(.+?)(?:\n\S|$)",
                    ]),
                }
            )

        if not common.get("abstract_zh") and compact:
            common["abstract_zh"] = compact[:3000]
        if not common.get("tldr"):
            summary_source = common.get("innovation_core") or common.get("abstract_zh") or compact
            common["tldr"] = self._summarize_plain_text(summary_source)
        if not any(v for v in common.values() if isinstance(v, str) and v.strip()):
            return {}
        return {k: v for k, v in common.items() if isinstance(v, str) and v.strip()}

    def _parse_extraction_payload(self, text: str) -> dict[str, Any]:
        parsed = self._safe_json(text, log_fail=False)
        if parsed:
            return parsed
        fallback = self._coerce_extraction_from_text(text)
        if fallback:
            logging.warning("LLM 返回非 JSON，已使用文本兜底解析")
        else:
            logging.warning("LLM JSON 解析失败，内容: %s", str(text or "")[:300])
        return fallback

    def _translate_abstract_with_llm(self, abstract: str) -> str:
        src = str(abstract or "").strip()
        if not src:
            return "未提及"

        try:
            messages: list[ChatCompletionUserMessageParam] = [
                {
                    "role": "user",
                    "content": ABSTRACT_TRANSLATE_PROMPT.format(abstract=src[:12000]),
                }
            ]
            content = self._chat_with_retry(
                model=self.deep_model,
                messages=messages,
                max_tokens=self.abstract_translate_max_tokens,
            )
            text = self._strip_llm_wrappers(str(content or ""))
            if text.startswith("{") or text.startswith("```"):
                parsed = self._safe_json(text)
                if parsed:
                    for key in ("摘要", "abstract_zh", "translation", "translated", "content", "result", "@/content", "@/value"):
                        val = parsed.get(key)
                        extracted = self._unwrap_text_payload(val)
                        if extracted:
                            text = extracted
                            break
                    else:
                        values = [self._unwrap_text_payload(v) for v in parsed.values()]
                        values = [v for v in values if v]
                        if len(values) == 1:
                            text = values[0].strip()
            text = self._sanitize_abstract_translation(self._unwrap_text_payload(text) or text)
            if not text or text.lower() in {"unknown", "none", "null", "n/a"}:
                return "未提及"
            return text
        except Exception as exc:
            logging.warning("摘要翻译失败，回退未提及: %s", exc)
            return "未提及"

    def _translate_figure_captions(self, figure_items: list[dict[str, Any]]) -> dict[str, str]:
        """将 figure_items 中的英文图注翻译为中文，返回 {\"Figure 1\": \"中文...\", ...}。"""
        captions_en: dict[str, str] = {}
        for item in figure_items:
            cap = str(item.get("caption", "")).strip()
            if not cap:
                continue
            m = re.match(r"(Fig(?:ure)?\s*\.?\s*\d+)", cap, re.IGNORECASE)
            if m:
                norm_key = re.sub(r"(?i)fig(?:ure)?\s*\.?\s*(\d+)", r"Figure \1", m.group(1).strip())
                captions_en[norm_key] = cap
        if not captions_en:
            return {}
        prompt = (
            "将以下论文图注翻译为中文。只输出 JSON，key 保持不变，value 为完整中文翻译。\n"
            + json.dumps(captions_en, ensure_ascii=False)
        )
        try:
            messages: list[ChatCompletionUserMessageParam] = [{"role": "user", "content": prompt}]
            content = self._chat_with_retry(
                model=self.deep_model,
                messages=messages,
                max_tokens=2048,
            )
            parsed = self._safe_json(self._strip_llm_wrappers(str(content or "")))
            if isinstance(parsed, dict) and parsed:
                logging.info("图注翻译成功: %d 条", len(parsed))
                return {k: str(v) for k, v in parsed.items() if isinstance(v, str) and v.strip()}
        except Exception as exc:
            logging.warning("图注翻译失败: %s", exc)
        return {}

    @staticmethod
    def _looks_incomplete_translation(abstract_en: str, abstract_zh: str) -> bool:
        src = str(abstract_en or "").strip()
        zh = str(abstract_zh or "").strip()
        if not src or not zh:
            return True

        # 英文句子数 vs 中文句子数，中文明显偏少通常意味着被截断或漏译
        en_sentences = [s for s in re.split(r"[\.!?;]+", src) if s.strip()]
        zh_sentences = [s for s in re.split(r"[。！？；]+", zh) if s.strip()]
        if len(en_sentences) >= 3 and len(zh_sentences) + 1 < len(en_sentences):
            return True

        # 长度占比过低也视为可疑（中文通常不会低到英文长度的 40% 以下）
        if len(src) > 300 and len(zh) < int(len(src) * 0.4):
            return True

        return False

    @staticmethod
    def _normalize_extracted(extracted: dict[str, Any]) -> dict[str, Any]:
        defaults = {
            "abstract_zh": "未提及",
            "tldr": "未提及",
            "task_modality": "未提及",
            "architecture_innovation": "未提及",
            "baselines": "未提及",
            "clinical_compliance": "未提及",
            "reviewer_critique": "未提及",
            "idea_takeaway": "未提及",
            "repro_recipe": "未提及",
            "next_experiment": "未提及",
            "ablation_gap": "未提及",
            "idea_score": 5,
            "implementation_effort": 3,
            "modality": "未提及",
            "task": "未提及",
            "architecture": "未提及",
            "institution": "未提及",
            "innovation_core": "未提及",
            "clinical_problem": "未提及",
            "performance_gain": "未提及",
            "limitations": "未提及",
            "evidence_anchor": "未提及",
            "physical_system": "未提及",
            "core_mechanism": "未提及",
            "experimental_setup": "未提及",
            "key_results": "未提及",
            "error_and_decoherence": "未提及",
            "future_impact": "未提及",
            "analysis_route": "abstract",
            "readability_score": 3,
            "hype_score": 3,
        }
        merged = {**defaults, **(extracted or {})}
        for k, v in list(merged.items()):
            if isinstance(v, str) and v.strip().lower() in {"", "unknown", "none", "null", "n/a"}:
                merged[k] = "未提及"
        merged["abstract_zh"] = LLMPipeline._sanitize_abstract_translation(merged.get("abstract_zh", ""))
        return merged

    @staticmethod
    def _clean_text(raw: str) -> str:
        text = re.sub(r"\s+", " ", str(raw or "")).strip()
        # references 后内容通常是文献列表，截断以提升 prompt 信噪比
        cut = re.search(r"\b(references|bibliography|acknowledg(e)?ments?)\b", text, flags=re.IGNORECASE)
        if cut:
            text = text[: cut.start()].strip()
        return text

    @staticmethod
    def _clip_words(text: str, max_words: int) -> str:
        words = text.split()
        if len(words) <= max_words:
            return text
        return " ".join(words[:max_words])

    def _clip_input_for_context(self, text: str) -> str:
        """按 LLM_MAX_INPUT_TOKENS 进行近似截断（按字符粗估 token）。"""
        raw = str(text or "")
        if not raw:
            return ""
        # 粗略估算：英文约 1 token≈1.4~1.6 chars；中文更紧凑。保守采用 1.5
        max_chars = int(self.max_input_tokens * 1.5)
        return raw[:max_chars]

    @staticmethod
    def _guess_pdf_url(url: str) -> str:
        u = (url or "").strip()
        if not u:
            return ""
        lu = u.lower()
        if lu.endswith(".pdf"):
            return u
        if "arxiv.org/abs/" in lu:
            return re.sub(r"/abs/", "/pdf/", u).rstrip("/") + ".pdf"
        if "openreview.net/forum?id=" in lu:
            return u.replace("/forum?id=", "/pdf?id=")
        return u

    @classmethod
    def _candidate_pdf_urls(cls, paper: dict[str, Any]) -> list[str]:
        urls: list[str] = []
        for key in ("pdf_url", "url"):
            value = str(paper.get(key, "") or "").strip()
            if not value:
                continue
            urls.append(value)
            guessed = cls._guess_pdf_url(value)
            if guessed and guessed != value:
                urls.append(guessed)

        doi = str(paper.get("doi", "") or "").strip()
        if doi:
            urls.append(f"https://doi.org/{doi}")

        seen: set[str] = set()
        unique: list[str] = []
        for url in urls:
            if url and url not in seen:
                unique.append(url)
                seen.add(url)
        return unique

    @staticmethod
    def _looks_like_pdf_url(url: str) -> bool:
        value = str(url or "").strip().lower()
        if not value:
            return False
        return value.endswith(".pdf") or "/pdf/" in value or "/pdf?" in value or "downloadpdf" in value

    @staticmethod
    def _extract_pdf_url_from_html(html: str, base_url: str) -> str:
        m = re.search(r'<meta[^>]+name=["\']citation_pdf_url["\'][^>]+content=["\']([^"\']+)["\']', html, flags=re.I)
        if m:
            return urljoin(base_url, m.group(1).strip())

        patterns = [
            r'href=["\']([^"\']+\.pdf(?:\?[^"\']*)?)["\']',
            r'href=["\']([^"\']*/pdf/[^"\']*)["\']',
            r'href=["\']([^"\']*(?:/doi/pdf|/pdfdirect|downloadpdf)[^"\']*)["\']',
        ]
        for pattern in patterns:
            m = re.search(pattern, html, flags=re.I)
            if m:
                return urljoin(base_url, m.group(1).strip())

        if "ieeexplore" in base_url.lower():
            m = re.search(r'"pdfPath"\s*:\s*"([^"]+)"', html, flags=re.I)
            if m:
                return urljoin("https://ieeexplore.ieee.org", m.group(1).strip())

        return ""

    @staticmethod
    def _resolve_local_pdf_path(paper: dict[str, Any]) -> Path | None:
        value = str(paper.get("pdf_local_path", "") or "").strip()
        if not value:
            return None
        candidate = Path(value).expanduser()
        if candidate.exists() and candidate.is_file():
            return candidate
        return None

    def _read_local_pdf_bytes(self, paper: dict[str, Any]) -> tuple[bytes, str]:
        local_path = self._resolve_local_pdf_path(paper)
        if local_path is None:
            return b"", ""
        try:
            return local_path.read_bytes(), str(local_path)
        except Exception as exc:
            logging.warning("读取本地 PDF 失败 path=%s err=%s", local_path, exc)
            return b"", ""

    def _has_pdf_for_figure_selection(self, paper: dict[str, Any], resolved_pdf_url: str = "") -> bool:
        if self._resolve_local_pdf_path(paper) is not None:
            return True
        if resolved_pdf_url:
            return True
        if bool(paper.get("pdf_downloaded", False)):
            return True
        return bool(self._candidate_pdf_urls(paper))

    @staticmethod
    def _extract_pdf_text(pdf_bytes: bytes) -> str:
        try:
            PdfReader = getattr(importlib.import_module("pypdf"), "PdfReader")
        except Exception:
            logging.warning("未安装 pypdf，跳过 PDF 正文解析")
            return ""

        try:
            reader = PdfReader(BytesIO(pdf_bytes))
            pages: list[str] = []
            for page in reader.pages:
                try:
                    pages.append(page.extract_text() or "")
                except Exception:
                    continue
            return "\n".join(pages)
        except Exception as exc:
            logging.warning("PDF 解析失败: %s", exc)
            return ""

    def _fetch_pdf_text(self, paper: dict[str, Any]) -> tuple[str, str]:
        local_pdf_bytes, local_pdf_path = self._read_local_pdf_bytes(paper)
        if local_pdf_bytes:
            text = self._extract_pdf_text(local_pdf_bytes)
            if text.strip():
                return text, local_pdf_path
            if self.local_pdf_only:
                return "", ""

        candidates = self._candidate_pdf_urls(paper)

        if self.local_pdf_only:
            return "", ""

        for candidate in candidates:
            try:
                request_kwargs: dict[str, Any] = {"timeout": self.pdf_fetch_timeout}
                token = str(os.getenv("OPENREVIEW_ACCESS_TOKEN", "")).strip()
                if token and "openreview.net" in candidate.lower():
                    request_kwargs["cookies"] = {"openreview.accessToken": token}
                resp = requests.get(candidate, **request_kwargs)
                resp.raise_for_status()
                ctype = str(resp.headers.get("content-type", "")).lower()
                final_url = str(resp.url or candidate)

                data = resp.content
                if "pdf" not in ctype and not final_url.lower().endswith(".pdf") and not data.startswith(b"%PDF"):
                    html = resp.text if "text/html" in ctype else ""
                    if not html:
                        continue
                    resolved_pdf_url = self._extract_pdf_url_from_html(html, final_url)
                    if not resolved_pdf_url:
                        continue
                    resp = requests.get(resolved_pdf_url, **request_kwargs)
                    resp.raise_for_status()
                    final_url = str(resp.url or resolved_pdf_url)
                    data = resp.content
                    ctype = str(resp.headers.get("content-type", "")).lower()
                    if "pdf" not in ctype and not final_url.lower().endswith(".pdf") and not data.startswith(b"%PDF"):
                        continue

                text = self._extract_pdf_text(data)
                if text.strip():
                    return text, final_url
            except Exception as exc:
                logging.debug("PDF 下载/解析失败 url=%s err=%s", candidate, exc)

        return "", ""

    def _fetch_pdf_bytes_from_url(self, candidate: str) -> bytes:
        request_kwargs: dict[str, Any] = {"timeout": self.pdf_fetch_timeout}
        token = str(os.getenv("OPENREVIEW_ACCESS_TOKEN", "")).strip()
        if token and "openreview.net" in candidate.lower():
            request_kwargs["cookies"] = {"openreview.accessToken": token}
        resp = requests.get(candidate, **request_kwargs)
        resp.raise_for_status()
        return resp.content

    def _initialize_empty_github_repo_branch(self, headers: dict[str, str]) -> None:
        """为空仓库创建首个提交与目标分支，便于后续 contents API 上传。"""
        base_url = f"https://api.github.com/repos/{self.github_user}/{self.github_repo}"

        blob_res = requests.post(
            f"{base_url}/git/blobs",
            headers=headers,
            json={"content": "MedPaper-Flow figure hosting init\n", "encoding": "utf-8"},
            timeout=self.github_timeout,
        )
        if blob_res.status_code not in {200, 201}:
            raise RuntimeError(f"GitHub init blob failed status={blob_res.status_code} body={(blob_res.text or '')[:240]}")
        blob_sha = str(blob_res.json().get("sha", "")).strip()
        if not blob_sha:
            raise RuntimeError("GitHub init blob failed: missing sha")

        tree_res = requests.post(
            f"{base_url}/git/trees",
            headers=headers,
            json={
                "tree": [
                    {
                        "path": ".gitkeep",
                        "mode": "100644",
                        "type": "blob",
                        "sha": blob_sha,
                    }
                ]
            },
            timeout=self.github_timeout,
        )
        if tree_res.status_code not in {200, 201}:
            raise RuntimeError(f"GitHub init tree failed status={tree_res.status_code} body={(tree_res.text or '')[:240]}")
        tree_sha = str(tree_res.json().get("sha", "")).strip()
        if not tree_sha:
            raise RuntimeError("GitHub init tree failed: missing sha")

        commit_res = requests.post(
            f"{base_url}/git/commits",
            headers=headers,
            json={
                "message": "Initialize repository for MedPaper-Flow figure hosting",
                "tree": tree_sha,
                "parents": [],
            },
            timeout=self.github_timeout,
        )
        if commit_res.status_code not in {200, 201}:
            raise RuntimeError(f"GitHub init commit failed status={commit_res.status_code} body={(commit_res.text or '')[:240]}")
        commit_sha = str(commit_res.json().get("sha", "")).strip()
        if not commit_sha:
            raise RuntimeError("GitHub init commit failed: missing sha")

        ref_res = requests.post(
            f"{base_url}/git/refs",
            headers=headers,
            json={"ref": f"refs/heads/{self.github_branch}", "sha": commit_sha},
            timeout=self.github_timeout,
        )
        if ref_res.status_code not in {200, 201, 422}:
            raise RuntimeError(f"GitHub init ref failed status={ref_res.status_code} body={(ref_res.text or '')[:240]}")

    def _ensure_github_branch_ready(self, headers: dict[str, str]) -> None:
        base_url = f"https://api.github.com/repos/{self.github_user}/{self.github_repo}"

        branch_res = requests.get(
            f"{base_url}/branches/{self.github_branch}",
            headers=headers,
            timeout=self.github_timeout,
        )
        if branch_res.status_code == 200:
            return
        if branch_res.status_code != 404:
            raise RuntimeError(f"GitHub branch check failed status={branch_res.status_code} body={(branch_res.text or '')[:240]}")

        contents_res = requests.get(
            f"{base_url}/contents",
            headers=headers,
            timeout=self.github_timeout,
        )
        contents_body = str(contents_res.text or "")
        if contents_res.status_code == 404 and "repository is empty" in contents_body.lower():
            logging.warning("GitHub 仓库为空，自动初始化分支 %s", self.github_branch)
            self._initialize_empty_github_repo_branch(headers)
            return

        raise RuntimeError(
            f"GitHub branch not ready: branch={self.github_branch} status={branch_res.status_code} body={(branch_res.text or '')[:240]}"
        )

    def _upload_image_bytes_to_github(self, image_bytes: bytes) -> str:
        date_str = time.strftime("%Y/%m/%d")
        unique_name = f"{time.strftime('%H%M%S')}_{uuid.uuid4().hex[:4]}.png"
        file_path = f"{date_str}/{unique_name}"
        content_b64 = base64.b64encode(image_bytes).decode("utf-8")

        api_url = f"https://api.github.com/repos/{self.github_user}/{self.github_repo}/contents/{file_path}"
        headers = {
            "Authorization": f"token {self.github_token}",
            "Accept": "application/vnd.github+json",
        }
        self._ensure_github_branch_ready(headers)
        payload = {
            "message": f"Auto-upload figure {unique_name} via MedPaper-Flow",
            "content": content_b64,
            "branch": self.github_branch,
        }
        res = requests.put(api_url, headers=headers, json=payload, timeout=self.github_timeout)
        if res.status_code not in {200, 201}:
            body = ""
            try:
                body = str((res.text or "")[:240])
            except Exception:
                body = ""
            if res.status_code == 404:
                raise RuntimeError(
                    "GitHub upload failed status=404. "
                    "请检查 GITHUB_TOKEN 是否具备仓库 Contents 写权限，"
                    "并确认仓库非空或允许初始化首个提交。 "
                    f"body={body}"
                )
            raise RuntimeError(f"GitHub upload failed status={res.status_code} body={body}")
        return f"https://cdn.jsdelivr.net/gh/{self.github_user}/{self.github_repo}@{self.github_branch}/{file_path}"

    @staticmethod
    def _normalize_figure_text(text: Any, limit: int = 4000) -> str:
        cleaned = re.sub(r"\s+", " ", str(text or "")).strip()
        if not cleaned:
            return ""
        return cleaned[:limit].strip()

    @classmethod
    def _looks_like_figure_caption(cls, text: str) -> bool:
        cleaned = cls._normalize_figure_text(text, limit=400)
        if not cleaned:
            return False
        return bool(
            re.match(
                r"^(figure|fig\.?|extended data fig\.?|supplementary fig\.?|图)\s*[a-z0-9.-]*\s*[:：.\-–—]?",
                cleaned,
                flags=re.IGNORECASE,
            )
        )

    @classmethod
    def _looks_like_noisy_nearby_text(cls, text: str) -> bool:
        cleaned = cls._normalize_figure_text(text, limit=500)
        if not cleaned:
            return True

        lowered = cleaned.lower()
        if re.match(r"^\d+\s+[a-z]\.?", lowered):
            return True
        if re.match(r"^\d+\s+[a-z].+et al\.", lowered):
            return True
        if re.match(r"^(page|p\.)\s*\d+", lowered):
            return True
        if "et al." in lowered and len(cleaned) < 120:
            return True

        numeric_tokens = re.findall(r"[-+]?\d+(?:\.\d+)?", cleaned)
        word_tokens = re.findall(r"[A-Za-z\u4e00-\u9fff]{2,}", cleaned)
        upper_tokens = re.findall(r"\b[A-Z]{2,}[A-Z0-9-]*\b", cleaned)
        if len(numeric_tokens) >= 6 and len(word_tokens) <= 10:
            return True
        if len(upper_tokens) >= 5 and len(word_tokens) <= 12:
            return True
        if cleaned.count("��") >= 2:
            return True
        return False

    @staticmethod
    def _rect_to_bbox(rect: Any) -> tuple[float, float, float, float]:
        return (
            float(getattr(rect, "x0", 0.0) or 0.0),
            float(getattr(rect, "y0", 0.0) or 0.0),
            float(getattr(rect, "x1", 0.0) or 0.0),
            float(getattr(rect, "y1", 0.0) or 0.0),
        )

    @staticmethod
    def _bbox_width(bbox: tuple[float, float, float, float]) -> float:
        return max(1.0, float(bbox[2]) - float(bbox[0]))

    @staticmethod
    def _bbox_height(bbox: tuple[float, float, float, float]) -> float:
        return max(1.0, float(bbox[3]) - float(bbox[1]))

    @classmethod
    def _bbox_area(cls, bbox: tuple[float, float, float, float]) -> float:
        return cls._bbox_width(bbox) * cls._bbox_height(bbox)

    @staticmethod
    def _merge_bboxes(
        left: tuple[float, float, float, float],
        right: tuple[float, float, float, float],
    ) -> tuple[float, float, float, float]:
        return (
            min(left[0], right[0]),
            min(left[1], right[1]),
            max(left[2], right[2]),
            max(left[3], right[3]),
        )

    @classmethod
    def _bboxes_related(
        cls,
        left: tuple[float, float, float, float],
        right: tuple[float, float, float, float],
    ) -> bool:
        left_width = cls._bbox_width(left)
        right_width = cls._bbox_width(right)
        left_height = cls._bbox_height(left)
        right_height = cls._bbox_height(right)

        overlap_x = max(0.0, min(left[2], right[2]) - max(left[0], right[0]))
        overlap_y = max(0.0, min(left[3], right[3]) - max(left[1], right[1]))
        horiz_gap = max(0.0, max(left[0], right[0]) - min(left[2], right[2]))
        vert_gap = max(0.0, max(left[1], right[1]) - min(left[3], right[3]))

        width_ref = max(1.0, min(left_width, right_width))
        height_ref = max(1.0, min(left_height, right_height))
        overlap_x_ratio = overlap_x / width_ref
        overlap_y_ratio = overlap_y / height_ref

        same_row = overlap_y_ratio >= 0.35 and horiz_gap <= max(18.0, 0.08 * max(left_width, right_width))
        same_col = overlap_x_ratio >= 0.35 and vert_gap <= max(18.0, 0.08 * max(left_height, right_height))
        tightly_touching = horiz_gap <= 6.0 and vert_gap <= 6.0
        overlapping = overlap_x > 0 and overlap_y > 0

        return overlapping or same_row or same_col or tightly_touching

    @staticmethod
    def _expand_bbox(
        bbox: tuple[float, float, float, float],
        page_rect: Any,
        pad_x: float = 8.0,
        pad_y: float = 8.0,
    ) -> tuple[float, float, float, float]:
        page_x0 = float(getattr(page_rect, "x0", 0.0) or 0.0)
        page_y0 = float(getattr(page_rect, "y0", 0.0) or 0.0)
        page_x1 = float(getattr(page_rect, "x1", 0.0) or 0.0)
        page_y1 = float(getattr(page_rect, "y1", 0.0) or 0.0)
        return (
            max(page_x0, bbox[0] - pad_x),
            max(page_y0, bbox[1] - pad_y),
            min(page_x1, bbox[2] + pad_x),
            min(page_y1, bbox[3] + pad_y),
        )

    def _collect_page_text_blocks(self, page: Any) -> list[dict[str, Any]]:
        try:
            raw_blocks = page.get_text("blocks") or []
        except Exception:
            return []

        text_blocks: list[dict[str, Any]] = []
        for block in raw_blocks:
            if len(block) < 5:
                continue
            block_type = int(block[6]) if len(block) > 6 else 0
            if block_type != 0:
                continue
            x0, y0, x1, y1, raw_text = block[:5]
            text = self._normalize_figure_text(raw_text)
            if not text:
                continue
            text_blocks.append(
                {
                    "bbox": (float(x0), float(y0), float(x1), float(y1)),
                    "text": text,
                    "caption_like": self._looks_like_figure_caption(text),
                }
            )
        return text_blocks

    @staticmethod
    def _bbox_key(bbox: tuple[float, float, float, float], step: float = 3.0) -> tuple[int, int, int, int]:
        return (
            int(round(bbox[0] / step)),
            int(round(bbox[1] / step)),
            int(round(bbox[2] / step)),
            int(round(bbox[3] / step)),
        )

    @classmethod
    def _bbox_iou(
        cls,
        left: tuple[float, float, float, float],
        right: tuple[float, float, float, float],
    ) -> float:
        inter_w = max(0.0, min(left[2], right[2]) - max(left[0], right[0]))
        inter_h = max(0.0, min(left[3], right[3]) - max(left[1], right[1]))
        inter_area = inter_w * inter_h
        if inter_area <= 0:
            return 0.0
        union = cls._bbox_area(left) + cls._bbox_area(right) - inter_area
        return inter_area / max(1.0, union)

    def _collect_visual_components(self, doc: Any, page: Any, page_num: int) -> list[dict[str, Any]]:
        components: list[dict[str, Any]] = []
        page_area = max(1.0, float(getattr(page.rect, "width", 1.0) or 1.0) * float(getattr(page.rect, "height", 1.0) or 1.0))

        try:
            for img_info in doc.get_page_images(page_num):
                xref = int(img_info[0])
                for rect in page.get_image_rects(xref) or []:
                    bbox = self._rect_to_bbox(rect)
                    width = self._bbox_width(bbox)
                    height = self._bbox_height(bbox)
                    area = self._bbox_area(bbox)
                    if width < 40 or height < 40:
                        continue
                    if area > page_area * 0.95:
                        continue
                    components.append({"bbox": bbox, "source": "image", "xref": xref})
        except Exception as exc:
            logging.warning("图像组件收集异常 page=%s err=%s", page_num + 1, exc)

        try:
            drawings = page.get_drawings() or []
        except Exception:
            drawings = []

        for drawing in drawings:
            try:
                rect = drawing.get("rect")
                if rect is None:
                    continue
                bbox = self._rect_to_bbox(rect)
                width = self._bbox_width(bbox)
                height = self._bbox_height(bbox)
                area = self._bbox_area(bbox)
                if width < 12 or height < 12:
                    continue
                if area < 180:
                    continue
                if area > page_area * 0.95:
                    continue
                components.append({"bbox": bbox, "source": "drawing", "xref": int(drawing.get("seqno", 0) or 0)})
            except Exception:
                continue

        deduped: list[dict[str, Any]] = []
        seen: dict[tuple[int, int, int, int], dict[str, Any]] = {}
        for component in components:
            key = self._bbox_key(component["bbox"])
            existing = seen.get(key)
            if existing is None:
                seen[key] = component
                deduped.append(component)
                continue
            if existing.get("source") == "drawing" and component.get("source") == "image":
                seen[key] = component
                idx = deduped.index(existing)
                deduped[idx] = component
        return deduped

    def _build_caption_anchored_regions(
        self,
        text_blocks: list[dict[str, Any]],
        visual_components: list[dict[str, Any]],
        page_rect: Any,
    ) -> list[dict[str, Any]]:
        anchors = [block for block in text_blocks if block.get("caption_like")]
        if not anchors or not visual_components:
            return []

        regions: list[dict[str, Any]] = []
        for anchor in anchors:
            anchor_bbox = anchor["bbox"]
            anchor_width = self._bbox_width(anchor_bbox)
            above_candidates: list[dict[str, Any]] = []
            below_candidates: list[dict[str, Any]] = []

            for component in visual_components:
                bbox = component["bbox"]
                overlap = max(0.0, min(anchor_bbox[2], bbox[2]) - max(anchor_bbox[0], bbox[0]))
                overlap_ratio = overlap / max(1.0, min(anchor_width, self._bbox_width(bbox)))
                if overlap_ratio < 0.12:
                    continue
                above_gap = anchor_bbox[1] - bbox[3]
                below_gap = bbox[1] - anchor_bbox[3]
                if -12 <= above_gap <= 260:
                    above_candidates.append({**component, "gap": above_gap, "overlap_ratio": overlap_ratio})
                if -12 <= below_gap <= 220:
                    below_candidates.append({**component, "gap": below_gap, "overlap_ratio": overlap_ratio})

            chosen = above_candidates if above_candidates else below_candidates
            if not chosen:
                continue
            min_gap = min(max(0.0, float(item["gap"])) for item in chosen)
            chosen = [item for item in chosen if float(item["gap"]) <= min_gap + 90.0]
            chosen.sort(key=lambda item: (float(item["gap"]), -float(item["overlap_ratio"]), item["bbox"][1], item["bbox"][0]))

            region_bbox = chosen[0]["bbox"]
            region_components = [chosen[0]]
            for item in chosen[1:]:
                if self._bboxes_related(region_bbox, item["bbox"]):
                    region_bbox = self._merge_bboxes(region_bbox, item["bbox"])
                    region_components.append(item)

            expanded = True
            while expanded:
                expanded = False
                for component in visual_components:
                    if any(self._bbox_iou(component["bbox"], existing["bbox"]) >= 0.95 for existing in region_components):
                        continue
                    if self._bboxes_related(region_bbox, component["bbox"]):
                        region_bbox = self._merge_bboxes(region_bbox, component["bbox"])
                        region_components.append(component)
                        expanded = True

            region_bbox = self._expand_bbox(region_bbox, page_rect, pad_x=10.0, pad_y=10.0)
            caption, nearby_text = self._extract_caption_and_nearby_text_from_blocks(text_blocks, region_bbox)
            if not caption:
                caption = self._normalize_figure_text(anchor.get("text", ""), limit=4000)
            regions.append(
                {
                    "bbox": region_bbox,
                    "component_count": len(region_components),
                    "caption": caption,
                    "context": nearby_text,
                    "anchor_text": self._normalize_figure_text(anchor.get("text", ""), limit=4000),
                }
            )
        return regions

    @classmethod
    def _group_figure_components(cls, components: list[dict[str, Any]], page_rect: Any) -> list[dict[str, Any]]:
        if not components:
            return []

        groups: list[dict[str, Any]] = []
        sorted_components = sorted(components, key=lambda item: (item["bbox"][1], item["bbox"][0]))
        for component in sorted_components:
            placed = False
            for group in groups:
                if cls._bboxes_related(group["bbox"], component["bbox"]):
                    group["bbox"] = cls._merge_bboxes(group["bbox"], component["bbox"])
                    group["components"].append(component)
                    placed = True
                    break
            if not placed:
                groups.append({"bbox": component["bbox"], "components": [component]})

        merged = True
        while merged and len(groups) > 1:
            merged = False
            next_groups: list[dict[str, Any]] = []
            while groups:
                current = groups.pop(0)
                index = 0
                while index < len(groups):
                    if cls._bboxes_related(current["bbox"], groups[index]["bbox"]):
                        current = {
                            "bbox": cls._merge_bboxes(current["bbox"], groups[index]["bbox"]),
                            "components": current["components"] + groups[index]["components"],
                        }
                        groups.pop(index)
                        merged = True
                        continue
                    index += 1
                next_groups.append(current)
            groups = next_groups

        page_area = max(1.0, float(getattr(page_rect, "width", 1.0) or 1.0) * float(getattr(page_rect, "height", 1.0) or 1.0))
        filtered: list[dict[str, Any]] = []
        for group in groups:
            bbox = group["bbox"]
            width = cls._bbox_width(bbox)
            height = cls._bbox_height(bbox)
            area = cls._bbox_area(bbox)
            if width < 80 or height < 80:
                continue
            if area < page_area * 0.01:
                continue
            filtered.append(group)
        return filtered

    @classmethod
    def _render_figure_crop(
        cls,
        page: Any,
        fitz: Any,
        bbox: tuple[float, float, float, float],
    ) -> tuple[bytes, int, int]:
        clip = fitz.Rect(*bbox)
        longest = max(1.0, float(getattr(clip, "width", 1.0) or 1.0), float(getattr(clip, "height", 1.0) or 1.0))
        scale = min(3.0, max(1.4, 1800.0 / longest))
        pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), clip=clip, alpha=False)
        return pix.tobytes("png"), int(pix.width), int(pix.height)

    def _extract_caption_and_nearby_text_from_blocks(
        self,
        text_blocks: list[dict[str, Any]],
        figure_bbox: tuple[float, float, float, float],
    ) -> tuple[str, str]:
        figure_width = self._bbox_width(figure_bbox)
        figure_y0 = float(figure_bbox[1])
        figure_y1 = float(figure_bbox[3])

        enriched: list[dict[str, Any]] = []
        for block in text_blocks:
            block_bbox = block["bbox"]
            block_width = self._bbox_width(block_bbox)
            overlap = max(0.0, min(figure_bbox[2], block_bbox[2]) - max(figure_bbox[0], block_bbox[0]))
            overlap_ratio = overlap / max(1.0, min(figure_width, block_width))
            below_gap = float(block_bbox[1]) - figure_y1
            above_gap = figure_y0 - float(block_bbox[3])
            enriched.append(
                {
                    **block,
                    "overlap_ratio": overlap_ratio,
                    "below_gap": below_gap,
                    "above_gap": above_gap,
                }
            )

        caption_candidates = [
            block
            for block in enriched
            if block["caption_like"]
            and block["overlap_ratio"] >= 0.18
            and ((-8 <= block["below_gap"] <= 220) or (-8 <= block["above_gap"] <= 140))
        ]
        caption_candidates.sort(
            key=lambda block: (
                0 if -8 <= block["below_gap"] <= 220 else 1,
                abs(block["below_gap"]) if -8 <= block["below_gap"] <= 220 else abs(block["above_gap"]),
                -block["overlap_ratio"],
            )
        )

        caption = ""
        merged_blocks: list[dict[str, Any]] = []
        anchor_side = ""
        if caption_candidates:
            anchor = caption_candidates[0]
            anchor_bbox = anchor["bbox"]
            anchor_side = "below" if -8 <= anchor["below_gap"] <= 220 else "above"
            merged_blocks = [anchor]
            if anchor_side == "below":
                current_y = float(anchor_bbox[3])
                for block in sorted(caption_candidates[1:], key=lambda item: item["bbox"][1]):
                    if len(merged_blocks) >= 4:
                        break
                    block_bbox = block["bbox"]
                    if block["overlap_ratio"] < 0.18:
                        continue
                    if -4 <= float(block_bbox[1]) - current_y <= 30:
                        merged_blocks.append(block)
                        current_y = float(block_bbox[3])
            else:
                current_y = float(anchor_bbox[1])
                prepend: list[dict[str, Any]] = []
                for block in sorted(caption_candidates[1:], key=lambda item: item["bbox"][1], reverse=True):
                    if len(prepend) >= 3:
                        break
                    block_bbox = block["bbox"]
                    if block["overlap_ratio"] < 0.18:
                        continue
                    if -4 <= current_y - float(block_bbox[3]) <= 30:
                        prepend.append(block)
                        current_y = float(block_bbox[1])
                merged_blocks = list(reversed(prepend)) + merged_blocks
            caption = self._normalize_figure_text(" ".join(block["text"] for block in merged_blocks), limit=4000)

        merged_keys = {self._bbox_key(block["bbox"], step=1.0) for block in merged_blocks}
        nearby_candidates: list[dict[str, Any]] = []
        for block in enriched:
            if self._bbox_key(block["bbox"], step=1.0) in merged_keys:
                continue
            if block["overlap_ratio"] < 0.18:
                continue
            if self._looks_like_noisy_nearby_text(block["text"]):
                continue

            keep = False
            priority = 2
            if anchor_side == "below" and -10 <= block["below_gap"] <= 70:
                keep = True
                priority = 0
            elif anchor_side == "above" and -10 <= block["above_gap"] <= 70:
                keep = True
                priority = 0
            elif anchor_side == "" and ((-20 <= block["below_gap"] <= 120) or (-20 <= block["above_gap"] <= 120)):
                keep = True
                priority = 1
            elif block["caption_like"] and ((-20 <= block["below_gap"] <= 180) or (-20 <= block["above_gap"] <= 140)):
                keep = True
                priority = 1

            if keep:
                nearby_candidates.append({**block, "priority": priority})

        nearby_candidates.sort(
            key=lambda block: (
                int(block.get("priority", 2)),
                min(abs(block["below_gap"]), abs(block["above_gap"])),
                -block["overlap_ratio"],
                block["bbox"][1],
            )
        )

        nearby_parts: list[str] = []
        if caption:
            nearby_parts.append(caption)
        for block in nearby_candidates[:3]:
            text = self._normalize_figure_text(block["text"], limit=500)
            if not text:
                continue
            if text in nearby_parts:
                continue
            nearby_parts.append(text)

        nearby_text = self._normalize_figure_text(" ".join(nearby_parts), limit=3000)
        return caption, nearby_text

    def _extract_caption_and_nearby_text(self, page: Any, image_rect: Any) -> tuple[str, str]:
        text_blocks = self._collect_page_text_blocks(page)
        return self._extract_caption_and_nearby_text_from_blocks(text_blocks, self._rect_to_bbox(image_rect))

    @staticmethod
    def _score_figure_candidate(candidate: dict[str, Any]) -> tuple[float, int, int]:
        width = max(1, int(candidate.get("width", 1) or 1))
        height = max(1, int(candidate.get("height", 1) or 1))
        area = width * height
        page = max(1, int(candidate.get("page", 1) or 1))
        component_count = max(1, int(candidate.get("component_count", 1) or 1))
        caption = re.sub(r"\s+", " ", str(candidate.get("caption", "") or "")).strip().lower()
        context = re.sub(r"\s+", " ", str(candidate.get("context", "") or "")).strip().lower()
        text_signal = caption or context

        score = float(area)
        if page <= 2:
            score *= 1.25
        elif page <= 4:
            score *= 1.12

        strong_keywords = (
            "overview",
            "framework",
            "pipeline",
            "workflow",
            "architecture",
            "method",
            "system",
            "schematic",
            "setup",
            "diagram",
            "overview of",
            "示意",
            "框架",
            "流程",
            "系统",
            "结构图",
            "装置",
        )
        result_keywords = (
            "result",
            "comparison",
            "benchmark",
            "ablation",
            "accuracy",
            "psnr",
            "auc",
            "实验结果",
            "对比",
            "性能",
            "结果",
            "消融",
        )
        weak_keywords = ("logo", "author", "affiliation", "table of contents")

        if caption:
            score *= 1.18
        if component_count >= 2:
            score *= min(1.22, 1.0 + 0.06 * (component_count - 1))
        if any(keyword in text_signal for keyword in strong_keywords):
            score *= 1.35
        if any(keyword in text_signal for keyword in result_keywords):
            score *= 1.18
        if any(keyword in text_signal for keyword in weak_keywords):
            score *= 0.7
        if not caption and not context:
            score *= 0.72
        if width < 240 or height < 180:
            score *= 0.6

        return score, -page, area

    def _rank_figure_candidates(self, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return sorted(candidates, key=self._score_figure_candidate, reverse=True)

    def _pick_diverse_figure_candidates(self, candidates: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
        ranked = self._rank_figure_candidates(candidates)
        if limit <= 0:
            return []

        picked: list[dict[str, Any]] = []
        used_pages: set[int] = set()
        for candidate in ranked:
            page_num = int(candidate.get("page", 0) or 0)
            if page_num in used_pages and len(ranked) > limit:
                continue
            picked.append(candidate)
            used_pages.add(page_num)
            if len(picked) >= limit:
                return picked

        for candidate in ranked:
            candidate_id = int(candidate.get("id", 0) or 0)
            if any(int(item.get("id", 0) or 0) == candidate_id for item in picked):
                continue
            picked.append(candidate)
            if len(picked) >= limit:
                break
        return picked[:limit]

    def _select_figure_ids_with_llm(
        self,
        paper: dict[str, Any],
        candidates: list[dict[str, Any]],
        max_images: int,
    ) -> list[int]:
        def _heuristic_pick() -> list[int]:
            picked = self._pick_diverse_figure_candidates(candidates, max_images)
            return [int(item["id"]) for item in picked[:max_images]]

        if not candidates:
            return []
        if len(candidates) <= max_images:
            return [int(c["id"]) for c in candidates[:max_images]]
        if not self.use_llm_for_figure_selection:
            return _heuristic_pick()

        llm_candidates = self._pick_diverse_figure_candidates(
            candidates,
            min(len(candidates), max(max_images + 2, self.figure_llm_candidate_cap)),
        )
        compact = []
        for c in llm_candidates:
            compact.append(
                {
                    "id": int(c["id"]),
                    "page": int(c["page"]),
                    "component_count": int(c.get("component_count", 1) or 1),
                    "width": int(c["width"]),
                    "height": int(c["height"]),
                    "area": int(c["width"]) * int(c["height"]),
                    "caption": self._normalize_figure_text(c.get("caption", ""), limit=2500),
                    "nearby_text": self._normalize_figure_text(c.get("context", ""), limit=2200),
                }
            )

        text_signal_candidates = sum(1 for item in compact if item.get("caption") or item.get("nearby_text"))
        if text_signal_candidates < max(1, min(max_images, 2)):
            logging.info(
                "候选图文本线索不足，跳过 LLM 选图并回退启发式: prompt_candidates=%s signal_candidates=%s total_candidates=%s",
                len(compact),
                text_signal_candidates,
                len(candidates),
            )
            return _heuristic_pick()

        prompt = FIGURE_SELECTION_PROMPT.format(
            max_images=max_images,
            title=str(paper.get("title", ""))[:500],
            abstract=str(paper.get("abstract", ""))[:2200],
            candidates_json=json.dumps(compact, ensure_ascii=False),
        )

        valid = {int(c["id"]) for c in candidates}
        deadline = time.monotonic() + self.figure_selection_total_budget
        last_error: Exception | None = None
        for attempt in range(1, self.figure_selection_attempts + 1):
            remaining_budget = max(0.0, deadline - time.monotonic())
            if remaining_budget < 8:
                break
            timeout = max(8, min(self.figure_selection_timeout, int(remaining_budget)))
            try:
                response = self.client.chat.completions.create(
                    model=self.deep_model,
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=800,
                    temperature=0.1,
                    top_p=0.9,
                    presence_penalty=0.0,
                    timeout=timeout,
                    response_format={"type": "json_object"},
                )
                raw = response.choices[0].message.content or "{}"
                obj = self._safe_json(raw)
                selected = obj.get("selected_ids", [])
                if isinstance(selected, str):
                    selected = re.findall(r"\d+", selected)
                ids = [int(x) for x in selected if isinstance(x, (int, float, str)) and str(x).isdigit()]
                ids = list(dict.fromkeys(ids))
                ids = [i for i in ids if i in valid]
                if ids:
                    logging.info(
                        "LLM 选图成功 model=%s attempt=%s timeout=%ss budget=%ss prompt_candidates=%s total_candidates=%s",
                        getattr(response, "model", self.deep_model),
                        attempt,
                        timeout,
                        self.figure_selection_total_budget,
                        len(llm_candidates),
                        len(candidates),
                    )
                    return ids[:max_images]
                raise ValueError("LLM 选图返回空结果或无效 id")
            except Exception as exc:
                last_error = exc
                remaining_budget = max(0.0, deadline - time.monotonic())
                if attempt >= self.figure_selection_attempts or remaining_budget < 10:
                    break
                sleep_seconds = min(4, attempt)
                logging.warning(
                    "LLM 选图第%s次失败，将重试: timeout=%ss remain=%.1fs prompt_candidates=%s err=%s",
                    attempt,
                    timeout,
                    remaining_budget,
                    len(llm_candidates),
                    exc,
                )
                if remaining_budget - sleep_seconds < 8:
                    break
                time.sleep(sleep_seconds)

        if last_error is not None:
            logging.warning(
                "LLM 选图失败（更常见是 502/超时/排队，不是 token 不够），回退启发式: budget=%ss attempts=%s prompt_candidates=%s total_candidates=%s err=%s",
                self.figure_selection_total_budget,
                self.figure_selection_attempts,
                len(llm_candidates),
                len(candidates),
                last_error,
            )

        return _heuristic_pick()

    def _build_figure_caption(self, candidate: dict[str, Any], order: int) -> str:
        caption = self._normalize_figure_text(candidate.get("caption", ""), limit=4000)
        if caption:
            return caption

        page_num = int(candidate.get("page", 0) or 0)
        context = re.sub(r"\s+", " ", str(candidate.get("context", "") or "")).strip()
        matches = re.findall(
            r"(?:Figure|Fig\.?|FIG\.?|图)\s*\d+[\s:\-–—]*[^\n]{8,220}",
            context,
            flags=re.IGNORECASE,
        )

        body = ""
        if matches:
            index = min(max(order - 1, 0), len(matches) - 1)
            body = re.sub(r"\s+", " ", matches[index]).strip(" .;，；")
        elif context:
            sentences = re.split(r"(?<=[。！？.!?])\s+", context)
            for sentence in sentences:
                cleaned = sentence.strip(" .;，；")
                if len(cleaned) >= 12:
                    body = cleaned[:180]
                    break

        if not body:
            body = "论文关键图表，建议结合原文图题与正文说明一起查看。"

        return f"图{order}（第{page_num}页）：{body}"

    def _extract_and_upload_figures_github(
        self,
        pdf_bytes: bytes,
        paper: dict[str, Any],
        max_images: int = 3,
    ) -> list[dict[str, Any]]:
        if not self.enable_figure_hosting:
            return []
        missing: list[str] = []
        if not self.github_token:
            missing.append("GITHUB_TOKEN")
        if not self.github_user:
            missing.append("GITHUB_USER")
        if not self.github_repo:
            missing.append("GITHUB_REPO")
        if missing:
            logging.warning(
                "FIGURE_HOSTING_ENABLED=true 但 GitHub 配置不完整，缺失=%s，跳过图表上传",
                ",".join(missing),
            )
            return []

        try:
            fitz = importlib.import_module("fitz")
        except Exception:
            logging.warning("未安装 PyMuPDF(fitz)，跳过图表提取")
            return []

        hosted_images: list[dict[str, Any]] = []
        try:
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        except Exception as exc:
            logging.warning("PDF 图像提取失败（打开文档失败）: %s", exc)
            return []

        candidates: list[dict[str, Any]] = []
        for page_num in range(min(self.figure_scan_pages, len(doc))):
            try:
                page = doc.load_page(page_num)
                text_blocks = self._collect_page_text_blocks(page)
                visual_components = self._collect_visual_components(doc, page, page_num)
            except Exception:
                continue

            regions: list[dict[str, Any]] = []
            groups = self._group_figure_components(visual_components, page.rect)
            for group in groups:
                regions.append(
                    {
                        "bbox": self._expand_bbox(group["bbox"], page.rect, pad_x=10.0, pad_y=10.0),
                        "component_count": len(group["components"]),
                    }
                )

            for anchored in self._build_caption_anchored_regions(text_blocks, visual_components, page.rect):
                matched_region = None
                for region in regions:
                    if self._bbox_iou(region["bbox"], anchored["bbox"]) >= 0.55:
                        matched_region = region
                        break
                if matched_region is not None:
                    if not str(matched_region.get("caption", "") or "").strip() and str(anchored.get("caption", "") or "").strip():
                        matched_region["caption"] = anchored["caption"]
                    if not str(matched_region.get("context", "") or "").strip() and str(anchored.get("context", "") or "").strip():
                        matched_region["context"] = anchored["context"]
                    matched_region["component_count"] = max(
                        int(matched_region.get("component_count", 1) or 1),
                        int(anchored.get("component_count", 1) or 1),
                    )
                    continue
                regions.append({"bbox": anchored["bbox"], "component_count": anchored["component_count"], "caption": anchored["caption"], "context": anchored["context"]})

            for region in regions:
                try:
                    figure_bbox = region["bbox"]
                    image_bytes, width, height = self._render_figure_crop(page, fitz, figure_bbox)
                    if not image_bytes:
                        continue
                    if width <= 320 or height <= 220:
                        continue
                    caption = self._normalize_figure_text(region.get("caption", ""), limit=4000)
                    nearby_text = self._normalize_figure_text(region.get("context", ""), limit=3000)
                    if not caption and not nearby_text:
                        caption, nearby_text = self._extract_caption_and_nearby_text_from_blocks(text_blocks, figure_bbox)
                    candidates.append(
                        {
                            "id": len(candidates),
                            "page": page_num + 1,
                            "width": width,
                            "height": height,
                            "component_count": int(region.get("component_count", 1) or 1),
                            "image_bytes": image_bytes,
                            "caption": caption,
                            "context": nearby_text,
                        }
                    )
                except Exception as exc:
                    logging.warning("Figure 区域候选提取异常: %s", exc)
                    continue

                if len(candidates) >= self.figure_candidate_limit:
                    break
            if len(candidates) >= self.figure_candidate_limit:
                break

        if not candidates:
            return []

        selected_ids = self._select_figure_ids_with_llm(paper, candidates, max_images)
        selected_map = {int(c["id"]): c for c in candidates}
        for sid in selected_ids:
            c = selected_map.get(int(sid))
            if not c:
                continue
            try:
                cdn_url = self._upload_image_bytes_to_github(c["image_bytes"])
                hosted_images.append(
                    {
                        "url": cdn_url,
                        "caption": self._build_figure_caption(c, len(hosted_images) + 1),
                        "page": int(c.get("page", 0) or 0),
                        "width": int(c.get("width", 0) or 0),
                        "height": int(c.get("height", 0) or 0),
                    }
                )
                if len(hosted_images) >= max_images:
                    break
            except Exception as exc:
                logging.warning("GitHub 图像上传失败: %s", exc)

        return hosted_images

    def _extract_and_host_figures_for_paper(self, paper: dict[str, Any], resolved_pdf_url: str = "") -> list[dict[str, Any]]:
        if not self.enable_figure_hosting:
            return []

        if not self._has_pdf_for_figure_selection(paper, resolved_pdf_url):
            logging.info("无 PDF，跳过 LLM 选图: title=%s", str(paper.get("title", ""))[:120])
            return []

        local_pdf_bytes, local_pdf_path = self._read_local_pdf_bytes(paper)
        if local_pdf_bytes.startswith(b"%PDF"):
            try:
                items = self._extract_and_upload_figures_github(
                    local_pdf_bytes,
                    paper=paper,
                    max_images=self.figure_max_images,
                )
                if items:
                    logging.info(
                        "图表提取成功: title=%s source=local_pdf path=%s count=%s",
                        str(paper.get("title", ""))[:120],
                        local_pdf_path,
                        len(items),
                    )
                    return items
            except Exception as exc:
                logging.debug("本地 PDF 图表提取失败 path=%s err=%s", local_pdf_path, exc)
            if self.local_pdf_only:
                logging.warning("本地 PDF 图表提取失败且 LOCAL_PDF_ONLY=true: title=%s", str(paper.get("title", ""))[:120])
                return []

        candidates: list[str] = []
        for candidate in [resolved_pdf_url, *self._candidate_pdf_urls(paper)]:
            if candidate and candidate not in candidates:
                candidates.append(candidate)

        if not candidates:
            logging.info("未找到可用 PDF 链接，跳过 LLM 选图: title=%s", str(paper.get("title", ""))[:120])
            return []

        if self.local_pdf_only:
            logging.info("LOCAL_PDF_ONLY=true 且未命中可用本地 PDF，跳过外部 PDF 拉取: title=%s", str(paper.get("title", ""))[:120])
            return []

        for candidate in candidates:
            try:
                pdf_bytes = self._fetch_pdf_bytes_from_url(candidate)
                if not pdf_bytes.startswith(b"%PDF"):
                    html = ""
                    try:
                        html = pdf_bytes.decode("utf-8", errors="ignore")
                    except Exception:
                        html = ""
                    if html:
                        resolved_pdf_url = self._extract_pdf_url_from_html(html, candidate)
                        if resolved_pdf_url:
                            pdf_bytes = self._fetch_pdf_bytes_from_url(resolved_pdf_url)
                if pdf_bytes.startswith(b"%PDF"):
                    items = self._extract_and_upload_figures_github(
                        pdf_bytes,
                        paper=paper,
                        max_images=self.figure_max_images,
                    )
                    if items:
                        logging.info(
                            "图表提取成功: title=%s count=%s",
                            str(paper.get("title", ""))[:120],
                            len(items),
                        )
                        return items
            except Exception as exc:
                logging.debug("图表提取下载失败 url=%s err=%s", candidate, exc)
                continue
        logging.warning("图表提取为空: title=%s", str(paper.get("title", ""))[:120])
        return []

    def _build_route_content(self, paper: dict[str, Any]) -> tuple[str, str, str]:
        def _from_existing() -> tuple[str, str, str] | None:
            for key in ("full_text_content", "fulltext", "content"):
                t = str(paper.get(key, "") or "").strip()
                if t:
                    clean = self._clean_text(t)
                    wc = len(clean.split())
                    if wc >= self.fulltext_word_min:
                        return self._clip_words(clean, self.fulltext_word_max), "fulltext", ""
            return None

        def _from_pdf() -> tuple[str, str, str] | None:
            if not self.enable_pdf_routing:
                return None
            pdf_text, pdf_url = self._fetch_pdf_text(paper)
            if pdf_text:
                clean = self._clean_text(pdf_text)
                wc = len(clean.split())
                if wc >= self.fulltext_word_min:
                    return self._clip_words(clean, self.fulltext_word_max), "fulltext", pdf_url
            return None

        if self.prefer_pdf_fulltext:
            routed = _from_pdf() or _from_existing()
        else:
            routed = _from_existing() or _from_pdf()
        if routed is not None:
            return routed

        abstract = self._clean_text(str(paper.get("abstract", "") or ""))
        return abstract, "abstract", ""

    def _chat_with_retry(
        self,
        model: str,
        messages: list[ChatCompletionUserMessageParam],
        max_tokens: int,
    ) -> str:
        last_exc: Exception | None = None
        total_attempts = 1 + self.max_retries

        for attempt in range(1, total_attempts + 1):
            try:
                try:
                    response = self.client.chat.completions.create(
                        model=model,
                        messages=messages,
                        max_tokens=max_tokens,
                        temperature=self.temperature,
                        top_p=self.top_p,
                        presence_penalty=self.presence_penalty,
                        timeout=self.request_timeout,
                        response_format={"type": "json_object"},
                    )
                except Exception:
                    response = self.client.chat.completions.create(
                        model=model,
                        messages=messages,
                        max_tokens=max_tokens,
                        temperature=self.temperature,
                        top_p=self.top_p,
                        presence_penalty=self.presence_penalty,
                        timeout=self.request_timeout,
                    )
                logging.info("LLM request ok model=%s", getattr(response, "model", model))
                return response.choices[0].message.content or "{}"
            except Exception as exc:
                last_exc = exc
                logging.warning("LLM 请求失败 attempt=%s/%s model=%s: %s", attempt, total_attempts, model, exc)
                if attempt < total_attempts:
                    time.sleep(min(2 * attempt, 5))

        if last_exc is not None:
            raise last_exc
        return "{}"

    async def _achat_with_retry(
        self,
        model: str,
        messages: list[ChatCompletionUserMessageParam],
        max_tokens: int,
    ) -> str:
        last_exc: Exception | None = None
        total_attempts = 1 + self.max_retries

        for attempt in range(1, total_attempts + 1):
            try:
                try:
                    response = await self.async_client.chat.completions.create(
                        model=model,
                        messages=messages,
                        max_tokens=max_tokens,
                        temperature=self.temperature,
                        top_p=self.top_p,
                        presence_penalty=self.presence_penalty,
                        timeout=self.request_timeout,
                        response_format={"type": "json_object"},
                    )
                except Exception:
                    response = await self.async_client.chat.completions.create(
                        model=model,
                        messages=messages,
                        max_tokens=max_tokens,
                        temperature=self.temperature,
                        top_p=self.top_p,
                        presence_penalty=self.presence_penalty,
                        timeout=self.request_timeout,
                    )
                logging.info("LLM async request ok model=%s", getattr(response, "model", model))
                return response.choices[0].message.content or "{}"
            except Exception as exc:
                last_exc = exc
                logging.warning("LLM 异步请求失败 attempt=%s/%s model=%s: %s", attempt, total_attempts, model, exc)
                if attempt < total_attempts:
                    await asyncio.sleep(min(2 * attempt, 5))

        if last_exc is not None:
            raise last_exc
        return "{}"

    @staticmethod
    def _normalize_fulltext_extracted(extracted: dict[str, Any]) -> dict[str, Any]:
        defaults = {
            "tldr": "未提及",
            "clinical_problem": "未提及",
            "innovation_core": "未提及",
            "performance_gain": "未提及",
            "modality_task": "未提及",
            "the_magic": "未提及",
            "experiment_assets": "未提及",
            "method_pipeline": "未提及",
            "experimental_protocol": "未提及",
            "quantitative_results": "未提及",
            "ablation_study": "文中未包含消融实验细节",
            "failure_boundary": "未提及",
            "reproducibility_checklist": "未提及",
            "evidence_map": "未提及",
            "steal_value": "未提及",
            "hype_check": "未提及",
            "figure_captions_zh": {},
            "idea_score": 5,
            "implementation_effort": 3,
        }
        merged = {**defaults, **(extracted or {})}
        for k, v in list(merged.items()):
            if isinstance(v, str) and v.strip().lower() in {"", "unknown", "none", "null", "n/a"}:
                merged[k] = "未提及"
        return merged

    @staticmethod
    def _normalize_fulltext_extracted_physics(extracted: dict[str, Any]) -> dict[str, Any]:
        defaults = {
            "tldr": "未提及",
            "innovation_core": "未提及",
            "performance_gain": "未提及",
            "physical_system": "未提及",
            "core_mechanism": "未提及",
            "experimental_setup": "未提及",
            "method_pipeline": "未提及",
            "experimental_protocol": "未提及",
            "key_results": "未提及",
            "error_and_decoherence": "未提及",
            "failure_boundary": "未提及",
            "reproducibility_checklist": "未提及",
            "evidence_map": "未提及",
            "future_impact": "未提及",
            "idea_takeaway": "未提及",
            "reviewer_critique": "未提及",
            "figure_captions_zh": {},
            "idea_score": 5,
            "implementation_effort": 3,
        }
        merged = {**defaults, **(extracted or {})}
        for k, v in list(merged.items()):
            if isinstance(v, str) and v.strip().lower() in {"", "unknown", "none", "null", "n/a"}:
                merged[k] = "未提及"
        return merged

    async def deep_analyze_fulltext(self, paper: dict[str, Any], full_text_content: str) -> dict[str, Any]:
        """
        全文精读审稿（异步）。
        输入 paper 与全文文本，返回带 analysis 字段与关键映射字段的 paper。
        """
        title = str(paper.get("title", "未命名论文"))
        content = str(full_text_content or "").strip()
        if not content:
            result = self._normalize_fulltext_extracted({})
            return {**paper, "analysis": result}

        # 控制 prompt 长度，避免上下文爆炸
        clipped = self._clip_input_for_context(content)

        async with self.fulltext_semaphore:
            logging.info("🧠 [全文精读] 正在解构: %s", title[:60])
            try:
                messages: list[ChatCompletionUserMessageParam] = [
                    {
                        "role": "user",
                        "content": (
                            PHYSICS_FULLTEXT_REVIEW_PROMPT if self.is_physics_domain else FULLTEXT_REVIEW_PROMPT
                        ).format(
                            title=title,
                            full_text_content=clipped,
                        ),
                    }
                ]
                raw = await self._achat_with_retry(
                    model=self.fulltext_model,
                    messages=messages,
                    max_tokens=self.fulltext_max_tokens,
                )
                if self.is_physics_domain:
                    analysis = self._normalize_fulltext_extracted_physics(self._safe_json(raw))
                else:
                    analysis = self._normalize_fulltext_extracted(self._safe_json(raw))

                # 映射到现有报告字段，保证下游模板可直接消费
                if self.is_physics_domain:
                    mapped = {
                        "tldr": analysis.get("tldr", "未提及"),
                        "physical_system": analysis.get("physical_system", "未提及"),
                        "core_mechanism": analysis.get("core_mechanism", "未提及"),
                        "experimental_setup": analysis.get("experimental_setup", "未提及"),
                        "method_pipeline": analysis.get("method_pipeline", "未提及"),
                        "experimental_protocol": analysis.get("experimental_protocol", "未提及"),
                        "key_results": analysis.get("key_results", "未提及"),
                        "error_and_decoherence": analysis.get("error_and_decoherence", "未提及"),
                        "failure_boundary": analysis.get("failure_boundary", "未提及"),
                        "reproducibility_checklist": analysis.get("reproducibility_checklist", "未提及"),
                        "evidence_map": analysis.get("evidence_map", "未提及"),
                        "future_impact": analysis.get("future_impact", "未提及"),
                        "task_modality": analysis.get("physical_system", "未提及"),
                        "architecture_innovation": analysis.get("core_mechanism", "未提及"),
                        "baselines": analysis.get("experimental_setup", "未提及"),
                        "ablation_gap": analysis.get("error_and_decoherence", "未提及"),
                        "idea_takeaway": analysis.get("idea_takeaway", analysis.get("future_impact", "未提及")),
                        "reviewer_critique": analysis.get("reviewer_critique", "未提及"),
                        "limitations": analysis.get("reviewer_critique", "未提及"),
                        "performance_gain": analysis.get("key_results", "未提及"),
                        "innovation_core": analysis.get("innovation_core", "未提及"),
                        "figure_captions_zh": analysis.get("figure_captions_zh", {}),
                        "idea_score": analysis.get("idea_score", 5),
                        "implementation_effort": analysis.get("implementation_effort", 3),
                    }
                else:
                    mapped = {
                        "tldr": analysis.get("tldr", "未提及"),
                        "task_modality": analysis.get("modality_task", "未提及"),
                        "architecture_innovation": analysis.get("the_magic", "未提及"),
                        "baselines": analysis.get("experiment_assets", "未提及"),
                        "clinical_problem": analysis.get("clinical_problem", "未提及"),
                        "innovation_core": analysis.get("innovation_core", "未提及"),
                        "performance_gain": analysis.get("performance_gain", "未提及"),
                        "method_pipeline": analysis.get("method_pipeline", "未提及"),
                        "experimental_protocol": analysis.get("experimental_protocol", "未提及"),
                        "quantitative_results": analysis.get("quantitative_results", "未提及"),
                        "ablation_gap": analysis.get("ablation_study", "未提及"),
                        "failure_boundary": analysis.get("failure_boundary", "未提及"),
                        "reproducibility_checklist": analysis.get("reproducibility_checklist", "未提及"),
                        "evidence_map": analysis.get("evidence_map", "未提及"),
                        "idea_takeaway": analysis.get("steal_value", "未提及"),
                        "reviewer_critique": analysis.get("hype_check", "未提及"),
                        "limitations": analysis.get("hype_check", "未提及"),
                        "figure_captions_zh": analysis.get("figure_captions_zh", {}),
                        "idea_score": analysis.get("idea_score", 5),
                        "implementation_effort": analysis.get("implementation_effort", 3),
                    }

                def _valid_text(v: Any) -> bool:
                    if not isinstance(v, str):
                        return False
                    t = v.strip()
                    return bool(t) and t not in {"未提及", "文中未包含消融实验细节"}

                merged = dict(paper)
                for k, v in mapped.items():
                    if isinstance(v, (int, float)):
                        if k == "idea_score":
                            # 仅在模型给出更有区分度的分数时覆盖
                            if int(v) > 1:
                                merged[k] = int(v)
                        else:
                            merged[k] = v
                    elif isinstance(v, dict):
                        if v:  # 非空 dict（如 figure_captions_zh）
                            merged[k] = v
                    elif isinstance(v, list):
                        if v:
                            merged[k] = v
                    elif _valid_text(v):
                        merged[k] = v

                merged["analysis"] = analysis
                return merged
            except Exception as exc:
                logging.exception("全文精读失败 id=%s: %s", paper.get("id", "unknown"), exc)
                return {**paper, "analysis": None}

    async def deep_analyze_fulltext_batch(
        self,
        papers: list[dict[str, Any]],
        top_k: int = 3,
        content_key: str = "full_text_content",
    ) -> list[dict[str, Any]]:
        """
        批量全文精读（异步并发）。
        优先读取 `content_key` 字段，缺失时回退到摘要。
        """
        candidates = papers[:top_k]
        tasks: list[asyncio.Task[dict[str, Any]]] = []
        for p in candidates:
            full_text = str(p.get(content_key, "") or p.get("abstract", ""))
            tasks.append(asyncio.create_task(self.deep_analyze_fulltext(p, full_text)))

        if not tasks:
            return []

        results = await asyncio.gather(*tasks, return_exceptions=True)
        enriched: list[dict[str, Any]] = []
        for idx, item in enumerate(results):
            if isinstance(item, BaseException):
                logging.exception("全文批量精读异常: %s", item)
                enriched.append(candidates[idx])
            elif isinstance(item, dict):
                enriched.append(item)
            else:
                enriched.append(candidates[idx])
        return enriched

    def quick_filter(self, papers: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if self.use_local_quick:
            local_result = self.local_llm.quick_filter(papers)
            if local_result:
                return local_result

        relevant: list[dict[str, Any]] = []
        for paper in papers:
            try:
                messages: list[ChatCompletionUserMessageParam] = [
                    {
                        "role": "user",
                        "content": (PHYSICS_QUICK_FILTER_PROMPT if self.is_physics_domain else QUICK_FILTER_PROMPT).format(
                            title=paper.get("title", ""),
                            abstract_snippet=paper.get("abstract", "")[:300],
                        ),
                    }
                ]
                content = self._chat_with_retry(
                    model=self.quick_model,
                    messages=messages,
                    max_tokens=160,
                )
                result = self._safe_json(content)
                if bool(result.get("relevant", False)) and bool(result.get("idea_worthy", False)):
                    topic = str(result.get("topic", "")).strip().lower()
                    allowed_topics = {"cqed", "plasmonics", "quantum", "materials"} if self.is_physics_domain else {"imaging", "recon", "agent"}
                    if topic in allowed_topics:
                        paper["topic"] = topic
                    idea_hint = str(result.get("idea_hint", "")).strip()
                    if idea_hint:
                        paper["idea_takeaway"] = idea_hint
                    relevant.append(paper)
            except Exception as exc:
                logging.exception("LLM 快筛失败: %s", exc)
        return relevant

    def deep_extract(self, papers: list[dict[str, Any]], top_k: int = 5) -> list[dict[str, Any]]:
        enriched: list[dict[str, Any]] = []
        candidates = papers[:top_k]
        started = time.monotonic()
        consecutive_failures = 0

        for idx, paper in enumerate(candidates):
            elapsed = time.monotonic() - started
            if elapsed > self.deep_stage_max_seconds:
                logging.warning(
                    "LLM 深析阶段触发超时熔断，已耗时 %.1fs（上限=%ss）",
                    elapsed,
                    self.deep_stage_max_seconds,
                )
                enriched.extend(candidates[idx:])
                break

            try:
                route_content, route, resolved_pdf_url = self._build_route_content(paper)
                if route == "fulltext":
                    if self.is_physics_domain:
                        prompt = PHYSICS_FULLTEXT_IDEA_PROMPT.format(
                            title=paper.get("title", ""),
                            authors=", ".join([str(a) for a in (paper.get("authors", []) or [])][:8]),
                            source=paper.get("source", ""),
                            affiliation=paper.get("affiliation", ""),
                            full_text=route_content,
                        )
                    else:
                        prompt = FULLTEXT_IDEA_PROMPT.format(
                            title=paper.get("title", ""),
                            authors=", ".join([str(a) for a in (paper.get("authors", []) or [])][:8]),
                            source=paper.get("source", ""),
                            affiliation=paper.get("affiliation", ""),
                            full_text=route_content,
                        )
                    max_tokens = max(1600, self.fulltext_max_tokens)
                else:
                    abstract_for_prompt = route_content
                    if str(paper.get("source", "")).lower() == "pubmed" and not bool(paper.get("pdf_downloaded", False)):
                        abstract_for_prompt = (
                            f"{route_content}\n\n"
                            '[说明] 当前仅有摘要，无法确认的实验细节请标注为"需查阅原文确认"。'
                        )
                    prompt = (
                        PHYSICS_DEEP_EXTRACT_PROMPT if self.is_physics_domain else DEEP_EXTRACT_PROMPT
                    ).format(
                        title=paper.get("title", ""),
                        authors=", ".join([str(a) for a in (paper.get("authors", []) or [])][:8]),
                        source=paper.get("source", ""),
                        affiliation=paper.get("affiliation", ""),
                        abstract=abstract_for_prompt,
                    )
                    max_tokens = max(1200, self.deep_extract_max_tokens)

                messages: list[ChatCompletionUserMessageParam] = [{"role": "user", "content": prompt}]
                content = self._chat_with_retry(
                    model=self.deep_model,
                    messages=messages,
                    max_tokens=max_tokens,
                )
                extracted = self._normalize_extracted(self._parse_extraction_payload(content))
                merged = {**paper, **extracted}
                if self.is_physics_domain:
                    merged["task_modality"] = str(merged.get("physical_system", merged.get("task_modality", "未提及")))
                    merged["architecture_innovation"] = str(
                        merged.get("core_mechanism", merged.get("architecture_innovation", "未提及"))
                    )
                    merged["baselines"] = str(merged.get("experimental_setup", merged.get("baselines", "未提及")))
                    merged["ablation_gap"] = str(
                        merged.get("error_and_decoherence", merged.get("ablation_gap", "未提及"))
                    )
                    merged["clinical_compliance"] = str(
                        merged.get("future_impact", merged.get("clinical_compliance", "未提及"))
                    )
                    merged["performance_gain"] = str(
                        merged.get("key_results", merged.get("performance_gain", "未提及"))
                    )
                existing_zh = str(merged.get("abstract_zh", "")).strip()
                if existing_zh in {"", "未提及"} or self._looks_incomplete_translation(
                    merged.get("abstract", ""),
                    existing_zh,
                ):
                    merged["abstract_zh"] = self._translate_abstract_with_llm(merged.get("abstract", ""))
                merged["analysis_route"] = route
                if resolved_pdf_url:
                    merged["pdf_url"] = resolved_pdf_url
                if route == "fulltext":
                    merged["full_text_content"] = route_content
                    if self._has_pdf_for_figure_selection(merged, resolved_pdf_url):
                        figure_items = self._extract_and_host_figures_for_paper(merged, resolved_pdf_url)
                        if figure_items:
                            merged["figure_items"] = figure_items
                            merged["figure_urls"] = [str(item.get("url", "")).strip() for item in figure_items if str(item.get("url", "")).strip()]
                            # 翻译图注为中文
                            captions_zh = self._translate_figure_captions(figure_items)
                            if captions_zh:
                                merged["figure_captions_zh"] = captions_zh
                        else:
                            logging.warning("全文论文未得到可用图片: title=%s", str(merged.get("title", ""))[:120])
                    else:
                        logging.info("当前论文无 PDF，跳过图片提取与 LLM 选图: title=%s", str(merged.get("title", ""))[:120])
                enriched.append(merged)
                consecutive_failures = 0
            except Exception as exc:
                logging.exception("LLM 深度提取失败: %s", exc)
                enriched.append(paper)
                consecutive_failures += 1
                if consecutive_failures >= self.circuit_breaker_fails:
                    logging.warning(
                        "LLM 深析阶段触发失败熔断，连续失败=%s（阈值=%s）",
                        consecutive_failures,
                        self.circuit_breaker_fails,
                    )
                    if idx + 1 < len(candidates):
                        enriched.extend(candidates[idx + 1 :])
                    break
        return enriched
