"""
口播稿引擎模块 — 提供口播稿优化、多风格变体生成和素材编排计划。

采用两阶段 LLM 调用策略：
  Stage 1: 理解产品/直播目的 → 优化原始稿为"标准稿"
  Stage 2: 基于标准稿用不同 system prompt 生成 N 条风格变体
  Stage 3: 为每条变体的每个自然段落分配素材策略
"""

import json
import re
from dataclasses import dataclass, field, asdict
from typing import List, Optional

from loguru import logger

from app.config import config
from app.services import llm


# ────────────────────────── 数据结构 ──────────────────────────

@dataclass
class ScriptSegment:
    """口播稿中的一个段落，附带素材编排计划。"""
    text: str                                       # 本段口播文本
    material_strategy: str = "ai_image"             # "user_upload" | "ai_image" | "stock"
    matched_user_segment_path: str = ""             # 匹配到的用户素材路径（如适用）
    ai_prompt: str = ""                             # AI 生成 prompt（如适用）
    stock_keywords: List[str] = field(default_factory=list)  # 素材库搜索关键词

    def to_dict(self):
        return asdict(self)


@dataclass
class ScriptVariant:
    """一条完整的口播稿变体。"""
    variant_id: str
    style: str                                      # "热情激昂型", "专业知性型" 等
    full_script: str                                # 完整口播稿文本
    segments: List[ScriptSegment] = field(default_factory=list)
    cta_text: str = ""                              # "点击关注，今晚8点直播间见！"
    estimated_duration: float = 0.0                 # 预估朗读时长（秒）

    def to_dict(self):
        d = asdict(self)
        return d


# ────────────────────────── 预设风格库 ──────────────────────────

SCRIPT_STYLES = {
    "热情激昂型": (
        "你是一个充满激情的带货主播。你的语言风格特点：\n"
        "- 情绪饱满，大量使用感叹号和强调词\n"
        "- 节奏紧凑，短句为主，有强烈的感染力\n"
        "- 适当使用口语化表达和网络流行语\n"
        "- 语气中带有兴奋和期待感\n"
        "示例语气：'家人们，这款面膜你们一定要试！真的绝了！'"
    ),
    "专业知性型": (
        "你是一个专业的美妆/产品评测专家。你的语言风格特点：\n"
        "- 理性分析，用数据和成分说话\n"
        "- 语言严谨有权威感，措辞专业但不晦涩\n"
        "- 引用具体成分、功效和使用方法\n"
        "- 客观对比，用事实打动观众\n"
        "示例语气：'这款面膜含有高浓度透明质酸，经过临床验证...'"
    ),
    "轻松种草型": (
        "你是用户的好朋友/闺蜜，在分享自己的真实使用感受。你的语言风格特点：\n"
        "- 语气亲和、自然，像朋友间聊天\n"
        "- 分享个人使用体验和感受\n"
        "- 适度使用可爱的语气词和表情\n"
        "- 真诚推荐，不过度夸张\n"
        "示例语气：'姐妹们我跟你们说，这个面膜我真的回购了好多次了...'"
    ),
    "紧迫促销型": (
        "你是一个精通促销的带货主播，擅长制造紧迫感。你的语言风格特点：\n"
        "- 强调限时限量，制造紧迫感\n"
        "- 突出价格优势和专属优惠\n"
        "- 使用倒计时、库存告急等促销技巧\n"
        "- 直击痛点，快速促成下单\n"
        "示例语气：'最后100单！错过等一年！现在下单立减50！'"
    ),
    "故事叙事型": (
        "你是一个善于讲故事的内容创作者。你的语言风格特点：\n"
        "- 以一个具体的使用场景或用户故事开场\n"
        "- 用叙事手法引导观众代入\n"
        "- 情感细腻，注重画面感描写\n"
        "- 从故事自然过渡到产品推荐\n"
        "示例语气：'上周出差回来，皮肤干到起皮，朋友推荐我试试这款...'"
    ),
    "对比测评型": (
        "你是一个客观的产品测评达人。你的语言风格特点：\n"
        "- 直接对比同类产品的优劣\n"
        "- 用具体指标和使用体验做评判\n"
        "- 坦诚说明优缺点，增强可信度\n"
        "- 最终给出明确的推荐结论\n"
        "示例语气：'对比了市面上5款热门面膜，这款在保湿持久度上遥遥领先...'"
    ),
}

DEFAULT_STYLES = list(SCRIPT_STYLES.keys())


# ────────────────────────── 内部 LLM 调用 ──────────────────────────

def _get_promo_model(model_key: str) -> str:
    """获取 promo 配置的专用模型名，如无则回退到通用 openai 模型。"""
    promo_cfg = config._cfg.get("promo", {})
    model = promo_cfg.get(model_key, "")
    if model:
        return model
    return config.app.get("openai_model_name", "")


def _call_llm(prompt: str, max_retries: int = 3) -> str:
    """带重试的 LLM 调用，复用现有 llm 模块的 _generate_response。"""
    for i in range(max_retries):
        try:
            response = llm._generate_response(prompt=prompt)
            if response and "Error: " not in response:
                return response.strip()
            logger.warning(f"LLM returned error or empty, retry {i+1}/{max_retries}")
        except Exception as e:
            logger.error(f"LLM call failed: {e}, retry {i+1}/{max_retries}")
    return ""


def _parse_json_from_response(response: str) -> dict:
    """从 LLM 响应中提取 JSON 对象，兼容 markdown 代码块包裹。"""
    # 去除 markdown 代码块标记
    cleaned = re.sub(r"```(?:json)?\s*", "", response)
    cleaned = cleaned.strip()

    # 尝试直接解析
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # 尝试提取 {} 或 [] 包裹的内容
    match = re.search(r'(\{[\s\S]*\}|\[[\s\S]*\])', cleaned)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    logger.error(f"Failed to parse JSON from LLM response: {response[:200]}...")
    return {}


def _estimate_duration(text: str, chars_per_second: float = 4.5) -> float:
    """估算中文口播稿的朗读时长（秒）。中文约 4-5 字/秒。"""
    # 只计算可读字符（去除标点和空格后的纯文字）
    readable = re.sub(r'[^\u4e00-\u9fff\u3400-\u4dbfa-zA-Z0-9]', '', text)
    return len(readable) / chars_per_second


# ────────────────────────── Stage 1: 口播稿优化 ──────────────────────────

def translate_script(script: str, target_language: str) -> str:
    """
    将口播稿翻译为目标语言，同时保持口播特征和节奏。
    """
    if not target_language or target_language.lower() in ["zh", "chinese", "中文"]:
        return script

    logger.info(f"Translating script to {target_language}")
    prompt = f"""
# 角色：跨境出海直播推广视频口播翻译专家

## 任务
将以下口播稿翻译成 {target_language}。

## 约束
1. 保持原有的带货口吻、痛点吸引、卖点阐述与 CTA（行动召唤）
2. 翻译后要自然流畅，适合目标语言的口播习惯
3. 只返回翻译后的纯文本，不要包含任何标题、标记或格式说明
4. 不要使用 markdown 格式
5. 用合理的标点符号断句

## 待翻译口播稿
{script}
""".strip()

    translated = _call_llm(prompt)
    if not translated:
        logger.error("Translation failed, returning original script")
        return script
    return translated.strip()


def optimize_script(
    raw_script: str,
    product_name: str,
    product_description: str = "",
    livestream_purpose: str = "",
    target_language: str = "",
) -> str:
    """
    优化用户提供的原始口播稿（可能不完整），输出完整的标准口播稿，并可选翻译为外语。

    Args:
        raw_script: 用户原始口播稿（可能不完整）
        product_name: 产品名称
        product_description: 产品描述
        livestream_purpose: 直播目的（如"新品发布""清仓促销"）
        target_language: 目标语种（可选，如 English, Japanese, Korean）

    Returns:
        优化并可能翻译后的完整标准口播稿文本
    """
    logger.info(f"Stage 1: Optimizing script for product '{product_name}'")

    prompt = f"""
# 角色：抖音直播推广视频口播稿优化专家

## 任务
你将收到一段可能不完整的原始口播稿，以及产品和直播相关信息。
请你：
1. 理解产品的核心卖点和目标受众
2. 补全不完整的内容（如缺少开场 hook、产品介绍、使用效果、CTA 等）
3. 优化表达，使其更适合抖音短视频的口播风格
4. 确保口播稿在朗读时长约 20-35 秒（约 90-160 个中文字符）
5. 确保包含以下结构要素：
   - 开场 Hook（1-2句，吸引注意力）
   - 产品核心卖点（2-3个重点）
   - 使用效果/用户反馈
   - 行动号召 CTA（引导关注或下单）

## 约束
1. 只返回优化后的口播稿纯文本，不要包含任何标题、标记或格式
2. 不要使用 markdown 格式
3. 用合理的标点符号断句，方便后续 TTS 合成
4. 使用中文
5. 语言自然流畅，适合口播朗读

## 输入信息
- 产品名称：{product_name}
- 产品描述：{product_description or '（未提供，请根据产品名称推断）'}
- 直播目的：{livestream_purpose or '产品推广'}
- 原始口播稿：
{raw_script}
""".strip()

    optimized = _call_llm(prompt)
    if not optimized:
        logger.error("Failed to optimize script, returning original")
        optimized = raw_script

    # 清理格式
    optimized = optimized.replace("*", "").replace("#", "")
    optimized = re.sub(r"\[.*?\]", "", optimized)
    optimized = re.sub(r"\(.*?\)", "", optimized)
    optimized = optimized.strip()

    # 翻译为外语（如指定）
    if target_language:
        optimized = translate_script(optimized, target_language)

    estimated_dur = _estimate_duration(optimized)
    logger.success(
        f"Stage 1 complete: optimized script ({len(optimized)} chars, "
        f"~{estimated_dur:.1f}s estimated)"
    )
    return optimized



# ────────────────────────── Stage 2: 风格变体生成 ──────────────────────────

def generate_variants(
    optimized_script: str,
    product_name: str,
    styles: Optional[List[str]] = None,
    count: int = 5,
    target_language: str = "",
) -> List[ScriptVariant]:
    """
    基于优化后的标准稿，生成 N 条不同风格的口播稿变体。

    每条变体使用不同的 system prompt，确保风格差异最大化。

    Args:
        optimized_script: 优化后的标准口播稿
        product_name: 产品名称
        styles: 指定风格列表（空则自动选择）
        count: 生成数量
        target_language: 目标语种（可选，如 English, Japanese, Korean）

    Returns:
        ScriptVariant 列表
    """
    logger.info(f"Stage 2: Generating {count} script variants for '{product_name}' in language '{target_language or 'zh'}'")

    if not styles:
        # 从预设风格中选取
        available = DEFAULT_STYLES.copy()
        styles = available[:count] if count <= len(available) else (
            available * (count // len(available) + 1)
        )[:count]

    variants = []
    for i, style in enumerate(styles[:count]):
        variant_id = f"variant-{i+1}"
        style_prompt = SCRIPT_STYLES.get(style, "")
        if not style_prompt:
            # 自定义风格，构造通用 prompt
            style_prompt = f"你的语言风格是：{style}。请根据这个风格特点来改写口播稿。"

        lang_instruction = f"使用目标语言 {target_language}（保持与输入口播稿相同的语言）" if target_language else "使用中文"

        prompt = f"""
# 角色设定
{style_prompt}

## 任务
将以下标准口播稿改写为符合你风格特点的版本。

## 约束
1. 保持核心卖点和产品信息不变，只改变表达风格和语气
2. 只返回改写后的口播稿纯文本，不要包含任何标题、标记、引号或格式说明
3. 不要使用 markdown 格式
4. 口播稿长度控制在 20-35 秒朗读时长
5. 用合理的标点符号断句
6. {lang_instruction}
7. 确保包含一句行动号召（CTA）作为结尾
8. 不要以"大家好"或"各位"（或其外语翻译）开头，要有吸引力的 hook 开场

## 产品名称
{product_name}

## 标准口播稿
{optimized_script}
""".strip()

        logger.info(f"  Generating variant {i+1}/{count}: style='{style}'")
        variant_text = _call_llm(prompt)

        if not variant_text:
            logger.warning(f"  Failed to generate variant {i+1}, using original script")
            variant_text = optimized_script

        # 清理
        variant_text = variant_text.replace("*", "").replace("#", "")
        variant_text = re.sub(r"\[.*?\]", "", variant_text)
        variant_text = re.sub(r"\(.*?\)", "", variant_text)

        # 提取 CTA（最后一句）
        sentences = re.split(r'[。！？!?\.]', variant_text)
        sentences = [s.strip() for s in sentences if s.strip()]
        cta_text = sentences[-1] if sentences else ""

        variant = ScriptVariant(
            variant_id=variant_id,
            style=style,
            full_script=variant_text.strip(),
            cta_text=cta_text,
            estimated_duration=_estimate_duration(variant_text),
        )
        variants.append(variant)
        logger.info(
            f"  Variant {i+1} done: {len(variant_text)} chars, "
            f"~{variant.estimated_duration:.1f}s"
        )

    logger.success(f"Stage 2 complete: generated {len(variants)} variants")
    return variants


# ────────────────────────── Stage 3: 素材编排计划 ──────────────────────────

def plan_materials(
    variant: ScriptVariant,
    analyzed_segments: Optional[List[dict]] = None,
    product_name: str = "",
) -> ScriptVariant:
    """
    为口播稿变体的每个自然段落分配素材策略。

    使用 LLM 理解每段内容的语义，智能决定该用哪种素材来源，
    并生成对应的 AI prompt 或素材库搜索关键词。

    Args:
        variant: 口播稿变体对象
        analyzed_segments: 用户上传素材的分析结果列表（可选）
        product_name: 产品名称

    Returns:
        更新了 segments 字段的 ScriptVariant
    """
    logger.info(f"Stage 3: Planning materials for variant '{variant.variant_id}'")

    # 将口播稿按自然段落/句群拆分
    full_text = variant.full_script
    # 按句号/感叹号/问号分组，每 2-3 句为一个 segment
    raw_sentences = re.split(r'(?<=[。！？!?])', full_text)
    raw_sentences = [s.strip() for s in raw_sentences if s.strip()]

    # 将句子分组为 segments（每 2-3 句为一组，目标 5-8 秒的片段）
    grouped_segments = []
    current_group = ""
    for sentence in raw_sentences:
        candidate = current_group + sentence
        if _estimate_duration(candidate) > 8.0 and current_group:
            grouped_segments.append(current_group.strip())
            current_group = sentence
        else:
            current_group = candidate
    if current_group.strip():
        grouped_segments.append(current_group.strip())

    if not grouped_segments:
        grouped_segments = [full_text]

    # 构造用户素材摘要（如有）
    user_material_summary = "无用户上传素材"
    if analyzed_segments:
        summaries = []
        for seg in analyzed_segments:
            tags = seg.get("content_tags", [])
            desc = seg.get("description", "")
            path = seg.get("file_path", "")
            summaries.append(f"- [{', '.join(tags)}] {desc} (path: {path})")
        user_material_summary = "\n".join(summaries)

    # 可用素材策略
    material_options = (
        "user_upload（使用用户上传的素材片段）, "
        "ai_image（AI 文生图，适合产品特写、场景展示）, "
        "stock（从 Pexels/Pixabay 素材库搜索，适合通用背景画面）"
    )

    segments_text = "\n".join(
        [f"Segment {i+1}: {seg}" for i, seg in enumerate(grouped_segments)]
    )

    prompt = f"""
# 角色：视频素材编排专家

## 任务
为你提供的口播稿中每个片段分配最合适的视频素材策略。你必须深入分析每一个片段的口播文本（text），并根据该段文本的具体语境、画面感和情感，量身定制专属的文生图提示词（ai_prompt）或素材库关键词（stock_keywords），确保最终渲染的视觉画面与口播配音内容高度契合、逻辑一致！

## 可用素材策略
{material_options}

## 用户上传的素材（已分析）
{user_material_summary}

## 产品名称
{product_name}

## 口播稿片段
{segments_text}

## 输出格式
请严格输出以下 JSON 格式（不要包含其他内容）：
```json
[
  {{
    "segment_index": 1,
    "material_strategy": "ai_image",
    "ai_prompt": "An English prompt for Flux image generation that visually illustrates or complements this specific segment's text. Avoid generic prompts. Be detailed, photorealistic, with cinematic lighting and professional photography terms.",
    "stock_keywords": ["keyword1", "keyword2"],
    "matched_user_path": ""
  }}
]
```

## 编排原则
1. **强相关性原则（核心要求）**：生成的 ai_prompt 必须紧密关联该段落的口播文本！禁止为所有片段生成千篇一律的产品图或背景。
   - 如果口播文本描述了某种痛点（如熬夜、皮肤差、工作累），ai_prompt 必须具体描述对应的痛点视觉场景（例如：A tired person late at night in front of a computer, dark circles, warm cozy room, cinematic, 8k）；
   - 如果口播文本描述了产品的某种使用效果或质感（如水润、吸收快、质地顺滑），ai_prompt 必须描述相应的质感或使用场景（例如：Macro close-up of a drop of skincare serum absorbing into smooth glowing skin, water splash, macro, 8k）；
   - 如果口播文本是吸引注意力的Hook或行动号召CTA（如“赶紧抢购吧！”、“今晚直播间见！”），ai_prompt 必须描述精美的产品陈列、热闹的直播间背景或具有抢购氛围的高质感画面（例如：A professional live streaming room setup with bright ring lights, glowing skincare products on a wooden desk, blurred background, cinematic, 8k）。
2. 如果有相关的用户上传素材，优先使用（material_strategy 设为 "user_upload"，填入 matched_user_path）。
3. 产品特写/细节展示/动态使用场景均适合 ai_image。
4. 通用背景、氛围过渡等适合 stock 搜索。
5. **ai_prompt 必须使用英文**描述，以供 Flux 模型直接调用。
6. **stock_keywords 必须使用英文**。
""".strip()

    response = _call_llm(prompt)
    material_plan = _parse_json_from_response(response)

    # 构建 ScriptSegment 列表
    script_segments = []
    if isinstance(material_plan, list):
        for i, seg_text in enumerate(grouped_segments):
            plan = material_plan[i] if i < len(material_plan) else {}
            segment = ScriptSegment(
                text=seg_text,
                material_strategy=plan.get("material_strategy", "ai_image"),
                matched_user_segment_path=plan.get("matched_user_path", ""),
                ai_prompt=plan.get("ai_prompt", f"A beautiful, high-quality, photorealistic depiction representing: {seg_text}. Cinematic lighting, 8k."),
                stock_keywords=plan.get("stock_keywords", [product_name]),
            )
            script_segments.append(segment)
    else:
        # LLM 返回解析失败，使用默认策略
        logger.warning("Failed to parse material plan, using default strategies")
        strategies = ["ai_image", "stock", "ai_image"]
        for i, seg_text in enumerate(grouped_segments):
            segment = ScriptSegment(
                text=seg_text,
                material_strategy=strategies[i % len(strategies)],
                ai_prompt=f"A beautiful, high-quality, photorealistic depiction representing: {seg_text}. Cinematic lighting, 8k.",
                stock_keywords=[product_name, "beauty", "skincare"],
            )
            script_segments.append(segment)

    variant.segments = script_segments
    logger.success(
        f"Stage 3 complete: planned {len(script_segments)} segments "
        f"for variant '{variant.variant_id}'"
    )
    return variant


# ────────────────────────── 便捷入口 ──────────────────────────

def generate_promo_scripts(
    raw_script: str,
    product_name: str,
    product_description: str = "",
    livestream_purpose: str = "",
    styles: Optional[List[str]] = None,
    count: int = 5,
    analyzed_segments: Optional[List[dict]] = None,
    target_language: str = "",
) -> List[ScriptVariant]:
    """
    一站式入口：执行 Stage 1 → Stage 2 → Stage 3 全流程。

    Args:
        raw_script: 用户原始口播稿
        product_name: 产品名称
        product_description: 产品描述
        livestream_purpose: 直播目的
        styles: 风格列表
        count: 变体数量
        analyzed_segments: 素材分析结果
        target_language: 目标语种（可选，如 English, Japanese, Korean）

    Returns:
        带完整素材编排计划的 ScriptVariant 列表
    """
    # Stage 1
    optimized = optimize_script(
        raw_script=raw_script,
        product_name=product_name,
        product_description=product_description,
        livestream_purpose=livestream_purpose,
        target_language=target_language,
    )

    # Stage 2
    variants = generate_variants(
        optimized_script=optimized,
        product_name=product_name,
        styles=styles,
        count=count,
    )

    # Stage 3
    for variant in variants:
        plan_materials(
            variant=variant,
            analyzed_segments=analyzed_segments,
            product_name=product_name,
        )

    return variants


def diagnose_script(script: str, product_name: str = "") -> dict:
    """
    对口播稿进行 4 维爆款诊断评估。
    四维维度：
    - hook_score (黄金首3秒吸睛度)
    - conversion_score (产品卖点说服力)
    - fluency_score (口语化脱口秀流畅度)
    - cta_score (行动号召引导力)
    """
    logger.info("Diagnosing script for viral potential")
    prompt = f"""
# 角色：抖音直播爆款推广视频文案诊断专家

## 任务
评估以下口播稿的爆款潜力。

## 评估维度与标准
1. **黄金首3秒吸睛度 (hook_score)**: 能否在第一秒抓住眼球，引出痛点或疑问。
2. **产品卖点说服力 (conversion_score)**: 卖点是否清晰可信，有无转化说服力。
3. **口语化流畅度 (fluency_score)**: 读起来是否顺口，是否自然口语化，适合短视频口播。
4. **行动号召引导力 (cta_score)**: 结尾引导点赞、关注或进直播间抢购是否明确有力。

## 产品名称
{product_name}

## 输入口播稿
{script}

## 输出格式
请严格输出以下 JSON 格式（不要包含任何 markdown 代码块或任何解释性文本，必须是纯 JSON）：
{{
  "hook_score": 85,
  "hook_feedback": "评估反馈文字",
  "conversion_score": 90,
  "conversion_feedback": "评估反馈文字",
  "fluency_score": 88,
  "fluency_feedback": "评估反馈文字",
  "cta_score": 95,
  "cta_feedback": "评估反馈文字"
}}
""".strip()

    response = _call_llm(prompt)
    diagnostic = _parse_json_from_response(response)
    if not diagnostic:
        logger.warning("Failed to parse diagnostic JSON, returning fallback scores")
        return {
            "hook_score": 80,
            "hook_feedback": "文案开场具备一定吸引力，可尝试增加反问或悬念语气。",
            "conversion_score": 80,
            "conversion_feedback": "产品卖点陈列合理，但可以更具说服力。",
            "fluency_score": 80,
            "fluency_feedback": "断句合理，口播表达顺畅。",
            "cta_score": 80,
            "cta_feedback": "具备基础行动号召，建议加入紧迫感提示。"
        }
    return diagnostic

